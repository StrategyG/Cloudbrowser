# CloudBrowser × Godot — controlled animation production MVP

CloudBrowser is a **web control panel and persistent job dispatcher**, with Godot 4 as the animation renderer. This branch contains working API integration; it is **not a production-certified, autonomous 3D editor**.

## Features

- Authenticated upload of an **already rigged `.glb`** (max 32 MiB). Basic structural glTF 2.0/skin validation, **not** comprehensive visual/topology/skin verification.
- Explicit human approval of GLB and shot manifest.
- Deterministic bounded shot manifest: 1–15 seconds, 24/30/60 fps, 640×360/1280×720/1920×1080, idle/walk/wave/jump.
- SQLite-backed queue; separate worker starts Godot Movie Maker via Xvfb, converts AVI to H.264 MP4 via FFmpeg, verifies video metadata, and serves completed files.
- Local dashboard on port `8085`. Bearer token required for all project endpoints. No arbitrary shell, browsing, or Telegram autonomous commands.

## Run

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Put generated secret in CLOUDBROWSER_API_TOKEN in .env
# Configure an actual Godot 4 release in Dockerfile if the pinned release is unavailable.
docker compose up --build
```

Go to `http://localhost:8085` and paste your token into the editor. The Compose ports bind to loopback; configure TLS and identity before sharing externally.

For tests without Godot installed:

```bash
pip install -r requirements.txt
python -m pytest -q
```

## Limitations / production gates

- Godot engine executable, script import, frame-accurate rendering and real GLB animation have **not** been verified in this environment. CI checks Python plus Godot GDScript import, but does not test an actual video export.
- Rig must already exist: PNG-to-GLB reconstruction and Blender rig authoring are separate, not silently implemented here.
- Animator is procedural and **not** motion-matching, IK, grounded locomotion, lip-sync or multi-character timeline. One character/shot at a time, up to 15 sec; 12-min episodes need an assembly pipeline.
- Restart during an active render leaves jobs in `claimed` or `rendering`. Recovery/lease system is a required production enhancement; manual DB updates are not supported.
- FFmpeg QA validates MP4 H.264, resolution and frame count when provided. It does not assess visual fidelity.

## Integration contracts

`POST /api/projects` (multipart `.glb`) → `POST /api/projects/{id}/approve-asset` → `PUT /api/projects/{id}/manifest` → `POST /api/projects/{id}/approve-manifest` → `POST /api/projects/{id}/render` → `GET /api/projects/{id}/video`.

This branch is proposed for review and smoke testing; do not merge into a public production service before external GLB security review and runtime renderer QA.
