"""CI acceptance: owner-reviewed PNG -> volumetric GLB -> Blender rig -> Godot MP4.

This is a synthetic CPU pipeline smoke, not proof of faithful image-to-3D
reconstruction, likeness, anatomy, or natural motion quality.
"""

from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path
from typing import Any

STUDIO_V4_ROOT = Path(__file__).resolve().parent.parent
if str(STUDIO_V4_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDIO_V4_ROOT))

from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

from studio import pipeline, store
from studio.api import app
from studio.settings import DATA_ROOT


def make_synthetic_png() -> bytes:
    """Return a small transparent character silhouette for deterministic CI."""
    picture = Image.new("RGBA", (64, 96), (0, 0, 0, 0))
    drawing = ImageDraw.Draw(picture)
    drawing.ellipse((17, 7, 47, 35), fill=(240, 128, 55, 255))
    drawing.rectangle((20, 34, 45, 68), fill=(238, 100, 32, 255))
    drawing.rectangle((11, 40, 20, 57), fill=(245, 128, 55, 255))
    drawing.rectangle((45, 40, 54, 57), fill=(245, 128, 55, 255))
    drawing.rectangle((22, 68, 30, 90), fill=(46, 80, 178, 255))
    drawing.rectangle((36, 68, 44, 90), fill=(46, 80, 178, 255))
    output = io.BytesIO()
    picture.save(output, format="PNG")
    return output.getvalue()


def require_success(response: Any, operation: str) -> dict[str, Any]:
    if response.status_code != 200:
        raise RuntimeError(
            f"{operation} returned HTTP {response.status_code}: {response.text[:2000]}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{operation} returned a non-object response")
    return payload


def process_queued_stage(project_id: str, expected_kind: str, expected_state: str) -> dict[str, Any]:
    """Run the single queued local worker job and require its durable state transition."""
    jobs = store.jobs(project_id)
    if not jobs:
        raise RuntimeError(f"No Studio job was queued for stage {expected_kind}")
    job = jobs[0]  # store.jobs orders newest first, scoped to this project.
    if job.get("kind") != expected_kind or job.get("state") != "queued":
        raise RuntimeError(
            f"Unexpected queued Studio job: expected {expected_kind}/queued, got {job!r}"
        )

    pipeline.run_job(job)
    project = store.get_project(project_id)
    if project is None:
        raise RuntimeError("Studio project disappeared after worker execution")
    if project.get("state") == "failed":
        metadata = store.read_metadata(project_id)
        raise RuntimeError(
            f"Studio {expected_kind} stage failed: {metadata.get('last_error', 'unknown error')}"
        )
    if project.get("state") != expected_state:
        raise RuntimeError(
            f"Studio {expected_kind} stage ended in {project.get('state')!r}, "
            f"expected {expected_state!r}"
        )
    return project


def approve_stage(client: TestClient, project_id: str, stage: str, expected_state: str) -> dict[str, Any]:
    current = require_success(
        client.get(f"/api/projects/{project_id}"),
        f"read project before {stage} approval",
    )
    if current.get("state") != expected_state:
        raise RuntimeError(
            f"Cannot approve {stage}: expected {expected_state}, got {current.get('state')}"
        )

    result = require_success(
        client.post(
            f"/api/projects/{project_id}/approve",
            json={"stage": stage, "confirm": True},
        ),
        f"approve {stage}",
    )
    if result.get("auto_advance_error"):
        raise RuntimeError(f"Owner approval did not advance {stage}: {result['auto_advance_error']}")
    return result


def main() -> None:
    client = TestClient(app)

    # This is the actual Studio upload contract: POST /api/projects, multipart "asset".
    uploaded = require_success(
        client.post(
            "/api/projects",
            files={
                "asset": (
                    "synthetic-character.png",
                    make_synthetic_png(),
                    "image/png",
                )
            },
        ),
        "upload generated PNG",
    )
    project_id = uploaded.get("id")
    if not isinstance(project_id, str) or len(project_id) != 32:
        raise RuntimeError(f"Studio upload returned an invalid project ID: {uploaded!r}")
    if uploaded.get("state") != "uploaded" or uploaded.get("source_type") != "png":
        raise RuntimeError(f"Studio did not register the PNG as an unprocessed source: {uploaded!r}")

    # Start through the current Studio route: POST /api/projects/{pid}/generate.
    generated = require_success(
        client.post(
            f"/api/projects/{project_id}/generate",
            json={
                "prompt": "KIO berjalan selama 3 detik",
                "mesh_mode": "volumetric_draft_3d",
                "fps": 24,
                "width": 640,
                "height": 360,
                "character": "KIO",
            },
        ),
        "start generated PNG workflow",
    )
    if generated.get("full_3d_reconstruction_verified") is not False:
        raise RuntimeError("Single-view draft must not claim verified full 3D reconstruction")

    process_queued_stage(project_id, "mesh", "mesh_review")
    mesh_qa = store.read_metadata(project_id).get("mesh_qa", {})
    if not mesh_qa.get("volumetric_mesh") or mesh_qa.get("full_3d_reconstruction") is not False:
        raise RuntimeError(f"Volumetric draft disclosure/QA missing: {mesh_qa!r}")
    if not mesh_qa.get("watertight") or not mesh_qa.get("winding_consistent"):
        raise RuntimeError(f"Volumetric draft failed topology QA: {mesh_qa!r}")
    if not (mesh_qa.get("dimensions") or [0, 0, 0])[2] > 0.1:
        raise RuntimeError(f"Volumetric draft has no meaningful depth: {mesh_qa!r}")

    approve_stage(client, project_id, "mesh", "mesh_review")
    process_queued_stage(project_id, "rig", "rig_review")
    rig_qa = store.read_metadata(project_id).get("rig_qa", {})
    if rig_qa.get("unweighted_vertices") != 0:
        raise RuntimeError(f"Rig contains unweighted vertices: {rig_qa!r}")
    if rig_qa.get("gltf", {}).get("skins", 0) < 1:
        raise RuntimeError(f"Rigged GLB has no skin: {rig_qa!r}")
    if len(rig_qa.get("pose_previews", [])) != 4:
        raise RuntimeError(f"Expected four Blender pose previews: {rig_qa!r}")

    approve_stage(client, project_id, "rig", "rig_review")
    manifest_project = require_success(
        client.get(f"/api/projects/{project_id}"),
        "read generated scene manifest",
    )
    if manifest_project.get("state") != "manifest_review":
        raise RuntimeError(
            f"Rig approval did not create manifest review state: {manifest_project.get('state')}"
        )
    manifest_path = DATA_ROOT / project_id / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("Generated scene manifest is missing")

    approve_stage(client, project_id, "manifest", "manifest_review")
    process_queued_stage(project_id, "render", "completed")
    final_metadata = store.read_metadata(project_id)
    render_qa = final_metadata.get("render_qa", {})
    mp4_sha256 = render_qa.get("mp4_sha256")
    if not isinstance(mp4_sha256, str) or len(mp4_sha256) != 64:
        raise RuntimeError(f"Completed render has no valid MP4 SHA-256: {render_qa!r}")
    if render_qa.get("frame_content_qa", {}).get("motion_quality_certified") is not False:
        raise RuntimeError("The smoke must not overclaim motion-quality certification")

    media = client.get(f"/api/projects/{project_id}/assets/mp4")
    if media.status_code != 200:
        raise RuntimeError(
            f"Verified MP4 download returned HTTP {media.status_code}: {media.text[:1000]}"
        )
    if len(media.content) < 12 or media.content[4:8] != b"ftyp":
        raise RuntimeError("Final output is not a valid MP4/ISO-BMFF file")
    import hashlib

    actual_sha256 = hashlib.sha256(media.content).hexdigest()
    if actual_sha256 != mp4_sha256:
        raise RuntimeError("Downloaded MP4 SHA-256 does not match the verified project record")

    report = {
        "passed": True,
        "project_id": project_id,
        "generator": "single_view_volumetric_loft_draft",
        "full_3d_reconstruction_verified": False,
        "rig": "Blender template",
        "render": "Godot offline",
        "output_mp4_sha256": mp4_sha256,
        "output_mp4_bytes": len(media.content),
        "motion_quality_certified": False,
        "owner_approval_gates": ["mesh", "rig", "manifest"],
        "steps": (
            "PNG upload -> volumetric GLB -> owner mesh approval -> Blender rig -> "
            "owner rig approval -> scene manifest -> owner manifest approval -> Godot MP4"
        ),
    }
    print("PASS GENERATED 3D DRAFT -> VIDEO " + json.dumps(report, sort_keys=True))

    evidence_dir = Path("/ci-output")
    if evidence_dir.is_dir():
        output_path = DATA_ROOT / project_id / "output.mp4"
        shutil.copyfile(output_path, evidence_dir / "generated_png_output.mp4")
        (evidence_dir / "generated_png_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
