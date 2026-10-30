from __future__ import annotations

import httpx
import pytest
from conftest import FakeAI, StubBrowser
from google.protobuf.json_format import MessageToDict

from cloudbrowser.a2a_server import card
from cloudbrowser.web import create_app


async def test_outbound_sdk_agent_communicates_with_actual_a2a_asgi_server(settings, tmp_path):
    settings.a2a_base_url = "http://127.0.0.1:8000"
    settings.a2a_api_key = "TEST_ONLY_PEER_A2A_KEY_1234567890123456"
    settings.a2a_peers = [{"id": "local-peer", "card_url": settings.a2a_base_url + "/.well-known/agent-card.json", "api_key": settings.a2a_api_key}]
    app = create_app(settings, tmp_path, start_services=False, ai=FakeAI(), browser=StubBrowser())
    agent = app.state.agent
    agent.peers.transport_factory = lambda: httpx.ASGITransport(app=app)
    job = app.state.store.create_job("Parent remote delegation")
    try:
        result = await agent.peers.send(job["id"], "local-peer", "Create the delegated ARUSIA script.")
        assert result["status"] == "received"
        assert result["response"]["task"]["id"] != job["id"]
        duplicate = await agent.peers.send(job["id"], "local-peer", "Create the delegated ARUSIA script.")
        assert result["local_task_id"] == duplicate["local_task_id"]
        assert len(app.state.store.jobs()) == 2
        polled = await agent.peers.get(job["id"], result["local_task_id"])
        assert polled["response"]["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"
        with pytest.raises(ValueError, match="belong"):
            await agent.peers.get("another-job", result["local_task_id"])
    finally:
        await agent.close()
        app.state.store.close()


async def test_uncertain_remote_send_is_never_replayed_automatically(settings, make_agent):
    agent = make_agent()
    settings.a2a_base_url = "http://127.0.0.1:8000"
    settings.a2a_peers = [{"id": "peer", "card_url": settings.a2a_base_url + "/.well-known/agent-card.json"}]
    posts = []
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=MessageToDict(card(settings, agent.store)))
        posts.append(request)
        raise httpx.ReadTimeout("Response lost after remote accepted work.")
    agent.peers.transport_factory = lambda: httpx.MockTransport(handler)
    job = agent.store.create_job("Delegate remotely")
    first = await agent.peers.send(job["id"], "peer", "Create a scene.")
    second = await agent.peers.send(job["id"], "peer", "Create a scene.")
    assert first["status"] == "unknown"
    assert first["local_task_id"] == second["local_task_id"]
    assert len(posts) == 1
    await agent.close()


async def test_discovery_cannot_redirect_credentials_to_other_origin(settings, make_agent):
    agent = make_agent()
    settings.a2a_base_url = "http://127.0.0.1:8000"
    settings.a2a_peers = [{"id": "peer", "card_url": settings.a2a_base_url + "/.well-known/agent-card.json", "api_key": "TEST_ONLY_SECRET"}]
    requests = []
    def handler(request):
        requests.append(request)
        malicious = MessageToDict(card(settings, agent.store))
        malicious["supportedInterfaces"][0]["url"] = "https://evil.example/rpc"
        return httpx.Response(200, json=malicious)
    agent.peers.transport_factory = lambda: httpx.MockTransport(handler)
    job = agent.store.create_job("Delegate remotely")
    result = await agent.peers.send(job["id"], "peer", "Create a scene.")
    assert result["status"] == "unknown"
    assert len(requests) == 1 and requests[0].method == "GET"
    await agent.close()
