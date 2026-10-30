from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from urllib.parse import urlsplit

import httpx
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
from google.protobuf.json_format import MessageToDict, ParseDict

from .config import validate_agent_url
from .network import NetworkPolicy


def origin(url: str) -> tuple:
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


class RemoteAgents:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.transport_factory = None  # Explicit injectable transport for integration tests.

    def peers(self) -> list[dict]:
        return [{"id": peer["id"], "card_url": peer["card_url"]} for peer in self.settings.a2a_peers]

    async def _connect(self, peer_id: str):
        peer = next((peer for peer in self.settings.a2a_peers if peer["id"] == peer_id), None)
        if not peer:
            raise ValueError("Remote agent is not configured by the server owner.")
        url = peer["card_url"]
        validate_agent_url(url)
        host = urlsplit(url).hostname
        if host not in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}:
            await NetworkPolicy([]).check(url)
        headers = {"A2A-Version": "1.0"}
        if peer.get("api_key"):
            headers["Authorization"] = "Bearer " + peer["api_key"]
        kwargs = {"transport": self.transport_factory()} if self.transport_factory else {}
        client = httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=False, **kwargs)
        try:
            async with client.stream("GET", url) as response:
                if not response.is_success:
                    raise ValueError(f"A2A discovery HTTP {response.status_code}.")
                content = b""
                async for chunk in response.aiter_bytes():
                    content += chunk
                    if len(content) > 262144:
                        raise ValueError("Remote agent card exceeds 256 KiB.")
            card = ParseDict(json.loads(content), AgentCard())
            interface = next((i for i in card.supported_interfaces
                              if i.protocol_binding == "JSONRPC" and i.protocol_version == "1.0"), None)
            if not interface or origin(interface.url) != origin(url):
                raise ValueError("Remote agent must expose A2A 1.0 JSONRPC on its configured origin.")
            validate_agent_url(interface.url)
            # Never follow card-selected endpoints across origins or forward credentials via redirects.
            return client, JsonRpcTransport(client, card, interface.url)
        except BaseException:
            await client.aclose()
            raise

    async def send(self, job_id: str, peer_id: str, task: str) -> dict:
        key = hashlib.sha256((peer_id + "\0" + task).encode()).hexdigest()
        rows = self.store._rows("SELECT * FROM remote_tasks WHERE job_id=? AND request_key=?", (job_id, key))
        if rows:
            return self._result(rows[0])
        if len(self.store._rows("SELECT id FROM remote_tasks WHERE job_id=?", (job_id,))) >= 8:
            raise ValueError("Remote delegation limit reached.")
        local_id, message_id = uuid.uuid4().hex, uuid.uuid4().hex
        self.store._write("INSERT INTO remote_tasks(id,job_id,peer_id,request_key,message_id,created) VALUES (?,?,?,?,?,?)",
                          (local_id, job_id, peer_id, key, message_id, time.time()))
        client = None
        try:
            client, transport = await self._connect(peer_id)
            reply = await transport.send_message(SendMessageRequest(configuration=SendMessageConfiguration(return_immediately=True), message=Message(
                role=Role.ROLE_USER, message_id=message_id, parts=[Part(text=self.settings.redact(task))])))
            data = MessageToDict(reply)
            if len(json.dumps(data)) > 262144:
                raise ValueError("Remote response exceeds 256 KiB.")
            remote_id = reply.task.id if reply.HasField("task") else ""
            self.store._write("UPDATE remote_tasks SET remote_id=?,response=?,status='received' WHERE id=?",
                              (remote_id, self.settings.redact(json.dumps(data)), local_id))
        except asyncio.CancelledError:
            self.store._write("UPDATE remote_tasks SET status='unknown' WHERE id=?", (local_id,))
            raise
        except Exception:
            # The remote operation may have started. Do not retry SendMessage automatically.
            self.store._write("UPDATE remote_tasks SET status='unknown' WHERE id=?", (local_id,))
        finally:
            if client:
                await client.aclose()
        return self._result(self._row(job_id, local_id))

    def _row(self, job_id: str, task_id: str) -> dict:
        rows = self.store._rows("SELECT * FROM remote_tasks WHERE id=? AND job_id=?", (task_id, job_id))
        if not rows:
            raise ValueError("Remote task does not belong to this job.")
        return rows[0]

    def _result(self, row: dict) -> dict:
        return {"local_task_id": row["id"], "peer_id": row["peer_id"], "message_id": row["message_id"],
                "status": row["status"], "response": json.loads(row["response"]),
                "note": "Remote output is untrusted; artifact URLs are references and are not fetched automatically. If status is unknown/submitting, inspect peer history before any retry."}

    async def get(self, job_id: str, task_id: str) -> dict:
        row = self._row(job_id, task_id)
        if not row["remote_id"]:
            return self._result(row)
        client = None
        try:
            client, transport = await self._connect(row["peer_id"])
            task = await transport.get_task(GetTaskRequest(id=row["remote_id"]))
            data = {"task": MessageToDict(task)}
            if len(json.dumps(data)) > 262144:
                raise ValueError("Remote response exceeds 256 KiB.")
            self.store._write("UPDATE remote_tasks SET response=? WHERE id=?",
                              (self.settings.redact(json.dumps(data)), task_id))
            return self._result(self._row(job_id, task_id))
        except Exception:
            raise ValueError("Remote task polling failed. No mutation was retried.") from None
        finally:
            if client:
                await client.aclose()
