#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BUILD="${BUILD_DIR:-$ROOT/build}"
APP="$BUILD/ProtonX.app"
MIN_MACOS="13.0"

command -v xcrun >/dev/null 2>&1 || {
    echo "error: xcrun is missing; install the Command Line Tools with: xcode-select --install" >&2
    exit 1
}
SDK="$(xcrun --show-sdk-path)"
SWIFTC="$(xcrun --find swiftc)"

mkdir -p "$BUILD"
for arch in arm64 x86_64; do
    "$SWIFTC" \
        -O \
        -parse-as-library \
        -warnings-as-errors \
        -swift-version 5 \
        -target "$arch-apple-macosx$MIN_MACOS" \
        -sdk "$SDK" \
        "$ROOT"/Sources/*.swift \
        -o "$BUILD/ProtonX-$arch" \
        -framework AppKit \
        -framework Foundation
done
lipo -create "$BUILD/ProtonX-arm64" "$BUILD/ProtonX-x86_64" -output "$BUILD/ProtonX"
rm -f "$BUILD/ProtonX-arm64" "$BUILD/ProtonX-x86_64"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ROOT/Info.plist" "$APP/Contents/Info.plist"
cp "$ROOT/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cp "$BUILD/ProtonX" "$APP/Contents/MacOS/ProtonX"
codesign --force --sign - --identifier com.protonx.menubar "$APP" >/dev/null 2>&1

echo "built $APP ($(lipo -archs "$APP/Contents/MacOS/ProtonX"))"
