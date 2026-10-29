#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Runs every offline check without hardware, services, or package installs.
# GUI checks need a display; CI runs this under xvfb-run and dbus-run-session.
# Uses ruff and mypy from .venv when scripts/check-tools.sh has created it.
# Set SCREENSHOTS=docs/screenshots to refresh the README images that packaging includes.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export GSK_RENDERER=cairo PATH="$PWD/.venv/bin:$PATH"

bash -n setup.sh run.sh scripts/*.sh
ruff check .
mypy
/usr/bin/python3 -m unittest discover -s tests -v
/usr/bin/python3 scripts/ui-smoke.py
./run.sh --screenshots "${SCREENSHOTS:-publish/screenshots}"
scripts/package.sh
