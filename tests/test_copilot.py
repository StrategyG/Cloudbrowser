"""Animation Copilot: owner boundary, context, agents and advisory guard."""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cloudbrowser.copilot import CopilotRequest, catalog, install_specialists, make_goal
from cloudbrowser.web import create_app


def body(**overrides):
    data = {
        "mode": "plan", "prompt": "Rencanakan walk cycle KIO secara aman",
        "project_id": "arusia", "target_name": "KIO left_foot",
        "scene_notes": "ground Z=0; 24fps",
        "idempotency_key": "copilot-test-0001",
    }
    return data | overrides


def login(client):
    response = client.post("/api/login", json={"password": "test-dashboard-password"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_copilot_input_validation_and_job_contract():
    req = CopilotRequest.model_validate(body())
    goal = make_goal(req)
    assert goal.startswith("CLOUDBROWSER ANIMATION COPILOT / PLAN\n")
    assert "copilot_qa_reviewer" in goal
    assert "KIO left_foot" in goal
    assert "CONTEXT_JSON:" in goal
    with pytest.raises(ValueError, match="requires"):
        make_goal(CopilotRequest.model_validate(body(mode="edit")))
    for bad in (body(mode="superuser"), body(project_id="../../escape"),
                body(prompt="a"), body(idempotency_key="x"),
                body(studio_project_id="not-a-studio-id"),
                body(artifact_id="not-an-artifact")):
        with pytest.raises(ValidationError):
            CopilotRequest.model_validate(bad)


def test_copilot_agents_reuse(make_agent):
    agent = make_agent()
    assert len(catalog(agent.store)) == 4
    definitions = install_specialists(agent.crew)
    assert len(definitions) == 4
    assert len(agent.store.agents()) == 4
    assert all(item["installed"] for item in catalog(agent.store))
    install_specialists(agent.crew)
    assert len(agent.store.agents()) == 4


def test_copilot_capacity_preflight(make_agent, settings):
    agent = make_agent()
    settings.max_agents = 3
    with pytest.raises(ValueError, match="capacity"):
        install_specialists(agent.crew)
    assert agent.store.agents() == []


@pytest.mark.asyncio
async def test_copilot_advisory_modes_block_mutation(make_agent):
    agent = make_agent()
    from cloudbrowser.tools import TOOL_MAP
    assert TOOL_MAP["studio_start_stage"].approval
    for mode in ("chat", "plan"):
        goal = make_goal(CopilotRequest.model_validate(body(
            mode=mode, idempotency_key="mode-" + mode + "-001")))
        job = agent.store.create_job(goal, project_id="arusia")
        result = await agent._checked_tool(job["id"], "studio_start_stage",
                                           {"project_id": "a" * 32, "stage": "render"})
        assert "advisory" in result["error"]
        assert not agent.store.actions(job["id"])
    # Agent-mode work still traverses the existing owner approval boundary.
    assert TOOL_MAP["studio_approve_stage"].approval


def test_copilot_http_auth_csrf_install_idempotency_and_source_check(settings, tmp_path):
    with TestClient(create_app(settings, tmp_path, start_services=False)) as client:
        assert client.get("/api/copilot/agents").status_code == 401
        assert client.post("/api/copilot/jobs", json=body()).status_code == 401
        headers = login(client)
        assert client.post("/api/copilot/jobs", json=body()).status_code == 403
        assert client.post("/api/copilot/jobs", json=body(), headers={
            **headers, "Origin": "https://evil.example"
        }).status_code == 403
        before = client.get("/api/copilot/agents").json()
        assert len(before["agents"]) == 4
        assert not any(item["installed"] for item in before["agents"])
        response = client.post("/api/copilot/jobs", json=body(), headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["mode"] == "plan"
        again = client.post("/api/copilot/jobs", json=body(), headers=headers)
        assert again.status_code == 200
        assert again.json()["id"] == response.json()["id"]
        after = client.get("/api/copilot/agents").json()
        assert all(item["installed"] for item in after["agents"])
        details = client.get("/api/jobs/" + response.json()["id"]).json()
        assert details["project_id"] == "arusia"
        assert "walk cycle KIO" in details["goal"]
        assert client.post("/api/copilot/jobs", json=body(
            mode="edit", idempotency_key="edit-without-asset"), headers=headers
        ).status_code == 400
        assert client.post("/api/copilot/jobs", json=body(
            mode="edit", artifact_id="f" * 32, idempotency_key="edit-without-studio"), headers=headers
        ).status_code == 400
        assert client.post("/api/copilot/jobs", json=body(
            artifact_id="f" * 32, idempotency_key="missing-artifact"), headers=headers
        ).status_code == 400
        assert client.post("/api/copilot/jobs", json=body(
            mode="agent", prompt="run another task", idempotency_key="copilot-test-0001"
        ), headers=headers).status_code == 400
        html = client.get("/studio")
        assert html.status_code == 200
        assert "/static/copilot.js" in html.text
        assert "copilot-prompt" in html.text
        assert "frame-ancestors 'none'" in html.headers["content-security-policy"]
        assert client.get("/static/copilot.js").status_code == 200
