#!/usr/bin/env bash
# Start, stop and check the ollo Spacetime edition on this computer.
#
#   scripts/nestwatch.sh start [--source demo|webcam|phone|FILE|URL] [--calls simulated|real] [--loud-alarm] [--demo-map]
#   scripts/nestwatch.sh status
#   scripts/nestwatch.sh stop
#
# --source   demo    a video of one person moving about, then a fall (built from the GMDCSA24 dataset, looped)   [default]
#            webcam  this computer's camera
#            phone   a phone's browser as the camera (prints the address to open on the phone)
#            FILE    a video file, played at its own speed (add --loop yourself in vision/ if you want it repeated)
#            URL     an rtsp:// or http:// camera address
# --calls    simulated  no real phone call is ever made                                                          [default]
#            real       the worker places REAL calls (needs CALLS_ENABLED values in worker/.env); asks you to type yes
# --loud-alarm  let the local alarm really sound (default: it is only logged, so testing does not blast the speaker)
# --no-claude   turn Claude off (the looping demo raises an alert every few seconds and each closed one gets a
#               Claude-written report, about $0.01 each, billed to the API key in worker/.env)
# --demo-map    stretch the picture over the room instead of using a calibration (positions are then not real)
#
# Needs the Spacetime server to be running already (`spacetime start`) and the module published to it.
# Logs: .run/logs/   Process ids: .run/*.pid   (both git-ignored)
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/.run"; LOGS="$RUN/logs"; mkdir -p "$LOGS"
STDB="http://127.0.0.1:3000"; WORKER_PORT=8787; VISION_PORT=8000; WEB_PORT=5173

say() { printf '%s\n' "$*"; }
alive() { [ -f "$RUN/$1.pid" ] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }
up() { curl -s -m 2 -o /dev/null "$1"; }

launch() {   # launch NAME DIRECTORY COMMAND...   runs COMMAND in DIRECTORY, detached, output to .run/logs/NAME.log, real pid in .run/NAME.pid
  local name="$1" dir="$2"; shift 2
  ( cd "$dir" && exec "$@" ) >> "$LOGS/$name.log" 2>&1 < /dev/null &
  echo $! > "$RUN/$name.pid"
}

stop_one() {   # stop_one name "pattern that identifies the process even without a pid file"
  if [ -f "$RUN/$1.pid" ]; then kill "$(cat "$RUN/$1.pid")" 2>/dev/null; rm -f "$RUN/$1.pid"; fi
  pkill -f "$2" 2>/dev/null
}

cmd_stop() {
  stop_one vision "nestwatch_vision.main"
  stop_one worker "nestwatch_worker.main"
  if [ -f "$RUN/web.pid" ]; then kill "$(cat "$RUN/web.pid")" 2>/dev/null; rm -f "$RUN/web.pid"; fi
  say "Stopped the vision service and the worker (and the website, if this script started it)."
}

cmd_status() {
  up "$STDB/v1/ping" && say "Database (Spacetime):  running" || say "Database (Spacetime):  NOT running  -> run: spacetime start"
  if up "http://127.0.0.1:$WORKER_PORT/health"; then
    say "Worker:                running  ($(curl -s -m 2 "http://127.0.0.1:$WORKER_PORT/health" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("calls:", d["calls"], "| Claude:", "on" if d["claude"]=="on" else "off")'))"
  else say "Worker:                not running"; fi
  if up "http://127.0.0.1:$VISION_PORT/health"; then
    say "Vision service:        running  ($(curl -s -m 2 "http://127.0.0.1:$VISION_PORT/health" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("camera", "online" if d["camera_online"] else "OFFLINE", "|", d["fps"], "fps |", "calibrated" if d["calibrated"] else "not calibrated")'))"
  else say "Vision service:        not running"; fi
  if curl -s -m 2 "http://127.0.0.1:$WEB_PORT/" | grep -q "ollo"; then say "Website:               running  -> http://127.0.0.1:$WEB_PORT"
  else say "Website:               not running"; fi
}

cmd_start() {
  local SOURCE=demo CALLS=simulated LOUD=0 DEMOMAP=0 CLAUDE=auto
  while [ $# -gt 0 ]; do
    case "$1" in
      --source) SOURCE="${2:-}"; shift 2;;
      --calls) CALLS="${2:-}"; shift 2;;
      --loud-alarm) LOUD=1; shift;;
      --demo-map) DEMOMAP=1; shift;;
      --no-claude) CLAUDE=off; shift;;
      *) say "Unknown option: $1"; exit 2;;
    esac
  done
  [ "$CALLS" = simulated ] || [ "$CALLS" = real ] || { say "--calls must be simulated or real"; exit 2; }

  up "$STDB/v1/ping" || { say "The database is not running. Start it first:  spacetime start   (then publish the module if it is a new one)"; exit 1; }

  if [ "$CALLS" = real ]; then
    say "REAL phone calls will be placed to the on-duty backup caregiver when an alert goes unanswered."
    if [ "$SOURCE" = demo ]; then say "The demo raises alerts again and again, so it would ring the phone again and again. Use --calls simulated for the demo."; exit 1; fi
    printf 'Type yes to turn real calls on: '; read -r ans; [ "$ans" = yes ] || { say "Cancelled."; exit 1; }
  fi

  cmd_stop >/dev/null

  # worker (its settings come from worker/.env; for simulated calls the real-call switch is forced off)
  local WENV=""
  [ "$CALLS" = simulated ] && WENV="CALLS_ENABLED=false SIM_CALL_OUTCOME=${SIM_CALL_OUTCOME:-press1} SIM_RING_S=${SIM_RING_S:-4}"
  if [ "$CLAUDE" = off ]; then WENV="$WENV CLAUDE_ENABLED=false"; say "Claude is off (--no-claude)."; fi
  : > "$LOGS/worker.log"
  # shellcheck disable=SC2086
  launch worker "$ROOT/worker" bash -c 'set -a; . ./.env; set +a; exec "$@"' _ env $WENV .venv/bin/python -m nestwatch_worker.main

  # website (only if it is not already up)
  if ! curl -s -m 2 "http://127.0.0.1:$WEB_PORT/" | grep -q "ollo"; then
    : > "$LOGS/web.log"
    launch web "$ROOT/web" node_modules/.bin/vite --host --port "$WEB_PORT"
  fi

  # vision
  local ARGS="--worker-url http://127.0.0.1:$WORKER_PORT" SRC
  [ "$LOUD" = 1 ] || ARGS="$ARGS --quiet-alarm"
  case "$SOURCE" in
    demo)
      [ -f "$ROOT/vision/out/demo_room.mp4" ] || ( cd "$ROOT/vision" && .venv/bin/python scripts/make_demo_room.py ) || exit 1
      SRC="out/demo_room.mp4"; ARGS="$ARGS --realtime --loop --demo-map";;
    webcam) SRC=0;;
    phone) SRC=phone;;
    *) SRC="$SOURCE"; case "$SRC" in /*|*://*) ;; *) SRC="$(cd "$(dirname "$SRC")" && pwd)/$(basename "$SRC")" 2>/dev/null || SRC="$SOURCE";; esac; ARGS="$ARGS --realtime";;
  esac
  [ "$DEMOMAP" = 1 ] && ARGS="$ARGS --demo-map"
  : > "$LOGS/vision.log"
  # shellcheck disable=SC2086
  launch vision "$ROOT/vision" .venv/bin/python -m nestwatch_vision.main "$SRC" $ARGS

  say "Starting (source: $SOURCE, calls: $CALLS)..."
  for i in $(seq 1 40); do
    up "http://127.0.0.1:$VISION_PORT/health" && up "http://127.0.0.1:$WORKER_PORT/health" && break
    if [ "$SOURCE" = phone ] && [ "$i" -gt 3 ]; then break; fi
    sleep 1
  done
  echo
  cmd_status
  echo
  say "Open the website:  http://127.0.0.1:$WEB_PORT   (sign in as Maria, code: maria)"
  if [ "$SOURCE" = phone ]; then
    say "Phone camera: open the address below on the phone (same Wi-Fi):"
    grep "PHONE CAMERA" "$LOGS/vision.log" | sed 's/.*open \(https[^ ]*\).*/  \1/'
  fi
  say "Logs: $LOGS     Stop everything: scripts/nestwatch.sh stop"
}

case "${1:-}" in
  start) shift; cmd_start "$@";;
  stop) cmd_stop;;
  status) cmd_status;;
  *) sed -n '2,19p' "$0"; exit 1;;
esac
