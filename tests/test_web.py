from __future__ import annotations

from fastapi.testclient import TestClient

from cloudbrowser.web import create_app


def login(client):
    response = client.post("/api/login", json={"password": "test-dashboard-password"})
    assert response.status_code == 200
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_authenticated_dashboard_csrf_and_no_secret_exposure(settings, tmp_path):
    settings.ai_api_key = "test-only-secret"
    with TestClient(create_app(settings, tmp_path, start_services=False)) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/state").status_code == 401
        assert client.get("/api/browser/screenshot").status_code == 401
        assert client.put("/api/artifacts?filename=secret.txt", content=b"x").status_code == 401
        headers = login(client)
        assert settings.ai_api_key not in client.get("/api/state").text
        assert client.post("/api/jobs", json={"text": "test"}).status_code == 403
        assert client.post("/api/jobs", json={"text": "test"}, headers=headers | {"Origin": "https://evil.example"}).status_code == 403
        result = client.post("/api/jobs", json={"text": "test"}, headers=headers)
        assert result.status_code == 200
        assert client.get("/api/state").json()["jobs"][0]["id"] == result.json()["id"]


def test_artifact_paths_and_logout_revocation(settings, tmp_path):
    with TestClient(create_app(settings, tmp_path, start_services=False)) as client:
        headers = login(client)
        original_cookie = client.cookies.get("cloudbrowser_session")
        result = client.put("/api/artifacts?filename=../../config.json", content=b"public upload", headers=headers)
        assert result.status_code == 200
        artifact_id = result.json()["id"]
        assert client.get(f"/api/artifacts/{artifact_id}").content == b"public upload"
        assert client.get("/api/artifacts/config.json").status_code == 400
        assert client.post("/api/logout", headers=headers).status_code == 200
        client.cookies.set("cloudbrowser_session", original_cookie)
        assert client.get("/api/state").status_code == 401


def test_oversized_upload_is_removed(settings, tmp_path):
    settings.max_upload_mb = 1
    with TestClient(create_app(settings, tmp_path, start_services=False)) as client:
        response = client.put("/api/artifacts?filename=large.mp4", content=b"x" * (1024 * 1024 + 1), headers=login(client))
        assert response.status_code == 413
        assert not list((tmp_path / "artifacts").iterdir())


def test_login_rate_limit(settings, tmp_path):
    with TestClient(create_app(settings, tmp_path, start_services=False)) as client:
        for _ in range(5):
            assert client.post("/api/login", json={"password": "wrong"}).status_code == 401
        assert client.post("/api/login", json={"password": "wrong"}).status_code == 429


def test_https_origin_behind_proxy(settings, tmp_path):
    settings.public_origin = "https://browser.example.com"
    with TestClient(create_app(settings, tmp_path, start_services=False)) as client:
        result = client.post("/api/login", json={"password": "test-dashboard-password"},
                             headers={"Origin": "https://browser.example.com"})
        assert result.status_code == 200
        assert client.post("/api/mode", json={"mode": "auto"}, headers={
            "Origin": "https://browser.example.com", "X-CSRF-Token": result.json()["csrf_token"]
        }).status_code == 200
