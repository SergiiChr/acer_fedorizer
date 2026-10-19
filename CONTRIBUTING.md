# Development

Use system Python 3, PyGObject/Pycairo, GTK 4.10+, and libadwaita 1.4+.
No pip packages or frontend compilation are required. `./run.sh` launches the
app; `./run.sh --preview` uses labelled deterministic data and no hardware/session
connections. `python3 -m hardware.daemon --inspect` is a live read-only diagnostic,
not an offline test. Do not use diagnostic exercise mode for routine checks.

## Source map

- `control_center/app.py`: libadwaita windows and async actions; no root operations.
- `control_center/widgets.py`: mode tiles, charts, and geometry-based keyboard preview.
- `control_center/markdown_view.py`: escaped Markdown rendering for the single-source `NOTICE.md` credits.
- `control_center/client.py`: bounded, serialized JSON socket client.
- `control_center/models.py`: independent lighting drafts and color validation.
- `control_center/telemetry.py`: read-only sysfs/proc sampling; NVIDIA opt-in only.
- `control_center/display.py`: unprivileged Mutter session-bus bridge.
- `control_center/preview.py`: isolated preview data for screenshots and UI tests.
- `hardware/`: preserved sysfs/HID controls, socket daemon, dedicated-button listener.
- `native-lightbar/`: separate, strictly model-scoped GPLv2 kernel module.
- `scripts/legacy-install.sh`: names retained solely to remove earlier installations.

The app uses `/run/acer-fedorizer.sock` and `/var/lib/acer-fedorizer/lighting.json`.
The root service is `fedorizer-daemon.service`, socket group `fedorizer`, and app
files live under `/opt/acer-fedorizer`. Requests contain `command` and `params`;
responses contain `success` plus `data` or `error`. Request limit is 65,536 bytes
including newline; client responses are bounded at 262,144 bytes. The backend
validates all writes independently of the GUI and serializes hardware access.

## Checks

```sh
bash -n setup.sh run.sh scripts/*.sh
python3 -m unittest discover -s tests -v
GSK_RENDERER=cairo python3 scripts/ui-smoke.py
GSK_RENDERER=cairo ./run.sh --screenshots docs/screenshots
scripts/package.sh
```

UI checks require a graphical display; CI uses Xvfb and a private D-Bus session.
Tests use temporary sysfs trees, fake system/package commands, and local sockets.
They do not install the app or change firmware. UI smoke tests check real widget
navigation, profile-name/hardware mappings, single-selection mode tiles, fan-slider sensitivity, draft independence, refresh preservation, palette restrictions, and
no startup writes, and rendered credits/links. Preview screenshots are actual GTK renders, visibly labelled.

No polling may overwrite editing drafts or apply a setting automatically. Worker
threads must not touch GTK. Stop timers on window closure, keep GPU sampling
opt-in and off hidden pages, and never give the GUI elevated credentials.
Hardware command acceptance is not visual verification of a lighting effect.

## Packaging and notices

`scripts/package.sh` includes all application and corresponding kernel-module
source, scripts, tests, docs, and license terms in one archive. Release output is
ignored under `publish/`. Setup/package cleanup removes Python caches and local
kernel build output, retaining source and required notices. No SDK/runtime build
cache is part of the application. Update NOTICE.md for borrowed code/assets and
system dependencies; preserve upstream authorship even when names are removed
from live module identifiers. Keep full license texts intact.
