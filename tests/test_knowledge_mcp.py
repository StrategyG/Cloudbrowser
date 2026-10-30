"""MCP 2.x protocol acceptance, strict gateway policy and private RAG adapter."""
from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
import pytest
from mcp import Client
from mcp.server.mcpserver import MCPServer

from cloudbrowser.config import Settings
from cloudbrowser.mcp_gateway import MCPGateway
from cloudbrowser.rag_client import RAGClient
from cloudbrowser.tools import TOOL_MAP


async def test_real_mcp_sdk_inprocess_discovery_and_scoped_call(settings, monkeypatch):
    mcp = MCPServer("CloudbrowserTest")

    @mcp.tool()
    def search_notes(query: str, limit: int = 2) -> dict:
        return {"hits": [f"match: {query}"], "limit": limit}

    @mcp.tool()
    def delete_everything(confirm: bool) -> str:
        return "UNEXPECTED"

    admin = replace(settings, mcp_servers=[{
        "id": "knowledge", "url": "http://127.0.0.1:9999/mcp",
        "read_tools": ["search_notes"]}])
    gateway = MCPGateway(admin)

    @asynccontextmanager
    async def local(_server):
        async with Client(mcp, raise_exceptions=True) as client:
            yield client

    monkeypatch.setattr(gateway, "_connect", local)
    catalog = await gateway.list_tools("knowledge")
    assert [tool["name"] for tool in catalog["tools"]] == ["search_notes"]
    output = await gateway.call_readonly("knowledge", "search_notes",
                                         {"query": "rig", "limit": 2})
    assert output["untrusted"] is True
    assert "rig" in str(output["result"])
    with pytest.raises(ValueError, match="allowlist"):
        await gateway.call_readonly("knowledge", "delete_everything", {"confirm": True})
    with pytest.raises(Exception):
        await gateway.call_readonly("knowledge", "search_notes",
                                    {"query": "rig", "limit": "invalid"})
    with pytest.raises(ValueError, match="8000"):
        await gateway.call_readonly("knowledge", "search_notes",
                                    {"query": "x" * 9000})


def test_mcp_config_rejects_broad_or_untrusted_endpoints(settings):
    for remote in (
        {"id": "x", "url": "http://public.example/mcp", "read_tools": ["search"]},
        {"id": "x", "url": "https://user:pass@example.com/mcp", "read_tools": ["search"]},
        {"id": "x", "url": "https://example.com/mcp", "read_tools": []},
    ):
        with pytest.raises(ValueError):
            replace(settings, mcp_servers=[remote]).validate()
    settings.mcp_servers = [{"id": "safe", "url": "https://example.com/mcp",
                             "api_token": "synthetic-only-mcp-key",
                             "read_tools": ["search"]}]
    assert "synthetic-only-mcp-key" not in repr(settings)
    assert "synthetic-only-mcp-key" not in settings.redact("synthetic-only-mcp-key")
    settings.validate()
    assert TOOL_MAP["mcp_readonly_call"].approval
    assert TOOL_MAP["rag_ingest_artifact"].approval
    assert not TOOL_MAP["rag_search"].approval


async def test_rag_local_search_project_scoping_and_citations(settings):
    def response(request: httpx.Request):
        assert request.url.path == "/v1/search"
        assert request.headers["Authorization"] == "Bearer " + "k" * 32
        project = __import__("json").loads(request.content)["project_id"]
        return httpx.Response(200, json={"chunks": [{
            "project_id": project, "source_id": "a" * 32, "chunk_id": "000001",
            "sha256": "b" * 64, "text": "ARUSIA motion guide", "score": 0.8}]})

    settings.rag_base_url = "http://127.0.0.1:8090"
    settings.rag_api_token = "k" * 32
    client = httpx.AsyncClient(transport=httpx.MockTransport(response))
    rag = RAGClient(settings, client)
    result = await rag.search("arusia", "walk motion")
    assert result["chunks"][0]["project_id"] == "arusia"
    assert result["chunks"][0]["sha256"] == "b" * 64
    assert result["untrusted"]
    await rag.close()


async def test_rag_rejects_cross_project_results_and_ingests_exact_artifact(settings, tmp_path):
    settings.rag_base_url = "http://127.0.0.1:8090"
    settings.rag_api_token = "k" * 32
    payloads = []

    def response(request: httpx.Request):
        body = __import__("json").loads(request.content)
        payloads.append(body)
        if request.url.path == "/v1/search":
            return httpx.Response(200, json={"chunks": [{"project_id": "foreign", "text": "secret"}]})
        return httpx.Response(200, json={"indexed": True, "source_id": body["source_id"]})

    rag = RAGClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(response)))
    with pytest.raises(ValueError, match="authorization mismatch"):
        await rag.search("arusia", "query")
    file = tmp_path / "note.md"
    file.write_text("# RUX Garage\nApproved character reference.")
    result = await rag.ingest("arusia", "a" * 32, file)
    assert result["indexed"]
    assert payloads[-1]["sha256"] == hashlib.sha256(file.read_bytes()).hexdigest()
    assert payloads[-1]["project_id"] == "arusia"
    assert payloads[-1]["source_id"] == "a" * 32
    with pytest.raises(ValueError, match="Only PDF"):
        await rag.ingest("arusia", "a" * 32, tmp_path / "not-found.bin")
    await rag.close()


async def test_mcp_owner_approval_blocks_unauthorized_call(make_agent, monkeypatch):
    from conftest import tool_call

    agent = make_agent(tool_call("mcp_readonly_call", {
        "server_id": "knowledge", "tool_name": "search_notes",
        "arguments": {"query": "arusia"}}))
    called = []

    async def fake_call(*args):
        called.append(args)
        return {"result": {"hits": ["ok"]}, "untrusted": True}

    monkeypatch.setattr(agent.mcp_gateway, "call_readonly", fake_call)
    await agent.start()
    try:
        job = agent.enqueue("Look up motion reference")
        async def wait():
            while not agent.store.pending_approvals():
                await asyncio.sleep(.01)
        await asyncio.wait_for(wait(), 5)
        assert not called
        approval = agent.store.pending_approvals()[0]
        assert agent.decide(approval["id"], True)
        await asyncio.wait_for(agent.queue.join(), 5)
        assert len(called) == 1
        assert agent.store.job(job["id"])["status"] == "completed"
        assert agent.store.actions(job["id"])[0]["status"] == "applied"
    finally:
        await agent.close()
