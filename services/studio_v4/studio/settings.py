import os
from pathlib import Path

DATA_ROOT = Path(os.getenv('STUDIO_DATA_ROOT', './workspace')).resolve()
DATA_ROOT.mkdir(parents=True, exist_ok=True)
DATABASE = DATA_ROOT / 'studio.sqlite3'
# Requires a strong token outside loopback deployment.
API_TOKEN = os.getenv('STUDIO_API_TOKEN', '')
BLENDER = os.getenv('BLENDER_BIN', 'blender')
FFMPEG = os.getenv('FFMPEG_BIN', 'ffmpeg')
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 6_000_000
MAX_DURATION_SECONDS = 15
MAX_TOTAL_FRAMES = 900

# Offline animation/render stage is always Godot. Blender is retained for GLB rig authoring.
GODOT = os.getenv('GODOT_BIN', 'godot')
FFPROBE = os.getenv('FFPROBE_BIN', 'ffprobe')
