# protonx

Manual country and server selection for Proton VPN. On macOS it ships as a menu-bar app plus the `protonx` command; on Linux and Windows it is the `protonx` command on its own (`protonx-cli`), which also works over SSH.

Proton VPN 4.x removed that ability for free accounts: every location is drawn greyed out and clicking one raises an upgrade prompt. This project gives the selection back as a native app of its own instead of modifying Proton's.

## Why not patch Proton's own app

Proton VPN 4.5.0 gates manual selection in three places (`CountryItemViewModel.isTierTooLow`, `ConnectionAuthorizer.authorize`, `VpnServerSelector.selectServer`), and every 4.x release contains the same three gates. Modifying the binary invalidates its signature, and the app cannot be re-signed on an ordinary Mac:

- ad-hoc signature with the original entitlements: killed by AMFI (`Killed: 9`, no crash report)
- full nested ad-hoc re-sign with original entitlements: killed by AMFI
- ad-hoc with empty entitlements: launches, then dies in dyld on Sparkle team-ID validation
- self-signed certificate plus the original provisioning profile: `TeamIdentifier=not set`, killed by AMFI

The blocker is `com.apple.developer.networking.networkextension`, a restricted entitlement that macOS only accepts from an Apple-issued profile for the signing team. Unlocking Proton's own UI therefore needs a paid Apple Developer team, a new App ID, and a re-signed system extension. That is not something this machine can do, so the app ships as a companion that drives the same WireGuard protocol Proton's own client uses.

## What you get

- A menu-bar shield: disconnected = outline, connected = filled
- Browse every country your plan can use, then every server in it, sorted by load
- One-click `Connect`, plus `Connect to fastest` for the country
- `Reconnect` on the last server you used, without opening anything
- Live handshake age and byte counters while connected
- The same features from the terminal through `protonx`: type `protonx` for a guided menu, or use one-shot commands with flags

## Which installer

| System | What you get | Install |
| --- | --- | --- |
| macOS 13+ | ProtonX.app and the `protonx` command | `curl -fsSL https://raw.githubusercontent.com/pentoshi007/protonx/main/get.sh \| bash` |
| Linux (systemd) | `protonx` command and a root helper service | `curl -fsSL https://raw.githubusercontent.com/pentoshi007/protonx/main/cli/get.sh \| bash` |
| Windows 10/11 | `protonx` command driving WireGuard for Windows | `irm https://raw.githubusercontent.com/pentoshi007/protonx/main/cli/get.ps1 \| iex` |
| Linux or Windows with Node 16+ | the same `protonx` command from npm | `npm install -g protonx-cli`, then `protonx` |

On macOS the CLI comes with the app, so use the app installer there. The npm package is a launcher: the first time you run `protonx` it offers to run the matching installer for your system (`protonx setup` does it explicitly), then starts the CLI.

## Install on macOS

From a checkout:

```sh
git clone https://github.com/pentoshi007/protonx.git
cd protonx
./install.sh
```

From a release (downloads, verifies and installs in one command):

```sh
curl -fsSL https://raw.githubusercontent.com/pentoshi007/protonx/main/get.sh | bash
```

The installer builds the app from a checkout (a release archive ships the prebuilt universal app), runs the test suite, installs the engine to `/usr/local/libexec/protonx`, creates a private Python environment there, installs a privileged helper daemon, and puts `ProtonX.app` in `/Applications`.

Requirements:

- macOS 13 or newer, Intel or Apple Silicon.
- `python3` with `venv` and `pip`. The Command Line Tools provide it (`xcode-select --install`); Homebrew's `python3` also works. The installer discovers the interpreter and creates `/usr/local/libexec/protonx/venv`, then installs `cryptography` and `bcrypt` into it, so nothing is added to the system Python and no wheels are vendored.
- `wireguard-tools` (`brew install wireguard-tools`).
- Building from source additionally needs the Swift toolchain from the Command Line Tools. A release archive ships the prebuilt universal app, so end users do not need Swift.

### Architectures

`app/build.sh` compiles the app twice, once for `arm64-apple-macosx13.0` and once for `x86_64-apple-macosx13.0`, and joins the slices with `lipo`. The result is one universal `ProtonX.app` that runs natively on Apple Silicon and on Intel Macs:

```sh
lipo -info /Applications/ProtonX.app/Contents/MacOS/ProtonX
# Architectures in the fat file: ... are: x86_64 arm64
```

The Python engine is architecture-independent source; the installer creates its environment from the interpreter already on the target Mac, so the same archive works on both architectures. The helper daemon runs from that same environment.

### Signing

The app is ad-hoc signed (`codesign --sign -`), not signed with an Apple Developer ID and not notarized. That is enough for it to run on the machine that built it, but Gatekeeper will block a copy downloaded from the internet with "cannot be opened because the developer cannot be verified" or "is damaged".

The installer handles this: it removes the quarantine attribute from the installed app and re-signs it ad-hoc in place. If you copy the app by hand instead, do the same:

```sh
xattr -dr com.apple.quarantine /Applications/ProtonX.app
codesign --force --sign - --identifier com.protonx.menubar /Applications/ProtonX.app
```

Without a paid Apple Developer team there is no way to notarize it, so the first launch always goes through that step. The app does not use restricted entitlements, so nothing else depends on the signature.

## Install on Linux

The one-line installer above downloads the repository and runs `cli/install-linux.sh`. From a checkout:

```sh
git clone https://github.com/pentoshi007/protonx.git
cd protonx
./cli/install-linux.sh
```

It needs systemd and installs any missing packages with apt, dnf, zypper or pacman: `python3` (with `venv`), `wireguard-tools`, `iproute2`, and `nftables` when neither `nft` nor `iptables-restore` exists (wg-quick needs one of them for a full tunnel). Then it:

- installs the engine to `/usr/local/libexec/protonx` with a private Python environment, and the command to `/usr/local/bin/protonx`
- creates the `protonx` group and adds the user who ran the installer to it
- installs and starts `protonx-helper.service`, the root helper that owns the tunnel

Only root and members of the `protonx` group may control the tunnel. Other users: `sudo usermod -aG protonx NAME`. The kernel needs WireGuard (built in since Linux 5.6) or `wireguard-go`.

## Install on Windows

The one-line installer above downloads the repository and runs `cli\install-windows.ps1`. It finds Python 3.9+ (or installs it with winget), installs WireGuard for Windows with winget when it is missing, puts the engine in `%LOCALAPPDATA%\protonx`, and adds `protonx` to your user `PATH`.

Starting and stopping the tunnel goes through WireGuard's own tunnel service, which needs an Administrator terminal. Signing in, browsing countries and checking status work in a normal terminal.

## Sign in once

ProtonX keeps its own Proton session; it does not borrow the one inside Proton VPN. The VPN app writes its session to the keychain once at login and then refreshes it **in memory only**, so the stored copy is already invalid by the time anything else reads it (verified here: its access token returns `401 Invalid access token` and its refresh token returns `422 Invalid refresh token`, while the app itself keeps working).

So sign in once inside ProtonX: open the app (or type `protonx`), enter your Proton username (pre-filled when known) and password, plus a two-factor code if your account has one. The password is used locally to compute an SRP proof and is never stored or written to disk. The resulting session tokens go to the login keychain on macOS, and to `~/.config/protonx/secrets/` (mode `0600`) on Linux or `%APPDATA%\protonx\secrets\` on Windows.

With flags instead of the menu:

```sh
protonx login --username aniket00736          # prompts for the password
protonx login --two-factor 123456             # only if 2FA was requested
protonx whoami --json
```

After that the session refreshes itself and survives restarts. `protonx logout` forgets it.

## Use the interactive menu

Type `protonx`. Everything is a list you move through with the arrow keys and Enter; Esc goes back and Ctrl+C quits. Long lists such as countries filter as you type (`net` jumps to the Netherlands).

- Not signed in: sign in (with a two-factor step when needed) or check the setup.
- Disconnected: reconnect to the last server, connect to the fastest server, or choose a country, then a server. Countries show how many servers they have and the best load; servers are sorted by load.
- Connected: disconnect, switch server, switch to the fastest server, or open the live connection details (handshake age, traffic, uptime).
- Settings: show Plus servers, P2P servers only, Proton DNS, and on Linux the SSH guard. They are saved in `~/.config/protonx/preferences.json`.
- Account shows the plan and signs out; Check setup runs `protonx doctor`.

Quitting the menu never touches the tunnel. Connect, quit, close the terminal or the SSH session, and the VPN stays up; run `protonx` again later to see its state, switch or disconnect. On terminals without cursor control (`TERM=dumb`, or `PROTONX_PLAIN=1`) the menu falls back to numbered choices.

## Use the app

Click the shield in the menu bar. Pick a country, then either `Connect to fastest` or a specific server. While connected, the card shows the server, interface, address, handshake age and traffic counters. `Disconnect` tears the tunnel down; the last server is remembered. The app and the CLI share the same session, last-server record and tunnel, so you can connect in one and disconnect in the other.

## One-shot commands

```sh
protonx countries --free          # countries with servers your plan can use
protonx servers --country NL      # servers in the Netherlands, lowest load first
protonx connect --country NL      # fastest free server in the Netherlands
protonx connect --country NL --server NL-FREE#1
protonx connect --country japan   # names work as well as codes
protonx connect --restore         # reconnect to the last server
protonx status --json             # state, peer, handshake, last server
protonx disconnect
```

`connect` while a tunnel is up switches to the new server; if the new one fails, the previous tunnel is restored. Add `--json` to any command for machine-readable output, `--offline` to work from the cached server list, `--paid` to include plus-tier servers, `--random` to pick a random server instead of the fastest, `--no-dns` to keep the system resolver, and `--dry-run` to print the generated configuration without connecting.

## Over SSH on Linux

A full tunnel normally cuts off the SSH session you used to start it, because the replies to your SSH client start going into the tunnel. When `protonx` runs inside an SSH session on Linux (it reads `SSH_CONNECTION`), it asks the helper for an SSH guard: one policy rule, `from <the address you SSH'd to> lookup main`, so replies sent from that address keep using the normal route. New outbound connections still go through the VPN. The rule is removed on disconnect. Turn it off with `--no-ssh-guard` or in Settings.

macOS and Windows do not have the SSH guard; starting a full tunnel from an SSH session there drops that session.

## How it works

- `protonxlib/` talks to the Proton API with your ProtonX session: server list, WireGuard certificate, key registration, X25519 identity, config generation. `protonxlib/repl.py` is the interactive menu and `protonxlib/service.py` holds the operations it shares with the one-shot commands.
- Neither the app nor the CLI calls `sudo`. On macOS and Linux a root helper owns the tunnel (`com.protonx.helper` under launchd, `protonx-helper.service` under systemd): it validates the request, writes the configuration itself, and runs `wg-quick`. `helper/helper_macos.py` and `helper/helper_linux.py` hold the system-specific parts.
- The helper only accepts structured fields (keys, address, endpoint, port, MTU, keepalive, SSH guard address). Directives such as `PostUp`, unknown fields, malformed keys, and shell metacharacters in the endpoint are rejected, so the socket cannot be used to run commands as root. The rules live in `protonxlib/wgconf.py`, shared with the Windows path.
- The socket lives at `/var/run/protonx/helper.sock`. On macOS it is owned `root:admin` with mode `0660` and the helper re-checks that the caller is root or an admin user. On Linux the helper reads the caller's uid with `SO_PEERCRED` and only serves root and members of the `protonx` group; the socket file itself is `0666` so a user added to the group can connect without logging out first.
- On Windows there is no helper: the CLI writes the configuration to `%APPDATA%\protonx\tunnel\protonx.conf` and installs it as a WireGuard for Windows tunnel service (`wireguard.exe /installtunnelservice`), which owns routing and DNS.
- **On Linux, DNS is owned by the helper too.** With systemd-resolved (when `/etc/resolv.conf` points at its stub), it sets Proton's resolver on the `protonx` link with `resolvectl`, which disappears with the link. Otherwise it saves `/etc/resolv.conf` (file or symlink) to `/var/lib/protonx/dns.json`, writes `nameserver 10.2.0.1`, and puts the original back on disconnect or at the next boot.
- **On macOS, DNS is owned by the daemon, not by `wg-quick`.** Before pointing the active network service at Proton's in-tunnel resolver (`10.2.0.1`), the daemon saves the previous resolvers to `/var/run/protonx/dns.json`; `disconnect` always restores them, and it drops any stale in-tunnel resolver instead of restoring a dead one. This is what makes "connected but no internet" impossible: a tunnel that dies can no longer leave the machine pointing at an unreachable resolver.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Sign-in card will not go away | `protonx whoami --json` shows whether a session exists; wrong credentials return code 8002, and Proton's captcha returns a message asking you to sign in at account.proton.me once. |
| "the protonx helper is not running" | macOS: re-run `./install.sh`. Linux: `systemctl status protonx-helper`, or re-run `cli/install-linux.sh`. |
| "the protonx helper refused this user" (Linux) | `sudo usermod -aG protonx $USER`. |
| "connecting on Windows needs an Administrator terminal" | Open the terminal with Run as administrator. |
| SSH session dropped after connecting | On Linux check that Settings shows SSH guard on. On macOS and Windows there is no guard; connect from a local terminal. |
| Country list is empty | No cached list and no live session. Sign in, then press refresh. |
| Connects but no internet | Fixed: the daemon now saves and restores DNS itself. If a machine was left broken by an older build, `sudo networksetup -setdnsservers Wi-Fi Empty` restores automatic DNS. |
| Menu-bar shield missing | `open -a ProtonX`; check `pgrep -fl ProtonX`. |

## Uninstall

Each uninstaller disconnects first.

```sh
./uninstall.sh                     # macOS: keeps cached servers and last-server record
./uninstall.sh --purge             # macOS: removes them too
./cli/uninstall-linux.sh [--purge] # Linux
```

On Windows: `powershell -ExecutionPolicy Bypass -File cli\uninstall-windows.ps1 [-Purge]`. With npm, run the uninstaller for your system, then `npm uninstall -g protonx-cli`.

## Status

Linux and Windows support is new in 1.1.0. The Linux helper was exercised end to end against stand-ins for `wg`, `wg-quick` and `ip` (connect, switch, failed switch with rollback, SSH guard, `resolv.conf` save and restore), and the interactive menu was driven through a pseudo-terminal. It has not yet run against a live Proton server on Linux or Windows, and the Windows path has not been run at all.

Verified on macOS with 1.0.0, before the helper was split into per-platform modules: 77 Python tests and 10 Swift state scenarios, the SRP client cross-checked against Proton's own `go-srp` server implementation (it accepted our proof and its server proof matched), a live sign-in, a live WireGuard tunnel to `CA-FREE#20` with a real handshake and hundreds of kilobytes of traffic, DNS resolution and HTTPS by name through that tunnel, DNS restored to automatic on disconnect, and the app's sign-in, country and server screens.

Free tier only: the app asks the engine for `countries --free`, so only locations with free servers appear (10 here, 199 servers in the US, 50 in NL), and the server list never shows plus-tier entries.

The menu-bar popover and the detached window each own a separate view controller, so opening and closing the window cannot empty the popover; `--selftest-popover` asserts that invariant.
