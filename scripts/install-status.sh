#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Same read-only checks used by the desktop interface; no administrator access.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd -- "$SCRIPT_DIR/.."
exec python3 -m control_center.installation
