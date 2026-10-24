#!/usr/bin/env bash
# Test the team's fall detector on the OmniFall (GMDCSA24) videos.   Usage:
#   scripts/run_omnifall.sh labels            make labels.json from OmniFall's labels      (seconds)
#   scripts/run_omnifall.sh eval              run their detector on all 160 clips           (about 5 min)
#   scripts/run_omnifall.sh score             accuracy per split + why falls were missed    (seconds)
#   scripts/run_omnifall.sh preview "Subject_1/Fall/04"      before | after video, opens it  (about 10 s per clip)
# Folders it expects (change the three variables below if yours differ):
set -euo pipefail
DATA=${DATA:-$HOME/Hackathons/datasets}                 # holds omnifall/ (labels) and gmdcsa24/ (videos)
TEAM=${TEAM:-$HOME/Hackathons/ollo-remote}              # the team's repo, with its own .venv
HERE="$(cd "$(dirname "$0")/.." && pwd)"                # the vision/ folder of our project
OUT="$DATA/omnifall_gmdcsa24"
THEIRS="$TEAM/.venv/bin/python"; OURS="$HERE/.venv/bin/python"

case "${1:-}" in
  labels)  python3 "$HERE/scripts/make_omnifall_labels.py" "$DATA" ;;
  eval)    mkdir -p "$OUT/full_out"; (cd "$TEAM" && "$THEIRS" -m server.evaluate "$OUT/labels.json" --out "$OUT/full_out") ;;
  score)   "$THEIRS" "$HERE/scripts/score_omnifall.py" "$OUT/full_out/eval.json" ;;
  preview) [ -n "${2:-}" ] || { echo 'give a clip, e.g. "Subject_1/Fall/04"'; exit 1; }
           "$THEIRS" "$HERE/scripts/render_preview.py" "$OUT/labels.json" "$OUT/previews" "$2"
           key="${2//\//_}"; src="$("$OURS" - "$OUT/labels.json" "$2" <<'PY'
import json, os, sys
labels, key = sys.argv[1], sys.argv[2]
c = next(c for c in json.load(open(labels))["clips"] if c["omnifall_path"] == key)
print(os.path.normpath(os.path.join(os.path.dirname(labels), c["path"])))
PY
)"
           mkdir -p "$OUT/compare"
           "$OURS" "$HERE/scripts/compare_before_after.py" "$src" "$OUT/previews/$key.mp4" "$OUT/compare/$key.mp4" "$2"
           open "$OUT/compare/$key.mp4" ;;
  *) sed -n '2,8p' "$0"; exit 1 ;;
esac
