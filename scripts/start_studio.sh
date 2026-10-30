#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
umask 077
python3 - <<'PY'
from pathlib import Path
import os
import secrets
path = Path('.env')
content = path.read_text() if path.exists() else ''
if not any(line.strip().startswith('STUDIO_API_TOKEN=') for line in content.splitlines()):
    path.write_text(content.rstrip() + '\nSTUDIO_API_TOKEN=' + secrets.token_hex(32) + '\n')
os.chmod(path, 0o600)
PY
docker compose -f compose.yaml -f compose.studio.yaml config -q
docker compose -f compose.yaml -f compose.studio.yaml build
docker compose -f compose.yaml -f compose.studio.yaml run --rm cloudbrowser configure --if-missing
docker compose -f compose.yaml -f compose.studio.yaml up -d
printf '\nCloudbrowser: http://127.0.0.1:8000 — Studio agent: http://127.0.0.1:8000/studio\n'
printf 'Editor manifest manual: http://127.0.0.1:8001 (token Studio di .env server).\n'
