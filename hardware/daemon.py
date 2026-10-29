# SPDX-License-Identifier: GPL-3.0-only
# Native PH16-72 edition; modified October 2026. Attribution and terms: NOTICE.md.
"""Hardware control daemon: stock Acer sysfs and direct HID, newline-delimited JSON."""
import argparse
import contextlib
import grp
import json
import logging
import os
import signal
import socket
import socketserver
import sys
import threading

from . import hotkey, uevents
from .controls import VERSION, NativeControls

MAX_MESSAGE = 65536
log = logging.getLogger('fedorizer')


class RequestHandler(socketserver.StreamRequestHandler):
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


def restore_in_background(controls: NativeControls) -> None:
    threading.Thread(target=controls.restore_lighting, daemon=True, name='restore-lighting').start()


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
    # systemctl reload (also sent after resume from sleep) replays saved lighting.
    signal.signal(signal.SIGUSR1, lambda *_: restore_in_background(controls))
    restore_in_background(controls)
    threading.Thread(target=watch_hid, args=(controls,), daemon=True, name='hid-hotplug').start()
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
