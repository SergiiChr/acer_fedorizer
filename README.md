# Acer Fedorizer

A native GTK4/libadwaita control center for the Acer Predator PH16-72 on Linux.
Performance, cooling, keyboard and chassis lighting, battery care, and display
color management in one desktop application. Uses Python and distribution GUI
libraries; no separate SDK, bundled language runtime, or frontend build step.

## Install

From the downloaded folder:

```sh
./setup.sh install
```

Setup installs the native dependencies, daemon, desktop launcher, and the
model-specific rear lightbar driver. Open **Acer Fedorizer** from your application
menu or run `acer-fedorizer`. Run setup as your desktop user; it requests sudo
for system changes. The GUI itself runs without administrator privileges.

| Command | Action |
| --- | --- |
| `./setup.sh install` | Install or completely replace the existing installation. |
| `./setup.sh uninstall` | Remove app files, settings, backups, and the lightbar driver. |
| `./setup.sh status` | Read-only checks of the service, socket, files, and driver. |
| `./setup.sh help` | Explain these commands. |

Existing or older installations trigger
`This will completely overwrite your installation. Proceed? [y/n]`.
Only `y` continues; cancellation changes nothing. Reinstallation resets saved
lighting state. The upgrade cleanup module removes the former installation's
service, socket, files, group, and driver registrations, so both daemons cannot
compete. OS packages shared with other applications and this downloaded folder
are retained during uninstall.

Supported setup environments: Fedora, Ubuntu 24.04, and Debian 13 on Linux
x86_64 with systemd, GTK 4.10+, and libadwaita 1.4+. Debian 12's stock libraries
are too old for this interface. Hardware support remains PH16-72-specific;
see [Compatibility.md](Compatibility.md). Secure Boot may require enrolling
the distribution's DKMS signing key before the rear lightbar module loads.

## Screens and behavior

- **Dashboard:** CPU usage/temperature, memory, physical-core frequencies, and
  optional NVIDIA temperature, VRAM, and board power. GPU monitoring starts off;
  enabling it may wake the discrete GPU. Sampling stops when the GUI closes.
- **Power & Performance:** detected stock-driver profiles and fan modes, with RPM and
  an explicit Apply action. Fan write failures restore automatic cooling.
- **Lighting:** independent device drafts, firmware effects, linked WASD,
  coordinated all-lights settings, four-zone colors, and per-key static editing
  using the keyboard's reported LED geometry. Lighting is last successful
  command state, not hardware readback; firmware Wave animations are independent.
- **Battery:** charge, time estimates when available, health/cycles, and only
  charge/calibration controls actually exposed by the driver.
- **Display:** persistent Native SDR color management on a supported active
  built-in Mutter panel; preserves monitor configuration and is disabled with HDR.
- **System Settings:** detected capabilities, connection details, and licenses/credits.

The lightweight Python hardware service stays running after the window closes,
waiting for commands and the Predator button. It does not run dashboard or GPU
monitoring. Existing hardware settings are not reset by closing the window.

## Screenshots and safe preview

These are screenshots of actual GTK widgets with explicitly labelled preview
data, not claims of live hardware measurements.

![Dashboard](docs/screenshots/overview.png)
![Lighting](docs/screenshots/lighting.png)

[Power & Performance](docs/screenshots/performance.png) · [Battery](docs/screenshots/battery.png) ·
[Display](docs/screenshots/display.png) · [System Settings](docs/screenshots/diagnostics.png) ·
[Per-key editor](docs/screenshots/keyboard.png) · [Credits](docs/screenshots/credits.png)

```sh
./run.sh --preview
./run.sh --screenshots docs/screenshots
```

Preview mode never connects to the hardware service or session display API.
For source development with native dependencies already installed, `./run.sh`
launches the real app without installing it.

## Development and licensing

See [CONTRIBUTING.md](CONTRIBUTING.md), [AGENTS.md](AGENTS.md), and
[NATIVE-CONTROLS.md](NATIVE-CONTROLS.md). `scripts/package.sh` produces one
source-complete archive and a checksum. Python sources and all module/build
sources are included; there is no separate binary GUI distribution.

The application and daemon are GPLv3; the separate kernel bridge is GPLv2.
[NOTICE.md](NOTICE.md) consolidates attribution, consulted protocol research,
and runtime dependency notices. Full terms are in [LICENSE](LICENSE) and the
remaining component license texts in [LICENSES](LICENSES).
