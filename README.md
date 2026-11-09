# Acer Fedorizer

A native GTK4/libadwaita control center for the Acer Predator PH16-72 on Linux.
It covers performance, cooling, keyboard and chassis lighting, battery care, and display color in one app.
It uses Python and your distribution's GUI libraries; there is nothing to compile for the app itself.

## Install

From the downloaded folder, as your desktop user:

```sh
./setup.sh install
```

Setup installs the dependencies, the hardware service, a desktop launcher, and the rear lightbar driver.
It asks for sudo only for system changes; the app itself runs without administrator rights.
Open **Acer Fedorizer** from your app menu or run `acer-fedorizer`.

| Command | Action |
| --- | --- |
| `./setup.sh install` | Install, or fully replace an existing installation. |
| `./setup.sh uninstall` | Remove app files, settings, backups, and the lightbar driver. |
| `./setup.sh status` | Check the service, socket, files, and driver without changing anything. |
| `./setup.sh help` | Explain these commands. |

If any installation exists, including one under an older name, setup asks `This will completely overwrite your installation. Proceed? [y/n]`.
Only `y` continues.
If the new installation fails, setup restores the previous one; if even that fails, it tells you where the backup is kept.
Saved lighting is reset only after a successful reinstall.
Uninstall keeps shared OS packages and the downloaded folder.

Supported: Fedora, Ubuntu 24.04, and Debian 13 on x86_64 with systemd, Python 3.12+, GTK 4.10+, and libadwaita 1.4+.
Debian 12's libraries are too old.
Hardware support is PH16-72 only; see [Compatibility.md](Compatibility.md).
With Secure Boot you may need to enroll your distribution's DKMS signing key before the lightbar driver loads.

## Screens

- **Dashboard:** stock driver profiles and fan modes (Auto, Max, Manual) that apply on one click, fan RPM, charts of CPU and GPU temperature, usage, memory (RAM and VRAM), and power with their sum, where hovering a line shows exact values, the CPU frequency section, and the device options your driver exposes. Fan speeds are a share of top speed: in Manual they apply with the Apply speeds button, and in Auto and Max the sliders show the current speed; the firmware still speeds fans up as the laptop warms. If a fan write fails or the service stops for any reason, fans return to automatic. GPU monitoring starts off because it may wake the discrete GPU; its switch is on the right of the dashboard heading. Sampling pauses while the window is minimized and stops when it closes.
- **CPU frequency (on the Dashboard):** one bar per physical core showing its current frequency over its 10-second average, with performance and efficiency cores in different colors and dashed lines at their caps. Separate frequency caps for performance and efficiency cores apply with a button; a cap at the hardware maximum means no cap.
- **Lighting:** one editor for Keyboard, WASD, Logo, and Bar, with a separate unsaved draft per device. Pick a firmware effect, color (picker, hex, or swatches), speed, brightness, and direction; options a device does not support are disabled. WASD can follow the keyboard, all lights can be set together, and the keyboard offers four zones or a per-key editor drawn from its real LED layout. Apply sends the selected device's draft.
- **Battery:** charge, time estimates when available, health and cycles, and only the charge controls your driver exposes.
- **Display:** Native SDR color management on a supported built-in Mutter panel; keeps your monitor setup and is off while HDR is on.
- **System Settings:** installation checks without sudo, device capabilities, connection details, and licenses and credits.

The hardware service keeps running after the window closes, waiting for commands and the Predator button.
It does no dashboard or GPU monitoring, and closing the window does not reset any setting.
Each read of the performance profile or fan modes briefly freezes every CPU on this laptop, so the service reads them only at start, after its own changes, after sleep, and when the kernel reports a profile change; a fan mode set by another tool shows after the next of these.
Saved CPU frequency caps are reapplied at start and after sleep, and put back within ten seconds when another tool, such as tuned, raises them.
A lower cap set by another tool, such as NVIDIA's `nvidia-powerd` moving power to the GPU during games, stays, and the Dashboard marks it as lowered by another tool.
Lighting shown in the app is the last successful command, not a reading from the device.
The service reapplies it at start, after sleep, and when a lighting device reconnects.

## Screenshots and preview

Screenshots are real app renders with labelled sample data, not live measurements.

![Dashboard](docs/screenshots/overview.png)
![Lighting](docs/screenshots/lighting.png)

[CPU frequency](docs/screenshots/cpu.png) · [Battery](docs/screenshots/battery.png) ·
[Display](docs/screenshots/display.png) · [System Settings](docs/screenshots/diagnostics.png) ·
[Per-key editor](docs/screenshots/keyboard.png) · [Credits](docs/screenshots/credits.png)

```sh
./run.sh --preview
./run.sh --screenshots docs/screenshots
```

Preview never connects to the hardware service or the desktop display API.
With dependencies installed, `./run.sh` starts the real app from source without installing it.

## Development and licensing

See [CONTRIBUTING.md](CONTRIBUTING.md), [AGENTS.md](AGENTS.md), and [NATIVE-CONTROLS.md](NATIVE-CONTROLS.md).
`scripts/package.sh` builds one source-complete archive and a checksum.

The app and daemon are GPLv3; the separate kernel module is GPLv2.
[NOTICE.md](NOTICE.md) lists attribution, protocol sources, and runtime dependencies.
Full terms are in [LICENSE](LICENSE) and [LICENSES](LICENSES).
