# SPDX-License-Identifier: GPL-3.0-only
"""Thread-safe, bounded newline-JSON transport. No import-time connections."""
import json
import os
import socket
import threading

type JSON = dict[str, JSON] | list[JSON] | str | int | float | bool | None

# Safe to repeat: they never change hardware state.
READ_COMMANDS = frozenset({'ping', 'get_all_settings', 'get_keyboard_layout'})


class ControlClient:
    def __init__(self, path: str | None = None, timeout: float = 5) -> None:
        self.path = path or os.environ.get('FEDORIZER_SOCKET', '/run/acer-fedorizer.sock')
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._lock = threading.Lock()
        self._closed = False

    def command(self, command: str, params: dict[str, JSON] | None = None) -> JSON:
        payload = json.dumps({'command': command, 'params': params or {}}).encode() + b'\n'
        if len(payload) > 65536:
            raise ValueError('Request exceeds framing limit')
        with self._lock:
            if self._closed:
                raise RuntimeError('Client is closed')
            # The service closes idle connections and restarts drop them, so a reused socket can be stale.
            # Reads are retried once on a fresh connection; writes are never sent twice.
            retry = command in READ_COMMANDS and self._socket is not None
            try:
                return self._exchange(payload)
            except ConnectionError:
                if not retry:
                    raise
            return self._exchange(payload)

    def _exchange(self, payload: bytes) -> JSON:
        try:
            if self._socket is None:
                self._socket = socket.socket(socket.AF_UNIX)
                self._socket.settimeout(self.timeout)
                self._socket.connect(self.path)
            self._socket.sendall(payload)
            result = bytearray()
            while True:
                chunk = self._socket.recv(4096)
                if not chunk:
                    raise ConnectionError('Hardware service disconnected')
                result.extend(chunk)
                if len(result) > 262144:
                    raise ValueError('Response exceeds framing limit')
                if b'\n' in chunk:
                    break
            line, remainder = bytes(result).split(b'\n', 1)
            if remainder:
                raise ValueError('Unexpected data after response')
            response: JSON = json.loads(line)
            if not isinstance(response, dict) or not isinstance(response.get('success'), bool):
                raise ValueError('Invalid hardware service response')
            if not response['success']:
                raise RuntimeError(str(response.get('error', 'Command failed')))
            return response.get('data', {})
        except Exception:
            self._disconnect()
            raise

    def _disconnect(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._disconnect()
