#!/bin/bash
set -euo pipefail

PURGE=false
[ "${1:-}" = "--purge" ] && PURGE=true

printf '\nprotonx CLI uninstaller (macOS)\n--------------------------------\n'

[ -x /usr/local/bin/protonx ] && /usr/local/bin/protonx disconnect >/dev/null 2>&1 || true
sudo rm -f /usr/local/bin/protonx
sudo rm -rf /usr/local/libexec/protonx
printf '[ok] command and engine removed\n'

if [ ! -d /Applications/ProtonX.app ]; then
  sudo launchctl bootout system/com.protonx.helper >/dev/null 2>&1 || true
  sudo rm -f /Library/LaunchDaemons/com.protonx.helper.plist
  printf '[ok] helper removed\n'
else
  printf '  kept the helper because ProtonX.app is installed\n'
fi

if $PURGE; then
  if [ -d /Applications/ProtonX.app ]; then
    printf '  kept ~/.config/protonx because ProtonX.app is installed\n'
  else
    rm -rf "$HOME/.config/protonx"
    printf '[ok] cached servers, identity and last server removed\n'
  fi
else
  printf '  kept %s/.config/protonx (use --purge to delete)\n' "$HOME"
fi
