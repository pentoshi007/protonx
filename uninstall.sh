#!/bin/bash
set -euo pipefail

PURGE=false
[ "${1:-}" = "--purge" ] && PURGE=true

printf '\nprotonx uninstaller\n-------------------\n'

[ -x /usr/local/bin/protonx ] && /usr/local/bin/protonx disconnect >/dev/null 2>&1 || true
pkill -f "ProtonX.app/Contents/MacOS/ProtonX" >/dev/null 2>&1 || true
sudo launchctl bootout system/com.protonx.helper >/dev/null 2>&1 || true
sudo rm -f /Library/LaunchDaemons/com.protonx.helper.plist
sudo rm -rf /usr/local/libexec/protonx
sudo rm -f /usr/local/bin/protonx
sudo rm -rf /Applications/ProtonX.app
printf '[ok] app, command and helper removed\n'

if $PURGE; then
  rm -rf "$HOME/.config/protonx"
  printf '[ok] cached servers, identity and last server removed\n'
else
  printf '  kept %s/.config/protonx (use --purge to delete)\n' "$HOME"
fi
