# protonx

Manual country and server selection for Proton VPN on macOS, plus a menu-bar shield that reconnects to your last server in one click.

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
- The same features from the terminal through `protonx`

## Install

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

## Sign in once

ProtonX keeps its own Proton session; it does not borrow the one inside Proton VPN. The VPN app writes its session to the keychain once at login and then refreshes it **in memory only**, so the stored copy is already invalid by the time anything else reads it (verified here: its access token returns `401 Invalid access token` and its refresh token returns `422 Invalid refresh token`, while the app itself keeps working).

So sign in once inside ProtonX: open the app, type your Proton username (the card pre-fills it) and password, plus a two-factor code if your account has one. The password is used locally to compute an SRP proof and is never stored or written to disk; only the resulting session tokens go to your login keychain.

From a terminal the same thing is:

```sh
protonx login --username aniket00736          # prompts for the password
protonx login --two-factor 123456             # only if 2FA was requested
protonx whoami --json
```

After that the session refreshes itself and survives restarts. `protonx logout` forgets it.

## Use

Click the shield in the menu bar. Pick a country, then either `Connect to fastest` or a specific server. While connected, the card shows the server, interface, address, handshake age and traffic counters. `Disconnect` tears the tunnel down; the last server is remembered.

From a terminal:

```sh
protonx countries --free          # countries with servers your plan can use
protonx servers --country NL      # servers in the Netherlands
protonx connect --country NL --server NL-FREE#1
protonx connect --restore         # reconnect to the last server
protonx status --json             # state, peer, handshake, last server
protonx disconnect
```

Add `--json` to any command for machine-readable output, `--offline` to work from the cached server list, `--paid` to include plus-tier servers, and `--dry-run` to print the generated configuration without connecting.

## How it works

- `protonxlib/` talks to the Proton API with your ProtonX session: server list, WireGuard certificate, key registration, X25519 identity, config generation.
- The app never calls `sudo`. A root launch daemon (`com.protonx.helper`) owns the tunnel: it validates the request, writes the configuration itself, and runs `wg-quick`.
- The daemon only accepts structured fields (keys, address, endpoint, port, MTU, keepalive). Directives such as `PostUp`, unknown fields, malformed keys, and shell metacharacters in the endpoint are rejected, so the socket cannot be used to run commands as root.
- The socket lives at `/var/run/protonx/helper.sock`, owned `root:admin` with mode `0660`, and the daemon re-checks that the caller is root or an admin user.
- **DNS is owned by the daemon, not by `wg-quick`.** Before pointing the active network service at Proton's in-tunnel resolver (`10.2.0.1`), the daemon saves the previous resolvers to `/var/run/protonx/dns.json`; `disconnect` always restores them, and it drops any stale in-tunnel resolver instead of restoring a dead one. This is what makes "connected but no internet" impossible: a tunnel that dies can no longer leave the machine pointing at an unreachable resolver.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Sign-in card will not go away | `protonx whoami --json` shows whether a session exists; wrong credentials return code 8002, and Proton's captcha returns a message asking you to sign in at account.proton.me once. |
| "protonx helper is not installed" | Re-run `./install.sh`. |
| Country list is empty | No cached list and no live session. Sign in, then press refresh. |
| Connects but no internet | Fixed: the daemon now saves and restores DNS itself. If a machine was left broken by an older build, `sudo networksetup -setdnsservers Wi-Fi Empty` restores automatic DNS. |
| Menu-bar shield missing | `open -a ProtonX`; check `pgrep -fl ProtonX`. |

## Uninstall

```sh
./uninstall.sh          # keeps cached servers and last-server record
./uninstall.sh --purge  # removes them too
```

## Status

Verified on this machine: 77 Python tests and 10 Swift state scenarios, the SRP client cross-checked against Proton's own `go-srp` server implementation (it accepted our proof and its server proof matched), a live sign-in, a live WireGuard tunnel to `CA-FREE#20` with a real handshake and hundreds of kilobytes of traffic, DNS resolution and HTTPS by name through that tunnel, DNS restored to automatic on disconnect, and the app's sign-in, country and server screens.

Free tier only: the app asks the engine for `countries --free`, so only locations with free servers appear (10 here, 199 servers in the US, 50 in NL), and the server list never shows plus-tier entries.

The menu-bar popover and the detached window each own a separate view controller, so opening and closing the window cannot empty the popover; `--selftest-popover` asserts that invariant.
