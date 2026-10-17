#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Native PH16-72 edition; modified October 2026. Attribution and terms: NOTICE.md.
# Low-level installer; setup.sh also handles dependencies and the optional bridge.
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

build_gui() {
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
}

if [[ "$MODE" == --build ]]; then
    build_gui
    exit
fi
if [[ "$MODE" != --install && "$MODE" != --uninstall ]]; then
    echo 'Usage: local-setup.sh [--build|--install|--uninstall]'
    exit 2
fi
if [[ "$MODE" == --install && ! -x "$GUI_DIR/DivAcerManagerMax" ]]; then
    if [[ $EUID -eq 0 ]]; then
        echo 'Build the GUI as your desktop user first: scripts/local-setup.sh --build'
        exit 1
    fi
    build_gui
fi
if [[ $EUID -ne 0 ]]; then
    exec sudo -- "$0" "$MODE"
fi

if [[ "$MODE" == --uninstall ]]; then
    systemctl disable --now damx-daemon.service || true
    rm -f /etc/systemd/system/damx-daemon.service /usr/local/bin/DAMX
    rm -f /usr/share/applications/damx.desktop
    rm -f /usr/share/icons/hicolor/256x256/apps/damx.png
    systemctl daemon-reload
    echo 'Daemon and launcher removed. /opt/damx retained for recovery.'
    exit
fi

# Keep one rollback copy, without recursively copying older GUI backups.
if [[ -d /opt/damx ]]; then
    BACKUP_STAGE=$(mktemp -d /opt/.damx-backup-XXXXXX)
    for component in daemon gui; do
        if [[ -d /opt/damx/$component ]]; then cp -a "/opt/damx/$component" "$BACKUP_STAGE/"; fi
    done
    rm -rf /opt/damx.previous
    mv "$BACKUP_STAGE" /opt/damx.previous
fi
systemctl stop damx-daemon.service 2>/dev/null || true
modprobe acer_wmi
getent group damx >/dev/null || groupadd --system damx
TARGET_USER=${SUDO_USER:-${PKEXEC_UID:-}}
if [[ "$TARGET_USER" =~ ^[0-9]+$ ]]; then TARGET_USER=$(getent passwd "$TARGET_USER" | cut -d: -f1); fi
if [[ -n "$TARGET_USER" && "$TARGET_USER" != root ]]; then
    usermod -aG damx "$TARGET_USER"
fi
install -d /opt/damx/daemon /opt/damx/gui /var/lib/damx
install -m 644 "$REPO_DIR/LICENSE" "$REPO_DIR/NOTICE.md" "$REPO_DIR/THIRD-PARTY-NOTICES.md" /opt/damx/
install -m 644 "$REPO_DIR/DAMM-Daemon/acer_hid.py" "$REPO_DIR/DAMM-Daemon/native_controls.py" "$REPO_DIR/DAMM-Daemon/predator_button.py" /opt/damx/daemon/
install -m 755 "$REPO_DIR/DAMM-Daemon/DAMX-Daemon.py" /opt/damx/daemon/
# Replace the directory atomically: an open executable cannot be overwritten.
GUI_STAGE=$(mktemp -d /opt/damx/.gui-XXXXXX)
cp -a "$GUI_DIR/." "$GUI_STAGE/"
chmod 755 "$GUI_STAGE"
chmod +x "$GUI_STAGE/DivAcerManagerMax"
rm -rf /opt/damx/.gui-old
mv /opt/damx/gui /opt/damx/.gui-old
mv "$GUI_STAGE" /opt/damx/gui
rm -rf /opt/damx/.gui-old
for previous in /opt/damx/gui.previous.*; do
    [[ -d "$previous" ]] && rm -rf -- "$previous"
done
SOCKET_UID=0
if [[ -n "$TARGET_USER" ]]; then SOCKET_UID=$(id -u "$TARGET_USER"); fi
cat > /etc/systemd/system/damx-daemon.service <<EOF
[Unit]
Description=DAMX native Acer controls
After=systemd-udevd.service
[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/damx/daemon/DAMX-Daemon.py --socket-owner $SOCKET_UID
Restart=on-failure
RestartSec=3
User=root
Group=damx
UMask=0007
[Install]
WantedBy=multi-user.target
EOF
cat > /usr/local/bin/DAMX <<'EOF'
#!/bin/sh
# Keep desktop credentials unchanged so portals can inspect this process.
exec /opt/damx/gui/DivAcerManagerMax "$@"
EOF
chmod +x /usr/local/bin/DAMX
install -d /usr/share/applications
cat > /usr/share/applications/damx.desktop <<'EOF'
[Desktop Entry]
Name=DAMX
Comment=Native Acer performance and lighting controls
Exec=/usr/local/bin/DAMX
Icon=damx
Terminal=false
Type=Application
Categories=Utility;System;
EOF
install -d /usr/share/icons/hicolor/256x256/apps
install -m 644 "$REPO_DIR/DivAcerManagerMax/icon.png" /usr/share/icons/hicolor/256x256/apps/damx.png
if command -v update-desktop-database >/dev/null; then update-desktop-database /usr/share/applications; fi
systemctl daemon-reload
systemctl enable --now damx-daemon.service
systemctl is-active --quiet damx-daemon.service
printf 'Installed native DAMX. Run DAMX from your desktop session.\n'
