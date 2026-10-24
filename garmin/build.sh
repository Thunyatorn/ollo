#!/usr/bin/env bash
# Build the ollo Garmin watch app, with your server address and pairing code baked in (for a sideloaded install,
# where the Garmin Connect phone app cannot edit settings). Nothing personal is written into the repository: the
# values go into a temporary copy of the project.
#
#   garmin/build.sh DEVICE [--server URL] [--code CODE] [--sim]
#     DEVICE    your watch's product id, e.g. fr265, fenix7, venu3 (it must be listed in garmin/ollo/manifest.xml)
#     --server  the worker's public https address (default: PUBLIC_BASE_URL from worker/.env)
#     --code    the pairing code from the dashboard (Settings > Garmin watch)
#     --sim     also open Garmin's simulator and run the app there
#
# Needs the Connect IQ SDK (install it with Garmin's SDK Manager and download the SDK and your device). Output:
# garmin/bin/ollo-DEVICE.prg (git-ignored). Copy it to the watch's GARMIN/APPS folder to install it.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
DEVICE="${1:-}"; [ -n "$DEVICE" ] || { sed -n '2,13p' "$0"; exit 1; }; shift
SERVER=""; CODE=""; SIM=0
while [ $# -gt 0 ]; do
  case "$1" in
    --server) SERVER="${2:-}"; shift 2;;
    --code) CODE="${2:-}"; shift 2;;
    --sim) SIM=1; shift;;
    *) echo "unknown option $1"; exit 2;;
  esac
done

# the server address: the worker's PUBLIC_BASE_URL unless given
if [ -z "$SERVER" ] && [ -f "$ROOT/worker/.env" ]; then
  SERVER="$(grep -E '^PUBLIC_BASE_URL=' "$ROOT/worker/.env" | head -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*//')"
fi
case "$SERVER" in https://*) ;; "") echo "No server address: pass --server https://... (the worker's public address)"; exit 1;; *) echo "The server address must start with https:// (Garmin refuses plain http)"; exit 1;; esac
case "$SERVER$CODE" in *[\<\>\&\"]*) echo "The server address or code contains a character that is not allowed"; exit 1;; esac
[ -n "$CODE" ] || echo "No --code given: the app will ask you to pair. Get a code from the dashboard (Settings > Garmin watch)."
grep -q "id=\"$DEVICE\"" "$HERE/ollo/manifest.xml" || { echo "$DEVICE is not in garmin/ollo/manifest.xml: add <iq:product id=\"$DEVICE\"/> there first"; exit 1; }

# the Connect IQ SDK: the one the SDK Manager marked current, else the newest installed
SDKS="$HOME/Library/Application Support/Garmin/ConnectIQ"
BIN=""
if [ -f "$SDKS/current-sdk.cfg" ]; then BIN="$(cat "$SDKS/current-sdk.cfg")/bin"; fi
if [ ! -x "$BIN/monkeyc" ]; then BIN="$(ls -d "$SDKS"/Sdks/*/bin 2>/dev/null | sort | tail -1 || true)"; fi
if [ ! -x "$BIN/monkeyc" ]; then
  command -v monkeyc >/dev/null && BIN="$(dirname "$(command -v monkeyc)")" || {
    echo "Connect IQ SDK not found. Install Garmin's SDK Manager (https://developer.garmin.com/connect-iq/sdk/),"
    echo "sign in, and download the latest SDK and your device ($DEVICE)."; exit 1; }
fi

# a developer key signs the build; made once, kept out of git
KEY="$HERE/developer_key.der"
if [ ! -f "$KEY" ]; then
  echo "Making a developer key (garmin/developer_key.der, git-ignored; keep it, it identifies your builds)."
  openssl genrsa -out "$HERE/developer_key.pem" 4096 2>/dev/null
  openssl pkcs8 -topk8 -inform PEM -outform DER -in "$HERE/developer_key.pem" -out "$KEY" -nocrypt
  chmod 600 "$HERE/developer_key.pem" "$KEY"
fi

# a private copy with the settings filled in
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cp -R "$HERE/ollo/." "$WORK/"
cat > "$WORK/resources/settings/properties.xml" <<EOF
<properties>
    <property id="ServerUrl" type="string">$SERVER</property>
    <property id="PairingCode" type="string">$CODE</property>
</properties>
EOF
mkdir -p "$HERE/bin"
OUT="$HERE/bin/ollo-$DEVICE.prg"
"$BIN/monkeyc" -d "$DEVICE" -f "$WORK/monkey.jungle" -o "$OUT" -y "$KEY" -w
echo "Built $OUT"
echo "Install: connect the watch by USB and copy it into GARMIN/APPS (on a Mac use OpenMTP or Garmin Express)."

if [ "$SIM" = 1 ]; then
  ( "$BIN/connectiq" >/dev/null 2>&1 & )
  sleep 4
  "$BIN/monkeydo" "$OUT" "$DEVICE"
fi
