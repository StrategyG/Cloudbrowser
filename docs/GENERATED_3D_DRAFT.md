# Generated 3D Draft → Video (CPU-first)

**Status: experimental, single-Studio-workspace pipeline.** This is an additive
Cloudbrowser Studio workflow, not faithful neural image-to-3D or a verified
three-Codespaces distributed production installation.

## One-click entry

1. Run the configured Cloudbrowser + Studio services (for example
   `sh scripts/start_studio.sh` on a host supporting Docker Compose).
2. Open authenticated `/studio` and locate **Generated 3D Draft → MP4 (CPU)**.
3. Upload a **transparent PNG**, select **Draft volumetrik 3D (CPU)**,
   enter a supported action (idle/walk/wave/jump), and start generation.
4. The PNG is registered as an immutable Cloudbrowser artifact. Cloudbrowser
   transfers it through an authenticated Studio API and creates a durable mesh job.
5. Inspect the generated GLB topology and shape. **Approve mesh** only if usable;
   the worker then queues Blender rigging automatically.
6. Inspect all four actual Blender pose previews, approve rig. The Studio
   generates a deterministic scene manifest from the prompt.
7. Inspect the manifest, approve it; the worker queues Godot rendering.
8. Inspect the final verified MP4, confirm artistic quality manually, then
   export. The backend enforces source, rig, manifest, output hashes and
   nonblank video frame checks; it does **not** certify plausible anatomy,
   foot locking, likeness, lip sync, or natural character motion.

## Generator limits

The **single-view volumetric loft draft** constructs elliptical cross-sections
from successive visible PNG rows and exports a genuine closed 3D surface with
nonzero width, height and depth. It has texture and can be rigged by the
existing Blender humanoid template. The back, depth and occluded body parts
are **inferred heuristically**, not recovered. This can bridge separate legs,
flatten details or create wrong proportions. For precise ARUSIA characters,
import a human-reviewed authored 3D GLB or add controlled multiview source
images, anatomy-aware reconstruction and retopology first.

The response explicitly reports
`"full_3d_reconstruction_verified": false`, while mesh QA reports
`"volumetric_mesh": true` and
`"hidden_surface_provenance": "inferred_elliptical_depth"`.

The existing Studio manifest still supports **one actor**, actions
idle/walk/wave/jump, up to **15 seconds and 900 frames** per job. Supported
resolutions are 640×360, 1280×720 and 1920×1080, at 24/30/60 FPS. The
generator does not automatically create new images, new body-part views, new
animation tracks, voices or realistic motion.

## Review-gated automation, not self-approval

The entry point `POST /api/studio/generate` is authenticated and CSRF-protected
by the owner dashboard. It accepts a registered PNG artifact ID, bounded
prompt, CPU mesh mode, FPS, resolution and character. The Cloudbrowser
service registers a Studio project, then calls
`POST /api/projects/{id}/generate`. The Studio atomically records the mode
and queues the first job. Repeated start requests on the same Studio project
are rejected, never duplicated.

The following transitions are **automatic only after exact owner approval**:
- `mesh_review` → owner approval → rig job queued.
- `rig_review` → owner approval → scene manifest created for review.
- `manifest_review` → owner approval → Godot render queued.
- `completed` → checksum-verified MP4 available.

An interrupted in-flight stage is marked failed rather than silently
replayed. Owner manually inspects and retries according to existing
recovery policy. Do not enable automatic approval just to claim autonomy.

## Evidence and rollout

Unit regression: `python -m pytest -q services/studio_v4/tests/test_generated_video.py`
with the Studio package on Python path (or execute from
`services/studio_v4` using `python -m pytest -q tests/test_generated_video.py`).
Studio CI also runs a real synthetic PNG → volumetric GLB → Blender
four-pose rig → owner approvals → Godot MP4 smoke test in the built
container, uploading a video and machine-readable report. **A green CI
establishes only the tested environment and synthetic assets.**

For the envisioned **three Codespaces** deployment, Cloudbrowser control
plane, 3D asset worker and render worker require an authenticated job API,
bounded upload/download, artifact integrity, durable shared *service* state,
worker identity and heartbeat, and backup outside Codespaces. Those
distributed mechanisms are **not implemented by this feature**; the current
Studio worker holds a single-host SQLite workspace lock. Do not mount the
same SQLite database over multiple Codespaces or expose a Studio token publicly.
