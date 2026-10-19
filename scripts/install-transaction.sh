#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Sourced by install.sh. Only app-owned paths belong in the rollback snapshot.
preflight_lightbar() {
    lightbar_supported || return 0
    [[ -d "$MODULES_DIR/$(uname -r)/build" ]] || {
        echo 'Matching kernel headers are missing. The existing installation was not removed.' >&2; return 1;
    }
    local command kernel staging="$TX_DIR/lightbar-check"
    kernel=$(uname -r)
    for command in dkms gcc make; do
        command -v "$command" >/dev/null || { echo "Required command missing: $command" >&2; return 1; }
    done
    install -d "$staging/src/laptop-lightbar-0.2.0" "$staging/dkms" "$staging/modules"
    install -m 644 "$REPO_DIR/native-lightbar/"{laptop_lightbar.c,Makefile,dkms.conf} "$staging/src/laptop-lightbar-0.2.0/"
    install -m 644 "$REPO_DIR/LICENSES/GPL-2.0.txt" "$staging/src/laptop-lightbar-0.2.0/LICENSE"
    # DKMS also finds headers and sign-file through installtree; expose only the
    # existing headers in the private tree, never the installed module directory.
    install -d "$staging/modules/$kernel"
    ln -s -- "$MODULES_DIR/$kernel/build" "$staging/modules/$kernel/build"
    # Separate trees avoid touching the installed registration/module during build/signing.
    local options=(--dkmstree "$staging/dkms" --sourcetree "$staging/src" --installtree "$staging/modules")
    dkms add -m laptop-lightbar -v 0.2.0 "${options[@]}"
    dkms build -m laptop-lightbar -v 0.2.0 -k "$(uname -r)" "${options[@]}"
}

snapshot_installation() {
    TX_TARGETS=("$APP_DIR" "$APP_DIR.previous" "$STATE_DIR" "$UNIT_DIR/fedorizer-daemon.service"
        "$UNIT_DIR/fedorizer-daemon.service.d" "$LAUNCHER" "$DESKTOP_FILE" "$ICON_FILE"
        /opt/damx /opt/damx.previous /var/lib/damx "$UNIT_DIR/damx-daemon.service"
        "$UNIT_DIR/damx-daemon.service.d" /usr/local/bin/DAMX
        /usr/share/applications/damx.desktop /usr/share/icons/hicolor/256x256/apps/damx.png
        "$DKMS_TREE/laptop-lightbar" "$DKMS_TREE/damx-lightbar" "$SOURCE_TREE/laptop-lightbar-0.2.0")
    local path kernel name record index
    for path in "$APP_DIR".backup.* /opt/damx.backup.* "$SOURCE_TREE"/laptop-lightbar-* "$SOURCE_TREE"/damx-lightbar-*; do
        [[ ! -e "$path" && ! -L "$path" ]] || TX_TARGETS+=("$path")
    done
    TX_KERNELS=()
    for kernel in "$MODULES_DIR/"*; do
        [[ -d "$kernel" ]] || continue
        TX_KERNELS+=("${kernel##*/}")
        while IFS= read -r -d '' path; do TX_TARGETS+=("$path"); done < <(
            find "$kernel" \( -type f -o -type l \) \( -name 'laptop_lightbar.ko*' -o -name 'damx_lightbar.ko*' \) -print0)
    done
    TX_EXISTING=()
    for path in "${TX_TARGETS[@]}"; do
        [[ ! -e "$path" && ! -L "$path" ]] || TX_EXISTING+=("$path")
    done
    TX_ENABLED=(); TX_RUNNING=(); TX_SERVICES=()
    : > "$TX_DIR/services"
    for name in fedorizer-daemon.service damx-daemon.service; do
        TX_ENABLED+=(0); TX_RUNNING+=(0)
        index=$((${#TX_ENABLED[@]}-1))
        if systemctl is-enabled --quiet "$name"; then TX_ENABLED[index]=1; fi
        if systemctl is-active --quiet "$name"; then TX_RUNNING[index]=1; fi
        if [[ -e "$UNIT_DIR/$name" || -L "$UNIT_DIR/$name" || ${TX_ENABLED[index]} == 1 || ${TX_RUNNING[index]} == 1 ]]; then
            TX_SERVICES+=("$name")
        else TX_SERVICES+=(''); fi
        printf '%s enabled=%s running=%s\n' "$name" "${TX_ENABLED[index]}" "${TX_RUNNING[index]}" >> "$TX_DIR/services"
    done
    : > "$TX_DIR/groups"
    for name in fedorizer damx; do
        if record=$(getent group "$name"); then printf '%s\n' "$record" >> "$TX_DIR/groups"; fi
    done
    TX_MODULE_LOADED=0; TX_LEGACY_MODULE_LOADED=0
    [[ ! -d "$MODULE_DIR" ]] || TX_MODULE_LOADED=1
    [[ ! -d "${MODULE_DIR%/*}/damx_lightbar" ]] || TX_LEGACY_MODULE_LOADED=1
    printf 'laptop_lightbar=%s\ndamx_lightbar=%s\n' "$TX_MODULE_LOADED" "$TX_LEGACY_MODULE_LOADED" > "$TX_DIR/modules"
    : > "$TX_DIR/paths"
    for path in "${TX_EXISTING[@]}"; do printf '%s\0' "$path" >> "$TX_DIR/paths"; done
    tar --create --file "$TX_DIR/previous.tar" --absolute-names --acls --xattrs --selinux --null --files-from "$TX_DIR/paths"
    TX_ACTIVE=1
}

rollback_installation() {
    local failed=0 path name password gid members kernel index
    echo 'Installation failed; restoring the previous installation.' >&2
    # These may not exist yet, or may already have been stopped by replacement.
    systemctl disable --now fedorizer-daemon.service >/dev/null 2>&1 || true
    systemctl stop damx-daemon.service >/dev/null 2>&1 || true
    if [[ $TX_NEW_DRIVER_STARTED == 1 && -d "$MODULE_DIR" ]]; then modprobe -r laptop_lightbar || failed=1; fi
    for path in "${TX_TARGETS[@]}"; do rm -rf -- "$path" || failed=1; done
    # Remove newly generated module variants too (compression suffix may differ).
    for kernel in "${TX_KERNELS[@]}"; do
        find "$MODULES_DIR/$kernel" \( -type f -o -type l \) \( -name 'laptop_lightbar.ko*' -o -name 'damx_lightbar.ko*' \) -delete || failed=1
    done
    rm -f -- "$RUN_DIR/acer-fedorizer.sock" "$RUN_DIR/DAMX.sock" || failed=1
    tar --extract --file "$TX_DIR/previous.tar" --absolute-names --acls --xattrs --selinux --preserve-permissions || failed=1
    for name in fedorizer damx; do
        if getent group "$name" >/dev/null; then groupdel "$name" || failed=1; fi
    done
    while IFS=: read -r name password gid members; do
        [[ -n "$name" ]] || continue
        groupadd --system --gid "$gid" "$name" || failed=1
        gpasswd --members "$members" "$name" || failed=1
    done < "$TX_DIR/groups"
    for kernel in "${TX_KERNELS[@]}"; do depmod -a "$kernel" || failed=1; done
    if [[ $TX_MODULE_LOADED == 1 ]]; then modprobe laptop_lightbar || failed=1; fi
    if [[ $TX_LEGACY_MODULE_LOADED == 1 ]]; then modprobe damx_lightbar || failed=1; fi
    systemctl daemon-reload || failed=1
    for index in 0 1; do
        name=${TX_SERVICES[index]}
        [[ -n "$name" ]] || continue
        if [[ ${TX_ENABLED[index]} == 1 ]]; then systemctl enable "$name" || failed=1
        else systemctl disable "$name" || failed=1; fi
        if [[ ${TX_RUNNING[index]} == 1 ]]; then
            systemctl start "$name" || failed=1
            systemctl is-active --quiet "$name" || failed=1
        fi
    done
    if command -v update-desktop-database >/dev/null; then update-desktop-database "${DESKTOP_FILE%/*}" || failed=1; fi
    [[ $failed == 0 ]]
}

finish_installation() {
    local result=$?
    trap - EXIT INT TERM
    if [[ $result != 0 && $TX_ACTIVE == 1 ]]; then
        if rollback_installation; then echo 'Previous installation restored.' >&2
        else
            echo "Rollback could not finish. Recovery snapshot retained at $TX_DIR/previous.tar" >&2
            echo 'Do not delete this directory; the original files and group records are preserved there.' >&2
            exit "$result"
        fi
    fi
    rm -rf -- "$TX_DIR"
    exit "$result"
}
