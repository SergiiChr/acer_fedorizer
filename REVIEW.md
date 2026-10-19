# Application review — 19 October 2026

Scope: current native PH16-72 source, installer/build flow, release contents,
agent guidance, and attribution. Existing uncommitted native implementation
changes were preserved. Hardware observations in NATIVE-CONTROLS.md are prior
observations, not tests performed by this review.

## Automatic build cleanup

Setup and build helpers now remove .NET compiler intermediates, Python caches,
and local kernel-module build leftovers on success and failure. Source setup
also removes its generated published GUI after installation; binary archives
retain their shipped GUI for reuse. Developer builds retain `publish/native`
for packaging. Cancellation and read-only commands do not clean the checkout.
Ignore rules cover release output, SDK caches, test reports, and native/.NET
binaries. License inventories and required redistribution notices remain source.

Validation: 55 Python tests and the C# regression suite passed. A real GUI
publish succeeded, and subsequent checks confirmed intermediate directories were
removed while the published app remained. Existing compiler warnings remain.

## Setup lifecycle update — 19 October 2026

The public interface is now `install`, `uninstall`, `status`, and `help`.
No component, dependency, or build flags are exposed to users. Install always
installs the required OS packages and rebuilds source checkouts. Existing app
files, saved state, backups, or module registrations trigger the explicit
`This will completely overwrite your installation. Proceed? [y/n]` prompt.
Declining or closing input makes no changes. Dependency/build failures occur
before the old application is removed. A complete staged replacement removes
stale daemon and GUI files rather than merging directories.

DKMS detection no longer pipes `status` into `grep -q` under `pipefail`.
Existing registrations are removed directly before add, including other versions.
Broken registration metadata and this module's orphaned kernel files are cleaned
up. Uninstall removes app state, backups, group, integration, module registrations,
module sources, and module files; shared OS packages and source checkout remain.
Status is read-only and checks a bounded daemon ping as well as service/files and
lightbar registration for the running kernel.

Validation: all 51 Python tests pass. The installer tests use a temporary system
tree and fake package/system tools, including a large multi-kernel DKMS response.
Shell syntax and release archive layout/checksums were checked. Live app removal,
service replacement, and module changes were not run. Application C# sources are unchanged by this setup update; build and C# checks
were subsequently repeated for the automatic-cleanup change above.

The earlier application review and its validation history follow below.

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
