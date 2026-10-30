"""Security and integration checks for the vendored MorphGLB studio."""
from pathlib import Path

from fastapi.testclient import TestClient

from cloudbrowser.web import create_app


def test_morphglb_requires_owner_login(settings, tmp_path):
    with TestClient(create_app(settings, tmp_path, start_services=False)) as client:
        assert client.get("/studio").status_code == 401
        assert client.get("/studio/morphglb").status_code == 401
        assert client.get("/api/studio/projects/" + "a" * 32).status_code == 401


def test_morphglb_isolated_with_csp_and_opaque_origin(settings, tmp_path):
    with TestClient(create_app(settings, tmp_path, start_services=False)) as client:
        login = client.post("/api/login", json={"password": "test-dashboard-password"})
        assert login.status_code == 200

        editor = client.get("/studio/morphglb")
        assert editor.status_code == 200
        assert editor.headers["content-type"].startswith("text/html")
        assert "MorphGLB" in editor.text
        assert len(editor.content) > 1_000_000
        csp = editor.headers["content-security-policy"]
        assert "sandbox allow-scripts allow-downloads" in csp
        assert "connect-src blob: data:" in csp
        assert "frame-ancestors 'self'" in csp
        assert "form-action 'none'" in csp
        assert "no-store" in editor.headers["cache-control"]

        page = client.get("/studio")
        assert page.status_code == 200
        assert 'sandbox="allow-scripts allow-downloads"' in page.text
        assert 'id="morphglb-frame"' in page.text
        assert 'src="about:blank"' in page.text
        assert "/static/morphglb-bridge.js" in page.text
        assert "unsafe-inline" not in page.headers["content-security-policy"]

        dashboard = client.get("/")
        assert "/studio#morphglb" in dashboard.text
        assert "frame-ancestors 'none'" in dashboard.headers["content-security-policy"]


def test_editor_not_published_under_unauthenticated_static(settings, tmp_path):
    source = Path(__file__).resolve().parents[1] / "cloudbrowser" / "morphglb"
    assert (source / "MorphGLB_AI_Studio_v3.3.0.html").is_file()
    with TestClient(create_app(settings, tmp_path, start_services=False)) as client:
        # /static is intentionally public; the 1.6 MB editor is outside it.
        assert client.get("/static/morphglb/MorphGLB_AI_Studio_v3.3.0.html").status_code == 404
        bridge = client.get("/static/morphglb-bridge.js")
        assert bridge.status_code == 200
        assert "csrf_token" in bridge.text
        assert "/api/artifacts" in bridge.text
