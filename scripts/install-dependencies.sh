#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/setup-common.sh"
as_root() {
    if [[ $EUID -eq 0 ]]; then "$@"; else sudo -- "$@"; fi
}
. /etc/os-release
case "$ID" in
    fedora)
        packages=(python3 python3-gobject python3-cairo gtk4 libadwaita kmod shadow-utils procps-ng)
        if lightbar_supported; then packages+=(dkms gcc make "kernel-devel-$(uname -r)"); fi
        as_root dnf install -y "${packages[@]}"
        ;;
    debian|ubuntu)
        case "$ID:$VERSION_ID" in
            debian:13|ubuntu:24.04) ;;
            *) echo 'GTK setup supports Debian 13 or Ubuntu 24.04; libadwaita 1.4+ is required.' >&2; exit 1 ;;
        esac
        packages=(python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 kmod passwd procps)
        if lightbar_supported; then packages+=(dkms build-essential "linux-headers-$(uname -r)"); fi
        as_root apt-get update
        as_root apt-get install -y "${packages[@]}"
        ;;
    *) echo "Automatic setup is unsupported on $ID. See README.md." >&2; exit 1 ;;
esac
