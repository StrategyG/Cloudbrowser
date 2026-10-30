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
   Use `assemble_cpu_episode` for up to 120 uniform H.264 shots (with optional
   episode audio and selectable subtitles); `compose_video` remains available
   for at most 20 mixed-format clips.

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

## Layered 2D scenes: up to five characters

\`render_cpu_scene\` composes one registered PNG background and up to five
transparent sprite actors in draw order (back-to-front). Each actor can have
1–4 authored pose PNGs, an independent horizontal translation and a pose
hold time. The engine uses CPU FFmpeg; it does not calculate skeletons,
inverse kinematics, shading, phonemes or natural movement. For ARUSIA, provide
real Kio/Lumi/Arka/Mayor/RUX pose assets and review visual correctness.

Example inputs (replace every illustrative artifact ID with actual IDs):

\`\`\`json
{
  "background_id": "00000000000000000000000000000001",
  "actors": [
    {"pose_ids": ["00000000000000000000000000000002"],
     "actor_width": 180, "start_x": 30, "end_x": 250,
     "y": 400, "pose_hold_frames": 3},
    {"pose_ids": ["00000000000000000000000000000003"],
     "actor_width": 180, "start_x": 450, "end_x": 450,
     "y": 400, "pose_hold_frames": 3}
  ],
  "duration": 8,
  "width": 1280, "height": 720, "fps": 24
}
\`\`\`

Scenes are individually bounded to 15 seconds or 900 frames and no more
than 20 actor pose PNG inputs. Actor layers are planar overlays; use the
author-supplied layer order for foreground/background occlusion. The editor
can queue this tool through Cloudbrowser, then use
\`assemble_cpu_episode\` to combine approved shots. Keep heavy render work
serial on low-resource Codespaces machines.

## Full CPU episode assembly (up to 120 approved MP4 shots)

The new \`assemble_cpu_episode\` editor/orchestrator tool accepts 1–120
**registered local MP4** shot IDs in playback order. It requires uniform
H.264/yuv420p dimensions, frame rate, timebase, codec profile and level.
Inputs must not carry audio streams; the optional episode-wide audio input
may be WAV, MP3, OGG, FLAC or M4A. Optional SRT captions are embedded as a
selectable MP4 subtitle stream (\`mov_text\`), **not burned into frames**.

\`\`\`json
{
  "shot_ids": [
    "00000000000000000000000000000001",
    "00000000000000000000000000000002"
  ],
  "audio_id": "",
  "subtitle_id": ""
}
\`\`\`

The assembler uses FFmpeg concat with \`-c:v copy\` for speed instead of
re-encoding the entire episode. It validates registered paths, matching
video parameters, per-shot duration (0–15 seconds), total duration
(maximum 20 minutes), resulting streams and approximate duration. It caches
the result by ordered content hashes and rejects source modifications seen
during assembly. Source files are not fetched from websites or arbitrary
filesystem locations. The whole MP4 is still bounded by the server's
artifact size limit, **100 MiB by default**.

It is a **single-worker bounded episode assembler**, not a distributed
durable queue or a multi-character animation engine. Shot generation is
checkpointed by per-shot hash caches, so a repeated approved job can reuse
completed source MP4s; an interrupted assembly is rerun from approved shots.
The assembled output still needs full decoding, listening, sync review and
owner approval. The system does not guarantee precisely once effects on
external providers.

### Target-machine release qualification

First install dependencies and run the Python test suite (see below).
Then run a real CPU smoke test on **the actual Codespace**:

\`\`\`bash
python scripts/cpu_production_acceptance.py --shot-seconds 3 \
  --report cpu-video-acceptance.json

# Long-duration synthetic episode: 120 x 6s = 720s, at 640x360/24fps.
# This does NOT certify image/animation quality.
python scripts/cpu_production_acceptance.py --shot-seconds 6 \
  --repeat-cycles 60 --report cpu-video-12min.json
\`\`\`

The acceptance tool synthesizes its own PNG assets and actually renders
two pose-cycled shots, concatenates them and decodes the resulting MP4
fully. It reports elapsed time, child-process peak RSS and actual duration.
It requires no GPU, model account or API credentials. The full test must
finish while the Codespace remains alive and within available storage.
Inspect both JSON reports. Run an additional production-sized real-asset
test at the intended final resolution and FPS, since the 640x360 smoke
test does not measure 1080p performance.

**Release gates:** passing CI and Codespaces CPU benchmark; verified
RAM/disk/headroom under load; repeatable restart/resume from persisted
artifacts; owner visual review of actual ARUSIA walk cycles, multi-character
timing and lip sync; final audio/subtitle sync; a 12-minute finished
episode that passes content QC. Failure of any gate means **NO-GO for
unattended commercial animation production**.

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
