"""Real network acceptance for MCP Streamable HTTP, not monkeypatched in-process."""
from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
from dataclasses import replace

import pytest

from cloudbrowser.mcp_gateway import MCPGateway

# Run MCPServer + ASGI/uvicorn in another *process*, exercising actual HTTP,
# SDK initialization, configured auth header, tool catalog and call_tool.
SERVER = """
import sys
from mcp.server import MCPServer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

mcp = MCPServer("CloudbrowserHTTPAcceptance")

@mcp.tool()
def search_notes(query: str) -> dict:
    return {"matches": [f"approved:{query}"]}

@mcp.tool()
def erase_notes(confirm: bool) -> str:
    return "MUST_NOT_BE_CALLED"

async def authorize(request, call_next):
    if request.headers.get("authorization") != "Bearer test-remote-token":
        return PlainTextResponse("Unauthorized", status_code=401)
    return await call_next(request)

app = mcp.streamable_http_app(stateless_http=True, json_response=True)
app.add_middleware(BaseHTTPMiddleware, dispatch=authorize)
import uvicorn
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="error")
"""


@pytest.mark.asyncio
async def test_real_streamable_http_mcp_auth_and_allowlist(settings):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = {"id": "local_mcp", "url": f"http://127.0.0.1:{port}/mcp",
              "read_tools": ["search_notes"], "api_token": "test-remote-token"}
    admin = replace(settings, mcp_servers=[server])
    admin.validate()
    gateway = MCPGateway(admin)
    process = subprocess.Popen([sys.executable, "-c", SERVER, str(port)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        catalog = None
        for _ in range(60):
            assert process.poll() is None, "MCP subprocess exited before HTTP readiness"
            try:
                catalog = await asyncio.wait_for(gateway.list_tools("local_mcp"), timeout=3)
                break
            except Exception:
                await asyncio.sleep(0.15)
        assert catalog is not None, "Remote MCP HTTP server did not become ready"
        assert [item["name"] for item in catalog["tools"]] == ["search_notes"]
        response = await gateway.call_readonly("local_mcp", "search_notes",
                                              {"query": "rigging"})
        assert "approved:rigging" in str(response["result"])
        assert response["untrusted"] is True
        with pytest.raises(ValueError, match="allowlist"):
            await gateway.call_readonly("local_mcp", "erase_notes", {"confirm": True})
        unauthorized = MCPGateway(replace(settings, mcp_servers=[
            {**server, "api_token": "incorrect"}]))
        denied = False
        try:
            await asyncio.wait_for(unauthorized.list_tools("local_mcp"), timeout=10)
        except Exception:
            denied = True
        assert denied, "Remote MCP accepted an invalid bearer token"
    finally:
        process.terminate()
        try:
            await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=8)
        except TimeoutError:
            process.kill()
            await asyncio.to_thread(process.wait)
