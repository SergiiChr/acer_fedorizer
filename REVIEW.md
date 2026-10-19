# GTK migration review — 19 October 2026

The migration branch is based on the latest main, including the merged simplified
setup work. The desktop frontend is Python/GTK4/libadwaita; the previous compiled
frontend, project/lock files, bundled fonts/assets, runtime binaries, and obsolete
package-license inventory were removed.

## Implemented

- Native Overview, Performance, Lighting, Battery, Display, and System pages,
  plus a geometry-based per-key editor, preferences rows, color dialogs, charts,
  and a single-instance desktop application.
- Generic `control_center` and `hardware` packages. Service, socket, group,
  launchers, module name, and install/state paths use the current application
  identity. Earlier identifiers survive only in directly used upgrade cleanup
  and its regression tests, and required attribution.
- Bounded, serialized JSON client; worker-thread transport/telemetry with GTK
  updates on the main loop. Polling does not write settings. Closing the window
  stops sampling; GPU monitoring is opt-in and does not query hidden pages.
- Independent lighting drafts, full-map per-key validation, palette-mode color
  restrictions, explicit profile/fan/lighting apply, confirmed cooling state,
  capability-based extras, and partial-failure reporting from the preserved backend.
- Four-command setup, distribution GUI packages, source-only application copy,
  generic kernel module registration, legacy-install removal, full uninstall,
  and cache cleanup. No GUI compilation or external package feed is needed.
- Attribution and dependency notes consolidated into NOTICE.md. Required distinct
  full legal texts remain intact. Unused font/runtime notices were removed along
  with their dependencies and assets.
- A single source-complete release archive, updated CI, and reproducible screenshots
  of actual GTK widgets with clearly labelled preview data.

## Validation and limits

All 60 Python regressions pass and cover hardware behavior, socket framing/reconnect/concurrency,
telemetry parsing, paused GPU behavior, drafts, display-config preservation, and
isolated installer/legacy-upgrade behavior. Real GTK smoke checks exercise page
navigation, draft independence, refresh preservation, palette restrictions, and
per-key selection/painting, and explicit asynchronous Apply without connecting to
hardware. The renamed kernel module also builds against the installed kernel
headers; optional BTF metadata was skipped because vmlinux/pahole is unavailable.
No module was loaded by validation. Screenshots are real
application renders using deterministic preview data, not live measurements.

The live system installation was not replaced and no hardware commands were
exercised. Existing protocol findings in NATIVE-CONTROLS.md remain prior hardware
evidence. Physical per-key/WASD coverage, animation appearance, Secure Boot signing,
and clean-machine distro installation still require hardware/install validation.
Wave parameters can match across devices; phase synchronization is unverified.
Minimum runtime is GTK 4.10 and libadwaita 1.4 (Fedora, Ubuntu 24.04, Debian 13).
