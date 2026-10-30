# MorphGLB 3D service integration — design and current gate

## Decision

Integrate MorphGLB AI Studio 3.3.0 as a **separate 3D service**. Keep the existing
Studio/Godot 2.5D service, Cloudbrowser A2A orchestrator, browser session, and artifact
registry intact. This branch is additive; do not merge to `main`, deploy, or change
runtime infrastructure without explicit owner approval.

## Source package inspected

- Input: `MorphGLB_AI_Studio_v3.3.0.zip`
- SHA-256: `c7455e6c70836e248f84b7d040911ec5e3763c49dd6c580b4a2be3355f1437be`
- 85 ZIP entries; approximately 4.27 MB expanded.
- Main components: static 3D editor/viewer, Python API, Tripo V3 client and durable
  SQLite job engine, GLB/UV validation, Blender renderer, FFmpeg MP4 pipeline, tests,
  reports, examples and third-party notices.

The upstream package labels itself `PRODUCTION_CANDIDATE`. Its own report states
131 local checks passed, but live Tripo inference/account entitlement is unverified,
artistic approval is false, and the application is single-user localhost only.
These are upstream claims from the supplied package, not tests run in Cloudbrowser.

## Intended service boundary

- Existing Cloudbrowser dashboard remains the entry point.
- Existing Studio/Godot stays available for silhouette-based 2.5D animation.
- MorphGLB runs as a separate internal service with its own persistent workspace and
  worker lifecycle.
- The A2A editor role will receive narrowly scoped MorphGLB tools only after the
  API adapter, approval flow, ownership checks and tests are implemented.
- Final GLB/MP4 artifacts must be imported through Cloudbrowser's artifact registry;
  intermediate assets remain explicitly labelled as intermediate.
- All paid Tripo task creation requires explicit owner approval. No automatic retry
  after an ambiguous POST; reconcile using the persisted task ID/state.

## Security and production gates

1. Do not expose MorphGLB's current unauthenticated localhost API on a public interface.
2. Add a service-to-service credential, constant-time verification, fixed route allowlist,
   bounded request/response bodies, timeouts, no redirects, and loopback/internal-only
   network binding before connecting Cloudbrowser.
3. Keep `TRIPO_API_KEY` in the server secret environment only; never put it in browser
   HTML, logs, repository files, ZIP, or user-visible tool arguments.
4. Use a non-root container, read-only root filesystem where practical, dropped Linux
   capabilities, CPU/RAM/PID limits, isolated writable workspace, and no host Docker
   socket. Blender/FFmpeg workers must not receive Cloudbrowser browser-session files.
5. Preserve user approval for paid generation, stage transitions, publication and
   external sharing. QA pass is not artistic approval.
6. Run package tests, Cloudbrowser regression tests, API boundary/security tests,
   container build, and one explicitly approved live Tripo smoke test separately.
   A live smoke test may spend credits and is not authorized by this branch creation.

## Current implementation status

- Branch created from `main`: `feat/morphglb-3d-service`.
- The safe source-staging script is provided at `scripts/import_morphglb.py`.
  It verifies the supplied archive hash, rejects traversal/symlinks/oversized archives,
  skips secrets and caches, and refuses to overwrite an existing target.
- **Blocked before runtime integration:** the GitHub connection can create repository
  objects, but cannot read the conversation's local ZIP bytes as an upload payload.
  Therefore the upstream source has not yet been copied into this repository, and no
  Docker service, A2A tool, API adapter, UI route, or deployment has been activated.
- Next local staging command after placing the supplied ZIP in the repo workspace:

  ```bash
  python scripts/import_morphglb.py --archive /path/to/MorphGLB_AI_Studio_v3.3.0.zip
  ```

  Review the staged source and notices before committing it. Then implement the
  authenticated service wrapper and Compose overlay; do not directly expose port 8080.

## Verification labels

- PASS: branch creation and source archive inventory/hash inspection.
- NOT RUN: importer execution in a Cloudbrowser checkout; no repository checkout is
  available in this session.
- BLOCKED: upstream source upload and executable service integration.
- NOT VERIFIED: Tripo live inference, paid credits, deployment, and production readiness.
