#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker compose version >/dev/null
docker compose build
docker compose run --rm cloudbrowser configure --if-missing
docker compose up -d
printf '\nCloudbrowser berjalan. Dashboard: http://127.0.0.1:8000\n'
printf 'Kirim /start ke bot Telegram. Log: docker compose logs -f\n'
