# Licenses, attribution, and distribution

This native PH16-72 edition is derived from Div Acer Manager Max. The current Python application and daemon remain under GNU GPL version 3; LICENSE contains the full terms. New application changes are GPL-3.0-only. Existing upstream notices and third-party licenses remain in force. Renaming or moving to a new repository does not remove these obligations.

## Original projects and protocol work

- **Div Acer Manager Max — PXDiv and its contributors.** https://github.com/PXDiv/Div-Acer-Manager-Max. Original historical GUI/dashboard and daemon foundation; GPL-3.0. This edition changes the control backend, lighting UI, telemetry, packaging, and installation. Changes were made in October 2026. The full GPL text is retained in LICENSE.
- **Linuwu-Sense — 0x7375646F and contributors; Div-Linuwu-Sense — PXDiv and contributors.** https://github.com/0x7375646F/Linuwu-Sense and https://github.com/PXDiv/Div-Linuwu-Sense. Historical hardware-control dependency and reference, credited even though its source and custom-driver dependency have been removed from this native package. The upstream repository distributes GPL-3.0 text; its Acer WMI source carries GPL-2.0-or-later notices crediting Carlos Corbacho and E.M. Smith. Those notices must be preserved if that source is reintroduced. This package does not redistribute that driver source.
- **Acer Predator Helios RGB protocol documentation — TensorRaya and credited contributors (including roosterduck and fuho).** https://github.com/TensorRaya/acer-predator-helios-rgb/blob/main/protocol/PROTOCOL.md. Documentation licensed CC BY 4.0: https://creativecommons.org/licenses/by/4.0/. Consulted as a protocol cross-check; PH16-72 corrections and findings are described in NATIVE-CONTROLS.md. Attribution is retained; no endorsement is implied. The reference credits roosterduck's PH16-71 USBPcap captures and fuho's analysis in [OpenRGB issue 4158](https://gitlab.com/CalcProgrammer1/OpenRGB/-/work_items/4158), [Exyons/Venator](https://github.com/Exyons/Venator), and [lau-bin/acer_brightness](https://github.com/lau-bin/acer_brightness). These are upstream research provenance, not additional bundled dependencies. The upstream implementation is GPL-2.0-only and is not copied into or relicensed as this GPLv3 application. The LampArray implementation here was retained from the existing local hardware-control source and extended using the USB HID specification.
- **Acer PredatorSense 5.0.1463 — Acer / respective rights holders.** Examined for interoperability and model-specific command behavior. Proprietary executables, DLLs, extracted application code, OEM configuration, and proprietary artwork from that download are not included in this distribution. Protocol facts are documented separately.

## Current distribution and consolidated notices

The GTK4/libadwaita interface replaces the prior C# frontend in October 2026.
The new interface, telemetry/client implementation, CSS, and SVG icon are project
source. No earlier GUI binaries, fonts, branding assets, NuGet libraries, or
language-runtime bundles are shipped. Their unused distribution notices have
been removed; required historical application/protocol attribution remains above.

- Application and daemon: GPL-3.0-only for new changes; full text in `LICENSE`.
- `native-lightbar/laptop_lightbar.c`: separate GPL-2.0-only module; full text in
  `LICENSES/GPL-2.0.txt`. It communicates through sysfs and is not linked into
  the GPLv3 application. Its C/build/DKMS source accompanies every release.
- Referenced protocol documentation: CC BY 4.0; full legal text retained in
  `LICENSES/CC-BY-4.0.html`. PH16-72 corrections are documented in NATIVE-CONTROLS.md.

## System runtime libraries

The following libraries are loaded from distribution packages, not copied or
bundled into our archive. Their own notices and licenses remain with those
packages; this project does not relicense them.

| Component | License / official project |
| --- | --- |
| GTK4 and GLib/GIO | GNU LGPL 2.1 or later; https://www.gtk.org/ |
| libadwaita | GNU LGPL 2.1 or later; https://gitlab.gnome.org/GNOME/libadwaita |
| PyGObject | GNU LGPL 2.1 or later; https://pygobject.gnome.org/ |
| Pycairo | LGPL 2.1 or MPL 1.1; https://pycairo.readthedocs.io/ |
| Cairo | LGPL 2.1 or MPL 1.1; https://www.cairographics.org/ |
| Python | Python Software Foundation License; https://docs.python.org/3/license.html |

The interface uses the desktop's installed fonts and symbolic icons. No font or
third-party icon binary is included. The app icon in `assets/` is project source.
NVIDIA's optional telemetry utility and Mutter's desktop D-Bus service are
external system components, not bundled dependencies.

## Distribution

Keep `LICENSE`, `NOTICE.md`, and the remaining full texts in `LICENSES/` with all
source/attribution headers. `scripts/package.sh` creates a source-complete archive:
the app, backend, separate module sources, scripts, tests, and documentation are
all included. No proprietary Acer reference files or extracted code are included.
Credits are accessible inside the app from System or the application menu.
Old installation identifiers in `scripts/legacy-install.sh` exist solely to
remove previous installs and are not the current app or protocol names.
