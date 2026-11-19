#!/bin/bash
set -euo pipefail

REPO="pentoshi007/protonx"
VERSION="${PROTONX_VERSION:-latest}"

fail() { printf '[!!] %s\n' "$1" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v shasum >/dev/null 2>&1 || fail "shasum is required"

if [ "$VERSION" = "latest" ]; then
  VERSION="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
    | sed -n 's/.*"tag_name": *"v\{0,1\}\([^"]*\)".*/\1/p' | head -1)"
fi
[ -n "$VERSION" ] || fail "could not determine the latest release"

ARCHIVE="protonx-$VERSION-macos-universal.tar.gz"
BASE="https://github.com/$REPO/releases/download/v$VERSION"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

printf 'Downloading ProtonX %s\n' "$VERSION"
curl -fsSL "$BASE/$ARCHIVE" -o "$TMP/$ARCHIVE" || fail "download failed: $BASE/$ARCHIVE"
curl -fsSL "$BASE/$ARCHIVE.sha256" -o "$TMP/$ARCHIVE.sha256" || fail "checksum download failed"
(cd "$TMP" && shasum -a 256 -c "$ARCHIVE.sha256" >/dev/null) || fail "checksum mismatch"

tar -xzf "$TMP/$ARCHIVE" -C "$TMP"
DIR="$TMP/protonx-$VERSION"
[ -x "$DIR/install.sh" ] || fail "archive layout is unexpected"

sudo "$DIR/install.sh"
