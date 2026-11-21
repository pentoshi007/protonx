#!/bin/bash
# Build the universal app and the archive the macOS installer expects.
# Publishing is separate: gh release create/upload with the two files this prints.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/protonxlib/__init__.py")"
OUT="${OUT_DIR:-$ROOT/dist}"
NAME="protonx-$VERSION-macos-universal"
STAGE="$OUT/protonx-$VERSION"
REQUIRED=(
  install.sh
  uninstall.sh
  README.md
  protonx
  protonxlib/__init__.py
  protonxlib/helper.py
  helper/protonx_helper.py
  helper/helper_macos.py
  helper/com.protonx.helper.plist
  ProtonX.app/Contents/MacOS/ProtonX
  ProtonX.app/Contents/Info.plist
)

[ -n "$VERSION" ] || { printf 'could not read the version from protonxlib/__init__.py\n' >&2; exit 1; }

printf 'ProtonX %s\n' "$VERSION"
BUILD_DIR="$OUT/build" "$ROOT/app/build.sh"

rm -rf "$STAGE"
mkdir -p "$STAGE"
ditto "$OUT/build/ProtonX.app" "$STAGE/ProtonX.app"
cp -R "$ROOT/protonxlib" "$STAGE/protonxlib"
cp -R "$ROOT/helper" "$STAGE/helper"
find "$STAGE/protonxlib" "$STAGE/helper" -name __pycache__ -type d -prune -exec rm -rf {} +
cp "$ROOT/protonx" "$ROOT/install.sh" "$ROOT/uninstall.sh" "$ROOT/README.md" "$STAGE/"
chmod 755 "$STAGE/install.sh" "$STAGE/uninstall.sh" "$STAGE/protonx"

missing=0
for entry in "${REQUIRED[@]}"; do
  if [ ! -e "$STAGE/$entry" ]; then
    printf 'missing from the archive: %s\n' "$entry" >&2
    missing=1
  fi
done
[ "$missing" = 0 ] || { printf 'refusing to package an incomplete release\n' >&2; exit 1; }

rm -rf "$OUT/build"
tar -czf "$OUT/$NAME.tar.gz" -C "$OUT" "protonx-$VERSION"
(cd "$OUT" && shasum -a 256 "$NAME.tar.gz" > "$NAME.tar.gz.sha256")

CHECK="$(mktemp -d)"
tar -xzf "$OUT/$NAME.tar.gz" -C "$CHECK"
[ -x "$CHECK/protonx-$VERSION/install.sh" ] || {
  printf 'the archive does not unpack to protonx-%s/install.sh, which get.sh and protonx update both need\n' "$VERSION" >&2
  rm -rf "$CHECK"
  exit 1
}
rm -rf "$CHECK"

printf '\n== Android ==\n'
VERSION="$VERSION" OUT_DIR="$OUT" "$ROOT/android/package-release.sh"

printf '%s\n%s\n%s\n%s\n' \
  "$OUT/$NAME.tar.gz" \
  "$OUT/$NAME.tar.gz.sha256" \
  "$OUT/protonx-$VERSION-android.apk" \
  "$OUT/protonx-$VERSION-android.apk.sha256"
