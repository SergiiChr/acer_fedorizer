#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Internal helper: always install all dependencies required by this machine.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
source "$SCRIPT_DIR/setup-common.sh"
NEED_BUILD=false
[[ ! -f "$ROOT/DivAcerManagerMax/DivAcerManagerMax.csproj" ]] || NEED_BUILD=true
LIGHTBAR=no
if lightbar_supported; then LIGHTBAR=yes; fi
has_sdk() {
    "${DAMX_DOTNET:-dotnet}" --list-sdks 2>/dev/null | grep '^8\.' >/dev/null
}
as_root() {
    if [[ $EUID -eq 0 ]]; then "$@"; else sudo -- "$@"; fi
}
. /etc/os-release
case "$ID" in
    fedora)
        packages=(python3 python3-gobject fontconfig freetype libX11 libICE libSM libXi libXcursor libXrandr libXrender libglvnd-glx ca-certificates libicu openssl-libs zlib krb5-libs libstdc++ tzdata)
        packages+=(kmod shadow-utils procps-ng)
        if [[ "$NEED_BUILD" == true ]] && ! has_sdk; then packages+=(dotnet-sdk-8.0); fi
        if [[ "$LIGHTBAR" == yes ]]; then packages+=(dkms gcc make "kernel-devel-$(uname -r)"); fi
        as_root dnf install -y "${packages[@]}"
        ;;
    debian|ubuntu)
        packages=(python3 python3-gi libfontconfig1 libfreetype6 libx11-6 libice6 libsm6 libxi6 libxcursor1 libxrandr2 libxrender1 libgl1 ca-certificates libc6 libgcc-s1 libgssapi-krb5-2 libstdc++6 tzdata zlib1g)
        case "$ID:$VERSION_ID" in
            debian:12) packages+=(libicu72 libssl3) ;;
            debian:13) packages+=(libicu76 libssl3t64) ;;
            ubuntu:24.04) packages+=(libicu74 libssl3t64) ;;
            *) echo 'Automatic apt dependencies support Debian 12/13 and Ubuntu 24.04. See README.md for supported distributions.' >&2; exit 1 ;;
        esac
        packages+=(kmod passwd procps)
        if [[ "$ID" == debian && "$NEED_BUILD" == true ]] && ! has_sdk; then
            as_root apt-get update
            as_root apt-get install -y ca-certificates wget
            feed_stage=$(mktemp -d)
            trap 'rm -rf -- "$feed_stage"' EXIT
            wget -q "https://packages.microsoft.com/config/debian/$VERSION_ID/packages-microsoft-prod.deb" -O "$feed_stage/feed.deb"
            as_root dpkg -i "$feed_stage/feed.deb"
            rm -rf -- "$feed_stage"
            trap - EXIT
        fi
        if [[ "$NEED_BUILD" == true ]] && ! has_sdk; then packages+=(dotnet-sdk-8.0); fi
        if [[ "$LIGHTBAR" == yes ]]; then packages+=(dkms build-essential "linux-headers-$(uname -r)"); fi
        as_root apt-get update
        as_root apt-get install -y "${packages[@]}"
        ;;
    *) echo "Automatic dependencies are unsupported on $ID. See README.md for supported distributions." >&2; exit 1 ;;
esac
