import os
from pathlib import Path

DATA_ROOT = Path(os.getenv('STUDIO_DATA_ROOT', './workspace')).resolve()
DATA_ROOT.mkdir(parents=True, exist_ok=True)
DATABASE = DATA_ROOT / 'studio.sqlite3'
# Requires a strong token outside loopback deployment.
API_TOKEN = os.getenv('STUDIO_API_TOKEN', '')
STUDIO_ENV = os.getenv('STUDIO_ENV', os.getenv('APP_ENV', 'development')).strip().lower()
BLENDER = os.getenv('BLENDER_BIN', 'blender')
FFMPEG = os.getenv('FFMPEG_BIN', 'ffmpeg')
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 6_000_000
MAX_DURATION_SECONDS = 15
MAX_TOTAL_FRAMES = 900

# Offline animation/render stage is always Godot. Blender is retained only for skinning/rig authoring.
GODOT = os.getenv('GODOT_BIN', 'godot')
FFPROBE = os.getenv('FFPROBE_BIN', 'ffprobe')


def validate_security_config(api_token: str = API_TOKEN, environment: str = STUDIO_ENV) -> None:
    """Fail closed for production and reject weak shared service credentials."""
    if not isinstance(api_token, str):
        raise RuntimeError('STUDIO_API_TOKEN must be a string')
    if api_token and len(api_token) < 32:
        raise RuntimeError('STUDIO_API_TOKEN must contain at least 32 characters')
    if not isinstance(environment, str):
        raise RuntimeError('STUDIO_ENV must be a string')
    if environment.strip().lower() in {'production', 'prod'} and len(api_token) < 32:
        raise RuntimeError('Production Studio requires STUDIO_API_TOKEN with at least 32 characters')
