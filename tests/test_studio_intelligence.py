"""Authenticated Cloudbrowser proxy + tool contract for read-only Studio scene IQ."""
from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from cloudbrowser.crew import PROFILES
from cloudbrowser.tools import TOOL_MAP
from cloudbrowser.web import create_app


PID = "a" * 32


def test_studio_scene_endpoints_require_owner_and_csrf(settings, tmp_path):
    settings.studio_base_url = "http://studio-api:8000"
    settings.studio_api_token = "test-studio-secret-" * 3
    seen = []

    def backend(request: httpx.Request):
        seen.append((request.method, request.url.path, request.headers["x-studio-token"]))
        if request.url.path.endswith("/scene"):
            return httpx.Response(200, json={"project_id": PID, "hierarchy": [{"id": 0, "name": "KIO"}]})
        if request.url.path.endswith("/motion-qa"):
            return httpx.Response(200, json={"project_id": PID, "blocked": True,
                                             "quality_certified": False})
        if request.url.path.endswith("/plan-preview"):
            return httpx.Response(200, json={"writes_performed": False, "project_id": PID})
        return httpx.Response(404, json={"detail": "unknown"})

    app = create_app(settings, tmp_path, start_services=False)
    app.state.agent.studio.transport = httpx.MockTransport(backend)
    root = f"/api/studio/projects/{PID}"
    with TestClient(app) as client:
        assert client.get(root + "/scene").status_code == 401
        assert client.get(root + "/motion-qa").status_code == 401
        assert client.post(root + "/plan-preview",
                           json={"project_id": PID, "prompt": "KIO berjalan"}).status_code == 401
        login = client.post("/api/login", json={"password": "test-dashboard-password"})
        assert login.status_code == 200
        csrf = {"X-CSRF-Token": login.json()["csrf_token"]}
        scene = client.get(root + "/scene")
        assert scene.status_code == 200
        assert scene.json()["hierarchy"][0]["name"] == "KIO"
        assert client.get(root + "/motion-qa").json()["blocked"] is True
        assert client.post(root + "/plan-preview", json={"project_id": PID,
                            "prompt": "KIO berjalan"}).status_code == 403
        assert client.post(root + "/plan-preview", headers=csrf | {
            "Origin": "https://evil.example"
        }, json={"project_id": PID, "prompt": "KIO berjalan"}).status_code == 403
        assert client.post(root + "/plan-preview", headers=csrf,
                           json={"project_id": "b" * 32,
                                 "prompt": "KIO berjalan"}).status_code == 422
        preview = client.post(root + "/plan-preview", headers=csrf,
                              json={"project_id": PID, "prompt": "KIO berjalan"})
        assert preview.status_code == 200, preview.text
        assert preview.json()["writes_performed"] is False
        assert all(token == settings.studio_api_token for _, _, token in seen)
        assert [route for _, route, _ in seen] == [
            root.replace("/api/studio", "/api") + "/scene",
            root.replace("/api/studio", "/api") + "/motion-qa",
            root.replace("/api/studio", "/api") + "/plan-preview",
        ]


def test_scene_tools_are_read_only_and_scoped_to_specialists():
    for name in ("studio_inspect_scene", "studio_motion_preflight", "studio_preview_scene"):
        assert TOOL_MAP[name].approval is False
        assert name in PROFILES["reviewer"]
        assert name in PROFILES["writer"]
        assert name in PROFILES["editor"]
    assert TOOL_MAP["studio_plan_scene"].approval is True
    assert "studio_plan_scene" not in PROFILES["reviewer"]
