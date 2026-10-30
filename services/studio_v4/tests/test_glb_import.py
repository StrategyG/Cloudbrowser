"""External GLB import contract: reject malformed assets and preserve approval gates."""
import io
import json

import pytest
import trimesh
from fastapi.testclient import TestClient

from studio.api import app
from studio import store
from studio.import_glb import validate_imported_glb

client = TestClient(app)


def glb_bytes(mesh=None):
    scene = trimesh.Scene()
    scene.add_geometry(mesh if mesh is not None else trimesh.creation.box(extents=(1, 1, 2)))
    return scene.export(file_type="glb")


def test_external_glb_enters_mesh_review_requires_owner_approval(tmp_path):
    payload = glb_bytes()
    assert payload[:4] == b"glTF"
    source = tmp_path / "actor.glb"
    source.write_bytes(payload)
    qa = validate_imported_glb(source)
    assert qa["geometry_kind"] == "imported_glb_3d"
    assert qa["watertight"]
    assert qa["gltf"]["valid_structure"]
    assert not qa["preexisting_skin"]

    result = client.post("/api/projects", files={
        "asset": ("character.glb", payload, "model/gltf-binary")
    })
    assert result.status_code == 200, result.text
    pid = result.json()["id"]
    assert result.json()["state"] == "mesh_review"
    project = client.get("/api/projects/" + pid).json()
    assert project["metadata"]["source"]["type"] == "glb"
    assert project["metadata"]["mesh_qa"]["watertight"]
    assert client.get(f"/api/projects/{pid}/assets/mesh").content == payload
    assert client.post(f"/api/projects/{pid}/mesh").status_code == 409
    assert client.post(f"/api/projects/{pid}/rig").status_code == 409
    assert client.post(f"/api/projects/{pid}/approve",
                       json={"stage": "mesh", "confirm": False}).status_code == 422
    approved = client.post(f"/api/projects/{pid}/approve",
                           json={"stage": "mesh", "confirm": True})
    assert approved.status_code == 200, approved.text
    rig = client.post(f"/api/projects/{pid}/rig")
    assert rig.status_code == 200
    assert rig.json()["state"] == "rig_building"


def test_external_glb_invalid_structure_fails_closed(tmp_path):
    cases = [
        (b"glTF" + b"x" * 20, 422),
        (b"not-a-GLB", 415),
        (glb_bytes(trimesh.creation.box()).replace(b"glTF", b"BAD!", 1), 415),
    ]
    for raw, code in cases:
        r = client.post("/api/projects", files={"asset": ("broken.glb", raw, "model/gltf-binary")})
        assert r.status_code == code, r.text


def test_external_glb_non_watertight_rejected():
    mesh = trimesh.creation.box()
    mesh.update_faces([False] + [True] * (len(mesh.faces) - 1))
    response = client.post("/api/projects", files={
        "asset": ("open.glb", glb_bytes(mesh), "model/gltf-binary")
    })
    assert response.status_code == 422
    assert "watertight" in response.text.lower()


def test_external_glb_rejects_remote_buffers_and_extensions(tmp_path, monkeypatch):
    # More stringent than base glTF compliance: no externally resolved resources.
    from studio import import_glb
    src = tmp_path / "actor.glb"
    src.write_bytes(glb_bytes())
    actual = import_glb.read_glb

    def inject_external(path):
        doc, binary = actual(path)
        doc["images"] = [{"uri": "https://attacker.invalid/pixel.png"}]
        return doc, binary

    monkeypatch.setattr(import_glb, "read_glb", inject_external)
    with pytest.raises(ValueError, match="URI"):
        validate_imported_glb(src)


def test_external_glb_rejects_more_than_one_mesh(tmp_path):
    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(), node_name="A")
    scene.add_geometry(trimesh.creation.box(), node_name="B")
    src = tmp_path / "two.glb"
    src.write_bytes(scene.export(file_type="glb"))
    with pytest.raises(ValueError, match="one mesh"):
        validate_imported_glb(src)
