#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Native PH16-72 edition; modified October 2026. Attribution and terms: NOTICE.md.
# Internal build/lifecycle helper. User entry point: setup.sh install/uninstall.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)
MODE=${1:---install}
if [[ $# -gt 1 ]]; then echo 'Expected a single mode argument.' >&2; exit 2; fi
if [[ "$MODE" == --help || "$MODE" == -h ]]; then
    echo 'Usage: scripts/local-setup.sh [--build|--install|--uninstall]'
    echo 'For dependencies and the optional bridge, use ./setup.sh.'
    exit 0
fi
GUI_DIR="$REPO_DIR/publish/native"
DOTNET_BIN=${DAMX_DOTNET:-dotnet}

build_gui() (
    # A subshell keeps this cleanup scoped to the build, including failed builds.
    stage=''
    trap 'result=$?; if [[ -n "$stage" ]]; then rm -rf -- "$stage"; fi; "$SCRIPT_DIR/clean-build.sh"; exit "$result"' EXIT
    mkdir -p "$REPO_DIR/publish"
    local stage
    stage=$(mktemp -d "$REPO_DIR/publish/.build-XXXXXX")
    "$DOTNET_BIN" publish "$REPO_DIR/DivAcerManagerMax/DivAcerManagerMax.csproj" \
        -c Release -r linux-x64 --self-contained true -o "$stage" || {
            rm -rf -- "$stage"; return 1;
        }
    # Finish and verify staging before replacing the last working build.
    if ! python3 "$SCRIPT_DIR/collect-licenses.py" ||
       ! cp "$REPO_DIR/THIRD-PARTY-NOTICES.md" "$stage/licenses/" ||
       ! cp -a "$REPO_DIR/LICENSES/." "$stage/licenses/LICENSES/"; then
        rm -rf -- "$stage"
        return 1
    fi
    rm -rf -- "$REPO_DIR/publish/.previous-build"
    if [[ -d "$GUI_DIR" ]]; then mv "$GUI_DIR" "$REPO_DIR/publish/.previous-build"; fi
    chmod 755 "$stage"
    mv "$stage" "$GUI_DIR"
    rm -rf -- "$REPO_DIR/publish/.previous-build"
)

if [[ "$MODE" == --build ]]; then
    build_gui
    exit
fi
if [[ "$MODE" != --install && "$MODE" != --uninstall ]]; then
    echo 'Usage: local-setup.sh [--build|--install|--uninstall]'
    exit 2
fi
if [[ "$MODE" == --install && ! -x "$GUI_DIR/DivAcerManagerMax" ]]; then
    echo 'The application build is missing. Run ./setup.sh install.' >&2
    exit 1
fi
if [[ $EUID -ne 0 ]]; then
    exec sudo -- "$0" "$MODE"
fi
source "$SCRIPT_DIR/setup-common.sh"
if [[ "$MODE" == --uninstall ]]; then
    remove_application
    echo 'DAMX completely removed, including settings, backups, and lightbar driver.'
    echo 'Shared system dependencies and this downloaded source folder were retained.'
    exit
fi

TARGET_USER=${SUDO_USER:-${PKEXEC_UID:-}}
if [[ "$TARGET_USER" =~ ^[0-9]+$ ]]; then TARGET_USER=$(getent passwd "$TARGET_USER" | cut -d: -f1); fi
SOCKET_UID=0
if [[ -n "$TARGET_USER" ]]; then SOCKET_UID=$(id -u "$TARGET_USER"); fi
# Prepare the complete replacement before stopping/removing the current app.
APP_STAGE=$(mktemp -d "${APP_DIR%/*}/.damx-install-XXXXXX")
trap 'rm -rf -- "$APP_STAGE"' EXIT
chmod 755 "$APP_STAGE"
install -d "$APP_STAGE/daemon" "$APP_STAGE/gui"
install -m 644 "$REPO_DIR/LICENSE" "$REPO_DIR/NOTICE.md" "$REPO_DIR/THIRD-PARTY-NOTICES.md" "$APP_STAGE/"
install -m 644 "$REPO_DIR/DAMM-Daemon/acer_hid.py" "$REPO_DIR/DAMM-Daemon/native_controls.py" "$REPO_DIR/DAMM-Daemon/predator_button.py" "$APP_STAGE/daemon/"
install -m 755 "$REPO_DIR/DAMM-Daemon/DAMX-Daemon.py" "$APP_STAGE/daemon/"
cp -a "$GUI_DIR/." "$APP_STAGE/gui/"
chmod 755 "$APP_STAGE/gui" "$APP_STAGE/gui/DivAcerManagerMax"
# Check the stock driver before removing a working installation.
modprobe acer_wmi
# Completely replace app files and saved state, including historical backups.
remove_application
getent group damx >/dev/null || groupadd --system damx
if [[ -n "$TARGET_USER" && "$TARGET_USER" != root ]]; then usermod -aG damx "$TARGET_USER"; fi
mv "$APP_STAGE" "$APP_DIR"
trap - EXIT
install -d "$STATE_DIR" "$UNIT_DIR" "${LAUNCHER%/*}" "${DESKTOP_FILE%/*}" "${ICON_FILE%/*}"
cat > "$UNIT_DIR/damx-daemon.service" <<SERVICE
[Unit]
Description=DAMX native Acer controls
After=systemd-udevd.service
[Service]
Type=simple
ExecStart=/usr/bin/python3 $APP_DIR/daemon/DAMX-Daemon.py --socket-owner $SOCKET_UID
Restart=on-failure
RestartSec=3
User=root
Group=damx
UMask=0007
[Install]
WantedBy=multi-user.target
SERVICE
cat > "$LAUNCHER" <<LAUNCH
#!/bin/sh
exec $APP_DIR/gui/DivAcerManagerMax "\$@"
LAUNCH
chmod 755 "$LAUNCHER"
cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Name=DAMX
Comment=Native Acer performance and lighting controls
Exec=$LAUNCHER
Icon=damx
Terminal=false
Type=Application
Categories=Utility;System;
DESKTOP
install -m 644 "$REPO_DIR/DivAcerManagerMax/icon.png" "$ICON_FILE"
if lightbar_supported; then "$SCRIPT_DIR/install-lightbar.sh"; fi
if command -v update-desktop-database >/dev/null; then update-desktop-database "${DESKTOP_FILE%/*}"; fi
systemctl daemon-reload
systemctl enable --now damx-daemon.service
systemctl is-active --quiet damx-daemon.service
printf 'Installed DAMX. Open DAMX from your applications menu or run DAMX.\n'
