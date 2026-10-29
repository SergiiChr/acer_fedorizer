#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# The distributable is source-complete; there is no compiled GUI payload.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
OUTPUT=${1:-$ROOT/publish/acer-fedorizer.tar.gz}
mkdir -p -- "$(dirname -- "$OUTPUT")"
"$ROOT/scripts/clean-build.sh"
tar --exclude='__pycache__' --exclude='*.pyc' --exclude='*.o' --exclude='*.ko' \
    --exclude='*.cmd' --exclude='*.mod*' --exclude='Module.symvers' --exclude='modules.order' \
    -czf "$OUTPUT" -C "$ROOT" \
    control_center hardware assets native-lightbar scripts tests docs \
    setup.sh run.sh AGENTS.md CODING.md CONTRIBUTING.md README.md FAQ.md Compatibility.md \
    NATIVE-CONTROLS.md LICENSE NOTICE.md LICENSES .github .gitignore ruff.toml mypy.ini
(cd -- "$(dirname -- "$OUTPUT")"; sha256sum -- "$(basename -- "$OUTPUT")") > "$OUTPUT.sha256"
printf 'Created source-complete package: %s\n' "$OUTPUT"
