from __future__ import annotations

import asyncio
import json

import pytest
from conftest import tool_call
from pydantic import ValidationError

from cloudbrowser.crew_models import Workflow


def define(agent, profile, agent_id=None):
    return agent.crew.create({"id": agent_id or profile, "name": profile.title(), "profile": profile,
                              "instructions": "Perform your assigned specialty and report grounded evidence."})


def workflow(agent, job_id, kind="text", **expected):
    return agent.crew.set_workflow(job_id, {"objective": "Create a verified ARUSIA deliverable", "steps": [
        {"id": "draft", "description": "Create the requested ARUSIA deliverable", "expected": {"kind": kind, **expected}}]})


async def test_model_created_agents_delegate_and_independently_review_actual_artifact(make_agent, settings):
    settings.require_workflow = True
    agent = make_agent(tool_call("write_text_artifact", {"filename": "script.md", "content": "ARUSIA: Kio membuka garasi."}),
                       {"role": "assistant", "content": "Script created."},
                       tool_call("record_review", {"passed": True, "summary": "Output matches the task.", "issues": []}))
    job = agent.store.create_job("Write an ARUSIA script")
    define(agent, "writer")
    define(agent, "reviewer")
    workflow(agent, job["id"], text_contains="ARUSIA")
    response = await agent.crew.delegate(job["id"], {"agent_id": "writer", "step_id": "draft", "task": job["goal"]})
    assert response["status"]["state"] == "TASK_STATE_COMPLETED"
    assert not agent.crew.completion(job["id"])[0]
    task_id = response["id"]
    review = await agent.crew.review(job["id"], task_id, "reviewer")
    assert review["review"]["passed"]
    evidence = review["evidence"]["outputs"][0]
    assert len(evidence["sha256"]) == 64 and evidence["size"] > 0
    assert agent.crew.completion(job["id"])[0]
    assert agent.store.job_artifacts(job["id"])
    await agent.close()


async def test_model_cannot_claim_completion_without_workflow(make_agent, settings):
    settings.require_workflow = True
    agent = make_agent({"role": "assistant", "content": "Video is finished, trust me."})
    await agent.start()
    try:
        job = agent.enqueue("Produce the requested final video")
        await asyncio.wait_for(agent.queue.join(), 5)
        assert agent.store.job(job["id"])["status"] == "incomplete"
    finally:
        await agent.close()


async def test_writer_cannot_escalate_to_browser_or_agent_factory(make_agent):
    agent = make_agent(tool_call("browser_click", {"element_id": "e1", "snapshot_id": "latest"}),
                       tool_call("a2a_create_agent", {"id": "escape"}),
                       {"role": "assistant", "content": "No output."})
    define(agent, "writer")
    define(agent, "reviewer")
    job = agent.store.create_job("Draft a script")
    workflow(agent, job["id"])
    response = await agent.crew.delegate(job["id"], {"agent_id": "writer", "step_id": "draft", "task": "Write a script."})
    assert not agent.browser.calls
    assert len(agent.store.agents()) == 2
    verdict = await agent.crew.review(job["id"], response["id"], "reviewer")
    assert not verdict["review"]["passed"]
    assert "No actual output" in verdict["review"]["issues"][0]
    await agent.close()


async def test_dependencies_cannot_bypass_review_and_contract_cannot_be_weakened(make_agent):
    agent = make_agent()
    define(agent, "writer")
    job = agent.store.create_job("Two step production")
    agent.crew.set_workflow(job["id"], {"objective": "Produce a script and final plan", "steps": [
        {"id": "draft", "description": "Write the episode script", "expected": {"kind": "text"}},
        {"id": "next", "description": "Build the final shot plan", "depends_on": ["draft"], "expected": {"kind": "text"}}]})
    with pytest.raises(ValueError, match="Dependency"):
        await agent.crew.delegate(job["id"], {"agent_id": "writer", "step_id": "next", "task": "Skip ahead."})
    await agent.crew.delegate(job["id"], {"agent_id": "writer", "step_id": "draft", "task": "Write a script."})
    with pytest.raises(ValueError, match="frozen"):
        workflow(agent, job["id"])
    await agent.close()


def test_invalid_cycles_and_agent_limits(make_agent, settings):
    with pytest.raises(ValidationError):
        Workflow.model_validate({"objective": "Invalid graph", "steps": [{"id": "cycle", "description": "Self dependency is invalid", "depends_on": ["cycle"], "expected": {"kind": "text"}}]})
    settings.max_agents = 1
    agent = make_agent()
    define(agent, "writer")
    with pytest.raises(ValueError, match="limit"):
        define(agent, "reviewer")
    with pytest.raises(ValueError, match="reserved"):
        define(agent, "browser", "orchestrator")


async def test_parent_shared_model_budget_applies_to_specialists(make_agent, settings):
    settings.max_model_calls = 1
    agent = make_agent(tool_call("write_text_artifact", {"filename": "script.md", "content": "A real script."}))
    define(agent, "writer")
    job = agent.store.create_job("Write a script")
    workflow(agent, job["id"])
    response = await agent.crew.delegate(job["id"], {"agent_id": "writer", "step_id": "draft", "task": "Write a script."})
    assert response["status"]["state"] == "TASK_STATE_FAILED"
    assert len(agent.ai.requests) == 1
    await agent.close()


async def test_owning_agent_cannot_review_its_own_output(make_agent):
    agent = make_agent()
    define(agent, "writer")
    job = agent.store.create_job("Write a script")
    workflow(agent, job["id"])
    response = await agent.crew.delegate(job["id"], {"agent_id": "writer", "step_id": "draft", "task": "Write a script."})
    with pytest.raises(ValueError, match="distinct"):
        await agent.crew.review(job["id"], response["id"], "writer")
    await agent.close()


async def test_input_required_specialist_resumes_same_task_with_owner_feedback(make_agent):
    agent = make_agent(tool_call("ask_user", {"question": "Confirm the episode title."}),
                       tool_call("write_text_artifact", {"filename": "title.md", "content": "ARUSIA: Balon Kembali"}),
                       {"role": "assistant", "content": "Title saved."})
    define(agent, "writer")
    job = agent.store.create_job("Write an ARUSIA title")
    workflow(agent, job["id"])
    first = await agent.crew.delegate(job["id"], {"agent_id": "writer", "step_id": "draft", "task": "Ask for the title."})
    assert first["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    second = await agent.crew.delegate(job["id"], {"agent_id": "writer", "step_id": "draft", "task": "The owner chose Balon Kembali. Save it."})
    assert second["id"] == first["id"]
    assert second["status"]["state"] == "TASK_STATE_COMPLETED"
    assert "Balon Kembali" in json.dumps(agent.ai.requests[-1])
    await agent.close()


async def test_specialist_secrets_are_redacted_in_persisted_history(make_agent, settings):
    settings.ai_api_key = "TEST_ONLY_AI_SECRET"
    agent = make_agent({"role": "assistant", "content": settings.ai_api_key})
    define(agent, "writer")
    job = agent.store.create_job("Write a script")
    workflow(agent, job["id"])
    result = await agent.crew.delegate(job["id"], {"agent_id": "writer", "step_id": "draft", "task": settings.ai_api_key})
    row = agent.store.agent_task(result["id"])
    assert settings.ai_api_key not in json.dumps(row)
    assert settings.ai_api_key not in json.dumps(agent.ai.requests)
    await agent.close()


@pytest.mark.parametrize(("final_passed", "tamper"), [(True, False), (False, False), (True, True)])
async def test_orchestrator_model_builds_and_runs_full_crew_workflow(make_agent, settings, final_passed, tamper):
    settings.require_workflow = True
    agent = make_agent()

    class WorkflowAI:
        def __init__(self):
            self.turn = 0

        async def complete(self, messages, tools):
            turn = self.turn
            self.turn += 1
            if turn < 2:
                profile = "writer" if turn == 0 else "reviewer"
                return tool_call("a2a_create_agent", {"id": profile, "name": profile.title(), "profile": profile,
                                                     "instructions": "Work on ARUSIA tasks with grounded evidence."})
            if turn == 2:
                return tool_call("a2a_set_workflow", {"objective": "Write an ARUSIA script", "steps": [
                    {"id": "draft", "description": "Write a short ARUSIA script", "expected": {"kind": "text"}}]})
            if turn == 3:
                return tool_call("a2a_delegate_task", {"agent_id": "writer", "step_id": "draft", "task": "Write an ARUSIA script."})
            if turn == 4:
                assert not any(tool["function"]["name"] == "browser_click" for tool in tools)
                return tool_call("write_text_artifact", {"filename": "scene.md", "content": "ARUSIA: Kio dan Lumi membuka garasi."})
            if turn == 5:
                return {"role": "assistant", "content": "Script artifact ready."}
            if turn == 6:
                row = agent.store.agent_tasks(agent.active_job)[-1]
                return tool_call("a2a_review_task", {"task_id": row["id"], "reviewer_id": "reviewer"})
            if turn == 7:
                return tool_call("record_review", {"passed": True, "summary": "The script matches its step.", "issues": []})
            if turn == 8:
                return {"role": "assistant", "content": "The reviewed ARUSIA script is ready."}
            if tamper:
                artifact_id = json.loads(agent.store.agent_tasks(agent.active_job)[-1]["outputs"])[0]
                agent.artifacts.path(artifact_id).write_text("Changed while final auditor was running.")
            return tool_call("record_review", {"passed": final_passed, "summary": "Whole goal reviewed.",
                                              "issues": [] if final_passed else ["Missing a user requirement."]})

        async def close(self):
            pass

    agent.ai = WorkflowAI()
    await agent.start()
    try:
        job = agent.enqueue("Write a short ARUSIA script with Kio and Lumi.")
        await asyncio.wait_for(agent.queue.join(), 5)
        assert agent.store.job(job["id"])["status"] == ("completed" if final_passed and not tamper else "incomplete")
        assert len(agent.store.agents()) == 2
        assert len(agent.store.agent_tasks(job["id"])) == 1
        assert int(agent.store.get("model_calls:" + job["id"])) == 10
    finally:
        await agent.close()
