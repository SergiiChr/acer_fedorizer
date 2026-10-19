#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Remove reproducible checkout intermediates, retaining source and release output.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
rm -rf -- "$ROOT/DivAcerManagerMax/bin" "$ROOT/DivAcerManagerMax/obj" \
    "$ROOT/tests/client-tests/bin" "$ROOT/tests/client-tests/obj" \
    "$ROOT/native-lightbar/.tmp_versions"
for directory in DAMM-Daemon DivAcerManagerMax scripts tests; do
    [[ -d "$ROOT/$directory" ]] || continue
    find "$ROOT/$directory" -type d -name __pycache__ -prune -exec rm -rf -- {} +
done
for artifact in "$ROOT/native-lightbar/"*.o "$ROOT/native-lightbar/"*.ko \
    "$ROOT/native-lightbar/"*.mod "$ROOT/native-lightbar/"*.mod.c \
    "$ROOT/native-lightbar/".*.cmd "$ROOT/native-lightbar/Module.symvers" \
    "$ROOT/native-lightbar/modules.order"; do
    [[ ! -f "$artifact" && ! -L "$artifact" ]] || rm -f -- "$artifact"
done
