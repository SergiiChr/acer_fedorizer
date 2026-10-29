#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Installs the pinned lint and type-check tools into .venv for scripts/check.sh.
# The environment sees system PyGObject and Pycairo, so GTK code type-checks against the installed libraries.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
/usr/bin/python3 -m venv --system-site-packages .venv
.venv/bin/pip install --quiet --disable-pip-version-check ruff==0.16.9 mypy==2.4.1
# The stubs declare a PyGObject dependency that would build from source; the system package provides it.
.venv/bin/pip install --quiet --disable-pip-version-check --no-deps pygobject-stubs==2.20.0
