"""Bounded, read-only Scene Intelligence and static motion preflight.

No model, arbitrary code execution, mesh mutation, image analysis or inferred foot
contact. Evidence is derived from the actual registered GLB and approved manifest.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .gltf_qa import read_glb
from .manifest import Manifest
from .settings import DATA_ROOT

MAX_NAMES = 128


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _label(value: object) -> str:
    return value[:80] if isinstance(value, str) else ""


def inspect_project(pid: str, project: dict) -> dict:
    metadata = json.loads(project["metadata"])
    folder = DATA_ROOT / pid
    source = metadata.get("source", {})
    source_file = folder / ("mesh.glb" if source.get("type") == "glb" else "source.png")
    if not source_file.is_file() or _digest(source_file) != project["sha256"]:
        raise ValueError("Source integrity mismatch; recreate project before editing.")
    rig_path = folder / "rigged.glb"
    asset_path = rig_path if rig_path.is_file() else folder / "mesh.glb"
    rig_sha = metadata.get("rig_qa", {}).get("sha256")
    if rig_path.is_file() and (not rig_sha or _digest(rig_path) != rig_sha):
        raise ValueError("Rig integrity mismatch; reimport before editing.")
    result = {
        "project_id": pid,
        "state": project["state"],
        "source_sha256": project["sha256"],
        "asset": "rig" if rig_path.is_file() else ("mesh" if asset_path.is_file() else "png"),
        "hierarchy": [],
        "bones": [],
        "materials": [],
        "mesh_count": 0,
        "skin_count": 0,
        "manifest": None,
        "inspection": "registered_glb_structure_only",
        "limitations": [
            "No live MorphGLB iframe selection or timeline access.",
            "Mesh/rig structural inspection cannot certify animation quality.",
        ],
    }
    if asset_path.is_file():
        doc, _ = read_glb(asset_path)
        nodes = doc.get("nodes", [])
        skins = doc.get("skins", [])
        if len(nodes) > 4096 or len(skins) > 1:
            raise ValueError("Unsupported GLB scene complexity.")
        result["hierarchy"] = [
            {
                "id": index,
                "name": _label(node.get("name", "")),
                "children": node.get("children", [])[:MAX_NAMES],
                "mesh": node.get("mesh"),
            }
            for index, node in enumerate(nodes[:MAX_NAMES])
        ]
        result["bones"] = [
            {"id": index, "name": _label(nodes[index].get("name", ""))}
            for skin in skins for index in skin.get("joints", [])[:MAX_NAMES]
            if isinstance(index, int) and 0 <= index < len(nodes)
        ][:MAX_NAMES]
        result["materials"] = [_label(item.get("name", ""))
                               for item in doc.get("materials", [])[:MAX_NAMES]]
        result["mesh_count"] = len(doc.get("meshes", []))
        result["skin_count"] = len(skins)
        result["asset_sha256"] = _digest(asset_path)
    manifest_path = folder / "manifest.json"
    if manifest_path.is_file():
        manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        result["manifest"] = manifest.model_dump()
        result["manifest_sha256"] = _digest(manifest_path)
    return result


_REQUIRED_BONES = {
    "walk": ("UpperLeg_L", "UpperLeg_R"),
    "wave": ("UpperArm_R",),
    "idle": (),
    "jump": (),
}


def motion_preflight(scene: dict) -> dict:
    """Static checks only; unknown physical properties always remain unknown."""
    manifest = scene.get("manifest")
    issues: list[dict] = []
    unknowns = [
        "Actual sole-to-ground contact is not measured.",
        "Foot sliding, root-motion continuity and self-collision are not measured.",
        "IK solver stability and visual likeness are not evaluated.",
    ]
    if manifest is None:
        issues.append({"code": "NO_MANIFEST", "severity": "blocked",
                       "detail": "Create a scene manifest before QA."})
    if scene.get("asset") != "rig" or not scene.get("bones"):
        issues.append({"code": "NO_RIG", "severity": "blocked",
                       "detail": "A validated rigged GLB is required for animation."})
    actions = [shot["action"] for shot in manifest["shots"]] if manifest else []
    bones = {bone["name"] for bone in scene.get("bones", [])}
    for action in sorted(set(actions)):
        missing = sorted(set(_REQUIRED_BONES[action]) - bones)
        if missing:
            issues.append({"code": "MISSING_ACTION_BONES", "severity": "blocked",
                           "detail": f"{action}: required named bones absent",
                           "bones": missing})
    if manifest and manifest["approval"] != "approved":
        issues.append({"code": "MANIFEST_UNAPPROVED", "severity": "blocked",
                       "detail": "Owner must approve the manifest before render."})
    return {
        "project_id": scene["project_id"],
        "manifest_sha256": scene.get("manifest_sha256"),
        "rig_sha256": scene.get("asset_sha256") if scene.get("asset") == "rig" else None,
        "actions": actions,
        "blocked": any(item["severity"] == "blocked" for item in issues),
        "findings": issues,
        "unknowns": unknowns,
        "method": "static_scene_manifest_and_bone_name_preflight",
        "quality_certified": False,
    }
