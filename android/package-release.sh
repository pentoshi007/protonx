#!/bin/bash
# Builds the signed release APK and writes it, plus its checksum, to dist/.
set -euo pipefail

ANDROID_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$ANDROID_DIR/.." && pwd)"
SDK="${ANDROID_HOME:-/opt/homebrew/share/android-commandlinetools}"
BUILD_TOOLS="$(ls -d "$SDK"/build-tools/* 2>/dev/null | sort -V | tail -1)"
VERSION="${VERSION:-$(sed -n 's/.*versionName = "\(.*\)".*/\1/p' "$ANDROID_DIR/app/build.gradle.kts" | head -1)}"
OUT="${OUT_DIR:-$ROOT/dist}"
NAME="protonx-$VERSION-android.apk"

[ -n "$VERSION" ] || { printf 'could not read versionName from app/build.gradle.kts\n' >&2; exit 1; }
[ -x "$BUILD_TOOLS/apksigner" ] || { printf 'apksigner not found under %s\n' "$SDK" >&2; exit 1; }

printf 'ProtonX Android %s\n' "$VERSION"
export ANDROID_HOME="$SDK" ANDROID_SDK_ROOT="$SDK"
"$ANDROID_DIR/gradlew" --console=plain --project-dir "$ANDROID_DIR" :app:testDebugUnitTest :app:assembleRelease

APK="$ANDROID_DIR/app/build/outputs/apk/release/app-release.apk"
[ -f "$APK" ] || { printf 'release APK was not produced\n' >&2; exit 1; }

mkdir -p "$OUT"
cp "$APK" "$OUT/$NAME"
(cd "$OUT" && shasum -a 256 "$NAME" > "$NAME.sha256")

"$BUILD_TOOLS/apksigner" verify --print-certs "$OUT/$NAME" | head -4
SIZE="$(ls -lh "$OUT/$NAME" | awk '{print $5}')"
printf 'apk %s (%s)\n' "$OUT/$NAME" "$SIZE"
printf '%s\n' "$(cat "$OUT/$NAME.sha256")"
