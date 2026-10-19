#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Names below are used only to remove installations from before the GTK migration.
legacy_paths() {
APP_DIR=/opt/damx
STATE_DIR=/var/lib/damx
DKMS_TREE=/var/lib/dkms
SOURCE_TREE=/usr/src
MODULES_DIR=/lib/modules
RUN_DIR=/run
UNIT_DIR=/etc/systemd/system
LAUNCHER=/usr/local/bin/DAMX
DESKTOP_FILE=/usr/share/applications/damx.desktop
ICON_FILE=/usr/share/icons/hicolor/256x256/apps/damx.png
PRODUCT_FILE=/sys/class/dmi/id/product_name
MODULE_DIR=/sys/module/damx_lightbar

}

legacy_installation_exists() (
    legacy_paths
    local path
    for path in "$APP_DIR" "$APP_DIR.previous" "$STATE_DIR" \
        "$UNIT_DIR/damx-daemon.service" "$LAUNCHER" "$DESKTOP_FILE" "$ICON_FILE" \
        "$RUN_DIR/DAMX.sock" "$DKMS_TREE/damx-lightbar" "$MODULE_DIR" \
        "$SOURCE_TREE"/damx-lightbar-* "$APP_DIR".backup.*; do
        [[ ! -e "$path" && ! -L "$path" ]] || return 0
    done
    getent group damx >/dev/null
)

remove_legacy_lightbar() (
    legacy_paths
    local entry version kernel leftovers
    if [[ -d "$MODULE_DIR" ]]; then modprobe -r damx_lightbar; fi
    for entry in "$DKMS_TREE/damx-lightbar/"*; do
        [[ -d "$entry" && ! -L "$entry" ]] || continue
        version=${entry##*/}
        [[ "$version" =~ ^[0-9][a-zA-Z0-9.+_-]*$ ]] || continue
        if [[ -L "$entry/source" && -d "$entry/source" ]] && command -v dkms >/dev/null; then
            # Inspect the registration directly: do not pipe status to grep -q
            # under pipefail (DKMS may receive SIGPIPE with multiple kernels).
            dkms remove -m damx-lightbar -v "$version" --all
        else
            echo "Cleaning leftover DAMX lightbar registration: $version"
        fi
    done
    # Remove this module's orphaned files too, including broken DKMS registrations.
    for kernel in "$MODULES_DIR/"*; do
        [[ -d "$kernel" ]] || continue
        leftovers=$(find "$kernel" \( -type f -o -type l \) -name 'damx_lightbar.ko*' -print -delete)
        if [[ -n "$leftovers" ]]; then depmod -a "${kernel##*/}"; fi
    done
    rm -rf -- "$DKMS_TREE/damx-lightbar"
    for entry in "$SOURCE_TREE"/damx-lightbar-*; do
        [[ ! -e "$entry" && ! -L "$entry" ]] || rm -rf -- "$entry"
    done
)

remove_legacy_application() (
    legacy_installation_exists || return 0
    legacy_paths
    local path
    # Missing/inactive services are normal on a first install or repeated removal.
    if [[ -e "$UNIT_DIR/damx-daemon.service" ]] || systemctl cat damx-daemon.service >/dev/null 2>&1; then
        systemctl disable --now damx-daemon.service
    fi
    if command -v pkill >/dev/null; then
        pkill -TERM -f "^$APP_DIR/gui/DivAcerManagerMax([[:space:]]|$)" || [[ $? -eq 1 ]]
    fi
    remove_legacy_lightbar
    rm -f -- "$UNIT_DIR/damx-daemon.service" "$LAUNCHER" "$DESKTOP_FILE" "$ICON_FILE" "$RUN_DIR/DAMX.sock"
    rm -rf -- "$UNIT_DIR/damx-daemon.service.d" "$APP_DIR" "$APP_DIR.previous" "$STATE_DIR"
    for path in "$APP_DIR".backup.* "$RUN_DIR"/user/*/damx-*.lock /tmp/CoreFxPipe_damx-* /tmp/damx-*.lock; do
        [[ ! -e "$path" && ! -L "$path" ]] || rm -rf -- "$path"
    done
    if getent group damx >/dev/null; then groupdel damx; fi
    systemctl daemon-reload
    systemctl reset-failed damx-daemon.service 2>/dev/null || true
    if command -v update-desktop-database >/dev/null; then update-desktop-database "${DESKTOP_FILE%/*}"; fi
)
