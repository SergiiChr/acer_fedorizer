# Development

Use Python 3 and the .NET 8 SDK on Linux x86_64. The Python daemon has no pip
dependencies. Optional GNOME display integration uses distribution PyGObject.
The public setup commands are `install`, `uninstall`, `status`, and `help`.
For development/CI, use `scripts/local-setup.sh --build` with prerequisites
already installed. This internal build helper does not install or remove the app.
`DAMX_DOTNET` selects an SDK executable outside PATH. Build as your regular user. The build helper automatically removes intermediate
`bin`/`obj` directories and caches after success or failure, retaining
`publish/native` for packaging. Public setup removes that generated GUI after
source installation; binary distributions retain their reusable GUI payload.

## Checks

```sh
bash -n setup.sh scripts/*.sh
python3 -m unittest discover -s tests -v
dotnet run --project tests/client-tests/ClientTests.csproj -c Release
scripts/local-setup.sh --build
scripts/package.sh
```

Python tests use temporary sysfs trees, fake HID devices, and local sockets.
C# tests cover client framing/concurrency, lighting drafts, instance coordination,
and NVIDIA telemetry parsing. They do not need root or an Acer laptop. CI runs
the same checks; Python's standard unittest runner needs no test dependencies.

## Architecture and protocol

The GUI sends newline-delimited JSON to `/run/DAMX.sock`. Requests are objects
with a string `command` and object `params`. Responses contain `success` and
`data` or `error`. The daemon limits requests to 65,536 bytes including newline,
serializes hardware commands, and restricts the socket to its desktop owner and
`damx` group. Group membership grants hardware-control access.

Read-only examples: `ping`, `get_version`, `get_all_settings`, and
`get_supported_features`. `get_keyboard_layout` queries HID geometry.
`native_controls.py:command` is the dispatch reference; `DAMXClient.cs` defines
client models. Hardware writes require backend validation even if the UI has
already validated input. Tests should exercise invalid input, unavailable
capabilities, partial writes, and persistence failures.

The display helper uses the logged-in user's session bus independently of the
root daemon. The optional lightbar module exposes constrained sysfs commands;
it must remain DMI-restricted. See NATIVE-CONTROLS.md for evidence and limits.

## Dependencies and distribution

NuGet versions are recorded in `DivAcerManagerMax/packages.lock.json`. Restore
with `dotnet restore DivAcerManagerMax/DivAcerManagerMax.csproj --locked-mode`
when checking dependency reproducibility. For upgrades, intentionally restore
without locked mode and review both dependency and license changes.

Build regenerates THIRD-PARTY-NOTICES.md using `scripts/collect-licenses.py`
and copies notices into the staged self-contained application before replacing
the previous build. Shared upstream license texts are curated in LICENSES.

`scripts/package.sh` creates binary and matching source archives plus SHA-256
checksums. The source includes tests, build scripts, agent guidance, and CI.
Extract binary and source archives into separate directories. Keep all license
texts, source headers, and NOTICE.md. Generated builds, caches, IDE state, and
proprietary references do not belong in source control or source archives.

For bug reports include model, BIOS, kernel, desktop, package versions, relevant
service logs, and whether a result was visually confirmed. Remove personal
information from logs. Attribute borrowed work as described in NOTICE.md.
