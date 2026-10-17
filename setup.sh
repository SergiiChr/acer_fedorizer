#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# One entry point for dependencies, source builds, installation, and removal.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
MODE=--install
MODE_SET=false
LIGHTBAR=auto
DEPS=true
for arg in "$@"; do
    case "$arg" in
        --install|--build|--uninstall)
            if [[ "$MODE_SET" == true && "$MODE" != "$arg" ]]; then
                echo 'Choose only one of --install, --build, or --uninstall.' >&2; exit 2
            fi
            MODE=$arg
            MODE_SET=true ;;

        --with-lightbar) LIGHTBAR=yes ;;
        --without-lightbar) LIGHTBAR=no ;;
        --no-deps) DEPS=false ;;
        --help|-h)
            cat <<'HELP'
Usage: ./setup.sh [--install|--build|--uninstall] [options]
  --install          Install dependencies, build if needed, and install (default)
  --build            Install build dependencies and publish without installing
  --uninstall        Remove service and launcher; retain app/state for recovery
  --with-lightbar    Include PH16-72 DKMS rear lightbar bridge
  --without-lightbar Skip the bridge (otherwise automatic on PH16-72)
  --no-deps          Use preinstalled dependencies; no package-manager calls
Run as your desktop user; sudo is requested for system changes only.
DAMX_DOTNET may select a dotnet executable. Fedora and Debian/Ubuntu supported.
HELP
            exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || {
    echo 'DAMX requires Linux x86_64.' >&2; exit 1;
}
if [[ "$MODE" == --uninstall ]]; then
    "$ROOT/scripts/local-setup.sh" --uninstall
    exit
fi
if [[ "$MODE" == --build ]]; then LIGHTBAR=no; fi
if [[ "$LIGHTBAR" == auto ]]; then
    LIGHTBAR=no
    if [[ $(cat /sys/class/dmi/id/product_name 2>/dev/null || true) == 'Predator PH16-72' ]]; then LIGHTBAR=yes; fi
fi
if [[ "$LIGHTBAR" == yes ]]; then
    [[ $(cat /sys/class/dmi/id/product_name 2>/dev/null || true) == 'Predator PH16-72' ]] || {
        echo 'The lightbar bridge supports only Predator PH16-72.' >&2; exit 1;
    }
fi
NEED_BUILD=false
if [[ "$MODE" == --build || ! -x "$ROOT/publish/native/DivAcerManagerMax" ]]; then NEED_BUILD=true; fi
has_sdk() {
    "${DAMX_DOTNET:-dotnet}" --list-sdks 2>/dev/null | grep -q '^8\.'
}
as_root() {
    if [[ $EUID -eq 0 ]]; then "$@"; else sudo -- "$@"; fi
}
if [[ "$DEPS" == true ]]; then
    # Use distribution packages; never download and execute a remote installer.
    . /etc/os-release
    case "$ID" in
        fedora)
            packages=(python3 python3-gobject fontconfig freetype libX11 libICE libSM libXi libXcursor libXrandr libXrender libglvnd-glx ca-certificates libicu openssl-libs zlib krb5-libs libstdc++ tzdata)
            if [[ "$MODE" == --install ]]; then packages+=(kmod shadow-utils); fi
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
                *) echo 'Automatic apt dependencies support Debian 12/13 and Ubuntu 24.04. Use --no-deps with preinstalled prerequisites.' >&2; exit 1 ;;
            esac
            if [[ "$MODE" == --install ]]; then packages+=(kmod passwd); fi
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
        *) echo "Automatic dependencies are unsupported on $ID. Install prerequisites from README.md and use --no-deps." >&2; exit 1 ;;
    esac
fi
if [[ "$NEED_BUILD" == true ]]; then
    has_sdk || {
        echo 'A .NET 8 SDK is required. Install it from your distribution or set DAMX_DOTNET.' >&2; exit 1;
    }
    "$ROOT/scripts/local-setup.sh" --build
fi
if [[ "$MODE" == --build ]]; then exit; fi
if [[ "$LIGHTBAR" == yes ]]; then
    [[ -d /lib/modules/$(uname -r)/build ]] || { echo 'Matching kernel development headers are missing.' >&2; exit 1; }
    as_root "$ROOT/scripts/install-lightbar.sh"
fi
"$ROOT/scripts/local-setup.sh" --install
