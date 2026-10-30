from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from a2a.client import ClientConfig, create_client
from a2a.client.transports.jsonrpc import JsonRpcTransport
from a2a.types import (
    AgentCard,
    CancelTaskRequest,
    GetTaskRequest,
    Message,
    Part,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
)
from a2a.utils.errors import A2AError
from conftest import FakeAI, StubBrowser, tool_call
from google.protobuf.json_format import ParseDict

from cloudbrowser.web import create_app


def enable(settings):
    settings.a2a_api_key = "TEST_ONLY_OWNER_A2A_KEY_12345678901234567890"
    settings.a2a_base_url = "http://127.0.0.1:8000"
    return {"Authorization": "Bearer " + settings.a2a_api_key, "A2A-Version": "1.0"}


def message(text="Write a short ARUSIA scene.", message_id="message-1", task_id=""):
    return SendMessageRequest(message=Message(role=Role.ROLE_USER, message_id=message_id, task_id=task_id,
                                            parts=[Part(text=text)]),
                              configuration=SendMessageConfiguration(return_immediately=True))


async def test_official_sdk_discovers_sends_gets_and_cancels_nonblocking_task(settings, tmp_path):
    headers = enable(settings)
    app = create_app(settings, tmp_path, start_services=False, ai=FakeAI(), browser=StubBrowser())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.a2a_base_url, headers=headers) as http:
        response = await http.get("/.well-known/agent-card.json")
        assert response.status_code == 200
        agent_card = ParseDict(response.json(), AgentCard())
        assert agent_card.supported_interfaces[0].protocol_version == "1.0"
        sdk = JsonRpcTransport(http, agent_card, agent_card.supported_interfaces[0].url)
        first = await sdk.send_message(message())
        duplicate = await sdk.send_message(message())
        assert first.task.id == duplicate.task.id
        assert len(app.state.store.jobs()) == 1
        assert (await sdk.get_task(GetTaskRequest(id=first.task.id))).id == first.task.id
        canceled = await sdk.cancel_task(CancelTaskRequest(id=first.task.id))
        assert canceled.status.state == 5
        with pytest.raises(A2AError):
            await sdk.send_message(message(message_id="resume", task_id=first.task.id))
    await app.state.agent.close()
    app.state.store.close()


async def test_sdk_factory_and_default_blocking_request_return_completed_task(settings, tmp_path):
    headers = enable(settings)
    app = create_app(settings, tmp_path, start_services=False, ai=FakeAI(), browser=StubBrowser())
    await app.state.agent.start()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.a2a_base_url, headers=headers) as http:
            agent_card = ParseDict((await http.get("/.well-known/agent-card.json")).json(), AgentCard())
            client = await create_client(agent_card, ClientConfig(streaming=False, httpx_client=http,
                                                                  supported_protocol_bindings=["JSONRPC"]))
            request = message()
            request.configuration.return_immediately = False
            async def send():
                return [chunk async for chunk in client.send_message(request)]
            chunks = await asyncio.wait_for(send(), 5)
            assert chunks[-1].HasField("task")
            assert chunks[-1].task.status.state == 3
    finally:
        await app.state.agent.close()
        app.state.store.close()


async def test_rpc_and_file_endpoints_require_bearer_and_bound_payload(settings, tmp_path):
    headers = enable(settings)
    app = create_app(settings, tmp_path, start_services=False, ai=FakeAI(), browser=StubBrowser())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.a2a_base_url) as http:
        assert (await http.post("/a2a/rpc", json={})).status_code == 401
        assert (await http.get("/a2a/artifacts/anything")).status_code == 401
        assert (await http.post("/a2a/rpc", content=b"x" * 262145, headers=headers)).status_code == 413
        assert (await http.post("/a2a/rpc", json={}, headers=headers | {"Origin": "https://evil.example"})).status_code == 403
        invalid = await http.post("/a2a/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {}}, headers=headers)
        assert "error" in invalid.json()
    await app.state.agent.close()
    app.state.store.close()


async def test_external_protocol_is_off_until_configured(settings, tmp_path):
    app = create_app(settings, tmp_path, start_services=False, ai=FakeAI(), browser=StubBrowser())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as http:
        assert (await http.get("/.well-known/agent-card.json")).status_code == 404
        assert (await http.post("/a2a/rpc", json={})).status_code == 404
    await app.state.agent.close()
    app.state.store.close()


async def test_dynamic_specialist_endpoint_returns_actual_scoped_artifact(settings, tmp_path):
    headers = enable(settings)
    ai = FakeAI(tool_call("write_text_artifact", {"filename": "scene.md", "content": "ARUSIA scene output."}),
                {"role": "assistant", "content": "Draft ready for review."})
    app = create_app(settings, tmp_path, start_services=False, ai=ai, browser=StubBrowser())
    app.state.store.set_project("private", "PRIVATE OWNER BRIEF")
    private = app.state.store.create_job("PRIVATE OWNER GOAL", project_id="private")
    app.state.store.update_job(private["id"], status="completed", result="PRIVATE OWNER RESULT")
    app.state.agent.crew.create({"id": "writer", "name": "Writer", "profile": "writer", "instructions": "Write scene scripts and save artifacts."})
    await app.state.agent.start()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=settings.a2a_base_url, headers=headers) as http:
            agent_card = ParseDict((await http.get("/a2a/agents/writer/.well-known/agent-card.json")).json(), AgentCard())
            sdk = JsonRpcTransport(http, agent_card, agent_card.supported_interfaces[0].url)
            request = message()
            request.configuration.return_immediately = False
            reply = await asyncio.wait_for(sdk.send_message(request), 5)
            assert reply.task.status.state == 3 and reply.task.artifacts
            assert app.state.store.job(reply.task.id)["project_id"].startswith("a2a-")
            assert "PRIVATE OWNER" not in json.dumps(ai.requests)
            file = await http.get(reply.task.artifacts[0].parts[0].url)
            assert file.status_code == 200 and "ARUSIA" in file.text
            wrong_endpoint = await http.post("/a2a/rpc", json={"jsonrpc": "2.0", "id": "get", "method": "GetTask", "params": {"id": reply.task.id}})
            assert wrong_endpoint.json()["error"]["code"] == -32001
    finally:
        await app.state.agent.close()
        app.state.store.close()
