#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Internal idempotent PH16-72 bridge installation.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ $EUID -ne 0 ]]; then exec sudo -- "$0"; fi
source "$SCRIPT_DIR/setup-common.sh"
lightbar_supported || { echo 'This bridge supports only Predator PH16-72.' >&2; exit 1; }
[[ -d "$MODULES_DIR/$(uname -r)/build" ]] || {
    echo 'Matching kernel headers are missing. Reboot after system updates and rerun ./setup.sh install.' >&2; exit 1;
}
command -v dkms >/dev/null || { echo 'DKMS is missing. Run ./setup.sh install.' >&2; exit 1; }
# Always remove existing versions before adding: no status | grep -q pipelines.
remove_lightbar
install -d "$SOURCE_TREE/damx-lightbar-0.2.0"
install -m 644 "$SCRIPT_DIR/../native-lightbar/"{damx_lightbar.c,Makefile,dkms.conf} "$SOURCE_TREE/damx-lightbar-0.2.0/"
install -m 644 "$SCRIPT_DIR/../LICENSES/GPL-2.0.txt" "$SOURCE_TREE/damx-lightbar-0.2.0/LICENSE"
dkms add -m damx-lightbar -v 0.2.0
dkms install -m damx-lightbar -v 0.2.0 -k "$(uname -r)"
if ! modprobe damx_lightbar; then
    echo 'The lightbar driver was built but could not load. Secure Boot may require enrolling your distribution DKMS signing key. Run ./setup.sh status for details.' >&2
    exit 1
fi
echo 'Rear lightbar driver installed.'
