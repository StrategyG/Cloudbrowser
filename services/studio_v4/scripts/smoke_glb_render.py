#!/usr/bin/env python3
"""Optional container smoke: real Blender rig authoring, GLB skin-preservation QA and Godot MP4.

This validates executable components, not correctness of natural locomotion or art quality.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

# Service is vendored, not pip-installed; make this script executable by path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import trimesh
from PIL import Image, ImageStat

from studio import pipeline, store
from studio.api import Approval, approve
from studio.gltf_qa import inspect
from studio.import_glb import validate_imported_glb
from studio.manifest import plan
from studio.settings import DATA_ROOT


def imported_project(source: bytes) -> str:
    pid = store.create_project("smoke_glb", hashlib.sha256(source).hexdigest())
    folder = DATA_ROOT / pid
    mesh = folder / "mesh.glb"
    mesh.write_bytes(source)
    qa = validate_imported_glb(mesh)
    store.update_metadata(pid, source={"type": "glb", "sha256": hashlib.sha256(source).hexdigest()}, mesh_qa=qa)
    store.change_state(pid, "uploaded", "mesh_review")
    # Exercise the same mesh approval API as real production.
    approve(pid, Approval(stage="mesh", confirm=True))
    return pid


def execute(pid: str, kind: str, from_state: str, running_state: str):
    store.enqueue(pid, kind, from_state, running_state)
    job = store.claim_job()
    if not job or job["project_id"] != pid or job["kind"] != kind:
        raise RuntimeError("Worker queue mismatch during smoke")
    pipeline.run_job(job)
    row = store.get_project(pid)
    if row["state"] == "failed":
        raise RuntimeError("Stage failed: " + str(store.read_metadata(pid).get("last_error")))
    print("PASS", kind, row["state"], flush=True)


def main():
    store.init()
    cube = trimesh.creation.box(extents=(0.7, 0.35, 1.5))
    scene = trimesh.Scene()
    scene.add_geometry(cube)
    source = scene.export(file_type="glb")

    # First exercise the unskinned 3D GLB → Blender template-rig route.
    initial = imported_project(source)
    execute(initial, "rig", "mesh_approved", "rig_building")
    first_qa = store.read_metadata(initial)["rig_qa"]
    assert first_qa["gltf"]["skins"] > 0
    assert len(first_qa["pose_previews"]) == 4
    rigged = (DATA_ROOT / initial / "rigged.glb").read_bytes()
    assert inspect(DATA_ROOT / initial / "rigged.glb", require_skin=True)["skinned_primitives"] > 0

    # Now reimport that output and exercise the non-destructive existing-rig route.
    second = imported_project(rigged)
    assert store.read_metadata(second)["mesh_qa"]["preexisting_skin"]
    execute(second, "rig", "mesh_approved", "rig_building")
    folder = DATA_ROOT / second
    assert (folder / "rigged.glb").read_bytes() == rigged
    for pose in ("rest", "arms", "legs", "combo"):
        path = folder / ("rig_pose_" + pose + ".png")
        assert path.is_file() and path.stat().st_size > 1024
    assert store.read_metadata(second)["rig_qa"]["rig_type"] == "imported_skinned_glb"

    # The production worker now verifies both owner approval checksums.
    approve(second, Approval(stage="rig", confirm=True))
    manifest = plan("Kio diam 1 detik", fps=24, width=640, height=360)
    (folder / "manifest.json").write_text(manifest.model_dump_json(indent=2))
    store.change_state(second, "rig_approved", "manifest_review")
    approve(second, Approval(stage="manifest", confirm=True))
    execute(second, "render", "manifest_approved", "rendering")

    mp4 = folder / "output.mp4"
    assert mp4.is_file() and mp4.stat().st_size > 1024
    qa = store.read_metadata(second)["render_qa"]
    assert qa["mp4_qa"]["codec"] == "h264"
    assert qa["mp4_sha256"] == hashlib.sha256(mp4.read_bytes()).hexdigest()
    assert qa["input_sha256"]["manifest_sha256"] == store.read_metadata(second)["manifest_approved_sha256"]
    assert qa["frames"] == 24 and qa["width"] == 640 and qa["height"] == 360
    still = folder / "smoke_first_frame.png"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
                    str(mp4), "-frames:v", "1", str(still)], check=True, timeout=45)
    with Image.open(still) as frame:
        spread = max(ImageStat.Stat(frame.convert("RGB")).stddev)
    if spread < 2.0:
        raise RuntimeError("Output video appears nearly uniform or blank")
    shutil.copyfile(mp4, DATA_ROOT / "smoke_output.mp4")
    shutil.copyfile(still, DATA_ROOT / "smoke_preview.png")
    (DATA_ROOT / "smoke_report.json").write_text(json.dumps({
        "synthetic_test_only": True,
        "initial_project": initial,
        "skinned_project": second,
        "rig_qa": store.read_metadata(second)["rig_qa"],
        "render_qa": qa,
        "frame_color_spread": spread,
    }, indent=2))
    print("PASS real imported GLB -> compatible rig -> Godot -> MP4",
          json.dumps({"bytes": mp4.stat().st_size, "frame_spread": spread}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("STUDIO_SMOKE_FAILED:", str(exc), file=sys.stderr)
        raise
