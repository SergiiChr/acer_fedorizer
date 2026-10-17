#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Native PH16-72 edition; modified October 2026. Attribution and terms: NOTICE.md.
# Package the native checkout with its tested self-contained GUI.
set -euo pipefail
REPO_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
OUTPUT=${1:-$REPO_DIR/publish/damx-native.tar.gz}
[[ -x "$REPO_DIR/publish/native/DivAcerManagerMax" ]] || {
    echo 'Build first: scripts/local-setup.sh --build'; exit 1;
}
mkdir -p -- "$(dirname -- "$OUTPUT")"
tar --exclude='__pycache__' --exclude='*.pyc' --exclude='*.o' --exclude='*.ko' --exclude='*.cmd' --exclude='*.mod*' --exclude='Module.symvers' --exclude='modules.order' -czf "$OUTPUT" -C "$REPO_DIR" \
    publish/native DAMM-Daemon native-lightbar \
    setup.sh scripts/local-setup.sh scripts/install-lightbar.sh scripts/native-selftest.py \
    DivAcerManagerMax/icon.png AGENTS.md CONTRIBUTING.md REVIEW.md README.md FAQ.md Compatibility.md NATIVE-CONTROLS.md LICENSE NOTICE.md THIRD-PARTY-NOTICES.md LICENSES
SOURCE_OUTPUT="${OUTPUT%.tar.gz}-source.tar.gz"
tar --exclude='bin' --exclude='obj' --exclude='__pycache__' --exclude='*.pyc' --exclude='*.o' --exclude='*.ko' --exclude='*.cmd' --exclude='*.mod*' --exclude='Module.symvers' --exclude='modules.order' -czf "$SOURCE_OUTPUT" -C "$REPO_DIR" \
    DivAcerManagerMax DivAcerManagerMax.sln global.json DAMM-Daemon native-lightbar scripts tests \
    setup.sh AGENTS.md CONTRIBUTING.md REVIEW.md .github .gitignore README.md FAQ.md Compatibility.md NATIVE-CONTROLS.md LICENSE NOTICE.md THIRD-PARTY-NOTICES.md LICENSES
(
    cd -- "$(dirname -- "$OUTPUT")"
    sha256sum -- "$(basename -- "$OUTPUT")" "$(basename -- "$SOURCE_OUTPUT")"
) > "$OUTPUT.sha256"
printf 'Created %s\n' "$OUTPUT"
