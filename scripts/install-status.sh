#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Read-only installation checks. No sudo, hardware writes, or module loading.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/setup-common.sh"
failed=0
check() {
    local label=$1
    shift
    if "$@"; then printf 'OK: %s\n' "$label"; else printf 'FAIL: %s\n' "$label"; failed=1; fi
}
printf 'DAMX installation status\nModel: %s\nKernel: %s\n' "$(cat "$PRODUCT_FILE" 2>/dev/null || echo unknown)" "$(uname -r)"
if ! installation_exists; then
    echo 'Not installed. Run ./setup.sh install.'
    exit 1
fi
check 'Application executable' test -x "$APP_DIR/gui/DivAcerManagerMax"
check 'Daemon source files' test -f "$APP_DIR/daemon/DAMX-Daemon.py"
check 'Desktop launcher' test -x "$LAUNCHER"
check 'Desktop menu entry' test -f "$DESKTOP_FILE"
check 'Daemon service enabled' systemctl is-enabled --quiet damx-daemon.service
check 'Daemon service running' systemctl is-active --quiet damx-daemon.service
check 'Control socket exists' test -S "$RUN_DIR/DAMX.sock"
if [[ -S "$RUN_DIR/DAMX.sock" ]]; then
    check 'Daemon responds to ping' python3 - "$RUN_DIR/DAMX.sock" <<'PY'
import json
import socket
import sys
try:
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(3)
        client.connect(sys.argv[1])
        client.sendall(b'{"command":"ping","params":{}}\n')
        with client.makefile('rb') as stream:
            line = stream.readline(65537)
        if len(line) > 65536 or not line.endswith(b'\n'):
            raise ValueError('Invalid daemon response')
        reply = json.loads(line)
        if not isinstance(reply, dict) or reply.get('success') is not True:
            raise ValueError('Daemon rejected ping')
except (OSError, ValueError) as error:
    print(f'Daemon connection: {error}')
    sys.exit(1)
PY
fi
if lightbar_supported; then
    check 'Rear lightbar driver loaded' test -d "$MODULE_DIR"
    if command -v dkms >/dev/null; then
        # Capture the full output so no producer gets SIGPIPE.
        if report=$(dkms status -m damx-lightbar -v 0.2.0 -k "$(uname -r)"); then
            if [[ "$report" == *": installed"* ]]; then
                echo 'OK: Rear lightbar driver installed for the running kernel'
            else
                echo 'FAIL: Rear lightbar driver is not installed for the running kernel'; failed=1
            fi
        else
            echo 'FAIL: DKMS could not inspect the rear lightbar driver'; failed=1
        fi
    else
        echo 'FAIL: DKMS is missing'; failed=1
    fi
else
    echo 'Rear lightbar driver: not required for this model.'
fi
if [[ $failed -ne 0 ]]; then
    echo 'Repair: run ./setup.sh install.'
    echo 'Service logs: journalctl -u damx-daemon.service -b --no-pager -n 30'
    exit 1
fi
echo 'Installation is healthy.'
