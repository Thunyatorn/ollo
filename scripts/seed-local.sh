#!/usr/bin/env bash
# Seeds a LOCAL ollo database with a demo room, caregivers and a stairs zone.
# Run as the admin (the identity that published the module).
#   VISION_ID=<hex identity of the vision service> [WORKER_ID=<hex>] ./scripts/seed-local.sh
# The fake-vision tool prints its identity when it connects.
set -eu
DB=${DB:-nestwatch-test}
SP=${SPACETIME:-spacetime}
call() { r=$1; shift; $SP call --no-config "$DB" "$r" "$@" --server local 2>&1 | grep -v WARNING || true; }
NONE='{"none":[]}'
SCHED="[$NONE,$NONE,$NONE]"

call upsert_room '"main"' '"Playroom"' 4 3 '""'
call upsert_caregiver '"c_maria"' '"Maria"' '"primary"' '"+15550000001"' '"maria"' '{"some":"buzzer-maria"}' true
call upsert_caregiver '"c_bob"' '"Bob"' '"backup"' '"+15550000002"' '"bob"' "$NONE" true
call upsert_camera '"cam1"' '"main"' '"Camera 1"' '[]' '[]'
# stairs in the bottom-right corner, kitchen gate along the top-left
call create_zone '"main"' '"Stairs"' '[[2.8,1.9],[4,1.9],[4,3],[2.8,3]]' '"high"' "$SCHED" '"buzzer_then_call"'
call upsert_named_area '"na_gate"' '"main"' '"Kitchen gate"' '[[0,0],[1.2,0],[1.2,0.8],[0,0.8]]'
[ -n "${VISION_ID:-}" ] && call grant_role "\"0x$VISION_ID\"" '"vision"' "$NONE"
[ -n "${WORKER_ID:-}" ] && call grant_role "\"0x$WORKER_ID\"" '"worker"' "$NONE"
echo "Seeded. Sign in on the web app as Maria with code 'maria' or Bob with code 'bob'."
