# Agent instructions

Acer Fedorizer is a native Python/GTK4/libadwaita control center for the Acer Predator PH16-72.
This file is the single source for working rules; other docs link here instead of repeating them.

## Source map

- `control_center/`: unprivileged GTK app.
  - `app.py`: windows and async actions.
  - `widgets.py`: mode tiles, charts, keyboard preview.
  - `keyboard.py`: keycap geometry from the reported LED layout.
  - `client.py`: bounded, serialized JSON socket client.
  - `models.py`: typed settings parsed once from each daemon reply, per-device lighting drafts, and color validation.
  - `telemetry.py`: read-only sysfs/proc sampling; NVIDIA only when enabled.
  - `display.py`: Mutter session-bus bridge.
  - `installation.py`: read-only install checks shared by the GUI and `setup.sh status`.
  - `markdown_view.py`: renders credits from `NOTICE.md`.
  - `services.py`: the window's data sources; live ones reach the daemon and session, `preview.py` supplies the preview ones.
  - `preview.py`: fake data for `--preview`, screenshots, and UI tests.
  - `screenshots.py`: renders the README screenshots from preview data.
- `hardware/`: root daemon using only the Python standard library; stock sysfs and direct HID controls.
- `native-lightbar/`: separate GPLv2 kernel module, limited to the PH16-72 DMI.
- `setup.sh`: the four public commands; `scripts/` holds internal install, package, and check helpers.
- `scripts/legacy-install.sh`: old names, used only to remove earlier installations.
- `tests/`: hardware-free regressions with fake sysfs trees and fake system tools.
- `NOTICE.md`, `LICENSE`, `LICENSES/`: attribution and full license texts.

## Read before you touch

- `hardware/` or `native-lightbar/`: [NATIVE-CONTROLS.md](NATIVE-CONTROLS.md).
- Install, package, or socket code: [CONTRIBUTING.md](CONTRIBUTING.md).
- Any code: [CODING.md](CODING.md).
- New dependency, borrowed code, or renamed module: [NOTICE.md](NOTICE.md).
- User-visible behavior: [README.md](README.md) and [FAQ.md](FAQ.md), and update them.

## Rules

- Never discard uncommitted work, yours or the user's.

Hardware:

- Use only commands verified in NATIVE-CONTROLS.md; never add guessed firmware commands.
- A new hardware feature stays a proposal until its Linux path is verified.
- On any fan write failure or service stop, return fans to automatic.
- Save lighting state only after the command succeeds.
- A command the device accepted is not proof of a visible result; say which one you have.

App:

- Reading or refreshing state must never write controls or reset a device's unsaved draft.
- GPU monitoring stays off until the user turns it on, and pauses on hidden pages and minimized windows.
- The GUI and session actions run as the desktop user; only the daemon is root.
- Keep existing feature and profile names and their hardware mappings.
- UI text describes the function plainly, without brand or marketing names.
- Performance profiles and fan modes use large icon tiles.
- Credits are rendered from `NOTICE.md`; do not copy credits elsewhere or generate HTML.

Licensing:

- Names from earlier projects belong only in attribution and `scripts/legacy-install.sh`.
- Keep original license headers when renaming or moving modules.
- The kernel module stays separate from the GPLv3 app and limited to PH16-72.
- Never commit proprietary reference software or anything extracted from it.

Docs:

- Describe current behavior only; history belongs in git.
- One sentence per line; keep all sentences of a list item on the item's line.
- Avoid numbers that go stale, such as test counts.

## Tests and reviews

Never install packages, restart services, load modules, or touch hardware during tests or reviews.
Use fake fixtures, `./run.sh --preview`, and `scripts/ui-smoke.py`.
Preview never contacts the hardware service or Mutter.
Checks write only `publish/` and the git-ignored `.venv/`, `.mypy_cache/`, and `.ruff_cache/`.
`python3 -m hardware.daemon --inspect` reads live HID devices, so it is not an offline test.

```sh
scripts/check.sh
```

It runs shell syntax checks, ruff, mypy, unit tests, the GTK smoke test, preview screenshots, and packaging.
Run `scripts/check-tools.sh` once to install the pinned ruff and mypy into `.venv`; it is a development setup step, not part of tests.
Screenshots go to `publish/screenshots` so local runs leave tracked files alone; set `SCREENSHOTS=docs/screenshots` to update the README images, as CI does before packaging.

GUI checks need GTK 4.10+, libadwaita 1.4+, PyGObject/Pycairo, and a display; CI uses Xvfb and a private D-Bus session.
Report checks you could not run.
Passing fake-hardware tests does not prove the app works on real hardware.

## Administrator access

Use sudo or pkexec only when the task truly needs it, after checking that user permissions are not enough.
Before asking, show each exact command on its own line with a plain explanation.
Status checks, tests, previews, and the GUI run as the desktop user.
Do not leave privileged operations running after work stops.
