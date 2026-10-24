#!/usr/bin/env bash
# End-to-end check of the Spacetime module against a LOCAL server.
# Needs: `spacetime start` running, and the module published as $DB (see README below).
#
# Identities are separate CLI configs, one per role:
#   admin  = your default config (the publisher)
#   vision / worker / maria = configs in $CFG, logged in with `spacetime login --server-issued-login local`
#
# Usage: CFG=/path/to/cfgdir DB=nestwatch-test ./scripts/test-local.sh
set -u
DB=${DB:-nestwatch-test}
CFG=${CFG:?set CFG to the directory holding vision.toml worker.toml maria.toml}
SP=${SPACETIME:-spacetime}
pass=0; fail=0

snake() { echo "$1" | sed -E 's/([a-z0-9])([A-Z])/\1_\2/g' | tr 'A-Z' 'a-z'; }
call() { # call <role> <reducer> <args...>   (admin uses the default config); reducer names are snake_case on the wire
  local role=$1 reducer; reducer=$(snake "$2"); shift 2; set -- "$reducer" "$@"
  if [ "$role" = admin ]; then $SP call --no-config "$DB" "$@" --server local 2>&1
  else $SP --config-path "$CFG/$role.toml" call --no-config "$DB" "$@" --server local 2>&1; fi
}
sql() { $SP sql --no-config "$DB" "$1" --server local 2>&1; }
sqlas() { $SP --config-path "$CFG/$1.toml" sql --no-config "$DB" "$2" --server local 2>&1; }
ident() { $SP --config-path "$CFG/$1.toml" login show 2>&1 | awk '{print $NF}'; }

ok()   { call "$@" >/dev/null; local rc=$?; check "$rc" 0 "ok:   $*"; }
INFRA='failed to find|No such|not logged in|Unable to|connection refused|invalid|could not parse|Failed to parse'
deny() {
  out=$(call "$@"); local rc=$?
  if [ $rc -eq 0 ]; then check 1 0 "deny: $* (was allowed!)"
  elif echo "$out" | grep -qiE "$INFRA"; then check 1 0 "deny: $* (infrastructure error, not a denial: $(echo "$out" | tail -1 | cut -c1-80))"
  else check 0 0 "deny: $*  -> $(echo "$out" | grep 'Response text' | sed 's/.*Response text: //' | cut -c1-70)"; fi
}
check() { if [ "$1" = "$2" ]; then pass=$((pass+1)); echo "  PASS $3"; else fail=$((fail+1)); echo "  FAIL $3"; fi; }
expect() { # expect <label> <sql> <needle>
  local out; out=$(sql "$2"); if echo "$out" | grep -q -- "$3"; then pass=$((pass+1)); echo "  PASS $1"; else fail=$((fail+1)); echo "  FAIL $1"; echo "$out"; fi
}
expect_not() { local out; out=$(sql "$2"); if echo "$out" | grep -qE -- "$3|Error"; then fail=$((fail+1)); echo "  FAIL $1"; echo "$out"; else pass=$((pass+1)); echo "  PASS $1"; fi; }

NONE='{"none":[]}'
SOME() { echo "{\"some\":\"$1\"}"; }
SCHED="[$NONE,$NONE,$NONE]"
SQUARE='[[0,0],[1,0],[1,1],[0,1]]'

echo "== setup (admin)"
ok admin upsertRoom '"main"' '"Main room"' 4 3 '"plan"'
ok admin upsertCaregiver '"c_maria"' '"Maria"' '"primary"' '"+10000000001"' '"maria-code"' "$(SOME buzzer-maria)" true
ok admin upsertCaregiver '"c_bob"' '"Bob"' '"backup"' '"+10000000002"' '"bob-code"' "$NONE" true
ok admin grantRole "\"0x$(ident vision)\"" '"vision"' "$NONE"
ok admin grantRole "\"0x$(ident worker)\"" '"worker"' "$NONE"
ok admin grantRole "\"0x$(ident maria)\"" '"caregiver"' "$(SOME c_maria)"
ok admin upsertNamedArea '"na_gate"' '"main"' '"Kitchen gate"' "$SQUARE"
ok admin createZone '"main"' '"Stairs"' "$SQUARE" '"high"' "$SCHED" '"buzzer_then_call"'

echo "== identity checks"
deny vision grantRole "\"0x$(ident maria)\"" '"admin"' "$NONE"
deny maria reportEvent '"t4"' '"fall"' '"z_1"' '"high"' "$NONE" '"clip"'
deny worker updatePositions '"main"' '[]'
deny vision saveReport "$NONE" '"x"' '[]'
out=$(call worker escalationTick '[1,{"time":0},"a_1",0]'); echo "$out" | grep -q "404" && check 0 0 "scheduler reducer is not callable by clients (404)" || check 1 0 "scheduler reducer is callable by clients!"
ok vision updatePositions '"main"' '[["t4","child","4",1.1,1.8,0,0,true],["t9","adult","M",2.3,0.6,0,0,true]]'
deny vision updatePositions '"main"' '[["t5","dog","5",1,1,0,0,true]]'

echo "== flow 1: primary acknowledges, alert closes, report saved"
ok vision reportEvent '"t4"' '"zone_entry_predicted"' '"z_1"' '"high"' '{"some":2.8}' '"evt1"'
expect "alert a_1 is notified with a timer" "SELECT status, escalation_level FROM alert WHERE id = 'a_1'" "notified"
ok vision reportEvent '"t4"' '"zone_entry_predicted"' '"z_1"' '"high"' '{"some":2.5}' '"evt1b"'
expect_not "same child+zone reuses the alert" "SELECT id FROM alert" "a_2"
deny maria acknowledgeAlert '"a_1"' '"c_bob"' '"dashboard"'
deny maria acknowledgeAlert '"a_1"' '"c_maria"' '"buzzer"'
ok maria acknowledgeAlert '"a_1"' '"c_maria"' '"phone_app"'
expect "alert a_1 owned by Maria" "SELECT status, owner_id FROM alert WHERE id = 'a_1'" "owned"
ok vision acknowledgeAlert '"a_1"' '"c_bob"' '"buzzer"'
expect "second ack does not steal ownership" "SELECT owner_id FROM alert WHERE id = 'a_1'" "c_maria"
deny worker closeAlert '"a_1"' '"safe"'
ok vision closeAlert '"a_1"' '"child back in play area"'
deny worker saveReport "$(SOME a_1)" '"summary"' '[["e_999","made up"]]'
ok worker saveReport "$(SOME a_1)" '"Child 4 approached stairs; Maria handled it."' '[["e_1","Detected"]]'
expect "alert a_1 reported" "SELECT status FROM alert WHERE id = 'a_1'" "reported"

echo "== flow 2: nobody answers, escalates twice, then backup/primary acknowledges"
ok vision reportEvent '"t7"' '"zone_entry"' '"z_1"' '"high"' "$NONE" '"evt2"'
echo "  (waiting 22 s for first escalation)"; sleep 22
expect "a_2 escalated" "SELECT status, escalation_level FROM alert WHERE id = 'a_2'" "escalated"
expect "call 1 queued for the backup" "SELECT status, attempt, caregiver_id FROM call_job WHERE alert_id = 'a_2'" "c_bob"
echo "  (waiting 31 s for second escalation)"; sleep 31
expect "a_2 unanswered" "SELECT status, escalation_level FROM alert WHERE id = 'a_2'" "unanswered"
expect "call 2 queued" "SELECT attempt FROM call_job WHERE alert_id = 'a_2' AND attempt = 2" "2"
ok worker acknowledgeAlert '"a_2"' '"c_bob"' '"phone_call"'
expect "a_2 owned by Bob via phone call" "SELECT owner_id, acked_via FROM alert WHERE id = 'a_2'" "phone_call"
expect_not "pending calls cancelled" "SELECT status FROM call_job WHERE alert_id = 'a_2'" "queued"

echo "== flow 4: second opinion lowers a medium alert, never a high one"
ok vision reportEvent '"t8"' '"unsupervised"' '"z_1"' '"medium"' "$NONE" '"evt3"'
expect "a_3 is medium" "SELECT severity FROM alert WHERE id = 'a_3'" "medium"
deny worker setUrgency '"a_3"' '"raise it"' '"high"'
deny worker setUrgency '"a_3"' '"same"' '"medium"'
ok worker setUrgency '"a_3"' '"child is next to an adult"' '"low"'
expect "a_3 lowered to low, timer cleared" "SELECT severity, next_escalation_at FROM alert WHERE id = 'a_3'" "low"
ok vision reportEvent '"t9"' '"fall"' '"z_1"' '"high"' "$NONE" '"evt4"'
deny worker setUrgency '"a_4"' '"try"' '"low"'

echo "== flow 3: rule draft needs a real named area and stays inactive until confirmed"
deny worker saveZoneDraft '"main"' '"Nowhere"' "$SCHED" '"high"' '"x"'
ok worker saveZoneDraft '"main"' '"Kitchen gate"' "$SCHED" '"high"' '"buzzer_then_call_after_20s"'
expect "draft zone is inactive" "SELECT status FROM zone WHERE name = 'Kitchen gate'" "draft"
deny vision confirmZone '"zd_1"'
ok maria confirmZone '"zd_1"'
expect "zone active after confirm" "SELECT status, confirmed_by FROM zone WHERE name = 'Kitchen gate'" "c_maria"

echo "== privacy: phone numbers readable only by the worker"
w=$(sqlas worker "SELECT phone FROM worker_contacts"); echo "$w" | grep -q "+1000000000" && check 0 0 "worker sees phone numbers" || check 1 0 "worker sees phone numbers"
m=$(sqlas maria "SELECT phone FROM worker_contacts"); echo "$m" | grep -q "+1000000000" && check 1 0 "caregiver must not see phones" || check 0 0 "caregiver must not see phones"

echo; echo "passed: $pass  failed: $fail"; [ "$fail" = 0 ]
