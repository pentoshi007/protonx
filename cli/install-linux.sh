#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIBEXEC="/usr/local/libexec/protonx"
VENV="$LIBEXEC/venv"
CLI="/usr/local/bin/protonx"
UNIT="/etc/systemd/system/protonx-helper.service"
SOCKET="/var/run/protonx/helper.sock"
GROUP="protonx"

ok()   { printf '[ok] %s\n' "$1"; }
info() { printf '  %s\n' "$1"; }
warn() { printf '[..] %s\n' "$1"; }
fail() { printf '[!!] %s\n' "$1" >&2; exit 1; }

[ "$(uname -s)" = "Linux" ] || fail "this installer is for Linux. On macOS run ./install.sh, which installs the app and the CLI."

if [ "$(id -u)" != "0" ]; then
  command -v sudo >/dev/null 2>&1 || fail "run this installer as root, or install sudo"
  exec sudo bash "$0" "$@"
fi

printf '\nprotonx CLI installer for Linux\n-------------------------------\n'

TARGET_USER="${SUDO_USER:-}"
[ "$TARGET_USER" = "root" ] && TARGET_USER=""

[ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1 \
  || fail "systemd is required to run the protonx helper"

package_manager() {
  local manager
  for manager in apt-get dnf zypper pacman; do
    command -v "$manager" >/dev/null 2>&1 && { printf '%s\n' "$manager"; return 0; }
  done
  return 1
}

install_packages() {
  local manager
  manager="$(package_manager)" || fail "missing: $*. Install them with your package manager, then re-run."
  info "installing $* with $manager"
  case "$manager" in
    apt-get) DEBIAN_FRONTEND=noninteractive apt-get update -qq </dev/null >/dev/null
             DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@" </dev/null >/dev/null ;;
    dnf)     dnf install -y -q "$@" </dev/null >/dev/null ;;
    zypper)  zypper --non-interactive --quiet install "$@" </dev/null >/dev/null ;;
    pacman)  pacman -S --noconfirm --needed "$@" </dev/null >/dev/null ;;
  esac
}

package_name() {
  local manager
  manager="$(package_manager || true)"
  case "$1:$manager" in
    python:apt-get) printf 'python3 python3-venv' ;;
    python:pacman)  printf 'python' ;;
    python:*)       printf 'python3' ;;
    ip:dnf)         printf 'iproute' ;;
    ip:*)           printf 'iproute2' ;;
    wireguard:*)    printf 'wireguard-tools' ;;
    firewall:*)     printf 'nftables' ;;
  esac
}

python_ready() {
  command -v python3 >/dev/null 2>&1 && python3 -c 'import sys, venv, ensurepip; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1
}

missing=()
python_ready || missing+=($(package_name python))
command -v wg-quick >/dev/null 2>&1 && command -v wg >/dev/null 2>&1 || missing+=($(package_name wireguard))
command -v ip >/dev/null 2>&1 || missing+=($(package_name ip))
command -v nft >/dev/null 2>&1 || command -v iptables-restore >/dev/null 2>&1 || missing+=($(package_name firewall))
if [ "${#missing[@]}" -gt 0 ]; then
  install_packages "${missing[@]}"
fi
python_ready || fail "python3 (3.9 or newer) with venv is still missing"
PYTHON_BIN="$(command -v python3)"
ok "python $("$PYTHON_BIN" -V 2>&1 | awk '{print $2}')"
ok "wireguard-tools, iproute2 and a packet filter present"

if [ ! -d /sys/module/wireguard ] && ! modprobe wireguard >/dev/null 2>&1 && ! command -v wireguard-go >/dev/null 2>&1; then
  warn "this kernel has no WireGuard module and wireguard-go is not installed; connecting will fail until one is available"
fi

printf '\ninstalling engine\n-----------------\n'
mkdir -p "$LIBEXEC"
rm -rf "$LIBEXEC/protonxlib" "$LIBEXEC/helper" "$LIBEXEC/helper.py" "$VENV"
cp -R "$ROOT/protonxlib" "$LIBEXEC/"
mkdir -p "$LIBEXEC/helper"
cp "$ROOT"/helper/*.py "$LIBEXEC/helper/"
install -m 755 "$ROOT/protonx" "$LIBEXEC/protonx"
find "$LIBEXEC" -name __pycache__ -type d -prune -exec rm -rf {} +
sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/protonxlib/__init__.py" > "$LIBEXEC/VERSION"
chown -R root:root "$LIBEXEC"
chmod -R go-w "$LIBEXEC"
ok "engine installed to $LIBEXEC"

"$PYTHON_BIN" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --no-cache-dir --disable-pip-version-check --upgrade pip >/dev/null
"$VENV/bin/python" -m pip install --quiet --no-cache-dir --disable-pip-version-check cryptography bcrypt certifi >/dev/null \
  || fail "pip could not install cryptography, bcrypt and certifi (check the network, then re-run)"
"$VENV/bin/python" -c 'import cryptography, bcrypt, certifi' >/dev/null 2>&1 || fail "the python environment at $VENV is incomplete"
ok "python environment ready at $VENV"

if [ -d "$ROOT/tests" ]; then
  TEST_HOME="$(mktemp -d)"
  (cd "$ROOT" && HOME="$TEST_HOME" PYTHONDONTWRITEBYTECODE=1 "$VENV/bin/python" -m unittest discover -s tests -t . -q >/dev/null 2>&1) \
    || { rm -rf "$TEST_HOME"; fail "unit tests failed; run them from the checkout to see why"; }
  rm -rf "$TEST_HOME"
  ok "unit tests pass"
fi

printf '\ninstalling command and helper\n-----------------------------\n'
rm -f "$CLI"
printf '#!/bin/sh\nexec %s %s/protonx "$@"\n' "$VENV/bin/python" "$LIBEXEC" > "$CLI"
chmod 755 "$CLI"
ok "command installed at $CLI"

getent group "$GROUP" >/dev/null || groupadd --system "$GROUP"
if [ -n "$TARGET_USER" ]; then
  usermod -aG "$GROUP" "$TARGET_USER"
  ok "$TARGET_USER may control the tunnel (group $GROUP)"
  info "log out and back in, or run 'newgrp $GROUP', so your current shell gets the group"
else
  info "add users who may connect to the '$GROUP' group: usermod -aG $GROUP NAME"
fi

sed -e "s|@PYTHON@|$VENV/bin/python|g" -e "s|@HELPER@|$LIBEXEC/helper/protonx_helper.py|g" \
  "$ROOT/helper/protonx-helper.service" > "$UNIT"
chmod 644 "$UNIT"
systemctl daemon-reload
systemctl enable protonx-helper.service >/dev/null 2>&1
systemctl restart protonx-helper.service
for _ in $(seq 1 25); do
  [ -S "$SOCKET" ] && break
  sleep 0.2
done
[ -S "$SOCKET" ] || fail "helper failed to start: journalctl -u protonx-helper"
ok "privileged helper running (systemctl status protonx-helper)"

printf '\nverifying\n---------\n'
if [ -n "$TARGET_USER" ]; then
  sudo -u "$TARGET_USER" -H "$CLI" doctor || true
else
  "$CLI" doctor || true
fi

printf '\nDone. Type protonx to open the menu: sign in, pick a country and a server, connect.\n'
printf 'One-shot commands work too: protonx --help\n\n'
