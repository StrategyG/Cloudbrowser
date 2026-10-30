from __future__ import annotations

import asyncio
import json
import mimetypes

from a2a.server.request_handlers import RequestHandler
from a2a.server.routes import create_jsonrpc_routes
from a2a.server.routes.common import DefaultServerCallContextBuilder
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Artifact,
    HTTPAuthSecurityScheme,
    ListTasksResponse,
    Message,
    Part,
    Role,
    SecurityRequirement,
    SecurityScheme,
    Task,
    TaskState,
    TaskStatus,
)
from a2a.utils.errors import (
    ContentTypeNotSupportedError,
    ExtendedAgentCardNotConfiguredError,
    InvalidParamsError,
    PushNotificationNotSupportedError,
    TaskNotCancelableError,
    TaskNotFoundError,
    UnsupportedOperationError,
)
from fastapi import HTTPException
from fastapi.responses import FileResponse
from google.protobuf.json_format import MessageToDict

JOB_STATES = {"queued": TaskState.TASK_STATE_SUBMITTED, "running": TaskState.TASK_STATE_WORKING,
              "awaiting_approval": TaskState.TASK_STATE_INPUT_REQUIRED, "waiting_user": TaskState.TASK_STATE_INPUT_REQUIRED,
              "incomplete": TaskState.TASK_STATE_INPUT_REQUIRED, "interrupted": TaskState.TASK_STATE_INPUT_REQUIRED,
              "completed": TaskState.TASK_STATE_COMPLETED, "failed": TaskState.TASK_STATE_FAILED,
              "stopped": TaskState.TASK_STATE_CANCELED}
TERMINAL = {TaskState.TASK_STATE_COMPLETED, TaskState.TASK_STATE_FAILED, TaskState.TASK_STATE_CANCELED}


class ContextBuilder(DefaultServerCallContextBuilder):
    def build(self, request):
        context = super().build(request)
        context.state["agent_id"] = request.path_params.get("agent_id", "orchestrator")
        return context


def card(settings, store, agent_id="orchestrator"):
    if agent_id == "orchestrator":
        name, description = "Cloudbrowser Orchestrator", "Build scoped AI agents and coordinate reviewed browser/video workflows."
        path = "/a2a/rpc"
    else:
        definition = store.agent(agent_id)
        name = definition["name"]
        description = "Scoped Cloudbrowser " + definition["profile"] + " agent. Outputs require caller review."
        path = f"/a2a/agents/{agent_id}/rpc"
    return AgentCard(name=name, description=description, version="0.3.0",
        supported_interfaces=[AgentInterface(url=settings.a2a_base_url.rstrip("/") + path, protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False, extended_agent_card=False),
        default_input_modes=["text/plain"], default_output_modes=["text/plain", "application/json", "video/mp4"],
        skills=[AgentSkill(id=agent_id, name=name, description=description, tags=["browser", "video", "a2a"])],
        security_schemes={"bearer": SecurityScheme(http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="bearer"))},
        security_requirements=[SecurityRequirement(schemes={"bearer": {"list": []}})])


class Handler(RequestHandler):
    def __init__(self, settings, agent, store):
        self.settings, self.agent, self.store = settings, agent, store

    def _entry(self, context):
        agent_id = context.state.get("agent_id", "orchestrator")
        if agent_id != "orchestrator":
            try:
                definition = self.store.agent(agent_id)
            except ValueError:
                raise TaskNotFoundError("Agent not found.") from None
            if definition["profile"] == "reviewer":
                raise UnsupportedOperationError("Reviewers are used through a2a_review_task.")
        return agent_id

    def task(self, task_id, agent_id):
        rows = self.store._rows("SELECT * FROM a2a_inbox WHERE job_id=? AND agent_id=?", (task_id, agent_id))
        if not rows:
            raise TaskNotFoundError()
        job = self.store.job(task_id)
        status = TaskStatus(state=JOB_STATES[job["status"]], message=Message(
            message_id=task_id + "-status", role=Role.ROLE_AGENT,
            parts=[Part(text=self.settings.redact(job["result"] or job["status"]))]))
        status.timestamp.FromSeconds(int(job["updated"]))
        task = Task(id=task_id, context_id=rows[0]["context_id"], status=status,
                    metadata={"agentId": agent_id, "workflowReviewed": bool(json.loads(self.store.get("final_review:" + task_id, "{}")).get("passed"))})
        for artifact in self.store.job_artifacts(task_id):
            task.artifacts.append(Artifact(artifact_id=artifact["id"], name=artifact["filename"],
                parts=[Part(url=self.settings.a2a_base_url.rstrip("/") + "/a2a/artifacts/" + artifact["id"],
                            media_type=mimetypes.guess_type(artifact["filename"])[0] or "application/octet-stream")]))
        return task

    async def on_message_send(self, params, context):
        agent_id, message = self._entry(context), params.message
        if params.tenant or message.role != Role.ROLE_USER or not message.message_id:
            raise InvalidParamsError("Require messageId and user role; tenancy is unsupported.")
        if params.configuration.HasField("task_push_notification_config"):
            raise PushNotificationNotSupportedError()
        if params.configuration.accepted_output_modes and not set(params.configuration.accepted_output_modes) & {"text/plain", "application/json", "video/mp4"}:
            raise ContentTypeNotSupportedError()
        if not message.parts or any(part.WhichOneof("content") != "text" for part in message.parts):
            raise ContentTypeNotSupportedError("Text input only; upload media through the owner dashboard.")
        text = "\n".join(part.text for part in message.parts).strip()
        if not text or len(text) > 12000:
            raise InvalidParamsError("Text must have 1–12000 characters.")
        key = f"a2a:{agent_id}:{message.message_id}"
        try:
            if message.task_id:
                current = self.task(message.task_id, agent_id)
                if current.status.state in TERMINAL:
                    raise UnsupportedOperationError("Terminal tasks cannot restart; send a new message without taskId.")
                if message.context_id and current.context_id != message.context_id:
                    raise InvalidParamsError("contextId does not match task.")
                job = self.agent.resume(message.task_id, text, key)
            else:
                previous = self.store._rows("SELECT goal FROM jobs WHERE request_key=?", (key,))
                if previous and previous[0]["goal"] != self.settings.redact(text):
                    raise InvalidParamsError("messageId was already used for different content.")
                import hashlib
                context_key = f"{agent_id}:{message.context_id or message.message_id}"
                project_id = "a2a-" + hashlib.sha256(context_key.encode()).hexdigest()[:24]
                job = self.agent.enqueue(text, key, project_id=project_id)
                self.store._write("INSERT OR IGNORE INTO a2a_inbox VALUES (?,?,?)", (job["id"], agent_id, message.context_id or job["id"]))
                if agent_id != "orchestrator":
                    self.store.set("entry_agent:" + job["id"], agent_id)
        except ValueError as exc:
            raise InvalidParamsError(self.settings.redact(str(exc))) from None
        if not params.configuration.return_immediately:
            while self.store.job(job["id"])["status"] in {"queued", "running"}:
                await asyncio.sleep(.05)
        return self.task(job["id"], agent_id)

    async def on_get_task(self, params, context):
        if params.tenant:
            raise InvalidParamsError("Tenancy is unsupported.")
        return self.task(params.id, self._entry(context))

    async def on_cancel_task(self, params, context):
        if params.tenant:
            raise InvalidParamsError("Tenancy is unsupported.")
        agent_id = self._entry(context)
        if self.task(params.id, agent_id).status.state in TERMINAL:
            raise TaskNotCancelableError()
        self.agent.stop(params.id)
        self.store.update_job(params.id, status="stopped", result="Canceled by A2A client; external side effects may already have occurred.")
        return self.task(params.id, agent_id)

    async def on_list_tasks(self, params, context):
        if params.tenant:
            raise InvalidParamsError("Tenancy is unsupported.")
        agent_id = self._entry(context)
        try:
            offset = int(params.page_token or "0")
        except ValueError:
            raise InvalidParamsError("Invalid page token.") from None
        if offset < 0 or params.page_size < 0:
            raise InvalidParamsError("Invalid pagination.")
        rows = self.store._rows("SELECT i.* FROM a2a_inbox i JOIN jobs j ON i.job_id=j.id WHERE i.agent_id=? ORDER BY j.created DESC", (agent_id,))
        tasks = [self.task(row["job_id"], agent_id) for row in rows]
        tasks = [task for task in tasks if (not params.context_id or params.context_id == task.context_id)
                 and (not params.status or task.status.state == params.status)
                 and (not params.HasField("status_timestamp_after") or task.status.timestamp.ToDatetime() >= params.status_timestamp_after.ToDatetime())]
        size, total = min(params.page_size or 50, 100), len(tasks)
        tasks = tasks[offset:offset + size]
        if not params.include_artifacts:
            for task in tasks:
                task.ClearField("artifacts")
        return ListTasksResponse(tasks=tasks, total_size=total, page_size=size,
                                 next_page_token=str(offset + size) if offset + size < total else "")

    async def on_message_send_stream(self, params, context):
        raise UnsupportedOperationError("Streaming is not advertised; use polling.")
        yield

    async def on_subscribe_to_task(self, params, context):
        raise UnsupportedOperationError("Subscriptions are not advertised; use polling.")
        yield

    async def on_create_task_push_notification_config(self, params, context):
        raise PushNotificationNotSupportedError()

    async def on_get_task_push_notification_config(self, params, context):
        raise PushNotificationNotSupportedError()

    async def on_list_task_push_notification_configs(self, params, context):
        raise PushNotificationNotSupportedError()

    async def on_delete_task_push_notification_config(self, params, context):
        raise PushNotificationNotSupportedError()

    async def on_get_extended_agent_card(self, params, context):
        raise ExtendedAgentCardNotConfiguredError()


def install_a2a(app, settings, agent, store, artifacts):
    handler = Handler(settings, agent, store)
    app.state.a2a_handler = handler
    for path in ("/a2a/rpc", "/a2a/agents/{agent_id}/rpc"):
        app.router.routes.extend(create_jsonrpc_routes(handler, rpc_url=path, context_builder=ContextBuilder()))

    def enabled():
        if not settings.a2a_api_key:
            raise HTTPException(404, "External A2A is not configured.")

    @app.get("/.well-known/agent-card.json")
    async def root_card():
        enabled()
        return MessageToDict(card(settings, store))

    @app.get("/a2a/agents/{agent_id}/.well-known/agent-card.json")
    async def specialist_card(agent_id: str):
        enabled()
        try:
            return MessageToDict(card(settings, store, agent_id))
        except ValueError:
            raise HTTPException(404, "Agent not found.") from None

    @app.get("/a2a/artifacts/{artifact_id}")
    async def artifact_file(artifact_id: str):
        enabled()
        return FileResponse(artifacts.path(artifact_id), filename=store.artifact(artifact_id)["filename"],
                            media_type="application/octet-stream")
