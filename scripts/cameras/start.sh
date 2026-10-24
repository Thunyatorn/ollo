#!/usr/bin/env bash
# Start the development cameras (scripts/cameras/README.md). Run from anywhere; Ctrl-C stops all.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
command -v ffmpeg >/dev/null || { echo "ffmpeg is required (brew install ffmpeg / sudo apt-get install ffmpeg)"; exit 1; }
command -v streamlink >/dev/null || [ -x "$HOME/.local/bin/streamlink" ] || echo "note: streamlink not found; public relays (bourbon, timessquare, dublin) will retry until it is installed (pipx install streamlink)"
[ -x scripts/cameras/.bin/mediamtx ] || scripts/cameras/get-mediamtx.sh
[ -f scripts/cameras/media/demo_room.mp4 ] || .venv/bin/python scripts/cameras/make_demo_room.py
exec scripts/cameras/.bin/mediamtx scripts/cameras/mediamtx.yml
