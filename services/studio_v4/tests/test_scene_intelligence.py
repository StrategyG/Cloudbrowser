"""Scene intelligence: real imported GLB evidence, static motion limitations."""
from __future__ import annotations

import hashlib
import json

import pytest
import trimesh
from fastapi.testclient import TestClient

from studio import api, scene_intelligence, store
from studio.manifest import plan

client = TestClient(api.app)


def upload_actor():
    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(extents=(1, 1, 2)), node_name="KIO")
    raw = scene.export(file_type="glb")
    result = client.post("/api/projects", files={"asset": ("actor.glb", raw, "model/gltf-binary")})
    assert result.status_code == 200, result.text
    return result.json()["id"], raw


def test_real_glb_hierarchy_and_static_preflight():
    pid, raw = upload_actor()
    response = client.get(f"/api/projects/{pid}/scene")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["asset"] == "mesh"
    assert result["asset_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["mesh_count"] == 1
    assert result["inspection"] == "registered_glb_structure_only"
    assert result["hierarchy"]
    assert result["bones"] == []
    assert result["manifest"] is None
    qa = client.get(f"/api/projects/{pid}/motion-qa")
    assert qa.status_code == 200
    codes = {x["code"] for x in qa.json()["findings"]}
    assert codes == {"NO_MANIFEST", "NO_RIG"}
    assert qa.json()["blocked"] is True
    assert qa.json()["quality_certified"] is False
    assert len(qa.json()["unknowns"]) >= 3


def test_tampered_source_rejected_by_scene_and_preflight():
    from studio.settings import DATA_ROOT

    pid, raw = upload_actor()
    (DATA_ROOT / pid / "mesh.glb").write_bytes(raw + b"tamper")
    for route in ("/scene", "/motion-qa"):
        result = client.get(f"/api/projects/{pid}{route}")
        assert result.status_code == 409


def test_preview_is_nonmutating_and_respects_approval_gate():
    from studio.settings import DATA_ROOT

    pid, _ = upload_actor()
    before = store.get_project(pid)
    denied = client.post(f"/api/projects/{pid}/plan-preview",
                         json={"prompt": "KIO berjalan selama 5 detik", "fps": 24})
    assert denied.status_code == 409
    store.change_state(pid, "mesh_review", "mesh_approved")
    store.change_state(pid, "mesh_approved", "rig_building")
    store.change_state(pid, "rig_building", "rig_review")
    store.change_state(pid, "rig_review", "rig_approved")
    result = client.post(f"/api/projects/{pid}/plan-preview",
                         json={"prompt": "KIO berjalan selama 5 detik", "fps": 24})
    assert result.status_code == 200, result.text
    assert result.json()["preview"]["shots"][0]["action"] == "walk"
    assert result.json()["writes_performed"] is False
    assert result.json()["requires_owner_approval"] is True
    assert not (DATA_ROOT / pid / "manifest.json").exists()
    assert store.get_project(pid)["metadata"] == before["metadata"]
    assert store.get_project(pid)["state"] == "rig_approved"
    bad = client.post(f"/api/projects/{pid}/plan-preview",
                      json={"prompt": "KIO terbang selama 5 detik", "fps": 24})
    assert bad.status_code == 422
    assert store.get_project(pid)["state"] == "rig_approved"


def test_motion_preflight_missing_and_supported_bones():
    scene = {
        "project_id": "1" * 32, "asset": "rig",
        "asset_sha256": "a" * 64, "manifest_sha256": "b" * 64,
        "bones": [{"name": "UpperLeg_L"}, {"name": "UpperArm_R"}],
        "manifest": plan("KIO berjalan lalu melambaikan tangan").model_dump(),
    }
    blocked = scene_intelligence.motion_preflight(scene)
    codes = {x["code"] for x in blocked["findings"]}
    assert "MISSING_ACTION_BONES" in codes and "MANIFEST_UNAPPROVED" in codes
    scene["bones"].append({"name": "UpperLeg_R"})
    scene["manifest"]["approval"] = "approved"
    clear = scene_intelligence.motion_preflight(scene)
    assert clear["blocked"] is False
    assert clear["quality_certified"] is False
    assert clear["unknowns"]  # No dishonest real-foot-contact PASS.



def test_manifest_approval_is_digest_bound_before_render():
    from studio.settings import DATA_ROOT

    pid, _ = upload_actor()
    store.change_state(pid, "mesh_review", "mesh_approved")
    store.change_state(pid, "mesh_approved", "rig_building")
    store.change_state(pid, "rig_building", "rig_review")
    store.change_state(pid, "rig_review", "rig_approved")
    store.change_state(pid, "rig_approved", "manifest_review")
    manifest_file = DATA_ROOT / pid / "manifest.json"
    manifest_file.write_text(plan("KIO berjalan").model_dump_json())
    approval = client.post(f"/api/projects/{pid}/approve",
                           json={"stage": "manifest", "confirm": True})
    assert approval.status_code == 200, approval.text
    original = store.read_metadata(pid)["manifest_approved_sha256"]
    assert original == hashlib.sha256(manifest_file.read_bytes()).hexdigest()
    # The project is still manifest_approved, but file content no longer matches approval.
    manifest_file.write_text(manifest_file.read_text().replace("walk", "wave"))
    render = client.post(f"/api/projects/{pid}/render")
    assert render.status_code == 409
    assert "modified since approval" in render.text
    assert store.get_project(pid)["state"] == "manifest_approved"
    assert not any(x["kind"] == "render" for x in store.jobs(pid))
