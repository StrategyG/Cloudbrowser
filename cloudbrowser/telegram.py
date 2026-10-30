from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import PurePosixPath
from urllib.parse import urlsplit

import httpx

from .agent import Agent
from .artifacts import Artifacts
from .config import Settings
from .store import Store

HELP = """Cloudbrowser — browser & produksi video di server

Kirim instruksi biasa atau /run <pekerjaan> atau /newtask <pekerjaan>.
/flow — buka Google Flow
/capcut — buka CapCut
/status — status pekerjaan
/tasks — daftar 8 pekerjaan terbaru
/health — health ringkas worker dan database
/browser — status sesi Chromium tanpa menampilkan token URL
/report <job_id> — status dan 5 audit event terakhir
/screen — tangkapan layar browser
/files — daftar file hasil/unggahan
/agents — daftar agent A2A yang dibangun model
/workflow <job_id> — langkah, delegasi dan hasil pemeriksaan
/get <artifact_id> — ambil file
/approve <id> atau /reject <id> — persetujuan tindakan
/stop [job_id] — hentikan pekerjaan (boleh dilanjutkan)
/pause [job_id] — jeda tanpa mengulang aksi eksternal
/cancel [job_id] — batalkan permanen
/resume <job_id> [arahan] — lanjutkan setelah login/manual review
/project <nama> — pilih konteks proyek yang terpisah
/brief <catatan> — simpan arahan tetap proyek; /brief - menghapusnya
/resolve_action <id> applied|not_applied — pastikan hasil tindakan setelah memeriksa website
/mode approve — minta persetujuan klik/ketik/unggah
/mode auto — otomatis untuk persiapan; aksi akun tetap mengikuti aturan server

Login, OTP dan CAPTCHA: gunakan dashboard, kemudian balas di sini.
Unggah media sebagai dokumen/video/audio; caption menjadi instruksi pekerjaan.
API AI dan kuota Flow/CapCut mengikuti akun masing-masing, terpisah dari ChatGPT Plus.
"""


def text_chunks(text: str) -> list[str]:
    chunks, current, units = [], [], 0
    for character in text:
        length = 2 if ord(character) > 0xFFFF else 1
        if units + length > 3800:
            chunks.append("".join(current))
            current, units = [], 0
        current.append(character)
        units += length
    if current:
        chunks.append("".join(current))
    return chunks or ["."]


class TelegramClient:
    def __init__(self, token: str, client: httpx.AsyncClient | None = None):
        self.token = token
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(45, connect=15), follow_redirects=False)

    async def close(self) -> None:
        await self.client.aclose()

    async def call(self, method: str, payload: dict | None = None, *, files=None):
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        try:
            if files:
                response = await self.client.post(url, data=payload, files=files, timeout=120)
            else:
                response = await self.client.post(url, json=payload or {})
            if not response.is_success:
                raise ValueError(f"Telegram API HTTP {response.status_code}.")
            data = response.json()
            if not data.get("ok"):
                raise ValueError(f"Telegram API rejected request ({data.get('error_code', 'unknown')}).")
            return data["result"]
        except httpx.HTTPError:
            raise ValueError("Telegram network request failed; check server connectivity.") from None


class TelegramService:
    def __init__(self, settings: Settings, store: Store, agent: Agent, artifacts: Artifacts,
                 client: TelegramClient | None = None):
        self.settings, self.store, self.agent, self.artifacts = settings, store, agent, artifacts
        self.client = client or TelegramClient(settings.telegram_bot_token)
        self.task: asyncio.Task | None = None
        self.last_poll = 0.0
        self.last_error = ""
        self.username = ""

    def authorized(self, message: dict) -> bool:
        user, chat = message.get("from", {}), message.get("chat", {})
        return (user.get("id") == self.settings.telegram_owner_id
                and chat.get("id") == self.settings.telegram_owner_id
                and chat.get("type") == "private" and not user.get("is_bot", False))

    async def start(self) -> None:
        me = await self.client.call("getMe")
        self.username = me.get("username", "")
        webhook = await self.client.call("getWebhookInfo")
        if webhook.get("url"):
            raise ValueError("Bot memiliki webhook aktif. Gunakan bot khusus atau hapus webhook sebelum menjalankan polling.")
        if not self.store.get("telegram_offset"):
            # Do not execute commands left in the bot's inbox before this installation was activated.
            stale = await self.client.call("getUpdates", {"offset": -1, "timeout": 0,
                                                         "allowed_updates": ["message", "callback_query"]})
            self.store.set("telegram_offset", str(stale[-1]["update_id"] + 1 if stale else 0))
        self.agent.notify = self.notify
        self.agent.deliver = self.send_artifact
        self.task = asyncio.create_task(self._poll())

    async def close(self) -> None:
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        await self.client.close()

    async def notify(self, text: str, keyboard: dict | None = None) -> None:
        for i, chunk in enumerate(text_chunks(self.settings.redact(text))):
            payload = {"chat_id": self.settings.telegram_owner_id, "text": chunk}
            if keyboard and i == 0:
                payload["reply_markup"] = keyboard
            await self.client.call("sendMessage", payload)

    async def send_artifact(self, artifact_id: str) -> dict:
        artifact, path = self.store.artifact(artifact_id), self.artifacts.path(artifact_id)
        if artifact["size"] > 49 * 1024 * 1024:
            await self.notify(f"File {artifact['filename']} melebihi batas pengiriman bot. Unduh melalui dashboard. ID: {artifact_id}")
            return {"sent": False, "dashboard_artifact_id": artifact_id, "reason": "Telegram upload size limit"}
        with path.open("rb") as file:
            result = await self.client.call("sendDocument", {"chat_id": str(self.settings.telegram_owner_id)},
                                            files={"document": (artifact["filename"], file, "application/octet-stream")})
        return {"sent": True, "message_id": result["message_id"], "artifact_id": artifact_id}

    async def _incoming_file(self, attachment: dict, filename: str) -> dict:
        limit = min(self.artifacts.max_bytes, 20 * 1024 * 1024)
        if attachment.get("file_size", 0) > limit:
            raise ValueError("File Telegram terlalu besar untuk diambil bot; unggah melalui dashboard.")
        metadata = await self.client.call("getFile", {"file_id": attachment["file_id"]})
        remote = PurePosixPath(metadata["file_path"])
        if remote.is_absolute() or ".." in remote.parts or metadata.get("file_size", 0) > limit:
            raise ValueError("Telegram file path or size is invalid.")
        artifact_id, path, filename = self.artifacts.allocate(filename)
        url = f"https://api.telegram.org/file/bot{self.settings.telegram_bot_token}/{remote}"
        try:
            size = 0
            async with self.client.client.stream("GET", url, timeout=120) as response:
                if not response.is_success:
                    raise ValueError("Telegram file download failed.")
                with path.open("wb") as file:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise ValueError("File Telegram melebihi batas unduhan bot.")
                        file.write(chunk)
            return self.artifacts.register(artifact_id, path, filename)
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    async def _poll(self) -> None:
        delay = 2
        while True:
            try:
                updates = await self.client.call("getUpdates", {
                    "offset": int(self.store.get("telegram_offset", "0")), "timeout": 25,
                    "allowed_updates": ["message", "callback_query"],
                })
                self.last_poll, self.last_error, delay = time.time(), "", 2
                for update in updates:
                    try:
                        await self.handle(update)
                    except Exception as exc:
                        self.store.event(None, "telegram_command_error", type(exc).__name__)
                        # Only report command errors to the configured owner; never reply to strangers.
                        message = update.get("message", {})
                        callback = update.get("callback_query", {})
                        original = callback.get("message", {}) | {"from": callback.get("from", {})}
                        if self.authorized(message) or self.authorized(original):
                            await self.notify(self.settings.redact(str(exc))[:1000] or "Perintah gagal.")
                    self.store.set("telegram_offset", str(update["update_id"] + 1))
            except asyncio.CancelledError:
                raise
            except Exception:
                self.last_error = "Koneksi Telegram terputus; mencoba kembali."
                await asyncio.sleep(delay)
                delay = min(30, delay * 2)

    async def handle(self, update: dict) -> None:
        if "callback_query" in update:
            callback = update["callback_query"]
            message = callback.get("message", {}) | {"from": callback.get("from", {})}
            if not self.authorized(message):
                return
            parts = callback.get("data", "").split(":", 1)
            success = len(parts) == 2 and parts[0] in {"approve", "reject"} and self.agent.decide(parts[1], parts[0] == "approve")
            await self.client.call("answerCallbackQuery", {"callback_query_id": callback["id"],
                                                          "text": "Tercatat." if success else "Sudah diproses atau kedaluwarsa."})
            return
        message = update.get("message", {})
        if not self.authorized(message):
            return
        text = message.get("text", "").strip()
        attachment, filename = None, "upload.bin"
        for key, default in (("document", "upload.bin"), ("video", "video.mp4"), ("audio", "audio.mp3")):
            if key in message:
                attachment = message[key]
                filename = attachment.get("file_name", default)
                break
        if not attachment and message.get("photo"):
            attachment, filename = message["photo"][-1], "photo.jpg"
        if attachment:
            # Durable update key prevents a Telegram retry from downloading/enqueuing twice.
            attachment_key = f"attachment:{update['update_id']}"
            artifact_id = self.store.get(attachment_key)
            artifact = self.store.artifact(artifact_id) if artifact_id else await self._incoming_file(attachment, filename)
            self.store.set(attachment_key, artifact["id"])
            await self.notify(f"File tersimpan: {artifact['filename']}\nArtifact ID: {artifact['id']}")
            if message.get("caption"):
                self.agent.enqueue(f"{message['caption']}\nGunakan artifact_id {artifact['id']} ({artifact['filename']}).", f"tg:{update['update_id']}")
            return
        command, _, argument = text.partition(" ")
        command = command.split("@")[0].lower()
        argument = argument.strip()
        if command in {"/start", "/help"}:
            await self.notify(HELP)
        elif command == "/status":
            rows = self.store.jobs()[:8]
            await self.notify(f"Model: {self.settings.ai_model}\nMode: {self.agent.mode}\nProyek: {self.store.get('current_project', 'default')}\n" +
                              ("\n".join(f"{j['id']} • {j['status']} • {j['goal'][:90]}" for j in rows) or "Belum ada pekerjaan."))
        elif command == "/tasks":
            rows = self.store.jobs()[:8]
            await self.notify("\n".join(f"{j['id']} • {j['status']} • {j['goal'][:75]}" for j in rows)
                              or "Belum ada pekerjaan.")
        elif command == "/health":
            try:
                self.store._rows("SELECT 1")
                database = "OK"
            except Exception:
                database = "ERROR"
            worker = bool(self.agent.worker and not self.agent.worker.done() and not self.agent.closing)
            await self.notify(f"Database: {database}\nWorker: {'OK' if worker else 'OFFLINE'}\n"
                              f"Browser: {'ACTIVE' if self.agent.browser.context else 'NOT_STARTED'}\n"
                              f"Studio: {'CONFIGURED' if self.agent.studio.enabled else 'DISABLED'}")
        elif command == "/browser":
            pages = self.agent.browser.context.pages if self.agent.browser.context else []
            hosts = [urlsplit(page.url).hostname or "local/blank" for page in pages[:10]]
            await self.notify("Browser: " + ("RUNNING" if self.agent.browser.context else "NOT_STARTED")
                              + "\nTab domains: " + (", ".join(hosts) if hosts else "(none)"))
        elif command == "/report":
            job = self.store.job(argument)
            events = self.store.events(argument)[:5]
            await self.notify(f"Job {job['id']}: {job['status']}\n"
                              + ("\n".join(f"{e['kind']}: {self.settings.redact(e['detail'])[:200]}"
                                          for e in events) or "Belum ada audit event."))
        elif command == "/screen":
            screenshot = await self.agent.browser.screenshot()
            await self.client.call("sendPhoto", {"chat_id": str(self.settings.telegram_owner_id)},
                                   files={"photo": ("browser.jpg", screenshot, "image/jpeg")})
        elif command == "/files":
            await self.notify("\n".join(f"{a['id']}\n{a['filename']} ({a['size']} bytes)" for a in self.store.artifacts()[:15]) or "Belum ada file.")
        elif command == "/agents":
            await self.notify("\n".join(f"{agent['id']} • {agent['profile']} • {agent['name']}" for agent in self.store.agents()) or "Belum ada agent. Minta AI membangun tim untuk tugas Anda.")
        elif command == "/workflow":
            self.store.job(argument)
            workflow = self.store.workflow(argument)
            if not workflow:
                await self.notify("Workflow belum dibuat oleh model.")
            else:
                latest = self.agent.crew.latest(argument)
                rows = []
                for step in workflow["steps"]:
                    task = latest.get(step["id"])
                    reviewed = bool(task and json.loads(task["review"]).get("passed"))
                    rows.append(f"{step['id']} • {task['agent_id'] if task else 'belum ditugaskan'} • {task['status'] if task else 'pending'} • review={'lulus' if reviewed else 'belum lulus'}")
                await self.notify(workflow["objective"] + "\n" + "\n".join(rows))
        elif command == "/get":
            await self.send_artifact(argument)
        elif command in {"/approve", "/reject"}:
            await self.notify("Tercatat." if self.agent.decide(argument, command == "/approve") else "Persetujuan tidak aktif atau sudah diproses.")
        elif command in {"/stop", "/pause", "/cancel"}:
            if command == "/stop":
                self.agent.stop(argument or None)
                await self.notify("Penghentian diminta.")
            elif command == "/pause":
                job = self.agent.pause(argument or None)
                await self.notify(f"Job {job['id']}: pause diminta. Status akan diperbarui oleh worker.")
            else:
                job = self.agent.cancel(argument or None)
                await self.notify(f"Job {job['id']}: pembatalan diminta. Tidak dapat di-resume.")
        elif command == "/mode":
            if argument not in {"auto", "approve"}:
                raise ValueError("Gunakan /mode auto atau /mode approve.")
            if self.agent.busy:
                raise ValueError("Hentikan job aktif sebelum mengubah mode.")
            self.store.set("approval_mode", argument)
            detail = "Persiapan otomatis aktif. Klik, unggah, keyboard dan delegasi remote tetap memerlukan persetujuan. Fill/select hanya otomatis jika diizinkan di konfigurasi server." if argument == "auto" else "Klik, ketik dan unggahan AI memerlukan persetujuan."
            await self.notify(f"Mode {argument}. {detail}")
        elif command == "/project":
            if argument:
                self.store.set_project(argument)
            await self.notify("Proyek aktif: " + self.store.get("current_project", "default"))
        elif command == "/brief":
            project_id = self.store.get("current_project", "default")
            if argument:
                if len(argument) > 8000:
                    raise ValueError("Arahan proyek maksimum 8000 karakter.")
                self.store.set_project(project_id, "" if argument == "-" else self.settings.redact(argument))
            await self.notify("Arahan proyek " + project_id + ":\n" + (self.store.get("project_brief:" + project_id, "") or "(kosong)"))
        elif command == "/resolve_action":
            action_id, _, outcome = argument.partition(" ")
            if outcome not in {"applied", "not_applied"}:
                raise ValueError("Gunakan /resolve_action ID applied atau /resolve_action ID not_applied setelah memeriksa website.")
            if self.agent.busy:
                raise ValueError("Hentikan job aktif sebelum memastikan hasil tindakan.")
            if not self.store.resolve_action(action_id, outcome == "applied"):
                raise ValueError("Tindakan sudah diperiksa atau tidak memiliki hasil yang belum pasti.")
            self.store.event(None, "owner_action_resolution", action_id + ": " + outcome)
            await self.notify("Hasil dicatat. Gunakan /resume JOB_ID dengan arahan yang sesuai.")
        elif command == "/resume":
            job_id, _, answer = argument.partition(" ")
            job = self.agent.resume(job_id, answer or "Lanjutkan setelah memeriksa browser.", f"tg:{update['update_id']}")
            await self.notify(f"Job {job['id']} masuk antrean kembali.")
        elif command in {"/flow", "/capcut"}:
            site = "Google Flow di https://labs.google/fx/tools/flow" if command == "/flow" else "CapCut di https://www.capcut.com/my-edit"
            job = self.agent.enqueue(f"Buka {site}. Laporkan status halaman dan minta login manual jika diperlukan.", f"tg:{update['update_id']}")
            await self.notify(f"Job {job['id']} masuk antrean.")
        elif command.startswith("/") and command not in {"/run", "/newtask"}:
            await self.notify("Perintah tidak dikenal. Gunakan /help.")
        elif text:
            goal = argument if command in {"/run", "/newtask"} else text
            previous = self.store.get(f"resume-request:tg:{update['update_id']}")
            waiting = [j for j in self.store.jobs(self.store.get("current_project", "default")) if j["status"] == "waiting_user"]
            if previous:
                job = self.store.job(previous)
            elif waiting and command not in {"/run", "/newtask"} and not self.agent.busy:
                job = self.agent.resume(waiting[0]["id"], goal, f"tg:{update['update_id']}")
            else:
                job = self.agent.enqueue(goal, f"tg:{update['update_id']}")
            await self.notify(f"Job {job['id']}: {job['status']}.")
