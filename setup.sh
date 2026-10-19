#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Public setup interface: no component or dependency decisions are required.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$ROOT/scripts/setup-common.sh"
usage() {
    cat <<'HELP'
Usage: ./setup.sh <command>
  install    Install all dependencies and a fresh copy of the complete app.
  uninstall  Remove the app, saved settings, backups, and DAMX lightbar driver.
  status     Check installation health without changing anything.
  help       Show these commands.
Run as your desktop user. Setup requests sudo when needed.
HELP
}
[[ $# -le 1 ]] || { usage >&2; exit 2; }
ACTION=${1:-help}
case "$ACTION" in
    help) usage; exit 0 ;;
    install|uninstall|status) ;;
    *) echo "Unknown command: $ACTION" >&2; usage >&2; exit 2 ;;
esac
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || {
    echo 'DAMX requires Linux x86_64.' >&2; exit 1;
}
if [[ "$ACTION" == status ]]; then exec "$ROOT/scripts/install-status.sh"; fi
finish_setup() {
    local result=$?
    trap - EXIT
    # In a source checkout this is disposable build output. In a binary archive
    # it is the distribution payload and must remain usable for reinstalls.
    if [[ -f "$ROOT/DivAcerManagerMax/DivAcerManagerMax.csproj" ]]; then
        rm -rf -- "$ROOT/publish/native" "$ROOT/publish/.previous-build"
    fi
    "$ROOT/scripts/clean-build.sh"
    exit "$result"
}
if [[ "$ACTION" == uninstall ]]; then
    trap finish_setup EXIT
    "$ROOT/scripts/local-setup.sh" --uninstall
    exit
fi
if installation_exists; then
    printf 'This will completely overwrite your installation. Proceed? [y/n] '
    answer=''
    if ! read -r answer || [[ "$answer" != y && "$answer" != Y ]]; then
        echo 'Installation cancelled. Nothing was changed.'
        exit 0
    fi
fi
trap finish_setup EXIT
trap 'echo "Installation failed. Run ./setup.sh status for details, then rerun ./setup.sh install after resolving the reported error." >&2' ERR
"$ROOT/scripts/install-dependencies.sh"
# Source checkouts always rebuild; binary archives contain no project file.
if [[ -f "$ROOT/DivAcerManagerMax/DivAcerManagerMax.csproj" ]]; then
    if [[ $EUID -eq 0 && -n ${SUDO_USER:-} && "$SUDO_USER" != root ]]; then
        sudo -u "$SUDO_USER" -- env DAMX_DOTNET="${DAMX_DOTNET:-dotnet}" "$ROOT/scripts/local-setup.sh" --build
    else
        "$ROOT/scripts/local-setup.sh" --build
    fi
fi
"$ROOT/scripts/local-setup.sh" --install
