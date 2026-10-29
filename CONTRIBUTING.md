# Development

Working rules, the source map, and `scripts/check.sh` are described in [AGENTS.md](AGENTS.md); they apply to people too.

## Running from source

You need system Python 3, PyGObject/Pycairo, GTK 4.10+, and libadwaita 1.4+.
There are no pip packages and no frontend build step.

- `./run.sh` starts the real app without installing it.
- `./run.sh --preview` uses labelled fake data and never connects to the hardware service or the desktop session.
- `./run.sh --screenshots docs/screenshots` renders the README screenshots from preview data.
- `python3 -m hardware.daemon --inspect` reads live hardware without changing it.
- `scripts/native-selftest.py --exercise` sends real commands; never use it for routine checks.

## Service and socket

| Item | Value |
| --- | --- |
| Service | `fedorizer-daemon.service` (root, sandboxed) |
| Socket | `/run/acer-fedorizer.sock`, mode 0660, owned by the installing user and group `fedorizer` |
| Saved lighting | `/var/lib/acer-fedorizer/lighting.json` |
| App files | `/opt/acer-fedorizer` |

Requests are one JSON line with `command` and `params`.
Responses contain `success` plus `data` or `error`.
A request may be at most 65,536 bytes including the newline; the client accepts responses up to 262,144 bytes.
The daemon validates every write itself, independently of the GUI, and handles one hardware request at a time.

The service sandbox gives a read-only system, access only to hidraw and input devices, and no network.
It keeps only `CAP_CHOWN` to hand over the socket, and `CAP_SETUID`/`CAP_SETGID` to start the GUI as the desktop user when the Predator button is pressed.
Writes to sysfs and hidraw work because root owns those files.
These sandbox limits are not yet verified on hardware; check `journalctl -u fedorizer-daemon.service` after installing.

## Installation transaction

`scripts/install.sh` with `scripts/install-transaction.sh` makes install all-or-nothing for the files the app owns:

1. Stage the new app and build and sign the lightbar module in private DKMS trees before removing anything.
2. Snapshot the current app, settings, service states, groups, and driver registrations.
3. Remove the previous installation, including old-name installs through `scripts/legacy-install.sh`, so two daemons never compete.
4. Install, then wait for the new service to answer a bounded ping (`scripts/wait-daemon.py`).
5. On any failure, restore the snapshot; if the restore itself fails, keep the snapshot archive and report where it is.

The app is staged in a new directory and moved into place, so updating a running app does not fail.
Installed OS packages are not rolled back.
A killed process or power loss mid-install may need manual recovery from the kept snapshot.

Installation checks in `control_center/installation.py` are shared by System Settings and `setup.sh status`.
They read files, systemd states, a socket ping, the loaded module, and DKMS status for the running kernel, all without sudo.
They never look for HID devices, change firmware, or load or unload modules.

## What the tests cover

Unit tests use temporary sysfs trees, fake system and package commands, and local sockets.
Installer tests simulate failures at each step: missing headers, build or signing, driver install or load, service start, health, readiness, legacy cleanup, and a failed restore.
They never install the app or change firmware.

`scripts/ui-smoke.py` drives real GTK widgets with preview data.
It checks navigation, profile and fan mappings, single-choice mode tiles, fan slider state, independent drafts, that refresh keeps drafts, palette limits, no writes at startup, credits and links, async status and errors, Wave colors per device, per-key brightness across edit/apply/reopen, and four-zone apply.

## Packaging

`scripts/package.sh` writes one source-complete archive and its checksum to `publish/`, which git ignores.
The archive holds the app, daemon, kernel module source, scripts, tests, docs, and license texts.
Setup and packaging remove Python caches and local kernel build output.
