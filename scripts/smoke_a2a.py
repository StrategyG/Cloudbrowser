"""Actual loopback HTTP/SDK smoke test, using an explicit deterministic AI stub.

No live AI, Telegram, Google or CapCut credentials are used. No browser binary is needed.
"""
from __future__ import annotations

import asyncio
import json
import socket
import tempfile
from pathlib import Path

import httpx
import uvicorn
from a2a.client.transports.jsonrpc import JsonRpcTransport
from a2a.types import (
    AgentCard,
    GetTaskRequest,
    Message,
    Part,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
)
from google.protobuf.json_format import ParseDict

from cloudbrowser.config import Settings, password_hash
from cloudbrowser.web import create_app


class StubBrowser:
    context = None
    last_error = ""

    async def snapshot(self):
        return {"url": "about:blank", "elements": []}

    async def close(self):
        pass


class StubModel:
    def __init__(self):
        self.turn = 0

    async def complete(self, messages, tools):
        self.turn += 1
        if self.turn == 1:
            return {"role": "assistant", "content": None, "tool_calls": [
                {"id": "write-1", "type": "function", "function": {"name": "write_text_artifact", "arguments": json.dumps(
                    {"filename": "scene.md", "content": "ARUSIA: Kio dan Lumi membuka garasi."})}}]}
        return {"role": "assistant", "content": "The script artifact is ready for caller review."}

    async def close(self):
        pass


async def main():
    with tempfile.TemporaryDirectory(prefix="cloudbrowser-a2a-smoke-") as temp:
        with socket.socket() as socket_probe:
            socket_probe.bind(("127.0.0.1", 0))
            port = socket_probe.getsockname()[1]
        settings = Settings(ai_base_url="http://127.0.0.1:9/v1", ai_model="deterministic-stub",
                            dashboard_password_hash=password_hash("test-only-dashboard-password"),
                            telegram_enabled=False, headless=True, a2a_base_url=f"http://127.0.0.1:{port}",
                            a2a_api_key="TEST_ONLY_LOOPBACK_OWNER_KEY_1234567890123")
        app = create_app(settings, Path(temp), ai=StubModel(), browser=StubBrowser())
        app.state.agent.crew.create({"id": "writer", "name": "Script writer", "profile": "writer",
                                     "instructions": "Write ARUSIA scene scripts and save real artifacts."})
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                               log_level="error", access_log=False, proxy_headers=False))
        server_task = asyncio.create_task(server.serve())
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(.02)
            else:
                raise RuntimeError("Loopback test server did not start.")
            # Direct local test only: no third-party destination or proxy/network-policy bypass.
            async with httpx.AsyncClient(base_url=settings.a2a_base_url, trust_env=False,
                headers={"Authorization": "Bearer " + settings.a2a_api_key, "A2A-Version": "1.0"}) as http:
                assert (await http.get("/healthz")).status_code == 200
                assert (await http.get("/api/state")).status_code == 401
                login = await http.post("/api/login", json={"password": "test-only-dashboard-password"})
                assert login.status_code == 200
                assert (await http.get("/api/state")).status_code == 200
                card = ParseDict((await http.get("/a2a/agents/writer/.well-known/agent-card.json")).json(), AgentCard())
                client = JsonRpcTransport(http, card, card.supported_interfaces[0].url)
                reply = await client.send_message(SendMessageRequest(
                    message=Message(role=Role.ROLE_USER, message_id="smoke-1", parts=[Part(text="Write an ARUSIA scene.")]),
                    configuration=SendMessageConfiguration(return_immediately=True)))
                task = reply.task
                for _ in range(100):
                    task = await client.get_task(GetTaskRequest(id=task.id))
                    if task.status.state not in {1, 2}:
                        break
                    await asyncio.sleep(.02)
                assert task.status.state == 3, task.status.message
                assert task.artifacts
                artifact = await http.get(task.artifacts[0].parts[0].url)
                assert artifact.status_code == 200 and "ARUSIA" in artifact.text
                details = (await http.get("/api/jobs/" + task.id)).json()
                assert details["project_id"].startswith("a2a-")
                assert details["budget"]["model_calls"] == 2
                print("Actual HTTP: liveness, protected dashboard, password login, scoped job/budget inspection: PASS")
                print("A2A 1.0 actual HTTP: discovery, authenticated SendMessage, task polling, real artifact download: PASS")
        finally:
            server.should_exit = True
            await asyncio.wait_for(server_task, 10)


if __name__ == "__main__":
    asyncio.run(main())
