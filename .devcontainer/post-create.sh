#!/usr/bin/env bash
set -euo pipefail

# No Docker-in-Docker or GPU access is required for the CPU video path.
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  ffmpeg fonts-dejavu-core xvfb xauth
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m playwright install --with-deps chromium
ffmpeg -hide_banner -version | head -n 1
python -m pip check
printf 'Codespaces CPU video dependencies installed. Run: python scripts/cpu_production_acceptance.py\n'
