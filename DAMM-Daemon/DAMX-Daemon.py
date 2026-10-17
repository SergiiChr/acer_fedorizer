#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Native PH16-72 edition; modified October 2026. Attribution and terms: NOTICE.md.
"""DAMX native daemon: stock Acer sysfs and direct HID, newline-delimited JSON."""
import argparse
import grp
import json
import logging
import os
import signal
import socket
import socketserver
import sys
from native_controls import NativeControls, VERSION
import predator_button

MAX_MESSAGE = 65536
log = logging.getLogger('damx')


class RequestHandler(socketserver.StreamRequestHandler):
    def handle(self):
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
                    response = dict(success=True, data=result)
                except (OSError, ValueError, RuntimeError, KeyError, TypeError) as e:
                    log.warning('Command failed: %s', e)
                    response = dict(success=False, error=str(e))
                self.wfile.write(json.dumps(response).encode() + b'\n')
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                break


class NativeServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path, controls):
        self.controls = controls
        super().__init__(path, RequestHandler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inspect', action='store_true', help='Read capabilities without starting a server')
    parser.add_argument('--socket', default='/run/DAMX.sock')
    parser.add_argument('--state-file', default='/var/lib/damx/lighting.json')
    parser.add_argument('--socket-owner', type=int, default=0, help='Desktop UID allowed to access the socket')
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    controls = NativeControls(state_file=args.state_file)
    if args.inspect:
        print(json.dumps(controls.settings(), indent=2))
        return
    if os.geteuid() != 0 and args.socket == '/run/DAMX.sock':
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
            os.chown(args.socket, args.socket_owner, grp.getgrnam('damx').gr_gid)
        except KeyError:
            os.chmod(args.socket, 0o600)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    button_stop = predator_button.start(args.socket_owner)
    try:
        log.info('Native controls: %s', ', '.join(sorted(controls.features)))
        server.serve_forever(poll_interval=0.5)
    finally:
        button_stop.set()
        server.server_close()
        os.unlink(args.socket)


if __name__ == '__main__':
    main()
