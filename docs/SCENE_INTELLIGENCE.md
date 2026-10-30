# Studio Scene Intelligence & Motion Preflight v1

**Scope:** trusted project file inspection, deterministic scene-plan preview, and **static** animation QA. This is not computer vision, real-time selection in the MorphGLB iframe, a mesh editing API, a full IK engine or natural-motion certification.

## What changed

The Studio worker reads the registered PNG/GLB, optionally the rigged GLB, and the current scene manifest only within the server-owned project directory. GLB parsing returns bounded lists of hierarchy nodes, joint names, material names, structural counts, model checksums, and the validated manifest. Access requires the existing Studio token; the Cloudbrowser dashboard endpoints additionally require the owner session.

The motion preflight reports missing manifests, absent rigged GLB, missing named bones for `walk` (`UpperLeg_L` and `UpperLeg_R`) and `wave` (`UpperArm_R`), and the current manifest approval state. It explicitly labels foot-ground contact, foot sliding, root motion continuity, IK behavior, self-collision and character likeness as **unknown**. A clear static report has `quality_certified: false` and is **not** a pass for naturalness.

### Read-only API

| Studio API | Cloudbrowser owner proxy | Effect |
| --- | --- | --- |
| `GET /api/projects/{id}/scene` | `GET /api/studio/projects/{id}/scene` | Read validated hierarchy and checksums. |
| `GET /api/projects/{id}/motion-qa` | `GET /api/studio/projects/{id}/motion-qa` | Static bone-name/action and approval checks. |
| `POST /api/projects/{id}/plan-preview` | `POST /api/studio/projects/{id}/plan-preview` | Compute a candidate deterministic manifest without writing or approving it. |

For preview, send the same validated `StudioPlan` payload as `studio_plan_scene`: `project_id`, `prompt`, `character`, `fps`, `width`, `height`. Only the existing `studio_plan_scene` tool mutates the manifest, and it remains approval-gated.

Three corresponding read-only tools are available to the Copilot orchestrator, writer, editor and independent reviewer: `studio_inspect_scene`, `studio_motion_preflight`, and `studio_preview_scene`.

Studio's **Tinjau proyek** panel displays actual scene data and static Motion QA. The Copilot **Preview manifest tanpa perubahan** button computes a shot plan without initiating a render or creating a job.

## Render safety

Manifest approval now records a SHA-256 of the approved manifest after the approval field becomes `approved`. Before a render job is queued, Studio verifies the manifest matches that approved digest and rejects changed files. It also requires the static motion preflight to have no blocking findings. Only existing supported named bones can drive the procedural walk and wave motions. No arbitrary rig mapping is inferred.

**This is not version history.** Prior manifests are not automatically retained, and direct vertex/bone manipulation or Undo/Redo is not implemented. The new digest prevents silently rendering a modified, previously approved manifest. Real motion QA still requires inspecting decoded render frames and/or instrumentation of foot/world transforms. A single-shot production test using real ARUSIA characters is still required.

## Test coverage

- `services/studio_v4/tests/test_scene_intelligence.py`: imported watertight GLB hierarchy, tamper detection, static bone QA, no-op preview, approval checksum and tampered-manifest rejection.
- `tests/test_studio_intelligence.py`: owner session, CSRF/origin policy, Studio bearer token, read-only endpoint mapping, restricted A2A tool capabilities.
- CI remains responsible for the real synthetic GLB→Blender/Godot MP4 smoke.

Avoid presenting a successful preflight as an animation-quality pass, and never imply this adds editing inside the sandboxed MorphGLB iframe.
