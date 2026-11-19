#!/bin/bash
set -euo pipefail

REPO="pentoshi007/protonx"
REF="${PROTONX_REF:-main}"

fail() { printf '[!!] %s\n' "$1" >&2; exit 1; }

case "$(uname -s)" in
  Linux) INSTALLER="cli/install-linux.sh" ;;
  Darwin) INSTALLER="cli/install-macos.sh" ;;
  *) fail "unsupported system: $(uname -s). On Windows use cli/get.ps1." ;;
esac
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

printf 'Downloading protonx CLI (%s)\n' "$REF"
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$REF" | tar -xz -C "$TMP" --strip-components=1 \
  || fail "download failed for $REPO@$REF"
[ -f "$TMP/$INSTALLER" ] || fail "that revision has no installer for $(uname -s)"

if [ "$(id -u)" = "0" ]; then
  bash "$TMP/$INSTALLER"
else
  sudo bash "$TMP/$INSTALLER"
fi
