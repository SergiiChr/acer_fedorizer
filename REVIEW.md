# Application review — 17 October 2026

Scope: current native PH16-72 source, installer/build flow, release contents,
agent guidance, and attribution. Existing uncommitted native implementation
changes were preserved. Hardware observations in NATIVE-CONTROLS.md are prior
observations, not tests performed by this review.

## Addressed

- Added `setup.sh` as the public installation entry point for OS dependencies,
  source builds, app/service installation, and the model-specific DKMS bridge.
  Binary installs skip the SDK. Build-only and preinstalled-dependency modes
  support development and CI. Invalid options fail before system changes.
- Published and installed GUI directory permissions are explicitly 0755.
  Root-created `mktemp` staging directories otherwise remain 0700 and prevent
  the desktop user from launching the installed GUI.
- Removed the unused Windows application manifest from this Linux target,
  unused startup imports, and 679 MiB of compiler output/Python caches. Verified
  release artifacts remain under ignored `publish/`.
- License collection/copying now finishes in staging before replacing a working
  published GUI. A license failure leaves the previous build usable.
- Removed obsolete third-party driver migration actions from installation.
  No driver is downloaded, unloaded, or configured by those old paths.
  Historical driver attribution remains only in NOTICE.md.
- Added AGENTS.md and CONTRIBUTING.md with architecture, command entry points,
  reproducible validation, privilege boundaries, and licensing rules.
- Replaced the accumulated session narrative with current guidance; retained
  protocol evidence and documented physical verification limits.
- Packaging includes the unified installer in binaries, and SDK selection,
  contributor/agent guidance, tests, and CI in matching source archives.
- Diagnostic exercise state uses a private temporary directory, avoiding a
  predictable root-written path in `/tmp`.
- Reinstalling the same bridge version rebuilds its DKMS source, so edited
  module source is not silently bypassed by an existing installation. The loaded
  module is reloaded after rebuilding.

## Remaining limitations

- Tests and builds cannot establish visible lighting behavior, cooling behavior,
  Secure Boot enrollment, or distribution installation compatibility. A clean
  machine installation and physical validation remain separate checks.
- Lighting state is last successful command state. Cross-device writes can
  partly apply before failure, with no atomic hardware rollback.
- Dashboard telemetry and discovery remain concentrated in the view code.
  A future refactor should isolate sampling/cancellation without changing
  opt-in GPU monitoring or unavailable-value semantics.
- Fan sliders are editing drafts and do not continuously mirror every external
  firmware change. Clearer separate confirmed-state presentation would help.
- Existing GUI nullability warnings require a focused binding/state refactor.
- Support remains PH16-72-specific. Do not enable another model based solely on
  OEM feature flags or firmware accepting a command.

See CONTRIBUTING.md for repeatable checks and NATIVE-CONTROLS.md for the
protocol evidence and earlier hardware observations. License provenance is in
NOTICE.md; exact package versions and notices are in THIRD-PARTY-NOTICES.md.

## Validation performed

- 36 Python regression tests passed, including 10 installer-routing and staging
  tests. Local-socket tests ran outside the filesystem/network sandbox; hardware
  operations remained mocked.
- C# console regression suite passed for socket behavior, instance coordination,
  telemetry parsing, and lighting state.
- `./setup.sh --build --no-deps` published successfully using .NET SDK 8.0.425.
  Existing nullability/platform and Avalonia loader warnings remain.
- Shell syntax checks passed. Binary/source archive contents, license copies,
  executable modes, and SHA-256 checksums were checked.
- System package installation, daemon replacement, kernel-module loading,
  Secure Boot enrollment, and physical controls were not exercised in this pass.
