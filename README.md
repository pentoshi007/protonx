# ProtonX

Pick any Proton VPN country and server yourself. ProtonX is a menu-bar app for macOS and a `protonx` command for macOS, Linux and Windows.

- Browse every country your plan can use, then every server in it, sorted by load.
- Connect to the fastest server or a specific one.
- Reconnect to the last server in one click.
- See the server, interface, handshake age and traffic while connected.
- Use the same features from the terminal with `protonx`.

The macOS app and the CLI are separate installs. Use either or both.

## Install

### Which installer

| System | What you get | Install |
| --- | --- | --- |
| macOS 13+ | ProtonX.app (menu-bar app) | `curl -fsSL https://raw.githubusercontent.com/pentoshi007/protonx/main/get.sh \| bash` |
| macOS 13+ | `protonx` command and root helper | `npm install -g @pentoshi/protonx`, or `curl -fsSL https://raw.githubusercontent.com/pentoshi007/protonx/main/cli/get.sh \| bash` |
| Linux (systemd) | `protonx` command and a root helper service | `curl -fsSL https://raw.githubusercontent.com/pentoshi007/protonx/main/cli/get.sh \| bash` |
| Windows 10/11 | `protonx` command driving WireGuard for Windows | `irm https://raw.githubusercontent.com/pentoshi007/protonx/main/cli/get.ps1 \| iex` |
| Linux, Windows or macOS with Node 16+ | the same `protonx` command from npm | `npm install -g @pentoshi/protonx`, then `protonx` |

The macOS app and the CLI are separate installs. Use either or both. The app installer does not install the `protonx` command; the CLI installer does not install the app.

### macOS app

From a release:

```sh
curl -fsSL https://raw.githubusercontent.com/pentoshi007/protonx/main/get.sh | bash
```

From a checkout:

```sh
git clone https://github.com/pentoshi007/protonx.git
cd protonx
./install.sh
```

The app installs to `/Applications/ProtonX.app`, starts at login, and puts a shield in the menu bar.

### macOS CLI

```sh
npm install -g @pentoshi/protonx
# or
curl -fsSL https://raw.githubusercontent.com/pentoshi007/protonx/main/cli/get.sh | bash
```

Then run:

```sh
protonx
```

The CLI installs `/usr/local/bin/protonx` and a root helper. On macOS it asks for your administrator password once.

### Linux

```sh
curl -fsSL https://raw.githubusercontent.com/pentoshi007/protonx/main/cli/get.sh | bash
```

From a checkout:

```sh
git clone https://github.com/pentoshi007/protonx.git
cd protonx
./cli/install-linux.sh
```

The installer handles the system packages and installs a systemd helper. Only root and members of the `protonx` group can control the tunnel. Add a user with:

```sh
sudo usermod -aG protonx NAME
```

A group change only reaches new logins: after adding yourself, run `newgrp protonx` or log out and back in before connecting.

### Windows

```powershell
irm https://raw.githubusercontent.com/pentoshi007/protonx/main/cli/get.ps1 | iex
```

From a checkout:

```powershell
powershell -ExecutionPolicy Bypass -File cli\install-windows.ps1
```

The installer installs Python and WireGuard via winget if they are missing. The first time you connect, Windows asks for permission: approve the prompt and the terminal keeps running. You do not need to open the terminal as Administrator.

### npm

```sh
npm install -g @pentoshi/protonx
protonx
```

Works on macOS, Linux and Windows with Node 16+. The first run offers to install the matching engine and helper; `protonx setup` does it explicitly.

## Sign in

Open ProtonX and sign in once with your Proton username and password (plus a two-factor code if your account uses one). The password is used locally and is never stored. The app and CLI share the session.

From the CLI:

```sh
protonx login --username YOUR_NAME
protonx whoami --json
```

## Use the app

Click the shield in the menu bar. Pick a country, then `Connect to fastest` or a specific server. While connected, the card shows the server, interface, handshake age and traffic. `Disconnect` tears the tunnel down; the last server is remembered. `Reconnect` repeats it. If you quit and reopen the app, it reads the live tunnel and shows the active server instead of starting from disconnected.

The account menu has `Launch at Login`, `Repair Network`, `Check for Updates…` and `Sign Out…`.

## Use the CLI

Type `protonx` for the interactive menu. Move with the arrow keys and Enter; Esc goes back; Ctrl+C quits. The VPN stays up when you quit.

- Not signed in: sign in or check setup.
- Disconnected: reconnect, connect to the fastest server, or choose a country and server.
- Connected: disconnect, switch server, or open connection details.
- Settings: show Plus servers, P2P only, Proton DNS, and on Linux the SSH guard.
- Account: plan and sign out.
- Check setup: dependencies, helper and session.
- Repair network: stop the tunnel, restore DNS and check that the internet works.
- Check for updates: install the latest CLI.

## Commands

```sh
protonx countries --free
protonx servers --country NL
protonx connect --country NL
protonx connect --country NL --server NL-FREE#1
protonx connect --restore
protonx status --json
protonx disconnect
protonx repair
protonx update --check
protonx update
```

Add `--json` to any command for machine-readable output, `--offline` to use the cached server list, `--paid` to include plus-tier servers, `--random` to pick a random server, `--no-dns` to keep the system resolver, and `--dry-run` to print the configuration without connecting.

## Update

The app and CLI update separately.

- App: `Check for Updates…` in the account menu, app menu, or right-click menu. It downloads the signed release, verifies it, installs with an administrator prompt, and offers to relaunch.
- CLI: `protonx update --check` reports the current and latest versions; `protonx update` installs the latest CLI. The interactive menu has `Check for updates` too.

## Requirements

- macOS 13+ (Intel or Apple Silicon), Linux with systemd, or Windows 10/11.
- Python 3.9+ with `venv` and `pip` on macOS and Linux. The installers create a private environment; nothing is added to the system Python.
- `wireguard-tools` on macOS and Linux; WireGuard for Windows.
- The macOS app is ad-hoc signed, not notarized. The installer removes the quarantine flag and re-signs it. If you copy the `.app` by hand, Gatekeeper may block it.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Sign-in fails | Wrong credentials return code 8002. If Proton asks for a captcha, sign in once at account.proton.me. |
| "the protonx helper is not running" | Re-run the installer: `get.sh` for the app, `cli/get.sh` for the CLI. |
| Country list is empty | Sign in, then refresh. |
| Connects but no internet | Disconnect and reconnect. If DNS is still stale, run `protonx repair` or choose `Repair Network` in the app. |
| Internet stops after a crash, reboot, or update | Run `protonx repair` (or `Repair Network` in the app). It stops any tunnel, restores DNS, flushes the resolver cache, and reports whether DNS and the internet work. |
| Menu-bar shield missing | `open -a ProtonX`; check `Launch at Login` in the account menu. |
| SSH session drops on Linux | Keep the SSH guard on in Settings. macOS and Windows do not have the guard; connect from a local terminal. |
| Linux says the helper refused this user | You are not in the `protonx` group in this session. Run `sudo usermod -aG protonx $USER`, then `newgrp protonx` or log out and back in. |
| Windows cannot connect | Approve the Windows permission prompt. If you declined it, run `protonx connect` again, or open the terminal as Administrator. |

## Uninstall

From a checkout:

```sh
./uninstall.sh [--purge]              # macOS app
./cli/uninstall-macos.sh [--purge]    # macOS CLI
./cli/uninstall-linux.sh [--purge]    # Linux
```

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File cli\uninstall-windows.ps1 [-Purge]
```

With npm:

```sh
npm uninstall -g @pentoshi/protonx
```

`--purge` also removes the cached server list, identity and last-server record.

## Links

- GitHub: https://github.com/pentoshi007/protonx
- npm: https://www.npmjs.com/package/@pentoshi/protonx
- Releases: https://github.com/pentoshi007/protonx/releases
