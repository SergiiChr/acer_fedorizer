# SPDX-License-Identifier: GPL-3.0-only
# Native PH16-72 edition; modified October 2026. Attribution and terms: NOTICE.md.
"""Hardware control daemon: stock Acer sysfs and direct HID, newline-delimited JSON."""
import argparse
import contextlib
import grp
import json
import logging
import os
import select
import signal
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path

from . import hotkey, uevents
from .controls import VERSION, NativeControls

MAX_MESSAGE = 65536
# Tools such as tuned rewrite CPU caps on profile changes; 32 sysfs reads per check cost far less than a timer unit.
CPU_LIMIT_INTERVAL = 10
log = logging.getLogger('fedorizer')


class RequestHandler(socketserver.StreamRequestHandler):
    server: 'NativeServer'

    def handle(self) -> None:
        self.request.settimeout(30)
        while True:
            try:
                line = self.rfile.readline(MAX_MESSAGE + 1)
                if not line:
                    break
                if len(line) > MAX_MESSAGE or not line.endswith(b'\n'):
                    self.wfile.write(b'{"success":false,"error":"Request exceeds framing limit"}\n')
                    break
                try:
                    request = json.loads(line)
                    if (not isinstance(request, dict) or
                            not isinstance(request.get('command'), str) or
                            not isinstance(request.get('params', {}), dict)):
                        raise ValueError('Expected a command object and parameter object')
                    result = self.server.controls.command(request.get('command', ''), request.get('params', {}))
                    response = {'success': True, 'data': result}
                except (OSError, ValueError, RuntimeError, KeyError, TypeError) as e:
                    log.warning('Command failed: %s', e)
                    response = {'success': False, 'error': str(e)}
                self.wfile.write(json.dumps(response).encode() + b'\n')
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                break


class NativeServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str, controls: NativeControls) -> None:
        self.controls = controls
        super().__init__(path, RequestHandler)


def watch_hid(controls: NativeControls) -> None:
    """Replay lighting when HID devices appear or disappear, once per burst of events."""
    hotplug = uevents.open_socket()
    while True:
        hotplug.settimeout(None)
        if not uevents.changed(hotplug, {'hidraw'}):
            continue
        # A keyboard reconnect adds several hidraw nodes; wait until events settle.
        hotplug.settimeout(1)
        with contextlib.suppress(TimeoutError):
            while True:
                uevents.changed(hotplug, set())
        controls.restore_lighting()


def watch_profile(controls: NativeControls, profile: Path) -> None:
    """Re-read profile and fan settings each time the kernel signals a profile change, such as from GNOME."""
    with profile.open('rb', buffering=0) as attribute:
        poller = select.poll()
        poller.register(attribute, select.POLLPRI | select.POLLERR)
        while True:
            # Only a read arms the next signal; right after opening, poll returns at once.
            try:
                # Holding the lock keeps a value read before the daemon's own write from replacing that write.
                with controls.lock:
                    attribute.seek(0)
                    controls.update_profile(attribute.read().decode().strip())
            except OSError as error:
                # A failed read may leave the signal unarmed; pausing keeps a retry loop from stalling the CPUs nonstop.
                log.warning('Could not read the performance profile: %s', error)
                time.sleep(1)
            poller.poll()


def restore_in_background(controls: NativeControls) -> None:
    threading.Thread(target=controls.restore_lighting, daemon=True, name='restore-lighting').start()


def keep_cpu_limits(controls: NativeControls, wake: threading.Event) -> None:
    """Reassert saved CPU caps now, whenever wake is set, and every CPU_LIMIT_INTERVAL seconds."""
    while True:
        controls.enforce_cpu_limits()
        wake.wait(CPU_LIMIT_INTERVAL)
        wake.clear()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inspect', action='store_true', help='Read capabilities without starting a server')
    parser.add_argument('--auto-fans', action='store_true', help='Return fans to automatic control and exit')
    parser.add_argument('--socket', default='/run/acer-fedorizer.sock')
    parser.add_argument('--state-file', default='/var/lib/acer-fedorizer/lighting.json')
    parser.add_argument('--socket-owner', type=int, default=0, help='Desktop UID allowed to access the socket')
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    if args.auto_fans:
        NativeControls(state_file=args.state_file, discover_hid=False).auto_fans()
        return
    controls = NativeControls(state_file=args.state_file)
    if args.inspect:
        print(json.dumps(controls.settings(), indent=2))
        return
    if os.geteuid() != 0 and args.socket == '/run/acer-fedorizer.sock':
        parser.error('The system daemon needs root; --inspect works without root')
    # Don't remove an active daemon's socket. A stale socket can be replaced.
    if os.path.exists(args.socket):
        with socket.socket(socket.AF_UNIX) as probe:
            try:
                probe.connect(args.socket)
            except ConnectionRefusedError:
                os.unlink(args.socket)
            else:
                parser.error('A daemon is already listening on this socket')
    old_mask = os.umask(0o117)
    try:
        server = NativeServer(args.socket, controls)
    finally:
        os.umask(old_mask)
    if os.geteuid() == 0:
        try:
            os.chown(args.socket, args.socket_owner, grp.getgrnam('fedorizer').gr_gid)
        except KeyError:
            os.chmod(args.socket, 0o600)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    cpu_wake = threading.Event()
    def reload(*_: object) -> None:
        restore_in_background(controls)
        threading.Thread(target=controls.refresh_firmware, daemon=True, name='refresh-firmware').start()
        cpu_wake.set()
    # systemctl reload (also sent after resume from sleep) replays saved lighting and CPU caps
    # and re-reads profile and fan settings.
    signal.signal(signal.SIGUSR1, reload)
    restore_in_background(controls)
    if controls.cpu.groups:
        threading.Thread(target=keep_cpu_limits, args=(controls, cpu_wake), daemon=True, name='cpu-limits').start()
    threading.Thread(target=watch_hid, args=(controls,), daemon=True, name='hid-hotplug').start()
    if controls.profile_dir:
        threading.Thread(target=watch_profile, args=(controls, controls.profile_dir / 'profile'), daemon=True,
                         name='profile-changes').start()
    hotkey.start(args.socket_owner)
    try:
        log.info('Native controls: %s', ', '.join(sorted(controls.features)))
        server.serve_forever(poll_interval=0.5)
    finally:
        # Manual fan speeds never outlive the service; ExecStopPost repeats this after a crash.
        controls.auto_fans()
        server.server_close()
        os.unlink(args.socket)


if __name__ == '__main__':
    main()
