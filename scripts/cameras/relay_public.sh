#!/usr/bin/env bash
# Relay an intentionally public live webcam page into MediaMTX as RTSP (scripts/cameras/README.md).
# MediaMTX runs this with MTX_PATH and RTSP_PORT set and restarts it if it exits, so expiring
# tokenized HLS URLs are re-resolved by streamlink on every restart.
#   relay_public.sh <webcam page URL> [streamlink quality]
set -euo pipefail
PAGE="$1"; QUALITY="${2:-720p,best}"
STREAMLINK="${STREAMLINK:-$(command -v streamlink || echo "$HOME/.local/bin/streamlink")}"
# --stdout: MPEG-TS on stdout. HLS arrives in segment-sized bursts; -re paces it back to real time so
# readers see a steady frame rate (a burst-then-gap feed would look offline to SRC-4 capture).
# ffmpeg copies the video track (no re-encode, no audio) into MediaMTX.
"$STREAMLINK" --quiet --stdout --hls-live-edge 2 --retry-open 3 "$PAGE" "$QUALITY" \
  | ffmpeg -hide_banner -loglevel error -re -fflags +genpts -i - -map 0:v:0 -c copy -an \
      -rtsp_transport tcp -f rtsp "rtsp://127.0.0.1:${RTSP_PORT:-8554}/${MTX_PATH}"
