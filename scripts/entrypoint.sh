#!/bin/sh
set -eu
umask 077
exec xvfb-run -a -s '-screen 0 1280x720x24 -nolisten tcp' python -m cloudbrowser "$@"
