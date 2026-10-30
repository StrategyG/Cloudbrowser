"""Cloudbrowser v5 P0: explicit owner-controlled durable pause/cancel semantics."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from conftest import tool_call
from cloudbrowser.web import create_app
from test_web import login


async def until(predicate, timeout=5):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


async def test_pause_inflight_approval_and_resume_without_click(make_agent):
    agent = make_agent(tool_call("browser_click", {"snapshot_id": "latest", "element_id": "e1"}))
    await agent.start()
    try:
        job = agent.enqueue("Inspect before click")
        await until(lambda: bool(agent.store.pending_approvals()))
        approval = agent.store.pending_approvals()[0]["id"]
        assert agent.pause(job["id"])["id"] == job["id"]
        await asyncio.wait_for(agent.queue.join(), 5)
        assert agent.store.job(job["id"])["status"] == "paused"
        assert not agent.store.pending_approvals()
        assert not agent.decide(approval, True)
        assert agent.browser.calls == []
        audit = agent.store.events(job["id"])
        assert any(e["kind"] == "owner_interrupt_requested" and e["detail"] == "paused" for e in audit)
        assert any(e["kind"] == "operator_interruption" for e in audit)
        assert agent.pause(job["id"])["status"] == "paused"
        resumed = agent.resume(job["id"], "Inspect fresh page state first.")
        assert resumed["status"] == "queued"
        await asyncio.wait_for(agent.queue.join(), 5)
        assert agent.store.job(job["id"])["status"] == "completed"
        assert agent.browser.calls == []
    finally:
        await agent.close()


async def test_cancel_active_approval_is_terminal(make_agent):
    agent = make_agent(tool_call("browser_fill", {
        "snapshot_id": "latest", "element_id": "e1", "text": "untrusted"
    }))
    await agent.start()
    try:
        job = agent.enqueue("Do not fill without owner permission")
        await until(lambda: bool(agent.store.pending_approvals()))
        assert agent.cancel(job["id"])["id"] == job["id"]
        await asyncio.wait_for(agent.queue.join(), 5)
        assert agent.store.job(job["id"])["status"] == "cancelled"
        assert agent.browser.calls == []
        assert not agent.store.pending_approvals()
        assert agent.cancel(job["id"])["status"] == "cancelled"
        with pytest.raises(ValueError, match="belum dapat dilanjutkan"):
            agent.resume(job["id"], "Try again")
        with pytest.raises(ValueError, match="terminal"):
            agent.stop(job["id"])
    finally:
        await agent.close()


async def test_cancel_queued_job_survives_worker_restart(make_agent):
    agent = make_agent()
    job = agent.enqueue("Queued cancellation cannot execute")
    assert agent.cancel(job["id"])["status"] == "cancelled"
    agent.store.recover()
    assert agent.store.job(job["id"])["status"] == "cancelled"
    await agent.start()
    try:
        await asyncio.wait_for(agent.queue.join(), 5)
        assert agent.store.job(job["id"])["status"] == "cancelled"
        assert agent.browser.calls == []
    finally:
        await agent.close()


def test_dashboard_pause_cancel_require_auth_csrf_and_cannot_resume_cancelled(settings, tmp_path):
    with TestClient(create_app(settings, tmp_path, start_services=False)) as client:
        new_job = "/api/jobs"
        assert client.post(new_job, json={"text": "test"}).status_code == 401
        auth = login(client)
        job = client.post(new_job, json={"text": "Review browser"}, headers=auth).json()
        root = f"/api/jobs/{job['id']}"
        assert client.post(root + "/pause").status_code == 403
        assert client.post(root + "/pause", headers=auth).json()["status"] == "paused"
        assert client.post(root + "/cancel", headers=auth).json()["status"] == "cancelled"
        assert client.get(root).json()["status"] == "cancelled"
        assert client.post(root + "/resume", headers=auth,
                           json={"text": "continue"}).status_code == 400
        assert client.post(root + "/cancel", headers=auth).json()["status"] == "cancelled"
