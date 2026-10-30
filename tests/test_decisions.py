from __future__ import annotations

import asyncio
import json
import sqlite3

import httpx
import pytest
from conftest import StubBrowser, tool_call
from fastapi.testclient import TestClient
from test_crew import define, workflow
from test_web import login

from cloudbrowser.crew_models import ExpectedOutput
from cloudbrowser.llm import AIClient
from cloudbrowser.policy import action_policy
from cloudbrowser.store import Store
from cloudbrowser.tools import TOOL_MAP
from cloudbrowser.web import create_app


async def approve_next(agent):
    async def wait():
        while not agent.store.pending_approvals():
            await asyncio.sleep(.01)
    await asyncio.wait_for(wait(), 3)
    row = agent.store.pending_approvals()[0]
    assert agent.decide(row["id"], True)


@pytest.mark.parametrize("name", ["browser_click", "browser_coordinate_click", "browser_drag",
                                  "browser_press", "browser_type", "browser_upload", "a2a_send_remote"])
def test_auto_cannot_remove_protected_action_gates(settings, name):
    settings.auto_browser_actions = ["fill", "select"]
    assert action_policy(settings, "auto", TOOL_MAP[name]).approval_required
    assert not action_policy(settings, "auto", TOOL_MAP["browser_fill"]).approval_required
    assert action_policy(settings, "approve", TOOL_MAP["browser_fill"]).approval_required


async def test_ambiguous_browser_effect_blocks_replay_until_owner_reconciles(make_agent):
    class TimeoutBrowser(StubBrowser):
        async def action(self, kind, args, **kwargs):
            self.calls.append((kind, args))
            raise TimeoutError("The click may already have happened.")

    browser = TimeoutBrowser()
    agent = make_agent(tool_call("browser_click", {"snapshot_id": "latest", "element_id": "e1"}),
                       browser=browser)
    agent.store.set("approval_mode", "auto")
    await agent.start()
    try:
        job = agent.enqueue("Create exactly one clip.")
        await approve_next(agent)
        await asyncio.wait_for(agent.queue.join(), 3)
        assert agent.store.job(job["id"])["status"] == "waiting_user"
        unknown = agent.store.actions(unresolved=True)
        assert len(unknown) == 1 and len(browser.calls) == 1
        assert "text" not in unknown[0] and len(unknown[0]["request_hash"]) == 64
        retry = await agent._checked_tool(job["id"], "browser_click", {"snapshot_id": "new", "element_id": "e1"})
        assert retry["waiting_for_user"] and len(browser.calls) == 1
        # Neither model-generated notes nor restarting the server clears uncertainty.
        agent.store.recover()
        assert agent.store.actions(unresolved=True)
        assert agent.store.resolve_action(unknown[0]["id"], True)
        assert not agent.store.resolve_action(unknown[0]["id"], False)
        assert not agent.store.actions(unresolved=True)
    finally:
        await agent.close()


async def test_cancellation_during_external_action_records_unknown_effect(make_agent):
    dispatched = asyncio.Event()
    class SlowBrowser(StubBrowser):
        async def action(self, kind, args, **kwargs):
            dispatched.set()
            await asyncio.Event().wait()

    agent = make_agent(tool_call("browser_click", {"snapshot_id": "latest", "element_id": "e1"}),
                       browser=SlowBrowser())
    await agent.start()
    try:
        job = agent.enqueue("Create a clip.")
        await approve_next(agent)
        await asyncio.wait_for(dispatched.wait(), 3)
        agent.stop()
        await asyncio.wait_for(agent.queue.join(), 3)
        assert agent.store.job(job["id"])["status"] == "stopped"
        assert agent.store.actions(unresolved=True)[0]["status"] == "unknown"
    finally:
        await agent.close()


def test_restart_distinguishes_not_started_from_dispatched_actions(tmp_path):
    store = Store(tmp_path)
    try:
        job = store.create_job("Work")
        pending = store.begin_action(job["id"], "browser_click", {"text": "private input"}, "Click")
        applying = store.begin_action(job["id"], "browser_click", {}, "Click")
        store.action_status(applying, "applying")
        store.recover()
        rows = {row["id"]: row for row in store.actions(job["id"])}
        assert rows[pending]["status"] == "canceled"
        assert rows[applying]["status"] == "unknown"
        assert "private input" not in json.dumps(rows)
    finally:
        store.close()


async def test_same_tool_error_yields_instead_of_looping(make_agent, settings):
    agent = make_agent(*[tool_call("invented_tool", {}, f"invalid-{i}") for i in range(8)])
    await agent.start()
    try:
        job = agent.enqueue("Do the task.")
        await asyncio.wait_for(agent.queue.join(), 3)
        assert agent.store.job(job["id"])["status"] == "waiting_user"
        assert len(agent.ai.requests) == settings.max_repeated_tool_errors
    finally:
        await agent.close()


async def test_mutated_artifact_invalidates_review_and_blocks_dependencies(make_agent):
    agent = make_agent(tool_call("write_text_artifact", {"filename": "scene.md", "content": "ARUSIA scene"}),
                       {"role": "assistant", "content": "Saved."},
                       tool_call("record_review", {"passed": True, "summary": "Matches goal.", "issues": []}))
    define(agent, "writer")
    define(agent, "reviewer")
    job = agent.store.create_job("Produce an ARUSIA scene and shot list")
    agent.crew.set_workflow(job["id"], {"objective": job["goal"], "steps": [
        {"id": "draft", "description": "Write the ARUSIA episode scene", "expected": {"kind": "text"}},
        {"id": "shots", "description": "Build a shot list from the reviewed scene", "depends_on": ["draft"], "expected": {"kind": "text"}}]})
    response = await agent.crew.delegate(job["id"], {"agent_id": "writer", "step_id": "draft", "task": "Write the ARUSIA scene."})
    assert (await agent.crew.review(job["id"], response["id"], "reviewer"))["review"]["passed"]
    row = agent.store.agent_task(response["id"])
    path = agent.artifacts.path(json.loads(row["outputs"])[0])
    path.write_text("Changed after review")
    assert not agent.crew.integrity(row)
    assert not agent.crew.completion(job["id"])[0]
    with pytest.raises(ValueError, match="Dependency"):
        await agent.crew.delegate(job["id"], {"agent_id": "writer", "step_id": "shots", "task": "Make shots."})
    path.unlink()
    assert not agent.crew.integrity(row)
    await agent.close()


async def test_redelegating_reviewed_identical_step_does_not_repeat_work(make_agent):
    agent = make_agent(tool_call("write_text_artifact", {"filename": "scene.md", "content": "ARUSIA scene"}),
                       {"role": "assistant", "content": "Saved."},
                       tool_call("record_review", {"passed": True, "summary": "Matches goal.", "issues": []}))
    define(agent, "writer")
    define(agent, "reviewer")
    job = agent.store.create_job("Produce an ARUSIA scene")
    workflow(agent, job["id"])
    args = {"agent_id": "writer", "step_id": "draft", "task": "Write the ARUSIA scene."}
    first = await agent.crew.delegate(job["id"], args)
    assert (await agent.crew.review(job["id"], first["id"], "reviewer"))["review"]["passed"]
    calls = len(agent.ai.requests)
    assert (await agent.crew.delegate(job["id"], args))["id"] == first["id"]
    assert len(agent.ai.requests) == calls
    await agent.close()


async def test_project_brief_and_history_are_scoped_and_restored_on_every_call(make_agent):
    agent = make_agent()
    first = agent.store.create_job("PRIVATE OTHER PROJECT", project_id="finance")
    agent.store.update_job(first["id"], status="completed", result="PRIVATE OTHER RESULT")
    agent.store.set_project("arusia", "Kio, Lumi, Arka, Mayor, RUX. Budget needs owner authorization.")
    await agent.start()
    try:
        job = agent.enqueue("Write an ARUSIA scene")
        await asyncio.wait_for(agent.queue.join(), 3)
        request = json.dumps(agent.ai.requests[0])
        assert job["project_id"] == "arusia"
        assert "Kio, Lumi, Arka, Mayor, RUX" in request
        assert "PRIVATE OTHER PROJECT" not in request and "PRIVATE OTHER RESULT" not in request
        await agent._complete(job["id"], [{"role": "user", "content": "continued"}], [])
        assert "Kio, Lumi, Arka, Mayor, RUX" in json.dumps(agent.ai.requests[-1])
    finally:
        await agent.close()


async def test_output_reservations_survive_missing_usage_and_resume(make_agent, settings):
    settings.ai_max_output_tokens = 256
    settings.max_job_output_tokens = 256
    agent = make_agent()
    job = agent.store.create_job("Work")
    await agent._complete(job["id"], [], [])
    assert agent.store.model_budget(job["id"])["output_tokens_charged"] == 256
    agent.store.recover()
    with pytest.raises(ValueError, match="output-token budget"):
        await agent._complete(job["id"], [], [])
    assert len(agent.ai.requests) == 1
    await agent.close()


async def test_provider_usage_settles_reservation_and_max_tokens_is_configurable(settings):
    captured = []
    settings.ai_max_output_tokens = 4096
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"usage": {"prompt_tokens": 50, "completion_tokens": 20},
                                        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "Done"}}]})
    ai = AIClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        await ai.complete([], [])
        assert captured[0]["max_tokens"] == 4096
        assert ai.last_usage["completion_tokens"] == 20
    finally:
        await ai.close()


async def test_truncated_model_answer_is_never_accepted_as_final(settings):
    ai = AIClient(settings, httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"choices": [{"finish_reason": "length", "message": {"role": "assistant", "content": "Everything is done"}}]}))))
    try:
        with pytest.raises(ValueError):
            await ai.complete([], [])
    finally:
        await ai.close()


def test_project_and_action_resolution_routes_require_auth_and_csrf(settings, tmp_path):
    with TestClient(create_app(settings, tmp_path, start_services=False)) as client:
        assert client.post("/api/project", json={"id": "arusia"}).status_code == 401
        headers = login(client)
        assert client.post("/api/project", json={"id": "arusia"}).status_code == 403
        assert client.post("/api/project", json={"id": "arusia", "brief": "Use the five friends."}, headers=headers).status_code == 200
        job = client.post("/api/jobs", json={"text": "Write a scene."}, headers=headers).json()
        details = client.get("/api/jobs/" + job["id"]).json()
        assert details["project_id"] == "arusia" and details["budget"]["recorded_calls"] == 0
        assert client.post("/api/project", json={"id": "a2a-internal"}, headers=headers).status_code == 400
        store = client.app.state.store
        action_id = store.begin_action(job["id"], "browser_click", {}, "Generate")
        store.action_status(action_id, "unknown")
        assert client.post(f"/api/actions/{action_id}/resolve", json={"approved": True}).status_code == 403
        assert client.post(f"/api/actions/{action_id}/resolve", json={"approved": True}, headers=headers).status_code == 200
        assert client.post(f"/api/actions/{action_id}/resolve", json={"approved": False}, headers=headers).status_code == 409


async def test_output_minimum_size_prevents_empty_placeholder_acceptance(make_agent):
    agent = make_agent()
    artifact = agent.artifacts.write("script.md", "x")
    with pytest.raises(ValueError, match="file size"):
        await agent.crew.verifier.inspect(artifact["id"], ExpectedOutput(kind="text", min_size_bytes=50))
    await agent.close()


async def test_owner_configured_role_routing_keeps_a_shared_budget(make_agent, settings):
    settings.role_models = {"reviewer": "local-review-model"}
    agent = make_agent()
    choices = []
    class RoutedAI:
        async def complete(self, messages, tools, *, model=None):
            choices.append(model)
            return {"role": "assistant", "content": "Reviewed."}
        async def close(self):
            pass
    agent.ai = RoutedAI()
    job = agent.store.create_job("Work")
    await agent._complete(job["id"], [], [])
    await agent._complete(job["id"], [], [], role="reviewer")
    assert choices == [None, "local-review-model"]
    assert agent.store.model_budget(job["id"])["model_calls"] == 2
    assert agent.store.model_budget(job["id"])["output_tokens_charged"] == 2 * settings.ai_max_output_tokens
    await agent.close()


def test_legacy_job_database_migrates_without_losing_history(tmp_path):
    db = sqlite3.connect(tmp_path / "state.sqlite3")
    db.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, request_key TEXT UNIQUE, goal TEXT NOT NULL, status TEXT NOT NULL, messages TEXT NOT NULL DEFAULT '[]', result TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL)")
    db.execute("INSERT INTO jobs VALUES ('legacy',NULL,'Original goal','completed','[]','Original result',0,0)")
    db.commit()
    db.close()
    store = Store(tmp_path)
    try:
        assert store.job("legacy")["project_id"] == "default"
        assert store.job("legacy")["result"] == "Original result"
        assert store.actions() == []
    finally:
        store.close()


@pytest.mark.parametrize(("field", "value"), [("auto_browser_actions", ["click"]),
                                             ("role_models", {"root": "model"}),
                                             ("ai_max_output_tokens", 0),
                                             ("max_job_output_tokens", 1)])
def test_invalid_capability_or_budget_configuration_is_rejected(settings, field, value):
    setattr(settings, field, value)
    with pytest.raises(ValueError):
        settings.validate()


async def test_reported_usage_releases_unused_reserved_output_tokens(make_agent, settings):
    settings.ai_max_output_tokens = 256
    settings.max_job_output_tokens = 300
    agent = make_agent()
    agent.ai.last_usage = {"prompt_tokens": 100, "completion_tokens": 20}
    job = agent.store.create_job("Work")
    await agent._complete(job["id"], [], [])
    await agent._complete(job["id"], [], [])
    budget = agent.store.model_budget(job["id"])
    assert budget["output_tokens_charged"] == 40 and budget["reported_prompt_tokens"] == 200
    await agent.close()


async def test_oversized_required_context_fails_before_api_or_budget_charge(make_agent, settings):
    settings.ai_context_chars = 8000
    agent = make_agent()
    job = agent.store.create_job("x" * 10000)
    with pytest.raises(ValueError, match="context exceeds"):
        await agent._complete(job["id"], [], [])
    assert agent.ai.requests == []
    assert agent.store.model_budget(job["id"])["recorded_calls"] == 0
    await agent.close()
