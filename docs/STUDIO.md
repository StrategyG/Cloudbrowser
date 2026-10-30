# Studio/Godot in Cloudbrowser 0.4

**Animation Copilot v1:** The authenticated `/studio` page offers Chat / Plan / Edit / Agent prompts with four scoped A2A specialist roles. See [Copilot workflow and boundaries](COPILOT.md). Editing is limited to existing approved Studio operations, not unrestricted live changes to the isolated MorphGLB iframe.

**Google Sites portal:** To open the authenticated MorphGLB editor from a Google Sites button, link to `https://your-cloudbrowser-domain.example/?open=studio`. The fixed same-origin deep link works after the owner logs in. Do not embed the authenticated Studio iframe; see [Google Sites editor integration](GOOGLE_SITES_EDITOR.md).

## External GLB → Studio/Godot (review-gated)

Cloudbrowser now accepts local **PNG or GLB** as the source artifact in
`studio_create_project`. In MorphGLB, export a GLB and select **Buat job A2A**
when importing it into the Cloudbrowser catalog. The owner approves each
mutating A2A tool call as before. Alternatively, ask the agent to create a
Studio project from an existing GLB artifact ID.

- PNG continues through `uploaded → mesh_building → mesh_review`.
- External GLB is validated on upload and starts at `mesh_review`. The mesh
  stage **must not** be retried; no mesh is automatically approved.
- After explicit mesh approval, `rig` creates a Blender humanoid template
  if the imported mesh has no existing skin. The original source GLB stays
  unchanged in `mesh.glb`.
- If the GLB contains a valid existing skin, Blender inspects the armature
  and produces rest/arms/legs/combo pose previews. The original skinned
  GLB is preserved as `rigged.glb`, not silently re-rigged.
- The rig still requires owner inspection/approval. A scene manifest, render
  and completed MP4 follow the existing approval and frame-QA workflow.

**Current import boundaries:** one **watertight**, consistently wound,
positive-volume, connected triangle mesh; a single GLB primitive and at most
one skin; embedded buffers/textures only; no required extensions, external
URIs or embedded GLB animations; at most 600k vertices and 50 MiB. Compatible
skinned assets must have `UpperArm_L`, `UpperArm_R`, `UpperLeg_L`, and
`UpperLeg_R` bones, valid vertex weights and one bound armature.
Mesh/rig numeric checks are not an animation or likeness guarantee.
Incompatible rigs **fail** instead of automatically replacing authored
bones; repair the rig in MorphGLB/Blender before reimport.

The Godot procedural runner still supports one actor with idle/walk/wave/jump
and does not play imported GLB animation tracks. Imported 3D assets are
**not** asserted to have accurate foot locking, retopology or professional
deformation. Real Blender four-pose previews, Godot asset import, video frame
QA, and independent visual approval remain the production release gates.

## MorphGLB AI Studio v3.3.0 (integrated editor)

Cloudbrowser serves the exact standalone editor supplied by the project owner as
`cloudbrowser/morphglb/MorphGLB_AI_Studio_v3.3.0.html`. Open the authenticated dashboard
and select **Buka MorphGLB 3D**, or visit `/studio#morphglb`. The original
`/studio` PNG → Studio/Godot/A2A controls are preserved.

The editor is loaded **on demand**, inside an iframe. It supports its original local
mesh/rig controls, WebGL preview and downloadable GLB/JSON/video where supported by
the device. The app file bundles its renderer and dependencies; these are not fetched
from third-party CDNs. Browser hardware/WebGL/WebCodecs compatibility varies.

### Transfer to Cloudbrowser

1. Export GLB, PNG or JSON in MorphGLB.
2. Under the iframe, select the exported file and click **Impor aset ke Cloudbrowser**.
3. The authenticated parent checks its extension, size and basic file signature, then
   registers it using `PUT /api/artifacts` with a session CSRF token.
4. For a **PNG or GLB**, optionally select **Buat job A2A** and provide a prompt. The job
   enters the existing A2A queue and requires the normal human approvals.

Limits at the bridge: PNG 12 MiB, GLB 50 MiB, JSON 2 MiB (also bounded by the configured
Cloudbrowser server upload limit). The original editor's optional local AI endpoints
such as `/api/tripo` are **not** implemented by Cloudbrowser. GLB is registered as
an artifact; the bundled Studio/Godot service ingests only **validated, review-gated** GLB.
Registration alone is not mesh validation, full 3D reconstruction or a completed video.
There is deliberately no automatic API-key sharing or silent enqueue.

### Isolation and security

The 1.6 MB editor source is **outside public `/static`**, accessible only through
the session-protected `GET /studio/morphglb` route. The iframe has
`sandbox="allow-scripts allow-downloads"` and **not** `allow-same-origin`.
The server also applies a CSP `sandbox` directive, including for direct visits.
The sandbox has an opaque origin, no arbitrary network connections (blob/data fetches are permitted for local GLB textures), no top-level navigation,
no forms, and no access to dashboard session/CSRF data. The parent handles explicit
asset transfers only. Inline script/style is permitted **within that sandbox only**,
while the ordinary Cloudbrowser dashboard retains its strict CSP.

The original source is checked into this repository as supplied, retaining its
dependency notices and licenses. Since this repository is public, that source is
public too. Do not place API keys, tokens or private content inside vendored HTML.

### Verification

Run `python -m pytest -q tests/test_morphglb.py` and existing project tests.
The test covers auth, CSP, embedding, public-static isolation and the bridge file.
Full acceptance also requires manually opening the frame in a logged-in browser,
importing a real PNG and GLB, then running a separate approved Studio/Godot job
on a server with Blender, Godot and FFmpeg. No remote provider account or video
render is validated by these unit tests.

Cloudbrowser 0.4 retains the persistent Chromium browser, private dashboard, Telegram owner controls,
model-created A2A specialists, project memory, action ledger and output verification from 0.3.
Studio/Godot is a separate bundled service connected to the same orchestrator and editor role.
The generated scene is a single-character 2.5D animation, not multiview 3D reconstruction.

## Start

On a Linux server with Python 3 and Docker Compose:

```bash
sh scripts/start_studio.sh
```

The script generates an independent Studio service token in the ignored, mode-0600 `.env` file
if none exists. It then builds all services, opens the existing first-run AI/Telegram configuration
wizard, and starts the stack. Reuse existing configuration and runtime data; the two data volumes
are independent. No OpenAI subscription, API key provider, or live account is bundled.

Open Cloudbrowser on port 8000, log in, and select **Buka Studio**. Upload a transparent PNG and
enter an action such as `KIO berjalan lalu melambaikan tangan, 5 detik`. The task enters the normal
durable A2A job queue and Telegram can control the same task. Studio mutations and each mesh/rig/
manifest approval require an exact owner decision even in auto mode.

Inspect the project ID reported by the agent in `/studio` to view mesh QA, four rig pose images,
manifest JSON and the completed MP4. The Studio token remains server-side on this page.
The original manual manifest editor is also available at `http://127.0.0.1:8001`; enter the Studio
token from the private server `.env`. Its optional Three.js preview requires access to esm.sh.
For a remote server, forward both ports with SSH:

```bash
ssh -L 8000:127.0.0.1:8000 -L 8001:127.0.0.1:8001 USER@SERVER
```

The Studio services add their own memory limits (1 GB API, 4 GB renderer) to the browser's 4 GB
limit. These are ceilings, not measured hardware requirements; benchmark the actual server.
The supplied Godot binary is for Linux x86_64. Other architectures need a matching verified binary.

For an already running native Studio service, use:

```bash
python -m cloudbrowser configure-studio
```

The configured origin and token can also be supplied by `CLOUDBROWSER_STUDIO_URL` and
`CLOUDBROWSER_STUDIO_TOKEN`. Plain HTTP is restricted to configured loopback/host gateway or the
Compose `studio-api` service. Remote services require HTTPS. Restart after configuration changes.

## Agent tools and proof

The orchestrator and editor receive `studio_create_project`, `studio_get_project`,
`studio_start_stage`, `studio_plan_scene`, `studio_approve_stage`, and `studio_import_asset`.
The reviewer can only read Studio project QA. Writer/browser specialists receive no Studio tools.
Inputs, project IDs, stage names, dimensions and FPS are bounded; models cannot choose endpoints
or credentials. HTTP redirects and oversized responses are rejected. No mutation is retried by
the client; ambiguous results enter the existing action ledger for owner reconciliation.

Use separate workflow steps for mesh/rig QA summaries, the approved scene manifest, and the final
video. Save intermediate QA summaries as JSON text artifacts when a workflow step expects text.
Only import the MP4 after Studio reports `completed`, then perform independent A2A video review.
Intermediate PNG/GLB files do not satisfy the final video requirement. Long render waits should
yield with `ask_user`, retain the Studio project ID, and resume after checking project state.

The renderer uses Blender for rig creation, Godot 4.7.2 for offline animation/movie capture,
and FFmpeg for MP4 conversion. The Godot download is SHA-256 checked against the official release
asset. NetworkX is explicitly installed and locked, fixing clean-install mesh graph failures.
Stage state changes and queue inserts are transactional; an OS file lease prevents a second
worker from reclaiming the first worker's running jobs in the same workspace.

## Limits and release gate

- One character, maximum 15 seconds/900 frames, 24/30/60 FPS, 640×360, 1280×720 or 1920×1080.
- PNG conversion remains a silhouette shell. External GLB upload has strict one-mesh, topology, single-rig and pose-review gates.
- Walking is procedural. Foot IK, foot lock, lip sync, facial acting and multi-character scenes
  remain outside the current renderer. Rendered clips have no generated narration or soundtrack.
- This is an animation pipeline; it does not add a nonlinear video timeline/audio mixer.
- Human mesh/rig/manifest inspection remains necessary. Numerical media checks do not prove
  natural motion, matching characters, correct narrative or nonblank frames.
- Godot/Blender and Docker are unavailable in the local authoring runtime. A real approved rig →
  Godot AVI → MP4 run and visual review on the target server remain required before production use.

GitHub CI is configured for root tests, clean Studio tests, container builds, and Godot import.
A workflow definition is not evidence of an executed/passing GitHub run. See VALIDATION.md.
