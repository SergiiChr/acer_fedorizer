# Div Acer Manager Max — native PH16-72 edition

Linux performance, cooling, lighting, and monitoring controls for the Acer
Predator PH16-72. This edition uses stock `acer_wmi` and direct USB HID. An
optional DKMS module controls the rear lightbar. Other models are unverified;
see [Compatibility.md](Compatibility.md).

## Setup

From the downloaded source folder or extracted binary archive, run:

```sh
./setup.sh install
```

Setup installs all dependencies and the complete app. It automatically handles
source builds, desktop integration, and the PH16-72 rear lightbar driver.
Run it as your desktop user; it requests sudo for system changes.

There are four commands:

| Command | What it does |
| --- | --- |
| `./setup.sh install` | Install a fresh copy, or completely overwrite an existing installation. |
| `./setup.sh uninstall` | Completely remove the app, saved settings, backups, and lightbar driver. |
| `./setup.sh status` | Check the app, daemon, socket connection, and lightbar installation without changing anything. |
| `./setup.sh help` | Explain these commands. |

If an installation or leftover files are detected, install asks:
`This will completely overwrite your installation. Proceed? [y/n]`
Only `y` continues; any other answer or end of input cancels before any changes.
Overwrite resets saved lighting settings and removes old installation backups.
Source downloads always rebuild, so old local build output cannot silently win.
Binary archives use their included application and need no .NET SDK.
Setup removes compiler intermediates, Python caches, and local module build
leftovers on success or failure. Source installs also remove the temporary
published GUI after copying it into place. Binary archives retain their included
GUI so they can be used again. Release archives and license notices are retained.

When setup succeeds, open **DAMX** from the applications menu or run `DAMX`.
If setup fails, run `./setup.sh status` for a readable diagnosis and repair
instructions. Repeating install replaces existing DKMS registrations rather
than trying to add the same module twice.

Automatic dependencies support Fedora, Ubuntu 24.04, and Debian 12/13 on Linux
x86_64 with systemd. Other distributions are currently unsupported by setup.
Package-manager support does not imply hardware compatibility. Stock
`acer_wmi` must remain enabled. Secure Boot can require enrolling the
distribution's DKMS signing key before a newly built module will load.

Installation uses `/opt/damx`; lighting state is in
`/var/lib/damx/lighting.json`. The root daemon exposes `/run/DAMX.sock` to the
installing desktop user and restricted `damx` group. Uninstall removes all of
these, desktop integration, prior app backups, and DAMX module sources and
registrations across kernels. Shared OS dependencies (including SDK/compiler
packages) and the downloaded source folder remain, since other software can use
them. Desktop display preferences already applied through Mutter remain desktop
preferences. See [FAQ.md](FAQ.md) for troubleshooting.

## Controls and limits

- Performance profiles and fan controls use detected stock platform-profile and
  Acer hwmon interfaces. Profiles and RPM refresh every two seconds. A failed
  manual fan write restores automatic cooling.
- Keyboard controls include four zones, per-key static layouts using the
  keyboard's reported geometry, native effects, and independent WASD lighting.
- Lid logo and optional rear lightbar offer their supported firmware effects.
  All-lights sync reports partial failures; animations are not phase-locked.
  Neon and Wave use firmware palettes where arbitrary RGB is unavailable.
- Battery status and supported charge controls have a separate tab. Unsupported
  controls are hidden. MUX switching, scenarios, and GPU tuning are unavailable.
- CPU and GPU telemetry includes per-core frequency and opt-in NVIDIA metrics,
  VRAM, and power. GPU queries may wake the discrete GPU.
- The Predator button opens or raises the app in the desktop session.
- The Display tab offers persistent Native SDR color management for active
  built-in panels advertising `sdr-native` in Mutter. It uses the user's D-Bus
  session and PyGObject, preserves monitor arrangement, and is disabled with HDR.
  It does not choose ICC profiles. See the [Mutter DisplayConfig interface](https://gitlab.gnome.org/GNOME/mutter/-/blob/main/data/dbus-interfaces/org.gnome.Mutter.DisplayConfig.xml).

Lighting state records the last successful command; firmware effect readback
is unverified. Command acceptance does not prove the physical result. Protocol
evidence and hardware observations are in [NATIVE-CONTROLS.md](NATIVE-CONTROLS.md).

## Development and review

Read [CONTRIBUTING.md](CONTRIBUTING.md) for architecture, tests, dependencies,
and packaging, and [AGENTS.md](AGENTS.md) for agent instructions. Current review
findings and validation limits are in [REVIEW.md](REVIEW.md).

```sh
python3 -m unittest discover -s tests -v
dotnet run --project tests/client-tests/ClientTests.csproj -c Release
scripts/local-setup.sh --build
scripts/package.sh
```

Packaging creates binary and corresponding-source archives with checksums.
`python3 scripts/native-selftest.py` inspects live capabilities. Its `--exercise`
option changes profiles, fans, and lighting; use it only for deliberate hardware
validation.

## Licensing and credits

Derived from [Div Acer Manager Max by PXDiv and contributors](https://github.com/PXDiv/Div-Acer-Manager-Max).
The application/daemon use GPLv3; the separate lightbar module uses GPLv2.
[NOTICE.md](NOTICE.md) credits the original app, historical driver work, protocol
references, fonts, and libraries. [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)
and [LICENSES](LICENSES) retain dependency terms. Preserve all notices and provide
matching source with binary releases. No Acer proprietary reference binaries or
extracts are distributed. Upstream credit links are not this edition's support
or update destinations.
