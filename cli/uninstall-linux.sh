#!/bin/bash
set -euo pipefail

PURGE=false
[ "${1:-}" = "--purge" ] && PURGE=true

if [ "$(id -u)" != "0" ]; then
  exec sudo bash "$0" "$@"
fi

printf '\nprotonx CLI uninstaller for Linux\n---------------------------------\n'

if [ -x /usr/local/bin/protonx ]; then
  /usr/local/bin/protonx disconnect >/dev/null 2>&1 || true
fi
systemctl disable --now protonx-helper.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/protonx-helper.service
systemctl daemon-reload >/dev/null 2>&1 || true
rm -rf /usr/local/libexec/protonx /var/run/protonx /var/lib/protonx
rm -f /usr/local/bin/protonx
getent group protonx >/dev/null && groupdel protonx
printf '[ok] tunnel stopped; command, helper and group removed\n'

USER_HOME="$(getent passwd "${SUDO_USER:-root}" | cut -d: -f6)"
if $PURGE; then
  rm -rf "$USER_HOME/.config/protonx"
  printf '[ok] session, identity, cached servers and preferences removed\n'
else
  printf '  kept %s/.config/protonx (use --purge to delete)\n' "$USER_HOME"
fi
