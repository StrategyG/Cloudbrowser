from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from .agent import Agent
from .artifacts import Artifacts
from .browser import Browser
from .config import Settings, password_matches
from .llm import AIClient
from .media import Media
from .store import Store
from .telegram import TelegramService
from .tools import TOOL_MAP, Input

COOKIE = "cloudbrowser_session"


class Goal(Input):
    text: str = Field(min_length=1, max_length=12000)


class NewGoal(Goal):
    project_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    # Supplied by the client for retry-safe POST. Omitted keys create new jobs.
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128,
                                        pattern=r"^[A-Za-z0-9:_-]+$")


class Project(Input):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    brief: str | None = Field(default=None, max_length=8000)


class Login(Input):
    password: str = Field(min_length=1, max_length=1024)


class Decision(Input):
    approved: bool


class Mode(Input):
    mode: Literal["auto", "approve"]


class Manual(Input):
    kind: Literal["navigate", "coordinate_click", "drag", "type", "press", "scroll", "tab", "new_tab"]
    args: dict = Field(default_factory=dict)


class Sessions:
    def __init__(self, settings: Settings, store: Store):
        self.settings = settings
        self.store = store
        self.failures: dict[str, list[float]] = defaultdict(list)

    def sign(self, text: str) -> str:
        return hmac.new(self.settings.session_secret.encode(), text.encode(), hashlib.sha256).hexdigest()

    def issue(self) -> str:
        value = f"{int(time.time())}.{secrets.token_hex(24)}"
        return f"{value}.{self.sign(value)}"

    def valid(self, cookie: str) -> bool:
        try:
            timestamp, nonce, signature = cookie.split(".")
            age = time.time() - int(timestamp)
            return (0 <= age <= 12 * 3600
                    and hmac.compare_digest(signature, self.sign(f"{timestamp}.{nonce}"))
                    and not self.store.get("revoked:" + self.sign(cookie)))
        except (ValueError, TypeError):
            return False

    def origin(self, request: Request) -> None:
        origin = request.headers.get("origin")
        expected = self.settings.public_origin or str(request.base_url)
        if origin and origin.rstrip("/") != expected.rstrip("/"):
            raise HTTPException(403, "Cross-origin request blocked.")

    def require(self, request: Request) -> str:
        cookie = request.cookies.get(COOKIE, "")
        if not self.valid(cookie):
            raise HTTPException(401, "Login diperlukan.")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            self.origin(request)
            if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), self.sign("csrf:" + cookie)):
                raise HTTPException(403, "CSRF token required.")
        return cookie


def create_app(settings: Settings, directory: Path, *, start_services: bool = True,
               ai: AIClient | None = None, browser: Browser | None = None) -> FastAPI:
    store = Store(directory)
    artifacts = Artifacts(directory, store, settings.max_upload_mb)
    browser = browser or Browser(settings, directory, artifacts)
    ai = ai or AIClient(settings)
    agent = Agent(settings, store, browser, artifacts, ai, Media(artifacts))
    telegram = TelegramService(settings, store, agent, artifacts) if settings.telegram_enabled else None
    sessions = Sessions(settings, store)

    @asynccontextmanager
    async def lifespan(_app):
        lock = None
        try:
            if start_services:
                from .process_lock import ProcessLock
                lock = ProcessLock(directory / "server.lock")
                lock.acquire()
                await agent.start()
                if telegram:
                    try:
                        await telegram.start()
                    except Exception as exc:
                        telegram.last_error = settings.redact(str(exc))[:1000]
                        store.event(None, "telegram_start_error", telegram.last_error)
            yield
        finally:
            await agent.close()
            if telegram:
                await telegram.close()
            store.close()
            if lock:
                lock.release()

    app = FastAPI(title="Cloudbrowser", version="0.4.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.agent, app.state.store, app.state.sessions = agent, store, sessions
    app.state.artifacts, app.state.telegram = artifacts, telegram
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.middleware("http")
    async def headers(request: Request, call_next):
        if request.url.path.startswith("/a2a/") and not request.url.path.endswith("/.well-known/agent-card.json"):
            if not settings.a2a_api_key:
                return JSONResponse({"detail": "External A2A is not configured."}, status_code=404)
            if not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer " + settings.a2a_api_key):
                return JSONResponse({"detail": "A2A bearer authentication required."}, status_code=401,
                                    headers={"WWW-Authenticate": "Bearer"})
            if request.headers.get("origin"):
                return JSONResponse({"detail": "Use the owner dashboard for browser-origin requests."}, status_code=403)
            body = b""
            async for chunk in request.stream():
                body += chunk
                if len(body) > 262144:
                    return JSONResponse({"detail": "A2A payload exceeds 256 KiB."}, status_code=413)
            request._body = body
        response = await call_next(request)
        if request.url.path == "/studio/morphglb":
            # Sandboxed even on direct navigation: third-party editor code has an opaque
            # origin and cannot access dashboard cookies, CSRF tokens or owner APIs.
            response.headers["Content-Security-Policy"] = (
                "sandbox allow-scripts allow-downloads; default-src 'none'; "
                "script-src 'unsafe-inline' 'wasm-unsafe-eval' blob:; "
                "style-src 'unsafe-inline'; img-src data: blob:; "
                "media-src blob:; worker-src blob:; font-src data:; "
                "connect-src blob: data:; object-src 'none'; frame-ancestors 'self'; "
                "base-uri 'none'; form-action 'none'"
            )
        else:
            response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def value_error(_request, exc):
        return JSONResponse({"detail": settings.redact(str(exc))[:1500]}, status_code=400)

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def ready():
        healthy = not telegram or (telegram.task and not telegram.task.done() and time.time() - telegram.last_poll < 90)
        return JSONResponse({"ready": bool(healthy)}, status_code=200 if healthy else 503)

    @app.post("/api/login")
    def login(body: Login, request: Request, response: Response):
        sessions.origin(request)
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        sessions.failures[ip] = [value for value in sessions.failures[ip] if now - value < 300]
        if len(sessions.failures[ip]) >= 5:
            raise HTTPException(429, "Terlalu banyak percobaan. Tunggu lima menit.")
        if not password_matches(body.password, settings.dashboard_password_hash):
            sessions.failures[ip].append(now)
            raise HTTPException(401, "Password tidak cocok.")
        sessions.failures.pop(ip, None)
        cookie = sessions.issue()
        response.set_cookie(COOKIE, cookie, httponly=True, secure=settings.secure_cookie,
                            samesite="strict", max_age=12 * 3600, path="/")
        return {"csrf_token": sessions.sign("csrf:" + cookie)}

    @app.get("/api/session")
    def session(cookie: str = Depends(sessions.require)):
        return {"csrf_token": sessions.sign("csrf:" + cookie)}

    @app.post("/api/logout")
    def logout(response: Response, cookie: str = Depends(sessions.require)):
        store.set("revoked:" + sessions.sign(cookie), "1")
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/state", dependencies=[Depends(sessions.require)])
    def state():
        project_id = store.get("current_project", "default")
        return {
            "model": settings.ai_model, "vision": settings.ai_vision, "mode": agent.mode,
            "agents": [{k: v for k, v in definition.items() if k != "instructions"} for definition in store.agents()],
            "a2a_external_enabled": bool(settings.a2a_api_key),
            "studio_enabled": agent.studio.enabled,
            "active_job": agent.active_job, "jobs": store.jobs(),
            "project": {"id": project_id, "brief": store.get("project_brief:" + project_id, "")},
            "unresolved_actions": store.actions(unresolved=True),
            "approvals": store.pending_approvals(), "artifacts": store.artifacts(),
            "telegram": {"enabled": bool(telegram), "username": telegram.username if telegram else "",
                         "error": telegram.last_error if telegram else "",
                         "connected": bool(telegram and telegram.task and not telegram.task.done()
                                           and time.time() - telegram.last_poll < 90)},
            "browser_error": browser.last_error,
            "tabs": [{"index": i, "url": p.url} for i, p in enumerate(browser.context.pages)] if browser.context else [],
        }

    @app.get("/studio", dependencies=[Depends(sessions.require)])
    def studio_editor():
        return FileResponse(static / "studio.html")

    @app.get("/studio/morphglb", dependencies=[Depends(sessions.require)])
    def morphglb_editor():
        # Deliberately outside /static: raw editor must not be publicly fetchable.
        document = Path(__file__).parent / "morphglb" / "MorphGLB_AI_Studio_v3.3.0.html"
        return FileResponse(document, media_type="text/html")

    @app.get("/api/studio/projects/{project_id}", dependencies=[Depends(sessions.require)])
    async def studio_project(project_id: str):
        return await agent.studio.execute("studio_get_project", {"project_id": project_id})

    @app.get("/api/studio/projects/{project_id}/assets/{kind}", dependencies=[Depends(sessions.require)])
    async def studio_preview(project_id: str, kind: str):
        from .studio_client import ASSETS
        if kind not in ASSETS:
            raise HTTPException(404, "Studio asset unavailable.")
        route = agent.studio.route(project_id)
        content = await agent.studio.request("GET", route + "/assets/" + kind, binary=True)
        suffix = ASSETS[kind]
        mime = {".png": "image/png", ".json": "application/json", ".mp4": "video/mp4", ".glb": "model/gltf-binary"}[suffix]
        return Response(content, media_type=mime)

    @app.post("/api/jobs", dependencies=[Depends(sessions.require)])
    async def create_job(body: NewGoal):
        if body.project_id and body.project_id.startswith("a2a-"):
            raise ValueError("The a2a- project prefix is reserved.")
        job = agent.enqueue(body.text, request_key=("web:" + body.idempotency_key) if body.idempotency_key else None,
                            project_id=body.project_id)
        return {"id": job["id"], "status": job["status"]}

    @app.get("/api/jobs/{job_id}", dependencies=[Depends(sessions.require)])
    def get_job(job_id: str):
        job = store.job(job_id)
        tasks = [{k: v for k, v in row.items() if k != "messages"} for row in store.agent_tasks(job_id)]
        return {k: v for k, v in job.items() if k != "messages"} | {"events": store.events(job_id),
                  "workflow": store.workflow(job_id), "agent_tasks": tasks,
                  "actions": store.actions(job_id), "budget": store.model_budget(job_id),
                  "model_limits": {"calls": settings.max_model_calls, "output_tokens": settings.max_job_output_tokens},
                  "final_review": json.loads(store.get("final_review:" + job_id, "{}")),
                  "model_calls": int(store.get("model_calls:" + job_id, "0"))}

    @app.post("/api/project", dependencies=[Depends(sessions.require)])
    async def project(body: Project):
        store.set_project(body.id, settings.redact(body.brief) if body.brief is not None else None)
        return {"id": body.id, "brief": store.get("project_brief:" + body.id, "")}

    @app.post("/api/actions/{action_id}/resolve", dependencies=[Depends(sessions.require)])
    async def resolve_action(action_id: str, body: Decision):
        if agent.busy:
            raise HTTPException(409, "Hentikan job aktif sebelum memastikan hasil tindakan.")
        if not store.resolve_action(action_id, body.approved):
            raise HTTPException(409, "Tindakan sudah diperiksa atau tidak memiliki hasil yang belum pasti.")
        store.event(None, "owner_action_resolution", action_id + (": applied" if body.approved else ": not applied"))
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/resume", dependencies=[Depends(sessions.require)])
    async def resume(job_id: str, body: Goal):
        job = agent.resume(job_id, body.text)
        return {"id": job["id"], "status": job["status"]}

    @app.post("/api/jobs/{job_id}/stop", dependencies=[Depends(sessions.require)])
    async def stop(job_id: str):
        agent.stop(job_id)
        return {"ok": True}

    @app.post("/api/approvals/{approval_id}", dependencies=[Depends(sessions.require)])
    async def decide(approval_id: str, body: Decision):
        if not agent.decide(approval_id, body.approved):
            raise HTTPException(409, "Persetujuan sudah diproses atau kedaluwarsa.")
        return {"ok": True}

    @app.post("/api/mode", dependencies=[Depends(sessions.require)])
    async def mode(body: Mode):
        if agent.busy:
            raise HTTPException(409, "Hentikan job aktif sebelum mengubah mode.")
        store.set("approval_mode", body.mode)
        return {"mode": agent.mode}

    @app.get("/api/browser/screenshot", dependencies=[Depends(sessions.require)])
    async def screenshot():
        try:
            return Response(await browser.screenshot(), media_type="image/jpeg")
        except Exception:
            raise HTTPException(503, "Browser belum siap. Periksa Chromium, display/Xvfb dan konfigurasi sandbox.") from None

    @app.post("/api/browser/manual", dependencies=[Depends(sessions.require)])
    async def manual(body: Manual):
        if agent.control_lock.locked():
            raise HTTPException(409, "Hentikan job aktif, atau tunggu sampai AI meminta bantuan manual.")
        name = "browser_" + body.kind
        args = body.args.copy()
        if body.kind in {"coordinate_click", "drag", "type", "press", "scroll"}:
            args["snapshot_id"] = "manual"
        args = TOOL_MAP[name].model.model_validate(args).model_dump()
        async with agent.control_lock:
            return await browser.action(body.kind, args, manual=True)

    @app.put("/api/artifacts", dependencies=[Depends(sessions.require)])
    async def upload(request: Request, filename: str = "upload.bin"):
        artifact_id, path, filename = artifacts.allocate(filename)
        try:
            total = 0
            with path.open("wb") as file:
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > artifacts.max_bytes:
                        raise HTTPException(413, "File melebihi batas ukuran server.")
                    file.write(chunk)
            return artifacts.register(artifact_id, path, filename)
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    @app.get("/api/artifacts/{artifact_id}", dependencies=[Depends(sessions.require)])
    def download(artifact_id: str):
        return FileResponse(artifacts.path(artifact_id), filename=store.artifact(artifact_id)["filename"],
                            media_type="application/octet-stream")

    from .a2a_server import install_a2a
    install_a2a(app, settings, agent, store, artifacts)
    return app
