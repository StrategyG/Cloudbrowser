"""Google Sites links use a safe post-login deep link, never cross-origin iframe access."""
from pathlib import Path

from fastapi.testclient import TestClient

from cloudbrowser.web import create_app

APP_JS = Path(__file__).resolve().parents[1] / "cloudbrowser/static/app.js"


def test_google_sites_portal_requires_login_and_preserves_frame_protection(settings, tmp_path):
    with TestClient(create_app(settings, tmp_path, start_services=False)) as client:
        portal = client.get("/?open=studio")
        assert portal.status_code == 200
        assert "Cloudbrowser" in portal.text
        assert "frame-ancestors 'none'" in portal.headers["content-security-policy"]
        assert client.get("/studio#morphglb").status_code == 401
        assert client.get("/studio/morphglb").status_code == 401
        auth = client.post("/api/login", json={"password": "test-dashboard-password"})
        assert auth.status_code == 200
        page = client.get("/studio")
        assert page.status_code == 200
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert "samesite=strict" in auth.headers["set-cookie"].lower()


def test_google_sites_deep_link_is_fixed_same_origin_not_open_redirect():
    js = APP_JS.read_text(encoding="utf-8")
    assert 'new URLSearchParams(window.location.search).get("open") !== "studio"' in js
    assert 'window.location.assign("/studio#morphglb")' in js
    assert "window.location.assign(window.location.search)" not in js
    assert "if (openPortalTarget()) return;" in js
    assert 'window.history.replaceState(null, "", "/")' in js
