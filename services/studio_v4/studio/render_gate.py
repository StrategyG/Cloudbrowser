"""Revalidate approved source, rig and manifest in the *worker* process.

API admission is not sufficient: queued files can change before or during
Blender/Godot execution. Every critical source is checksum-bound, and the worker
must fail closed instead of publishing an MP4 from modified inputs.
"""
from __future__ import annotations

import hashlib
import json

from . import store
from .manifest import Manifest
from .scene_intelligence import inspect_project, motion_preflight
from .settings import DATA_ROOT


def _sha256(path):
    with path.open("rb") as data:
        return hashlib.file_digest(data, "sha256").hexdigest()


def verify_render_inputs(project_id: str) -> dict:
    project = store.get_project(project_id)
    if not project or project["state"] != "rendering":
        raise ValueError("Render project is not in the running state")
    metadata = json.loads(project["metadata"])
    manifest_file = DATA_ROOT / project_id / "manifest.json"
    expected = metadata.get("manifest_approved_sha256")
    if not expected or not manifest_file.is_file():
        raise ValueError("Missing manifest approval evidence")
    if _sha256(manifest_file) != expected:
        raise ValueError("Manifest changed after owner approval")
    manifest = Manifest.model_validate_json(manifest_file.read_text(encoding="utf-8"))
    if manifest.approval != "approved":
        raise ValueError("Manifest is not approved")
    scene = inspect_project(project_id, project)
    report = motion_preflight(scene)
    if report["blocked"]:
        raise ValueError("Static motion preflight blocked render: " +
                         ",".join(item["code"] for item in report["findings"]))
    rig_sha = metadata.get("rig_qa", {}).get("sha256")
    if not rig_sha or scene.get("asset") != "rig" or scene.get("asset_sha256") != rig_sha:
        raise ValueError("Rig has no verified approval checksum")
    return {
        "source_sha256": project["sha256"],
        "rig_sha256": rig_sha,
        "manifest_sha256": expected,
    }
