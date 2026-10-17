#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Native PH16-72 edition; modified October 2026. Attribution and terms: NOTICE.md.
# Optional bridge; DKMS rebuilds it when the kernel changes.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ $EUID -ne 0 ]]; then exec sudo -- "$0"; fi
[[ $(cat /sys/class/dmi/id/product_name) == 'Predator PH16-72' ]] || {
    echo 'This bridge supports only Predator PH16-72.'; exit 1;
}
[[ -d /lib/modules/$(uname -r)/build ]] || { echo 'Matching kernel development headers are missing.'; exit 1; }
command -v dkms >/dev/null || { echo 'Install DKMS and kernel development headers first.'; exit 1; }
if dkms status -m damx-lightbar -v 0.1.0 | grep -q .; then
    dkms remove -m damx-lightbar -v 0.1.0 --all
fi
# Rebuild even when the version is unchanged: the checkout may contain fixes.
if dkms status -m damx-lightbar -v 0.2.0 | grep -q .; then
    dkms remove -m damx-lightbar -v 0.2.0 --all
fi
install -d /usr/src/damx-lightbar-0.2.0
install -m 644 "$SCRIPT_DIR/../native-lightbar/"{damx_lightbar.c,Makefile,dkms.conf} /usr/src/damx-lightbar-0.2.0/
install -m 644 "$SCRIPT_DIR/../LICENSES/GPL-2.0.txt" /usr/src/damx-lightbar-0.2.0/LICENSE
if ! dkms status -m damx-lightbar -v 0.2.0 | grep -q .; then
    dkms add -m damx-lightbar -v 0.2.0
fi
dkms install -m damx-lightbar -v 0.2.0 -k "$(uname -r)"
if [[ -d /sys/module/damx_lightbar ]]; then modprobe -r damx_lightbar; fi
modprobe damx_lightbar
if systemctl is-active --quiet damx-daemon.service; then systemctl restart damx-daemon.service; fi
echo 'Optional rear lightbar bridge installed.'
