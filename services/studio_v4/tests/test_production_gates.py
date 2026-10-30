"""Production regression gates: crash recovery, render TOCTOU, stale export."""
from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from studio import api, pipeline, render_gate, store
from studio.manifest import plan
from studio.settings import DATA_ROOT

client = TestClient(api.app)


def _render_ready(monkeypatch):
    pid = store.create_project("approval-gate", "source-checksum")
    states = ["uploaded", "mesh_building", "mesh_review", "mesh_approved",
              "rig_building", "rig_review", "rig_approved",
              "manifest_review", "manifest_approved", "rendering"]
    for before, after in zip(states, states[1:]):
        store.change_state(pid, before, after)
    folder = DATA_ROOT / pid
    manifest = plan("KIO berjalan selama 1 detik")
    manifest = manifest.model_copy(update={"approval": "approved"})
    path = folder / "manifest.json"
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    store.update_metadata(pid, manifest_approved_sha256=digest,
                          rig_qa={"sha256": "rig-checksum"})
    scene = {
        "project_id": pid,
        "state": "rendering",
        "asset": "rig",
        "asset_sha256": "rig-checksum",
        "manifest": manifest.model_dump(),
        "bones": [{"name": "UpperLeg_L"}, {"name": "UpperLeg_R"}],
        "manifest_sha256": digest,
    }
    # Isolate hashing and worker logic from Blender's GLB fixture generation.
    monkeypatch.setattr(render_gate, "inspect_project", lambda _id, _row: scene)
    return pid, folder, path


def test_running_job_after_crash_is_failed_not_replayed():
    store.init()
    pid = store.create_project("crash", "untrusted")
    jid = store.enqueue(pid, "mesh", "uploaded", "mesh_building")
    row = store.claim_job()
    assert row["id"] == jid
    assert store.recover_interrupted() == 1
    assert store.get_project(pid)["state"] == "failed"
    assert store.jobs(pid)[0]["state"] == "failed"
    assert "manual retry" in store.jobs(pid)[0]["message"]
    assert store.claim_job() is None
    assert store.recover_interrupted() == 0
    retried = api.retry_project(pid)
    assert retried["kind"] == "mesh"
    assert store.get_project(pid)["state"] == "mesh_building"
    assert store.claim_job()["id"] == retried["job_id"]


def test_worker_refuses_tampered_manifest_before_render(monkeypatch):
    pid, folder, path = _render_ready(monkeypatch)
    assert render_gate.verify_render_inputs(pid)["manifest_sha256"]
    path.write_text(path.read_text().replace("walk", "wave"))
    with pytest.raises(ValueError, match="Manifest changed"):
        render_gate.verify_render_inputs(pid)
    job = {"id": "manual-render-guard", "project_id": pid, "kind": "render"}
    called = []
    monkeypatch.setattr(pipeline, "godot_render", lambda *_: called.append(True))
    pipeline.run_job(job)
    assert called == []
    assert store.get_project(pid)["state"] == "failed"
    assert "Manifest changed" in store.read_metadata(pid)["last_error"]


def test_worker_refuses_change_during_render(monkeypatch):
    pid, folder, path = _render_ready(monkeypatch)
    called = []

    def malicious_render(_folder, _command):
        called.append(True)
        (folder / "output.mp4").write_bytes(b"untrusted-placeholder")
        path.write_text(path.read_text().replace("walk", "wave"))
        return {"mp4_qa": {"codec": "h264"}}

    monkeypatch.setattr(pipeline, "godot_render", malicious_render)
    pipeline.run_job({"id": "manual-race", "project_id": pid, "kind": "render"})
    assert called == [True]
    assert store.get_project(pid)["state"] == "failed"
    assert "manifest" in store.read_metadata(pid)["last_error"].lower()
    assert "render_qa" not in store.read_metadata(pid)


def test_completed_mp4_download_requires_integrity():
    pid = store.create_project("export", "source")
    states = ["uploaded", "mesh_building", "mesh_review", "mesh_approved",
              "rig_building", "rig_review", "rig_approved",
              "manifest_review", "manifest_approved", "rendering", "completed"]
    for before, after in zip(states, states[1:]):
        store.change_state(pid, before, after)
    mp4 = DATA_ROOT / pid / "output.mp4"
    mp4.write_bytes(b"video-hash-check")
    expected = hashlib.sha256(mp4.read_bytes()).hexdigest()
    store.update_metadata(pid, render_qa={"mp4_sha256": expected})
    good = client.get(f"/api/projects/{pid}/assets/mp4")
    assert good.status_code == 200
    mp4.write_bytes(b"tampered-output")
    result = client.get(f"/api/projects/{pid}/assets/mp4")
    assert result.status_code == 409
    assert "changed since QA" in result.text
