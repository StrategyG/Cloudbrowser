# Studio/Godot in Cloudbrowser 0.4

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
- PNG conversion is a silhouette shell; external rigged GLB upload is not implemented.
- Walking is procedural. Foot IK, foot lock, lip sync, facial acting and multi-character scenes
  remain outside the current renderer. Rendered clips have no generated narration or soundtrack.
- This is an animation pipeline; it does not add a nonlinear video timeline/audio mixer.
- Human mesh/rig/manifest inspection remains necessary. Numerical media checks do not prove
  natural motion, matching characters, correct narrative or nonblank frames.
- Godot/Blender and Docker are unavailable in the local authoring runtime. A real approved rig →
  Godot AVI → MP4 run and visual review on the target server remain required before production use.

GitHub CI is configured for root tests, clean Studio tests, container builds, and Godot import.
A workflow definition is not evidence of an executed/passing GitHub run. See VALIDATION.md.
