#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$ROOT/scripts/setup-common.sh"
usage() {
    cat <<'HELP'
Usage: ./setup.sh <command>
  install    Install dependencies and a fresh copy of the complete app.
  uninstall  Remove the app, settings, backups, and lightbar driver.
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
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || { echo 'Linux x86_64 is required.' >&2; exit 1; }
if [[ "$ACTION" == status ]]; then exec "$ROOT/scripts/install-status.sh"; fi
if [[ "$ACTION" == install ]] && installation_exists; then
    printf 'This will completely overwrite your installation. Proceed? [y/n] '
    answer=''
    if ! read -r answer || [[ "$answer" != y && "$answer" != Y ]]; then
        echo 'Installation cancelled. Nothing was changed.'; exit 0
    fi
fi
finish_setup() {
    local result=$?
    trap - EXIT
    "$ROOT/scripts/clean-build.sh"
    exit "$result"
}
trap finish_setup EXIT
if [[ "$ACTION" == uninstall ]]; then "$ROOT/scripts/install.sh" --uninstall; exit; fi
trap 'echo "Installation failed. Run ./setup.sh status for details." >&2' ERR
"$ROOT/scripts/install-dependencies.sh"
# Parse Python sources without generating bytecode or touching hardware.
python3 - "$ROOT" <<'PY'
import ast
import sys
from pathlib import Path
for folder in ('control_center','hardware'):
    for path in (Path(sys.argv[1])/folder).glob('*.py'):
        ast.parse(path.read_text(),filename=str(path))
PY
"$ROOT/scripts/install.sh" --install
