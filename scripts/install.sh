#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Internal lifecycle helper. Public interface: setup.sh.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
MODE=${1:---install}
[[ $# -eq 1 && ( "$MODE" == --install || "$MODE" == --uninstall ) ]] || { echo 'Use ./setup.sh install or uninstall.' >&2; exit 2; }
if [[ $EUID -ne 0 ]]; then
    exec sudo -- "$0" "$MODE"
fi
source "$SCRIPT_DIR/setup-common.sh"
if [[ "$MODE" == --uninstall ]]; then
    remove_application
    echo 'Acer Fedorizer completely removed, including settings, backups, and lightbar driver.'
    echo 'Shared system packages and the source folder were retained.'
    exit
fi
TARGET_USER=${SUDO_USER:-${PKEXEC_UID:-}}
if [[ "$TARGET_USER" =~ ^[0-9]+$ ]]; then TARGET_USER=$(getent passwd "$TARGET_USER" | cut -d: -f1); fi
SOCKET_UID=0
if [[ -n "$TARGET_USER" ]]; then SOCKET_UID=$(id -u "$TARGET_USER"); fi
APP_STAGE=$(mktemp -d "${APP_DIR%/*}/.fedorizer-install-XXXXXX")
trap 'rm -rf -- "$APP_STAGE"' EXIT
chmod 755 "$APP_STAGE"
cp -a "$REPO_DIR/control_center" "$REPO_DIR/hardware" "$REPO_DIR/assets" "$REPO_DIR/LICENSES" "$APP_STAGE/"
install -m 644 "$REPO_DIR/LICENSE" "$REPO_DIR/NOTICE.md" "$APP_STAGE/"
find "$APP_STAGE" -type d -name __pycache__ -prune -exec rm -rf -- {} +
modprobe acer_wmi
remove_application
getent group fedorizer >/dev/null || groupadd --system fedorizer
if [[ -n "$TARGET_USER" && "$TARGET_USER" != root ]]; then usermod -aG fedorizer "$TARGET_USER"; fi
mv "$APP_STAGE" "$APP_DIR"
trap - EXIT
install -d "$STATE_DIR" "$UNIT_DIR" "${LAUNCHER%/*}" "${DESKTOP_FILE%/*}" "${ICON_FILE%/*}"
cat > "$UNIT_DIR/fedorizer-daemon.service" <<SERVICE
[Unit]
Description=Acer Fedorizer hardware controls
After=systemd-udevd.service
[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 -m hardware.daemon --socket-owner $SOCKET_UID
Restart=on-failure
RestartSec=3
User=root
Group=fedorizer
UMask=0007
[Install]
WantedBy=multi-user.target
SERVICE
cat > "$LAUNCHER" <<LAUNCH
#!/bin/sh
cd $APP_DIR
exec /usr/bin/python3 -m control_center "\$@"
LAUNCH
chmod 755 "$LAUNCHER"
cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Name=Acer Fedorizer
Comment=Performance, cooling, lighting, and monitoring
Exec=$LAUNCHER
Icon=acer-fedorizer
Terminal=false
Type=Application
Categories=Utility;System;
StartupNotify=true
DESKTOP
install -m 644 "$REPO_DIR/assets/acer-fedorizer.svg" "$ICON_FILE"
if lightbar_supported; then "$SCRIPT_DIR/install-lightbar.sh"; fi
if command -v update-desktop-database >/dev/null; then update-desktop-database "${DESKTOP_FILE%/*}"; fi
systemctl daemon-reload
systemctl enable --now fedorizer-daemon.service
systemctl is-active --quiet fedorizer-daemon.service
printf 'Installed Acer Fedorizer. Open it from your applications menu or run acer-fedorizer.\n'
