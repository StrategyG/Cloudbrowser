from __future__ import annotations

import asyncio
import io
from pathlib import Path

import httpx
import pytest
from conftest import tool_call
from fastapi.testclient import TestClient
from PIL import Image

from cloudbrowser.artifacts import Artifacts
from cloudbrowser.crew import PROFILES
from cloudbrowser.media import Media
from cloudbrowser.policy import action_policy
from cloudbrowser.store import Store
from cloudbrowser.studio_client import StudioClient
from cloudbrowser.tools import TOOL_MAP
from cloudbrowser.verification import Verifier
from cloudbrowser.web import create_app

PID = "a" * 32


def configure(settings):
    settings.studio_base_url = "http://studio-api:8000"
    settings.studio_api_token = "test-studio-secret-" * 3
    return settings


def test_studio_config_and_capabilities(settings):
    configure(settings).validate()
    assert settings.studio_api_token not in repr(settings)
    assert settings.studio_api_token not in settings.redact(settings.studio_api_token)
    assert "studio_approve_stage" in PROFILES["editor"]
    assert "studio_approve_stage" not in PROFILES["reviewer"]
    assert action_policy(settings, "auto", TOOL_MAP["studio_approve_stage"]).approval_required
    settings.studio_base_url = "http://untrusted.example"
    with pytest.raises(ValueError, match="Studio"):
        settings.validate()


async def test_studio_mutation_waits_for_owner_even_in_auto(make_agent):
    agent = make_agent(tool_call("studio_approve_stage", {"project_id": PID, "stage": "mesh"}))
    configure(agent.settings)
    agent.store.set("approval_mode", "auto")
    sent = []

    def backend(request):
        sent.append(request)
        return httpx.Response(200, json={"state": "mesh_approved"})

    agent.studio.transport = httpx.MockTransport(backend)
    await agent.start()
    try:
        agent.enqueue("Approve the reviewed mesh")
        async with asyncio.timeout(5):
            while not agent.store.pending_approvals():
                await asyncio.sleep(.01)
        assert not sent
        approval = agent.store.pending_approvals()[0]
        assert PID in approval["summary"]
        assert agent.decide(approval["id"], True)
        await asyncio.wait_for(agent.queue.join(), 5)
        assert len(sent) == 1
        assert sent[0].headers["x-studio-token"] == agent.settings.studio_api_token
    finally:
        await agent.close()


async def test_real_studio_png_mesh_approval_and_import(settings, tmp_path, monkeypatch):
    # Real Studio API, mesh code and SQLite; transport is in-process, not a network or renderer claim.
    import importlib
    import sys

    root = Path(__file__).resolve().parents[1] / "services/studio_v4"
    monkeypatch.syspath_prepend(str(root))
    monkeypatch.setenv("STUDIO_DATA_ROOT", str(tmp_path / "backend"))
    monkeypatch.setenv("STUDIO_API_TOKEN", configure(settings).studio_api_token)
    for name in list(sys.modules):
        if name == "studio" or name.startswith("studio."):
            monkeypatch.delitem(sys.modules, name)
    backend = importlib.import_module("studio.api")
    pipeline = importlib.import_module("studio.pipeline")
    store = Store(tmp_path)
    try:
        artifacts = Artifacts(tmp_path, store)
        studio = StudioClient(settings, artifacts, transport=httpx.ASGITransport(app=backend.app))
        image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        for x in range(8, 24):
            for y in range(4, 28):
                image.putpixel((x, y), (90, 130, 220, 255))
        data = io.BytesIO()
        image.save(data, format="PNG")
        aid, path, name = artifacts.allocate("character.png")
        path.write_bytes(data.getvalue())
        artifacts.register(aid, path, name)
        project = await studio.execute("studio_create_project", {"artifact_id": aid})
        pid = project["id"]
        await studio.execute("studio_start_stage", {"project_id": pid, "stage": "mesh"})
        pipeline.run_job(backend.store.claim_job())
        info = await studio.execute("studio_get_project", {"project_id": pid})
        assert info["state"] == "mesh_review"
        assert info["metadata"]["mesh_qa"]["connected_components"] == 1
        assert (await studio.execute("studio_approve_stage", {"project_id": pid, "stage": "mesh"}))["state"] == "mesh_approved"
        with pytest.raises(ValueError, match="not completed"):
            await studio.execute("studio_import_asset", {"project_id": pid, "kind": "mp4"})
        mesh = await studio.execute("studio_import_asset", {"project_id": pid, "kind": "mesh"})
        assert artifacts.path(mesh["artifact"]["id"]).read_bytes()[:4] == b"glTF"
    finally:
        store.close()


async def test_completed_mp4_is_imported_and_decoded(settings, tmp_path):
    store = Store(tmp_path)
    try:
        artifacts = Artifacts(tmp_path, store)
        media = Media(artifacts)
        actual = await media.storyboard([{"title": "QC", "text": "Actual output", "duration": 1}])
        data = artifacts.path(actual["artifact"]["id"]).read_bytes()

        def backend(request):
            if request.url.path.endswith("/assets/mp4"):
                return httpx.Response(200, content=data)
            return httpx.Response(200, json={"state": "completed"})

        studio = StudioClient(configure(settings), artifacts, transport=httpx.MockTransport(backend))
        output = await studio.execute("studio_import_asset", {"project_id": PID, "kind": "mp4"})
        inspection = await Verifier(artifacts, media).inspect(output["artifact"]["id"])
        assert inspection["kind"] == "video" and inspection["duration_seconds"] > 0
    finally:
        store.close()


async def test_studio_rejects_redirect_and_oversize(settings, tmp_path):
    store = Store(tmp_path)
    try:
        studio = StudioClient(configure(settings), Artifacts(tmp_path, store),
                              transport=httpx.MockTransport(lambda _: httpx.Response(302, headers={"location": "https://evil.example"})))
        with pytest.raises(ValueError, match="302"):
            await studio.execute("studio_get_project", {"project_id": PID})
        studio.transport = httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 262145))
        with pytest.raises(ValueError, match="transfer limit"):
            await studio.execute("studio_get_project", {"project_id": PID})
    finally:
        store.close()


def test_studio_dashboard_requires_owner_and_hides_service_token(settings, tmp_path):
    app = create_app(configure(settings), tmp_path, start_services=False)
    with TestClient(app) as client:
        assert client.get("/studio").status_code == 401
        assert client.get(f"/api/studio/projects/{PID}").status_code == 401
        assert client.post("/api/login", json={"password": "test-dashboard-password"}).status_code == 200
        assert client.get("/studio").status_code == 200
        state = client.get("/api/state")
        assert state.json()["studio_enabled"]
        assert settings.studio_api_token not in state.text
        assert client.get(f"/api/studio/projects/{PID}/assets/invalid").status_code == 404


async def test_studio_client_hands_off_glb_with_owner_approval(settings, tmp_path):
    store = Store(tmp_path)
    try:
        artifacts = Artifacts(tmp_path, store)
        aid, path, filename = artifacts.allocate("character.glb")
        path.write_bytes(b"glTF" + b"x" * 32)
        artifacts.register(aid, path, filename)
        requests = []

        def backend(request):
            requests.append(request)
            return httpx.Response(200, json={"id": PID, "state": "mesh_review", "source_type": "glb"})

        studio = StudioClient(configure(settings), artifacts, transport=httpx.MockTransport(backend))
        assert action_policy(settings, "auto", TOOL_MAP["studio_create_project"]).approval_required
        result = await studio.execute("studio_create_project", {"artifact_id": aid})
        assert result["state"] == "mesh_review"
        assert len(requests) == 1
        assert requests[0].method == "POST"
        assert requests[0].url.path == "/api/projects"
        assert b"filename=\"asset.glb\"" in requests[0].content
        assert b"model/gltf-binary" in requests[0].content
        assert requests[0].headers["x-studio-token"] == settings.studio_api_token
    finally:
        store.close()
