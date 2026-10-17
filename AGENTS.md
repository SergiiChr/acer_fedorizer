# Agent instructions

## Scope and source map

DAMX is a Linux x86_64 Avalonia/.NET 8 desktop app for Acer Predator PH16-72.
Read README.md for installation, CONTRIBUTING.md for development, NOTICE.md
for provenance, and NATIVE-CONTROLS.md before changing hardware protocols.

- `DivAcerManagerMax/`: GUI; `DAMXClient.cs` implements the socket client.
- `DAMM-Daemon/`: standard-library Python daemon; `native_controls.py` handles
  validated commands/sysfs, `acer_hid.py` handles HID, and `predator_button.py`
  listens for the dedicated button. Imports must not access hardware.
- `DivAcerManagerMax/display_config.py`: desktop-session Mutter D-Bus helper;
  PyGObject comes from the OS. Do not run it as root.
- `native-lightbar/`: separate GPLv2 DKMS module, restricted to exact DMI model.
- `setup.sh`: public entry point; `scripts/` contains implementation helpers.
- `tests/`: hardware-independent Python tests and C# console regression tests.
- `LICENSES/`: required redistribution notices, not disposable build output.

## Working rules

Preserve existing uncommitted work. Keep changes scoped; do not replace the
backend or introduce speculative firmware commands. Use capability discovery
and retain the fan failure fallback to automatic cooling. Persist lighting only
after successful commands; distinguish firmware acceptance from visible results.
Keep GPU monitoring opt-in and desktop/session actions unprivileged.

Ordinary review and tests must not install software, restart system services,
load kernel modules, write hardware, or use `native-selftest.py --exercise`.
Do those only when requested for a hardware/install task. Read-only inspection
can still send HID queries; use the mocked test suite for offline validation.

Do not hand-edit packages.lock.json or generated THIRD-PARTY-NOTICES.md. For
intentional dependency changes, restore, review the lock diff, regenerate the
notices via the build, and retain exact upstream terms and attribution. Never
include proprietary reference software/extracts in releases. Keep GPLv2 kernel
code separate from GPLv3 application code.

## Validation

Run from the repository root:

```sh
bash -n setup.sh scripts/*.sh
python3 -m unittest discover -s tests -v
dotnet run --project tests/client-tests/ClientTests.csproj -c Release
./setup.sh --build --no-deps
scripts/package.sh
```

Set `DAMX_DOTNET=/absolute/path/to/dotnet` when needed; invoke that same executable
for C# tests. Build/package need a restored SDK/NuGet cache or network access.
Do not infer physical compatibility from mock tests. Report unavailable checks
and pre-existing compiler warnings accurately. Do not add tests that merely
repeat implementation; cover meaningful failure and state-transition behavior.
