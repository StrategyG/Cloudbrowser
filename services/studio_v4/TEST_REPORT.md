> Historical upstream package record. For Cloudbrowser 0.4 integration results, see ../../docs/VALIDATION.md.

# Verification Report — Full Pipeline Studio V4

Date: 2026-10-30

## Verified locally

- `python -m compileall -q studio workers` — PASS.
- `node --check` on extracted UI JavaScript — PASS.
- `python -m pytest -q` — **8 passed**.
- Synthetic humanoid silhouette → `samples/test_silhouette.glb` — PASS, 5,246 vertices, 10,488 triangles.
- Mesh QA — watertight true; consistent winding true; connected components 1; volume >0.
- GLB round-trip structural validation — PASS.
- FFmpeg H.264 encoding smoke — PASS, 12 frames @ 24 FPS.
- Disconnected alpha island reporting — PASS (detected two components).
- Approval API blocks rigging before mesh approval — PASS.
- Unsupported prompt and multi-character manifest rejection — PASS.

## Not verified

- Blender 4.2+ executable was unavailable in the authoring environment.
- No Blender skin export/GLB reimport, four-pose preview, offline scene render, or final MP4 job was run end-to-end.
- No Khronos glTF Validator binary was available; the supplied validator checks structural constraints, not the complete specification.
- No external browser/OS/GPU end-to-end QA, production-scale load tests, security penetration tests, or visual animation QA.

## Release decision

**Production gating prototype — not production-certified.** Do not mark the deployment production-ready until the unverified stages pass on target hardware and realistic ARUSIA assets. In particular, 2.5D silhouette extrusion cannot reconstruct the unseen rear and side surfaces from one PNG; walk cycle and IK precision require character-specific animation engineering.
