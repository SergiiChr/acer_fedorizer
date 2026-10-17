# Licenses, attribution, and distribution

This native PH16-72 edition is derived from Div Acer Manager Max. The application and daemon remain under GNU GPL version 3; LICENSE contains the full terms. New application changes are GPL-3.0-only. Existing upstream notices and third-party licenses remain in force. Renaming or moving to a new repository does not remove these obligations.

## Original projects and protocol work

- **Div Acer Manager Max — PXDiv and its contributors.** https://github.com/PXDiv/Div-Acer-Manager-Max. Original GUI, dashboard, assets, and daemon foundation; GPL-3.0. This edition changes the control backend, lighting UI, telemetry, packaging, and installation. Changes were made in October 2026. The full GPL text is retained in LICENSE and LICENSES/GPL-3.0.txt.
- **Linuwu-Sense — 0x7375646F and contributors; Div-Linuwu-Sense — PXDiv and contributors.** https://github.com/0x7375646F/Linuwu-Sense and https://github.com/PXDiv/Div-Linuwu-Sense. Historical hardware-control dependency and reference, credited even though its source and custom-driver dependency have been removed from this native package. The upstream repository distributes GPL-3.0 text; its Acer WMI source carries GPL-2.0-or-later notices crediting Carlos Corbacho and E.M. Smith. Those notices must be preserved if that source is reintroduced. This package does not redistribute that driver source.
- **Acer Predator Helios RGB protocol documentation — TensorRaya and credited contributors (including roosterduck and fuho).** https://github.com/TensorRaya/acer-predator-helios-rgb/blob/main/protocol/PROTOCOL.md. Documentation licensed CC BY 4.0: https://creativecommons.org/licenses/by/4.0/. Consulted as a protocol cross-check; PH16-72 corrections and findings are described in NATIVE-CONTROLS.md. Attribution is retained; no endorsement is implied. The reference credits roosterduck's PH16-71 USBPcap captures and fuho's analysis in [OpenRGB issue 4158](https://gitlab.com/CalcProgrammer1/OpenRGB/-/work_items/4158), [Exyons/Venator](https://github.com/Exyons/Venator), and [lau-bin/acer_brightness](https://github.com/lau-bin/acer_brightness). These are upstream research provenance, not additional bundled dependencies. The upstream implementation is GPL-2.0-only and is not copied into or relicensed as this GPLv3 application. The LampArray implementation here was retained from the existing DAMX local source and extended using the USB HID specification.
- **Acer PredatorSense 5.0.1463 — Acer / respective rights holders.** Examined for interoperability and model-specific command behavior. Proprietary executables, DLLs, extracted application code, OEM configuration, and proprietary artwork from that download are not included in this distribution. Protocol facts are documented separately.

## Optional kernel bridge

native-lightbar/damx_lightbar.c is a separate GPL-2.0-only kernel module. The full GPLv2 text is in LICENSES/GPL-2.0.txt. It communicates with the application through sysfs and is packaged as a separate component; it is not linked into the GPLv3 application. Its source and build/DKMS files are included.

## Fonts, icons, libraries, and runtime

Open Sans, Oxanium, and the Inter font supplied through Avalonia are SIL OFL 1.1 fonts. Their copyright notices and full license texts are in LICENSES/OpenSans-OFL.txt, Oxanium-OFL.txt, and Inter-OFL.txt. Font files are unmodified.

Avalonia, LiveCharts, Material.Icons, MessageBox.Avalonia, DialogHost, MicroCom, Tmds.DBus, SkiaSharp/HarfBuzzSharp wrappers, and .NET runtime components retain their own license notices. See THIRD-PARTY-NOTICES.md and LICENSES. Material Design icon notices and full Apache 2.0 terms are included in addition to the MIT wrapper license. Native Skia/HarfBuzz and .NET third-party notices are retained with the binaries. These components are not relicensed by the top-level GPL notice.

## When distributing the new repository or a binary release

Keep LICENSE, NOTICE.md, THIRD-PARTY-NOTICES.md, LICENSES, and the existing attribution/change notices. Distribute corresponding source for the application, daemon, kernel bridge, and build/install scripts alongside the binary release. scripts/package.sh creates a matching source archive and checksum with each binary package. The self-contained GUI carries a licenses directory so installed users can open these notices.

Do not distribute Acer reference packages or reverse-engineering extracts as part of the open-source release. A new project name and repository can be chosen independently of attribution; attribution links are not update/support destinations.

## Attribution maintenance

When adding borrowed code or assets, record the source URL, author/copyright,
applicable version or revision, license, modifications, and whether the material
is bundled or consulted only. Retain original headers and exact required texts.
The generated NuGet inventory is not a substitute for source/asset provenance.
Protocol reference attribution was cross-checked against the upstream Sources
section on 17 October 2026. Historical driver credits above do not indicate a
runtime or installation dependency.
