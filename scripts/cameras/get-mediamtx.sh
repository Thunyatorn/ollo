#!/usr/bin/env bash
# Download MediaMTX (MIT, github.com/bluenviron/mediamtx) into scripts/cameras/.bin. Skips if present.
set -euo pipefail
VERSION="${MEDIAMTX_VERSION:-v1.21.2}"
DIR="$(cd "$(dirname "$0")" && pwd)/.bin"
[ -x "$DIR/mediamtx" ] && { echo "present: $DIR/mediamtx"; exit 0; }
case "$(uname -s)" in Linux) OS=linux;; Darwin) OS=darwin;; *) echo "Windows: download mediamtx_${VERSION}_windows_amd64.zip from https://github.com/bluenviron/mediamtx/releases"; exit 1;; esac
case "$(uname -m)" in x86_64|amd64) ARCH=amd64;; arm64|aarch64) ARCH=arm64;; armv7l) ARCH=armv7;; *) echo "unsupported arch $(uname -m)"; exit 1;; esac
mkdir -p "$DIR"
URL="https://github.com/bluenviron/mediamtx/releases/download/${VERSION}/mediamtx_${VERSION}_${OS}_${ARCH}.tar.gz"
echo "downloading $URL"
curl -fsSL "$URL" | tar -xz -C "$DIR" mediamtx
echo "installed: $DIR/mediamtx"
