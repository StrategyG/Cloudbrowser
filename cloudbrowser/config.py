from __future__ import annotations

import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def data_directory() -> Path:
    return Path(os.environ.get("CLOUDBROWSER_DATA_DIR", "data")).expanduser().resolve()


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600_000).hex()
    return f"{salt}${value}"


def password_matches(password: str, encoded: str) -> bool:
    try:
        return hmac.compare_digest(password_hash(password, encoded.split("$")[0]), encoded)
    except (ValueError, TypeError):
        return False


@dataclass
class Settings:
    ai_base_url: str = ""
    ai_model: str = ""
    ai_api_key: str = field(default="", repr=False)
    ai_vision: bool = False
    telegram_bot_token: str = field(default="", repr=False)
    telegram_owner_id: int = 0
    telegram_enabled: bool = True
    dashboard_password_hash: str = field(default="", repr=False)
    session_secret: str = field(default_factory=lambda: secrets.token_hex(32), repr=False)
    allowed_domains: list[str] = field(default_factory=lambda: ["google.com", "labs.google", "capcut.com"])
    approval_mode: str = "approve"
    headless: bool = False
    chromium_sandbox: bool = True
    browser_channel: str = ""
    bind_host: str = "127.0.0.1"
    port: int = 8000
    secure_cookie: bool = False
    public_origin: str = ""
    max_steps: int = 30
    job_timeout_seconds: int = 1800
    max_upload_mb: int = 100
    require_workflow: bool = True
    max_agents: int = 8
    agent_max_steps: int = 8
    max_model_calls: int = 60
    ai_max_output_tokens: int = 2048
    ai_context_chars: int = 65000
    max_job_output_tokens: int = 122880
    max_repeated_tool_errors: int = 3
    auto_browser_actions: list[str] = field(default_factory=list)
    role_models: dict[str, str] = field(default_factory=dict)
    a2a_base_url: str = ""
    a2a_api_key: str = field(default="", repr=False)
    a2a_peers: list[dict] = field(default_factory=list, repr=False)
    studio_base_url: str = ""
    studio_api_token: str = field(default="", repr=False)
    rag_base_url: str = ""
    rag_api_token: str = field(default="", repr=False)
    mcp_servers: list[dict] = field(default_factory=list, repr=False)

    def validate(self) -> None:
        parsed = urlsplit(self.ai_base_url)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (parsed.scheme == "http" and not local)
        ):
            raise ValueError("AI base URL must use HTTPS (HTTP is allowed only for a local AI server).")
        if not self.ai_model.strip():
            raise ValueError("AI model is required; use a model that supports function/tool calling.")
        if self.telegram_enabled and (
            not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", self.telegram_bot_token)
            or self.telegram_owner_id <= 0
        ):
            raise ValueError("A valid Telegram bot token and positive numeric owner user ID are required.")
        if not re.fullmatch(r"[a-f0-9]{32}\$[a-f0-9]{64}", self.dashboard_password_hash):
            raise ValueError("Configure a dashboard password before starting the server.")
        if len(self.session_secret) < 32:
            raise ValueError("Session secret is too short.")
        if self.approval_mode not in {"approve", "auto"}:
            raise ValueError("approval_mode must be approve or auto.")
        if not self.allowed_domains or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}", d)
            for d in self.allowed_domains
        ):
            raise ValueError("Use a list of hostnames, without URLs or wildcards, for allowed_domains.")
        if not (1 <= self.max_steps <= 100 and 60 <= self.job_timeout_seconds <= 7200):
            raise ValueError("Invalid job limits.")
        if not (1 <= self.port <= 65535 and 1 <= self.max_upload_mb <= 1000):
            raise ValueError("Invalid port or file size limit.")
        if self.public_origin:
            origin = urlsplit(self.public_origin)
            if (origin.scheme != "https" or not origin.hostname or origin.path not in {"", "/"}
                    or origin.query or origin.fragment or origin.username or origin.password):
                raise ValueError("public_origin must be an HTTPS origin without a path.")
        if not (1 <= self.max_agents <= 16 and 1 <= self.agent_max_steps <= 30 and 1 <= self.max_model_calls <= 200):
            raise ValueError("Invalid A2A agent/model call limits.")
        if not (256 <= self.ai_max_output_tokens <= 16384 and 8000 <= self.ai_context_chars <= 250000
                and self.ai_max_output_tokens <= self.max_job_output_tokens <= 3276800
                and 1 <= self.max_repeated_tool_errors <= 10):
            raise ValueError("Invalid model output, context or repeated-error limits.")
        if (not isinstance(self.auto_browser_actions, list)
                or any(not isinstance(action, str) for action in self.auto_browser_actions)
                or not set(self.auto_browser_actions) <= {"fill", "select"}):
            raise ValueError("Only owner-configured fill/select actions may bypass approval in auto mode.")
        if (not isinstance(self.role_models, dict)
                or not self.role_models.keys() <= {"orchestrator", "writer", "browser", "editor", "reviewer"}
                or any(not isinstance(value, str) or not value.strip() or len(value) > 160
                       or any(ord(c) < 32 for c in value) for value in self.role_models.values())):
            raise ValueError("role_models must map fixed agent roles to valid configured endpoint model names.")
        if self.studio_base_url:
            parsed = urlsplit(self.studio_base_url)
            local = parsed.hostname in {"localhost", "127.0.0.1", "::1", "studio-api", "host.docker.internal"}
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
                    or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                    or parsed.scheme == "http" and not local or len(self.studio_api_token) < 32):
                raise ValueError("Studio requires an HTTPS origin (or local service) and a token of at least 32 characters.")
        elif self.studio_api_token:
            raise ValueError("Configure a Studio origin with the Studio token.")
        if self.a2a_api_key:
            if len(self.a2a_api_key) < 32:
                raise ValueError("A2A API key must have at least 32 characters.")
            validate_agent_url(self.a2a_base_url)
        if self.rag_base_url:
            parsed = urlsplit(self.rag_base_url)
            local = parsed.hostname in {"localhost", "127.0.0.1", "::1", "rag-api", "host.docker.internal"}
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                    or parsed.password or parsed.path not in {"", "/"} or parsed.query
                    or parsed.fragment or (parsed.scheme == "http" and not local)
                    or len(self.rag_api_token) < 32):
                raise ValueError("RAG requires a local or HTTPS origin and 32+ character token.")
        elif self.rag_api_token:
            raise ValueError("RAG token requires rag_base_url.")
        if not isinstance(self.mcp_servers, list) or len(self.mcp_servers) > 8:
            raise ValueError("Maximum eight administrator-configured MCP servers.")
        mcp_ids = set()
        for server in self.mcp_servers:
            if not isinstance(server, dict):
                raise ValueError("MCP server configuration must be a dictionary.")
            sid, url, names = server.get("id"), server.get("url"), server.get("read_tools")
            if (not isinstance(sid, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", sid)
                    or sid in mcp_ids or not isinstance(url, str)):
                raise ValueError("MCP servers require unique IDs and valid URLs.")
            parsed = urlsplit(url)
            local = parsed.hostname in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
            if (parsed.scheme not in {"https", "http"} or not parsed.hostname
                    or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or (parsed.scheme == "http" and not local)):
                raise ValueError("MCP endpoint requires HTTPS except approved loopback hosts.")
            if (not isinstance(names, list) or not names or len(names) > 30
                    or any(not isinstance(n, str)
                           or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,79}", n) for n in names)
                    or len(names) != len(set(names))):
                raise ValueError("MCP read_tools must be an explicit unique allowlist.")
            if not isinstance(server.get("api_token", ""), str):
                raise ValueError("MCP server api_token must be a string.")
            mcp_ids.add(sid)
        peer_ids = set()
        if len(self.a2a_peers) > 8:
            raise ValueError("Maximum eight configured remote agents.")
        for peer in self.a2a_peers:
            if (not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", peer.get("id", ""))
                    or peer["id"] in peer_ids):
                raise ValueError("Remote agent IDs must be unique slugs.")
            validate_agent_url(peer.get("card_url", ""))
            peer_ids.add(peer["id"])

    def redact(self, value: str) -> str:
        for secret in (self.ai_api_key, self.telegram_bot_token, self.session_secret, self.a2a_api_key, self.studio_api_token, self.rag_api_token,
                       *(peer.get("api_key", "") for peer in self.a2a_peers),
                       *(server.get("api_token", "") for server in self.mcp_servers if isinstance(server, dict))):
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value


def load_settings(directory: Path) -> Settings:
    settings = Settings(**json.loads((directory / "config.json").read_text()))
    # Optional environment overrides support server secret managers; never printed.
    settings.ai_api_key = os.environ.get("CLOUDBROWSER_AI_API_KEY", settings.ai_api_key)
    settings.telegram_bot_token = os.environ.get(
        "CLOUDBROWSER_TELEGRAM_BOT_TOKEN", settings.telegram_bot_token
    )
    settings.public_origin = os.environ.get("CLOUDBROWSER_PUBLIC_ORIGIN", settings.public_origin)
    settings.a2a_api_key = os.environ.get("CLOUDBROWSER_A2A_API_KEY", settings.a2a_api_key)
    settings.studio_base_url = os.environ.get("CLOUDBROWSER_STUDIO_URL", settings.studio_base_url)
    settings.studio_api_token = os.environ.get("CLOUDBROWSER_STUDIO_TOKEN", settings.studio_api_token)
    settings.rag_base_url = os.environ.get("CLOUDBROWSER_RAG_URL", settings.rag_base_url)
    settings.rag_api_token = os.environ.get("CLOUDBROWSER_RAG_TOKEN", settings.rag_api_token)
    if settings.public_origin:
        settings.secure_cookie = True
    settings.validate()
    return settings


def validate_agent_url(url: str) -> None:
    parsed = urlsplit(url)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.scheme not in {"https", "http"} or (parsed.scheme == "http" and not local)):
        raise ValueError("A2A URLs require HTTPS; HTTP is allowed only for explicitly configured local endpoints.")


def configure_studio(directory: Path) -> None:
    if not sys.stdin.isatty():
        raise ValueError("Studio configuration requires an interactive terminal.")
    settings = load_settings(directory)
    settings.studio_base_url = input(f"Studio URL [{settings.studio_base_url or 'http://127.0.0.1:8001'}]: ").strip() or settings.studio_base_url or "http://127.0.0.1:8001"
    settings.studio_api_token = getpass.getpass("Studio token (minimal 32 karakter; Enter: pertahankan): ") or settings.studio_api_token
    save_settings(directory, settings)
    print("Studio tersimpan. Restart server untuk menerapkannya.")


def configure_a2a(directory: Path) -> None:
    if not sys.stdin.isatty():
        raise ValueError("A2A configuration requires an interactive terminal.")
    settings = load_settings(directory)
    print("Agent lokal A2A aktif. Isi pengaturan berikut untuk menerima tugas dari agent eksternal.")
    settings.a2a_base_url = input(f"URL server A2A [{settings.a2a_base_url}]: ").strip() or settings.a2a_base_url
    settings.a2a_api_key = getpass.getpass("A2A bearer key (minimal 32 karakter; Enter: pertahankan): ") or settings.a2a_api_key
    save_settings(directory, settings)
    print("Pengaturan A2A tersimpan. Restart server untuk menerapkannya.")


def save_settings(directory: Path, settings: Settings) -> None:
    settings.validate()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    fd, name = tempfile.mkstemp(prefix=".config-", dir=directory)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(asdict(settings), file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, directory / "config.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)


def configure(directory: Path, if_missing: bool = False) -> Settings:
    if if_missing and (directory / "config.json").exists():
        return load_settings(directory)
    if not sys.stdin.isatty():
        raise ValueError("First run needs a terminal: run 'python -m cloudbrowser configure'.")
    old = load_settings(directory) if (directory / "config.json").exists() else Settings()
    print("\nCloudbrowser — konfigurasi server (rahasia tidak ditampilkan)\n")
    print("Gunakan API kompatibel Chat Completions dengan tool calling.")
    print("Base URL mencakup /v1 jika penyedia memerlukannya; jangan tambahkan /chat/completions.")

    def ask(label: str, default: str = "") -> str:
        return input(f"{label}" + (f" [{default}]" if default else "") + ": ").strip() or default

    old.ai_base_url = ask("AI base URL", old.ai_base_url)
    old.ai_model = ask("Nama model AI", old.ai_model)
    old.ai_api_key = getpass.getpass("API key AI (Enter: pertahankan/kosong untuk lokal): ") or old.ai_api_key
    old.ai_vision = ask("Model mendukung gambar? y/n", "y" if old.ai_vision else "n").lower() == "y"
    old.telegram_bot_token = (
        getpass.getpass("Telegram bot token dari @BotFather (Enter: pertahankan): ")
        or old.telegram_bot_token
    )
    owner_id = ask("ID numerik Telegram pemilik (kosong: pairing melalui bot)", str(old.telegram_owner_id or ""))
    if owner_id:
        old.telegram_owner_id = int(owner_id)
    else:
        import asyncio
        old.telegram_owner_id = asyncio.run(pair_owner(old.telegram_bot_token))
    password = getpass.getpass("Password dashboard (minimal 12 karakter; Enter: pertahankan): ")
    if password:
        if len(password) < 12 or password != getpass.getpass("Ulangi password dashboard: "):
            raise ValueError("Password harus cocok dan minimal 12 karakter.")
        old.dashboard_password_hash = password_hash(password)
        old.session_secret = secrets.token_hex(32)
    old.allowed_domains = [
        x.strip().lower() for x in ask("Domain navigasi yang diizinkan", ",".join(old.allowed_domains)).split(",")
    ]
    old.headless = ask("Jalankan tanpa layar virtual? y/n", "y" if old.headless else "n").lower() == "y"
    old.bind_host = ask("Bind host (Docker: 0.0.0.0; native: 127.0.0.1)", old.bind_host)
    print("Mode awal: approve. Mode auto tetap meminta persetujuan untuk klik, unggah, keyboard, dan delegasi remote.")
    old.approval_mode = "approve"
    save_settings(directory, old)
    if (directory / "state.sqlite3").exists():
        from .store import Store
        state = Store(directory)
        try:
            state.set("approval_mode", "approve")
        finally:
            state.close()
    print("Konfigurasi tersimpan. Mulai server lalu kirim /start ke bot Telegram Anda.")
    return old


async def pair_owner(token: str) -> int:
    import secrets

    from .telegram import TelegramClient
    client = TelegramClient(token)
    try:
        me = await client.call("getMe")
        if (await client.call("getWebhookInfo")).get("url"):
            raise ValueError("Bot memiliki webhook aktif; gunakan bot khusus untuk Cloudbrowser.")
        code = secrets.token_hex(8)
        print(f"Buka https://t.me/{me['username']} dan kirim: /pair {code}")
        print("Kode hanya berlaku selama proses konfigurasi ini (maksimal tiga menit).")
        stale = await client.call("getUpdates", {"offset": -1, "timeout": 0, "allowed_updates": ["message"]})
        offset, deadline = (stale[-1]["update_id"] + 1 if stale else 0), time.monotonic() + 180
        while time.monotonic() < deadline:
            updates = await client.call("getUpdates", {"offset": offset, "timeout": 20, "allowed_updates": ["message"]})
            for update in updates:
                offset = update["update_id"] + 1
                message = update.get("message", {})
                user, chat = message.get("from", {}), message.get("chat", {})
                if (message.get("text", "").strip() == f"/pair {code}"
                        and chat.get("type") == "private" and chat.get("id") == user.get("id")
                        and isinstance(user.get("id"), int) and user["id"] > 0
                        and not user.get("is_bot")):
                    print(f"Akun Telegram terpasang: {user['id']}.")
                    return user["id"]
        raise ValueError("Pairing kedaluwarsa. Jalankan configure kembali.")
    finally:
        await client.close()
