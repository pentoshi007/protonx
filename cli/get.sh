#!/bin/bash
set -euo pipefail

REPO="pentoshi007/protonx"
REF="${PROTONX_REF:-main}"

fail() { printf '[!!] %s\n' "$1" >&2; exit 1; }

case "$(uname -s)" in
  Linux) ;;
  Darwin) fail "on macOS the CLI ships with the ProtonX app: curl -fsSL https://raw.githubusercontent.com/$REPO/main/get.sh | bash" ;;
  *) fail "unsupported system: $(uname -s). On Windows use cli/get.ps1." ;;
esac
command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v tar >/dev/null 2>&1 || fail "tar is required"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

printf 'Downloading protonx-cli (%s)\n' "$REF"
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$REF" | tar -xz -C "$TMP" --strip-components=1 \
  || fail "download failed for $REPO@$REF"
[ -f "$TMP/cli/install-linux.sh" ] || fail "that revision has no Linux installer"

if [ "$(id -u)" = "0" ]; then
  bash "$TMP/cli/install-linux.sh"
else
  sudo bash "$TMP/cli/install-linux.sh"
fi
