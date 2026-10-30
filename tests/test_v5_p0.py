"""v5 P0 contracts: replay-safe job creation and fail-closed service readiness."""
import pytest
from fastapi.testclient import TestClient

from cloudbrowser.store import Store
from cloudbrowser.web import create_app
from test_web import login


def test_exact_idempotency_is_atomic_and_survives_reopening_database(tmp_path):
    store = Store(tmp_path)
    first = store.create_job("Build scene", "tg:update-123", project_id="arusia")
    repeated = store.create_job("Build scene", "tg:update-123", project_id="arusia")
    assert first["id"] == repeated["id"]
    assert len(store.jobs("arusia")) == 1
    store.close()

    restarted = Store(tmp_path)
    try:
        same = restarted.create_job("Build scene", "tg:update-123", project_id="arusia")
        assert same["id"] == first["id"]
        with pytest.raises(ValueError, match="different goal or project"):
            restarted.create_job("Publish content", "tg:update-123", project_id="arusia")
        with pytest.raises(ValueError, match="different goal or project"):
            restarted.create_job("Build scene", "tg:update-123", project_id="finance")
        assert len(restarted.jobs()) == 1
        assert restarted.job(first["id"])["goal"] == "Build scene"
    finally:
        restarted.close()


def test_idempotency_key_must_not_be_blank_or_have_control_characters(tmp_path):
    store = Store(tmp_path)
    try:
        for key in ("", "x" * 161, "bad\nkey"):
            with pytest.raises(ValueError, match="Invalid idempotency key"):
                store.create_job("Task", key)
        assert not store.jobs()
    finally:
        store.close()


def test_dashboard_idempotency_and_cross_project_reuse_denial(settings, tmp_path):
    with TestClient(create_app(settings, tmp_path, start_services=False)) as client:
        headers = login(client)
        request = {"text": "Create a shot", "project_id": "arusia",
                   "idempotency_key": "submit-00000001"}
        first = client.post("/api/jobs", headers=headers, json=request)
        assert first.status_code == 200, first.text
        repeat = client.post("/api/jobs", headers=headers, json=request)
        assert repeat.status_code == 200
        assert repeat.json()["id"] == first.json()["id"]
        conflict = client.post("/api/jobs", headers=headers,
                               json=request | {"text": "Delete project"})
        assert conflict.status_code == 400
        project_conflict = client.post("/api/jobs", headers=headers,
                                       json=request | {"project_id": "finance"})
        assert project_conflict.status_code == 400
        assert len(client.get("/api/state").json()["jobs"]) == 1
        assert client.post("/api/jobs", headers=headers,
                           json=request | {"idempotency_key": "?"}).status_code == 422


def test_readiness_does_not_claim_worker_active_when_services_are_disabled(settings, tmp_path):
    with TestClient(create_app(settings, tmp_path, start_services=False)) as client:
        response = client.get("/readyz")
        assert response.status_code == 503
        body = response.json()
        assert body["ready"] is False
        assert body["checks"]["database"] is True
        assert body["checks"]["worker"] is False
        assert "ai_api_key" not in response.text
        assert "telegram_bot_token" not in response.text
        assert client.get("/healthz").status_code == 200
