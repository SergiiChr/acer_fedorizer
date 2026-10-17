# Div Acer Manager Max — native PH16-72 edition

Linux performance, cooling, lighting, and monitoring controls for the Acer
Predator PH16-72. This edition uses stock `acer_wmi` and direct USB HID. An
optional DKMS module controls the rear lightbar. Other models are unverified;
see [Compatibility.md](Compatibility.md).

## Install

From the source checkout or an extracted binary archive, run as your desktop user:

```sh
./setup.sh
DAMX
```

The script installs OS dependencies, builds the self-contained GUI when needed,
installs the daemon and desktop launcher, and includes the rear lightbar bridge
on PH16-72. It requests sudo for system changes. A binary archive needs no .NET
SDK. Source builds require network access for NuGet restoration and a .NET SDK;
the script installs .NET 8 when its SDK is unavailable. `DAMX_DOTNET` can select an
existing SDK executable.

Automatic dependencies support Fedora, Ubuntu 24.04, and Debian 12/13 on Linux
x86_64 with systemd. Debian source setup adds Microsoft's package feed when an
SDK is missing. Other distributions require equivalent dependencies and
`--no-deps`. Package-manager availability does not imply hardware compatibility.
Dependencies include Python 3, fontconfig/FreeType, X11/GL libraries, .NET native
runtime libraries, and PyGObject. The bridge also needs DKMS, a C compiler,
make, and headers matching the running kernel. Secure Boot may require enrolling
the distribution's DKMS signing key before the module can load.

```sh
./setup.sh --without-lightbar       # core controls only
./setup.sh --build                  # dependencies and build, no app installation
./setup.sh --build --no-deps        # build using existing dependencies
./setup.sh --no-deps                # install using existing dependencies
./setup.sh --uninstall              # remove service and launchers
./setup.sh --help
```

Installation uses `/opt/damx`, keeps one GUI/daemon rollback copy at
`/opt/damx.previous`, and saves lighting state in `/var/lib/damx/lighting.json`.
The root daemon exposes `/run/DAMX.sock` to the installing desktop user and
restricted `damx` group. Stock `acer_wmi` must be enabled; remove any conflicting
third-party hardware driver before installation. Updates reuse a bundled GUI;
run `./setup.sh --build` first after changing source.

Uninstall retains app files, state, group, and the separate DKMS bridge for
recovery. See [FAQ.md](FAQ.md) for bridge removal and troubleshooting. Low-level
helpers remain in `scripts/`; ordinary installation uses `setup.sh`.

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
./setup.sh --build --no-deps
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
