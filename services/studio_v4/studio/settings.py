import os
import re
from pathlib import Path

DATA_ROOT = Path(os.getenv('STUDIO_DATA_ROOT', './workspace')).resolve()
DATA_ROOT.mkdir(parents=True, exist_ok=True)
DATABASE = DATA_ROOT / 'studio.sqlite3'
# Production uses a 256-bit, externally provisioned shared service token.
API_TOKEN = os.getenv('STUDIO_API_TOKEN', '')
STUDIO_ENV = os.getenv('STUDIO_ENV', os.getenv('APP_ENV', 'development')).strip().lower()
BLENDER = os.getenv('BLENDER_BIN', 'blender')
FFMPEG = os.getenv('FFMPEG_BIN', 'ffmpeg')
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 6_000_000
MAX_DURATION_SECONDS = 15
MAX_TOTAL_FRAMES = 900

# Offline animation/render stage is always Godot. Blender is retained for GLB rig authoring.
GODOT = os.getenv('GODOT_BIN', 'godot')
FFPROBE = os.getenv('FFPROBE_BIN', 'ffprobe')

_HEX_256 = re.compile(r'^[A-Fa-f0-9]{64}$')
_URLSAFE_256 = re.compile(r'^[A-Za-z0-9_-]{43,}$')


def _is_256_bit_token(value: str) -> bool:
    """Accept common textual encodings of at least 256 bits of random material."""
    if _HEX_256.fullmatch(value):
        return len(set(value.lower())) >= 10
    if _URLSAFE_256.fullmatch(value):
        return len(set(value)) >= 12
    return False


def validate_security_config(api_token: str = API_TOKEN, environment: str = STUDIO_ENV) -> None:
    """Fail closed unless configured shared credentials use a 256-bit token encoding."""
    if not isinstance(api_token, str):
        raise RuntimeError('STUDIO_API_TOKEN must be a string')
    if not isinstance(environment, str):
        raise RuntimeError('STUDIO_ENV must be a string')

    production = environment.strip().lower() in {'production', 'prod'}
    if not api_token:
        if production:
            raise RuntimeError('Production Studio requires a 256-bit STUDIO_API_TOKEN')
        return

    if not _is_256_bit_token(api_token):
        raise RuntimeError(
            'STUDIO_API_TOKEN must encode at least 256-bit random material: use 64 hex '
            'characters or at least 43 URL-safe base64 characters with sufficient character diversity; generate with '
            'secrets.token_hex(32) or secrets.token_urlsafe(32)'
        )
