#!/bin/bash
set -euo pipefail

PURGE=false
[ "${1:-}" = "--purge" ] && PURGE=true

printf '\nprotonx CLI uninstaller (macOS)\n--------------------------------\n'

stop_tunnel() {
  local stopped=0
  if [ -x /usr/local/bin/protonx ]; then
    /usr/local/bin/protonx disconnect >/dev/null 2>&1 && stopped=1 || true
  fi
  if [ -x /usr/local/libexec/protonx-app/app-engine ]; then
    /usr/local/libexec/protonx-app/app-engine disconnect >/dev/null 2>&1 && stopped=1 || true
  fi
  if [ "$stopped" = "0" ] && [ -S /var/run/protonx/helper.sock ]; then
    /usr/bin/python3 - <<'PY' >/dev/null 2>&1 && stopped=1 || true
import json, socket
connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
connection.settimeout(30)
connection.connect("/var/run/protonx/helper.sock")
connection.sendall(b'{"command":"down"}\n')
reply = connection.recv(65536)
raise SystemExit(0 if json.loads(reply).get("ok") else 1)
PY
  fi
  local config="/Library/Application Support/ProtonX/protonx.conf"
  if [ "$stopped" = "0" ] && sudo test -f "$config"; then
    sudo wg-quick down "$config" >/dev/null 2>&1 || true
    sudo rm -f /var/run/wireguard/protonx.name
    local helper_dir=""
    for candidate in /usr/local/libexec/protonx/helper /usr/local/libexec/protonx-app/helper; do
      if sudo test -f "$candidate/helper_macos.py"; then helper_dir="$candidate"; break; fi
    done
    if [ -n "$helper_dir" ]; then
      sudo /usr/bin/python3 - "$helper_dir" <<'PY' >/dev/null 2>&1 || true
import os, sys
helper_dir = sys.argv[1]
sys.path.insert(0, os.path.dirname(helper_dir))
sys.path.insert(0, helper_dir)
import helper_macos
helper_macos.restore_dns()
PY
    fi
    sudo rm -f "$config" "/Library/Application Support/ProtonX/tunnel.json"
    stopped=1
  fi
  if [ "$stopped" = "1" ]; then
    printf '[ok] stopped the active tunnel and restored DNS\n'
  else
    printf '[ok] no active tunnel\n'
  fi
}

stop_tunnel
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
    sudo rm -rf "/Library/Application Support/ProtonX"
    printf '[ok] cached servers, identity, last server and tunnel state removed\n'
  fi
else
  printf '  kept %s/.config/protonx (use --purge to delete)\n' "$HOME"
fi
