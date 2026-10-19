# Agent instructions

Acer Fedorizer is a native Python/GTK4/libadwaita app for Predator PH16-72.
Read README.md, CONTRIBUTING.md, NOTICE.md, and NATIVE-CONTROLS.md before work.

## Source map

- `control_center/`: unprivileged GTK UI, socket client, models, telemetry, display bridge.
- `hardware/`: Python standard-library daemon and validated stock sysfs/direct HID controls.
- `native-lightbar/`: separate GPLv2, exact-DMI kernel bridge.
- `setup.sh`: four public commands. `scripts/` contains internal lifecycle helpers.
- `scripts/legacy-install.sh`: old identifiers used only for upgrade/uninstall cleanup.
- `tests/`: hardware-independent regressions and fake system tools.
- `NOTICE.md` and `LICENSES/`: required attribution and full component terms.

## Working rules

Preserve uncommitted work. Keep the backend and verified protocol semantics;
do not add guessed firmware commands. Retain automatic-fan recovery on failure
and persist lighting only after successful commands. Distinguish acceptance from
physical results. Keep GPU monitoring opt-in and session/GUI actions unprivileged.
Preserve established feature/profile names and mappings; use neutral functional UI text.
Performance profiles and fan modes use large icon tiles. Render credits programmatically
from `NOTICE.md`; do not add duplicate credits content or generated HTML files.
No import-time hardware access. Never call GTK from a worker thread. Reading or
refreshing state must not write controls or discard per-device editing drafts.

Ordinary tests/reviews must not install packages, restart services, load modules,
or exercise hardware. Use fake fixtures, `--preview`, and `scripts/ui-smoke.py`.
Preview must not access the hardware service or Mutter. Actual HID inspection is
not an offline test. Do not distribute proprietary reference software or extracts.
Names from earlier projects belong in attribution or directly used upgrade code,
not the new UI. Preserve original licensing when renaming modules. The module
must remain separate from the GPLv3 application and scoped to PH16-72.

## Administrator access

Use sudo/pkexec only when a task actually requires administrator access. Before
requesting it, show each exact command on its own line with a plain-language
explanation. Check whether ordinary user permissions are sufficient first.
Status checks, tests, previews, and launching the GUI run as the desktop user.
Do not leave pending privileged operations running after work is stopped.

## Validation

```sh
bash -n setup.sh run.sh scripts/*.sh
python3 -m unittest discover -s tests -v
GSK_RENDERER=cairo python3 scripts/ui-smoke.py
GSK_RENDERER=cairo ./run.sh --screenshots docs/screenshots
scripts/package.sh
```

GUI checks need GTK 4.10+, libadwaita 1.4+, PyGObject/Pycairo, and a display.
Use Xvfb/private D-Bus in CI. There is no frontend build step. Report unavailable
checks and hardware limits honestly; mock tests do not establish compatibility.
