"""Allowlisted, owner-gated MCP v2 client. Never expose arbitrary server/tool selection."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from jsonschema import validate

from .config import Settings


class MCPGateway:
    def __init__(self, settings: Settings):
        self.servers = {item["id"]: item for item in settings.mcp_servers}
        self.settings = settings

    def catalog(self) -> list[dict]:
        """Only advertise administrator-approved names, never dynamic untrusted tools."""
        return [{"id": key, "read_tools": list(value["read_tools"])}
                for key, value in self.servers.items()]

    def _allowed(self, server_id: str, tool_name: str) -> dict:
        server = self.servers.get(server_id)
        if server is None or tool_name not in server["read_tools"]:
            raise ValueError("MCP tool denied by administrator allowlist.")
        return server

    @asynccontextmanager
    async def _connect(self, server: dict) -> AsyncIterator:
        try:
            from mcp import Client
            from mcp.client.streamable_http import streamable_http_client
            import httpx2
        except ImportError:
            raise ValueError("MCP SDK not installed: pip install 'cloudbrowser[mcp]'.") from None
        headers = ({"Authorization": "Bearer " + server["api_token"]}
                   if server.get("api_token") else {})
        # Only exact endpoints from Settings; tool output cannot alter these URLs.
        async with httpx2.AsyncClient(headers=headers,
                                      timeout=httpx2.Timeout(15, read=30),
                                      trust_env=False, follow_redirects=False) as transport_client:
            async with Client(streamable_http_client(server["url"],
                                                    http_client=transport_client)) as session:
                yield session

    async def list_tools(self, server_id: str) -> dict:
        if server_id not in self.servers:
            raise ValueError("Unknown MCP server.")
        server = self.servers[server_id]
        async with asyncio.timeout(35):
            async with self._connect(server) as client:
                discovered = await client.list_all_tools()
        approved = set(server["read_tools"])
        return {"server_id": server_id, "tools": [
            {"name": tool.name, "description": (tool.description or "")[:400],
             "input_schema": tool.input_schema}
            for tool in discovered if tool.name in approved][:30]}

    async def call_readonly(self, server_id: str, tool_name: str, arguments: dict) -> dict:
        server = self._allowed(server_id, tool_name)
        if not isinstance(arguments, dict) or len(json.dumps(arguments)) > 8000:
            raise ValueError("MCP arguments must be a JSON object of at most 8000 characters.")
        async with asyncio.timeout(35):
            async with self._connect(server) as client:
                discovered = await client.list_all_tools()
                match = next((tool for tool in discovered if tool.name == tool_name), None)
                if match is None:
                    raise ValueError("Approved MCP tool not advertised by connected server.")
                validate(instance=arguments, schema=match.input_schema)
                result = await client.call_tool(tool_name, arguments)
        if result.is_error:
            raise ValueError("MCP tool reported an execution error.")
        # MCP output is untrusted text/data. Cap it before giving it to the LLM.
        payload = result.structured_content
        if payload is None:
            payload = [getattr(item, "text", "") for item in result.content
                       if getattr(item, "type", "") == "text"]
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
        if len(encoded) > 12000:
            raise ValueError("MCP tool result exceeds the authorized response budget.")
        return {"server_id": server_id, "tool_name": tool_name, "result": payload,
                "untrusted": True}
