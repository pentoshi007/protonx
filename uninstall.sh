#!/bin/bash
set -euo pipefail

PURGE=false
[ "${1:-}" = "--purge" ] && PURGE=true

printf '\nProtonX app uninstaller\n-----------------------\n'

TARGET_USER="${SUDO_USER:-$USER}"
TARGET_HOME="$(dscl . -read "/Users/$TARGET_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')"
[ -n "$TARGET_HOME" ] || TARGET_HOME="$HOME"
launchctl bootout "gui/$(id -u "$TARGET_USER")/com.protonx.menubar.login" >/dev/null 2>&1 || true
rm -f "$TARGET_HOME/Library/LaunchAgents/com.protonx.menubar.login.plist"
printf '[ok] login item removed\n'

[ -x /usr/local/libexec/protonx-app/app-engine ] && /usr/local/libexec/protonx-app/app-engine disconnect >/dev/null 2>&1 || true
[ -x /usr/local/bin/protonx ] && /usr/local/bin/protonx disconnect >/dev/null 2>&1 || true
pkill -f "ProtonX.app/Contents/MacOS/ProtonX" >/dev/null 2>&1 || true
sudo rm -rf /usr/local/libexec/protonx-app
sudo rm -rf /Applications/ProtonX.app
printf '[ok] app and app engine removed\n'

if [ ! -x /usr/local/bin/protonx ]; then
  sudo launchctl bootout system/com.protonx.helper >/dev/null 2>&1 || true
  sudo rm -f /Library/LaunchDaemons/com.protonx.helper.plist
  printf '[ok] helper removed\n'
else
  printf '  kept the helper because the protonx CLI is installed\n'
fi

if $PURGE; then
  if [ -x /usr/local/bin/protonx ]; then
    printf '  kept ~/.config/protonx because the protonx CLI is installed\n'
  else
    rm -rf "$HOME/.config/protonx"
    printf '[ok] cached servers, identity and last server removed\n'
  fi
else
  printf '  kept %s/.config/protonx (use --purge to delete)\n' "$HOME"
fi
