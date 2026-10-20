#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Internal shared paths and lifecycle operations. Never override via environment.
APP_DIR=/opt/acer-fedorizer
STATE_DIR=/var/lib/acer-fedorizer
DKMS_TREE=/var/lib/dkms
SOURCE_TREE=/usr/src
MODULES_DIR=/lib/modules
RUN_DIR=/run
UNIT_DIR=/etc/systemd/system
RESUME_UNIT=$UNIT_DIR/fedorizer-resume.service
SLEEP_TARGETS=(suspend hibernate hybrid-sleep suspend-then-hibernate)
LAUNCHER=/usr/local/bin/acer-fedorizer
DESKTOP_FILE=/usr/share/applications/io.github.SergiiChr.AcerFedorizer.desktop
ICON_FILE=/usr/share/icons/hicolor/scalable/apps/acer-fedorizer.svg
PRODUCT_FILE=/sys/class/dmi/id/product_name
MODULE_DIR=/sys/module/laptop_lightbar

lightbar_supported() {
    [[ $(cat "$PRODUCT_FILE" 2>/dev/null || true) == 'Predator PH16-72' ]]
}

# Unit files, including the links that enable the resume unit.
unit_paths() {
    local target
    printf '%s\n' "$UNIT_DIR/fedorizer-daemon.service" "$RESUME_UNIT"
    for target in "${SLEEP_TARGETS[@]}"; do printf '%s\n' "$UNIT_DIR/$target.target.wants/${RESUME_UNIT##*/}"; done
}

installation_exists() {
    local path
    for path in "$APP_DIR" "$APP_DIR.previous" "$STATE_DIR" \
        "$UNIT_DIR/fedorizer-daemon.service" "$RESUME_UNIT" "$LAUNCHER" "$DESKTOP_FILE" "$ICON_FILE" \
        "$RUN_DIR/acer-fedorizer.sock" "$DKMS_TREE/laptop-lightbar" "$MODULE_DIR" \
        "$SOURCE_TREE"/laptop-lightbar-* "$APP_DIR".backup.*; do
        [[ ! -e "$path" && ! -L "$path" ]] || return 0
    done
    if getent group fedorizer >/dev/null; then return 0; fi
    legacy_installation_exists
}

remove_lightbar() {
    local entry version kernel leftovers
    if [[ -d "$MODULE_DIR" ]]; then modprobe -r laptop_lightbar; fi
    for entry in "$DKMS_TREE/laptop-lightbar/"*; do
        [[ -d "$entry" && ! -L "$entry" ]] || continue
        version=${entry##*/}
        [[ "$version" =~ ^[0-9][a-zA-Z0-9.+_-]*$ ]] || continue
        if [[ -L "$entry/source" && -d "$entry/source" ]] && command -v dkms >/dev/null; then
            # Inspect the registration directly: do not pipe status to grep -q
            # under pipefail (DKMS may receive SIGPIPE with multiple kernels).
            dkms remove -m laptop-lightbar -v "$version" --all
        else
            echo "Cleaning leftover Acer Fedorizer lightbar registration: $version"
        fi
    done
    # Remove this module's orphaned files too, including broken DKMS registrations.
    for kernel in "$MODULES_DIR/"*; do
        [[ -d "$kernel" ]] || continue
        leftovers=$(find "$kernel" \( -type f -o -type l \) -name 'laptop_lightbar.ko*' -print -delete)
        if [[ -n "$leftovers" ]]; then depmod -a "${kernel##*/}"; fi
    done
    rm -rf -- "$DKMS_TREE/laptop-lightbar"
    for entry in "$SOURCE_TREE"/laptop-lightbar-*; do
        [[ ! -e "$entry" && ! -L "$entry" ]] || rm -rf -- "$entry"
    done
}

remove_application() {
    local path units
    # Missing/inactive services are normal on a first install or repeated removal.
    if [[ -e "$UNIT_DIR/fedorizer-daemon.service" ]] || systemctl cat fedorizer-daemon.service >/dev/null 2>&1; then
        systemctl disable --now fedorizer-daemon.service
    fi
    if [[ -e "$RESUME_UNIT" ]]; then systemctl disable fedorizer-resume.service; fi
    if command -v pkill >/dev/null; then
        pkill -TERM -f "^/usr/bin/python3 -m control_center([[:space:]]|$)" || [[ $? -eq 1 ]]
    fi
    remove_lightbar
    remove_legacy_application
    mapfile -t units < <(unit_paths)
    rm -f -- "${units[@]}" "$LAUNCHER" "$DESKTOP_FILE" "$ICON_FILE" "$RUN_DIR/acer-fedorizer.sock"
    rm -rf -- "$UNIT_DIR/fedorizer-daemon.service.d" "$APP_DIR" "$APP_DIR.previous" "$STATE_DIR"
    for path in "$APP_DIR".backup.*; do
        [[ ! -e "$path" && ! -L "$path" ]] || rm -rf -- "$path"
    done
    if getent group fedorizer >/dev/null; then groupdel fedorizer; fi
    systemctl daemon-reload
    systemctl reset-failed fedorizer-daemon.service 2>/dev/null || true
    if command -v update-desktop-database >/dev/null; then update-desktop-database "${DESKTOP_FILE%/*}"; fi
}

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/legacy-install.sh"
