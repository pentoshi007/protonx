#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIBEXEC="/usr/local/libexec/protonx"
VENV="$LIBEXEC/venv"
CLI="/usr/local/bin/protonx"
PLIST="/Library/LaunchDaemons/com.protonx.helper.plist"

info() { printf '  %s\n' "$1"; }
ok()   { printf '[ok] %s\n' "$1"; }
fail() { printf '[!!] %s\n' "$1"; exit 1; }

printf '\nprotonx CLI installer for macOS\n-------------------------------\n'

[ "$(uname -s)" = "Darwin" ] || fail "this installer is for macOS. On Linux run cli/install-linux.sh; on Windows run cli/install-windows.ps1."

if [ "$(id -u)" != "0" ]; then
  exec sudo -S "$0" "$@"
fi

for entry in helper/com.protonx.helper.plist helper/protonx_helper.py protonxlib/__init__.py protonx; do
  [ -e "$ROOT/$entry" ] || fail "this release is incomplete: $entry is missing from $ROOT. Download it again."
done

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
  if [ -x "$CLI" ]; then
    "$CLI" disconnect >/dev/null 2>&1 && stopped=1 || true
  fi
  if [ -x /usr/local/libexec/protonx-app/app-engine ]; then
    /usr/local/libexec/protonx-app/app-engine disconnect >/dev/null 2>&1 && stopped=1 || true
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

printf '\ninstalling engine\n-----------------\n'
mkdir -p "$LIBEXEC"
rm -rf "$LIBEXEC/protonxlib" "$LIBEXEC/vendor" "$LIBEXEC/helper" "$LIBEXEC/helper.py" "$VENV"
cp -R "$ROOT/protonxlib" "$LIBEXEC/"
mkdir -p "$LIBEXEC/helper"
cp "$ROOT"/helper/*.py "$LIBEXEC/helper/"
install -m 755 "$ROOT/protonx" "$LIBEXEC/protonx"
sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/protonxlib/__init__.py" > "$LIBEXEC/VERSION"
find "$LIBEXEC" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
chown -R root:wheel "$LIBEXEC"
ok "engine installed to $LIBEXEC"

"$PYTHON_BIN" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --no-cache-dir --disable-pip-version-check --upgrade pip >/dev/null
"$VENV/bin/python" -m pip install --quiet --no-cache-dir --disable-pip-version-check cryptography bcrypt certifi >/dev/null \
  || fail "pip could not install cryptography, bcrypt and certifi (check the network, then re-run)"
"$VENV/bin/python" -c 'import cryptography, bcrypt, certifi' >/dev/null 2>&1 || fail "the python environment at $VENV is incomplete"
ok "python environment ready at $VENV"

if [ -d "$ROOT/tests" ]; then
  TEST_HOME="$(mktemp -d)"
  TEST_LOG="$(mktemp)"
  if (cd "$ROOT" && HOME="$TEST_HOME" PYTHONDONTWRITEBYTECODE=1 "$VENV/bin/python" -m unittest discover -s tests -t . -q >"$TEST_LOG" 2>&1); then
    ok "unit tests pass"
  else
    tail -n 25 "$TEST_LOG" >&2 || true
    rm -rf "$TEST_HOME" "$TEST_LOG"
    fail "unit tests failed; the output above names them"
  fi
  rm -rf "$TEST_HOME" "$TEST_LOG"
fi

printf '\ninstalling command and helper\n-----------------------------\n'
stop_tunnel
rm -f "$CLI"
printf '#!/bin/sh\nexec %s %s/protonx "$@"\n' "$VENV/bin/python" "$LIBEXEC" > "$CLI"
chmod 755 "$CLI"
ok "command installed at $CLI"

sed -e "s|@PYTHON@|$VENV/bin/python|g" -e "s|@HELPER@|$LIBEXEC/helper/protonx_helper.py|g" \
  "$ROOT/helper/com.protonx.helper.plist" > "$PLIST"
chmod 644 "$PLIST"
start_helper
ok "privileged helper running"

printf '\nverifying\n---------\n'
"$CLI" doctor || true

printf '\nDone. Type protonx to open the menu: sign in, pick a country and a server, connect.\n'
printf 'The ProtonX app is separate: curl -fsSL https://raw.githubusercontent.com/pentoshi007/protonx/main/get.sh | bash\n\n'
