#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_TARGET="/Applications/ProtonX.app"
LIBEXEC="/usr/local/libexec/protonx-app"
VENV="$LIBEXEC/venv"
PLIST="/Library/LaunchDaemons/com.protonx.helper.plist"

info() { printf '  %s\n' "$1"; }
ok()   { printf '[ok] %s\n' "$1"; }
fail() { printf '[!!] %s\n' "$1"; exit 1; }

printf '\nProtonX app installer\n---------------------\n'

[ "$(uname -s)" = "Darwin" ] || fail "this installer is for the macOS app. The CLI is separate: cli/get.sh (Linux/macOS) or cli/get.ps1 (Windows)."

if [ "$(id -u)" != "0" ]; then
  exec sudo -S "$0" "$@"
fi

BUILD_USER="${SUDO_USER:-root}"
run_as_user() {
  if [ "$(id -u)" = "0" ] && [ "$BUILD_USER" != "root" ]; then
    sudo -u "$BUILD_USER" "$@"
  else
    "$@"
  fi
}

find_python() {
  local candidate
  for candidate in "$(command -v python3 2>/dev/null || true)" \
                   /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    [ -n "$candidate" ] && [ -x "$candidate" ] || continue
    if "$candidate" -c 'import venv, ensurepip' >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python)" || fail "need python3 with venv and pip (xcode-select --install, or brew install python)"
ok "python $PYTHON_BIN ($("$PYTHON_BIN" -V 2>&1 | awk '{print $2}'))"

for tool in wg wg-quick; do
  command -v "$tool" >/dev/null 2>&1 || fail "$tool missing (brew install wireguard-tools)"
done
ok "wireguard-tools present"

stop_tunnel() {
  local stopped=0
  if [ -x /usr/local/bin/protonx ]; then
    /usr/local/bin/protonx disconnect >/dev/null 2>&1 && stopped=1 || true
  fi
  if [ -x "$LIBEXEC/app-engine" ]; then
    "$LIBEXEC/app-engine" disconnect >/dev/null 2>&1 && stopped=1 || true
  fi
  if [ "$stopped" = "0" ] && [ -S /var/run/protonx/helper.sock ]; then
    "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1 && stopped=1 || true
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
  if [ "$stopped" = "0" ] && [ -f "$config" ]; then
    wg-quick down "$config" >/dev/null 2>&1 || true
    rm -f /var/run/wireguard/protonx.name
    "$PYTHON_BIN" - "$ROOT" <<'PY' >/dev/null 2>&1 || true
import sys
root = sys.argv[1]
sys.path.insert(0, root)
sys.path.insert(0, root + "/helper")
import helper_macos
helper_macos.restore_dns()
PY
    rm -f "$config" "/Library/Application Support/ProtonX/tunnel.json"
    stopped=1
  fi
  if [ "$stopped" = "1" ]; then
    ok "stopped the active tunnel and restored DNS"
  else
    ok "no active tunnel"
  fi
}

start_helper() {
  launchctl bootout system/com.protonx.helper >/dev/null 2>&1 || true
  sleep 1
  if ! launchctl bootstrap system "$PLIST" >/dev/null 2>&1; then
    sleep 1
    launchctl bootout system/com.protonx.helper >/dev/null 2>&1 || true
    sleep 1
    launchctl bootstrap system "$PLIST" >/dev/null 2>&1 || fail "helper daemon failed to start"
  fi
  sleep 1
  launchctl print system/com.protonx.helper >/dev/null 2>&1 || fail "helper daemon failed to start"
}

printf '\nstopping any active tunnel\n--------------------------\n'
stop_tunnel

printf '\ninstalling app engine\n---------------------\n'
sudo mkdir -p "$LIBEXEC"
sudo rm -rf "$LIBEXEC/protonxlib" "$LIBEXEC/vendor" "$LIBEXEC/helper" "$LIBEXEC/helper.py" "$VENV"
sudo cp -R "$ROOT/protonxlib" "$LIBEXEC/"
sudo mkdir -p "$LIBEXEC/helper"
sudo cp "$ROOT"/helper/*.py "$LIBEXEC/helper/"
sudo install -m 755 "$ROOT/protonx" "$LIBEXEC/protonx"
sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/protonxlib/__init__.py" | sudo tee "$LIBEXEC/VERSION" >/dev/null
sudo find "$LIBEXEC" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
sudo chown -R root:wheel "$LIBEXEC"
ok "app engine installed to $LIBEXEC"

sudo "$PYTHON_BIN" -m venv "$VENV"
sudo "$VENV/bin/python" -m pip install --quiet --no-cache-dir --disable-pip-version-check --upgrade pip >/dev/null
sudo "$VENV/bin/python" -m pip install --quiet --no-cache-dir --disable-pip-version-check cryptography bcrypt certifi >/dev/null \
  || fail "pip could not install cryptography, bcrypt and certifi (check the network, then re-run)"
sudo "$VENV/bin/python" -c 'import cryptography, bcrypt, certifi' >/dev/null 2>&1 \
  || fail "the python environment at $VENV is incomplete"
printf '#!/bin/sh\nexec %s %s/protonx "$@"\n' "$VENV/bin/python" "$LIBEXEC" | sudo tee "$LIBEXEC/app-engine" >/dev/null
sudo chmod 755 "$LIBEXEC/app-engine"
ok "app engine ready at $LIBEXEC/app-engine"

if [ -d "$ROOT/app/Sources" ]; then
  printf '\nbuilding\n--------\n'
  run_as_user env PYTHONDONTWRITEBYTECODE=1 "$VENV/bin/python" -m unittest discover -s "$ROOT/tests" -t "$ROOT" -q >/dev/null
  ok "unit tests pass"
  run_as_user "$ROOT/app/build.sh" >/dev/null
  APP_SOURCE="$ROOT/app/build/ProtonX.app"
  ok "universal app built"
else
  APP_SOURCE="$ROOT/ProtonX.app"
  [ -d "$APP_SOURCE" ] || fail "no app to install: expected ProtonX.app beside install.sh"
  ok "using prebuilt app ($(lipo -archs "$APP_SOURCE/Contents/MacOS/ProtonX"))"
fi

printf '\ninstalling app\n--------------\n'
stop_tunnel
sed -e "s|@PYTHON@|$VENV/bin/python|g" -e "s|@HELPER@|$LIBEXEC/helper/protonx_helper.py|g" \
  "$ROOT/helper/com.protonx.helper.plist" | sudo tee "$PLIST" >/dev/null
sudo chmod 644 "$PLIST"
start_helper
ok "privileged helper running"

if [ "${PROTONX_KEEP_APP:-}" != "1" ]; then
  pkill -f "ProtonX.app/Contents/MacOS/ProtonX" >/dev/null 2>&1 || true
fi
sudo rm -rf "$APP_TARGET"
sudo cp -R "$APP_SOURCE" /Applications/
sudo xattr -dr com.apple.quarantine "$APP_TARGET" >/dev/null 2>&1 || true
sudo codesign --force --sign - --identifier com.protonx.menubar "$APP_TARGET" >/dev/null 2>&1 || true
ok "app installed at $APP_TARGET"

LOGIN_USER="$BUILD_USER"
if [ "$LOGIN_USER" = "root" ]; then
  LOGIN_USER="$(stat -f%Su /dev/console 2>/dev/null || true)"
fi
if [ -n "$LOGIN_USER" ] && [ "$LOGIN_USER" != "root" ]; then
  sudo -u "$LOGIN_USER" -H "$APP_TARGET/Contents/MacOS/ProtonX" --enable-login-item >/dev/null 2>&1 || true
  ok "launch at login enabled for $LOGIN_USER"
fi

printf '\nverifying\n---------\n'
"$LIBEXEC/app-engine" doctor || true

printf '\nDone.\n'
printf '  1. Open ProtonX and sign in once with your Proton username and password\n'
printf '     (plus a two-factor code if you use one). The card pre-fills the username.\n'
printf '  2. Click the shield in the menu bar: pick a country, pick a server, Connect.\n'
printf '  3. "Reconnect" repeats your last server in one click. Proton VPN can stay\n'
printf '     installed and signed in; only one tunnel should be up at a time.\n'
printf '  4. The CLI is a separate install:\n'
printf '       npm install -g @pentoshi/protonx\n'
printf '       curl -fsSL https://raw.githubusercontent.com/pentoshi007/protonx/main/cli/get.sh | bash\n'
printf '  5. ProtonX starts at login; turn that off from the account menu.\n\n'
