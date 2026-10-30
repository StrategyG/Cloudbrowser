# Codespaces: CPU-only Video Production (no GPU)

This is an **opt-in, bounded 2D sprite workflow** for Cloudbrowser. It uses
registered PNGs and FFmpeg/libx264; it does **not** generate images, reconstruct
3D meshes, perform IK, lip sync, photorealistic animation, or run Blender/Godot.
Do not infer GPU availability or an external rendering provider.

## One Codespace, two workloads

The existing Cloudbrowser process provides the private dashboard, Telegram,
Playwright browser and A2A agents. The same process can invoke FFmpeg through
the new \`render_cpu_shot\` editor/orchestrator tool. It serializes active jobs
through the existing queue/browser control lease. Do **not** start a second
independent Cloudbrowser worker against the same data directory.

The existing Studio/Blender/Godot stack is **optional**, not a prerequisite.
Its documented Godot movie rendering has not been validated in a GPU-free
Codespace; start with the CPU FFmpeg path and keep Studio disabled initially.

Suggested starting Codespace: **4 vCPU / 16 GiB**, when available to your
account. For 2 vCPU, reduce resolution to 640×360 and avoid simultaneous
Chromium sessions. Costs depend on Codespaces machine size and active hours.

## Setup in GitHub Codespaces

From the repository root, using a Python 3.11+ environment:

\`\`\`bash
sudo apt-get update
sudo apt-get install -y ffmpeg fonts-dejavu-core xvfb xauth
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m playwright install --with-deps chromium
python -m cloudbrowser configure
xvfb-run -a -s '-screen 0 1280x720x24 -nolisten tcp' \
    python -m cloudbrowser --host 127.0.0.1 --port 8000
\`\`\`

Alternatively use the existing Docker startup, when Docker is supported by
the Codespace. Keep ports 8000/8001 private; use the Codespaces forwarded-port
URL and the existing dashboard authentication. Telegram polling itself needs
only outgoing network connectivity.

Never paste API keys into prompts or commit them to Git. Codespaces can be
stopped/idle-terminated; it is not a 24-hour production host. Persist
\`CLOUDBROWSER_DATA_DIR\` (or Docker data volume) and export approved media
to durable storage before deleting/rebuilding a Codespace.

## Rendering a shot with the Cloudbrowser agent

1. Upload a **PNG background** and **1–8 transparent PNG actor poses** to
   Cloudbrowser. In the dashboard or \`list_artifacts\` capture each 32-character
   artifact ID; files must be in Cloudbrowser's registered artifact catalog.
2. Have an editor specialist (or the orchestrator) call
   \`render_cpu_shot\` with those IDs and motion parameters.
3. Inspect the actual returned MP4 with \`inspect_artifact\` and human visual
   review; then pass the returned ID to \`compose_video\` for sequential shots.
   The current compose tool accepts 1–20 clips. Split larger episodes into
   batches and perform final assembly in a separate approved workflow.

Example **tool arguments** (replace the placeholder IDs with real artifact IDs):

\`\`\`json
{
  "background_id": "00000000000000000000000000000001",
  "pose_ids": [
    "00000000000000000000000000000002",
    "00000000000000000000000000000003"
  ],
  "duration": 5,
  "width": 1280,
  "height": 720,
  "fps": 24,
  "actor_width": 220,
  "start_x": 90,
  "end_x": 520,
  "y": 390,
  "pose_hold_frames": 3
}
\`\`\`

Each shot is limited to **1–15 seconds**, **900 output frames maximum**,
up to 1080p, and **two encoder threads**. The FFmpeg filter graph is derived
from validated numeric parameters; no model-supplied shell command, arbitrary
filter, URL, or unregistered media path is accepted. All media decoding uses
the existing FFmpeg input format/protocol restrictions.

Pose cycling changes expression/limb artwork only when distinct pose PNGs
are provided; linear horizontal translation alone is *not a walk cycle*.
Use 4–8 authored PNG poses for a simple walk cycle. The position is
interpolated over the shot. Background scaling preserves aspect ratio with
letterboxing. Audio, narration and subtitles can be added later with
\`compose_video\`.

Successful outputs are registered in the Cloudbrowser artifact catalog.
An identical job uses a SHA-256 cache keyed on PNG content and all render
parameters. Cache hits validate the rendered file's hash before reuse;
changed input PNG bytes or parameters force a new render. Failed or cancelled
encodes remove their unregistered partial MP4. These protections reduce
duplicate CPU work; they are not a substitute for persistent backup.

## Validation

\`\`\`bash
python -m ruff check cloudbrowser/cpu_shot.py cloudbrowser/tools.py \
  cloudbrowser/agent.py cloudbrowser/crew.py tests/test_cpu_shot.py
python -m pytest -q tests/test_cpu_shot.py
python -m pytest -q
\`\`\`

Acceptance requires actual FFmpeg/libx264 rendering on the target Codespace,
correct MP4 streams/duration/FPS, cache reuse and invalid-input rejection,
followed by visual approval. CI passing is not proof of animation naturalness.

## Episode production recommendation

For an ARUSIA episode, plan 5–15 second shots, reuse approved environments,
reuse authored sprite cycles, and render 640×360 or 1280×720 previews before
1080p finals. Keep one render running at a time and do not run Studio 3D
jobs concurrently in a small Codespace. A full 12-minute, five-character
episode is **not** supported by one \`render_cpu_shot\` call or by an
automatically verified episode pipeline; the shot producer and assembly gates
must be extended and benchmarked separately.
