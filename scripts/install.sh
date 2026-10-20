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
# Serialize lifecycle changes; the /run lock is released when the process exits.
command -v flock >/dev/null || { echo 'flock is required for safe installation.' >&2; exit 1; }
exec 9>"$RUN_DIR/fedorizer-setup.lock"
flock -n 9 || { echo 'Another installation is already running.' >&2; exit 1; }
if [[ "$MODE" == --uninstall ]]; then
    remove_application
    echo 'Acer Fedorizer completely removed, including settings, backups, and lightbar driver.'
    echo 'Shared system packages and the source folder were retained.'
    exit
fi
for required in tar gpasswd; do
    command -v "$required" >/dev/null || { echo "Required command missing: $required" >&2; exit 1; }
done
TARGET_USER=${SUDO_USER:-${PKEXEC_UID:-}}
if [[ "$TARGET_USER" =~ ^[0-9]+$ ]]; then TARGET_USER=$(getent passwd "$TARGET_USER" | cut -d: -f1); fi
SOCKET_UID=0
if [[ -n "$TARGET_USER" ]]; then SOCKET_UID=$(id -u "$TARGET_USER"); fi
TX_DIR=$(mktemp -d "${APP_DIR%/*}/.fedorizer-install-XXXXXX")
TX_ACTIVE=0; TX_NEW_DRIVER_STARTED=0
source "$SCRIPT_DIR/install-transaction.sh"
trap finish_installation EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
APP_STAGE="$TX_DIR/app"
install -d -m 755 "$APP_STAGE"
cp -a --no-preserve=ownership "$REPO_DIR/control_center" "$REPO_DIR/hardware" "$REPO_DIR/assets" "$REPO_DIR/LICENSES" "$APP_STAGE/"
install -m 644 "$REPO_DIR/LICENSE" "$REPO_DIR/NOTICE.md" "$APP_STAGE/"
find "$APP_STAGE" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$APP_STAGE" -type d -exec chmod 755 {} +
find "$APP_STAGE" -type f -exec chmod 644 {} +
preflight_lightbar
modprobe acer_wmi
snapshot_installation
remove_application
getent group fedorizer >/dev/null || groupadd --system fedorizer
if [[ -n "$TARGET_USER" && "$TARGET_USER" != root ]]; then usermod -aG fedorizer "$TARGET_USER"; fi
mv "$APP_STAGE" "$APP_DIR"
install -d "$STATE_DIR" "$UNIT_DIR" "${LAUNCHER%/*}" "${DESKTOP_FILE%/*}" "${ICON_FILE%/*}"
cat > "$UNIT_DIR/fedorizer-daemon.service" <<SERVICE
[Unit]
Description=Acer Fedorizer hardware controls
After=systemd-udevd.service
[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 -m hardware.daemon --socket-owner $SOCKET_UID
# Hand fans back to firmware control after every stop, including a crash.
ExecStopPost=/usr/bin/python3 -m hardware.daemon --auto-fans
# Replays saved lighting; the resume unit uses it after sleep.
ExecReload=/usr/bin/kill -USR1 \$MAINPID
Restart=on-failure
RestartSec=3
User=root
Group=fedorizer
UMask=0077
# Root already owns the sysfs and device files it writes. The capabilities only cover
# handing the socket to the desktop user and switching to that user for the button launch.
CapabilityBoundingSet=CAP_CHOWN CAP_SETUID CAP_SETGID
NoNewPrivileges=yes
# /sys stays writable for the stock controls; ProtectKernelTunables would block them.
ProtectSystem=strict
ReadWritePaths=$RUN_DIR $STATE_DIR
# Read-only still allows connecting to the desktop user's bus under /run/user.
ProtectHome=read-only
PrivateTmp=yes
DevicePolicy=closed
DeviceAllow=char-hidraw rw
DeviceAllow=char-input r
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectHostname=yes
RestrictAddressFamilies=AF_UNIX AF_NETLINK
IPAddressDeny=any
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
SystemCallArchitectures=native
SystemCallFilter=@system-service
[Install]
WantedBy=multi-user.target
SERVICE
cat > "$RESUME_UNIT" <<SERVICE
[Unit]
Description=Reapply Acer Fedorizer lighting after sleep
After=${SLEEP_TARGETS[*]/%/.target}
[Service]
Type=oneshot
ExecStart=-/usr/bin/systemctl --no-block reload fedorizer-daemon.service
[Install]
WantedBy=${SLEEP_TARGETS[*]/%/.target}
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
if lightbar_supported; then
    TX_NEW_DRIVER_STARTED=1
    "$SCRIPT_DIR/install-lightbar.sh"
fi
if command -v update-desktop-database >/dev/null; then update-desktop-database "${DESKTOP_FILE%/*}"; fi
systemctl daemon-reload
systemctl enable fedorizer-resume.service
systemctl enable --now fedorizer-daemon.service
systemctl is-active --quiet fedorizer-daemon.service
# Type=simple can be active before Python finishes importing or opens its socket.
PYTHONDONTWRITEBYTECODE=1 python3 "$SCRIPT_DIR/wait-daemon.py" "$RUN_DIR/acer-fedorizer.sock"
TX_ACTIVE=0
printf 'Installed Acer Fedorizer. Open it from your applications menu or run acer-fedorizer.\n'
