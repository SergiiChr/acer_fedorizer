# SPDX-License-Identifier: GPL-3.0-only
# Native PH16-72 edition; modified October 2026. See NOTICE.md.
"""Read the dedicated Predator button; launch through the desktop user manager."""
import logging
import os
import pwd
import select
import struct
import subprocess
import threading
import time
from pathlib import Path

from . import uevents

EVENT = struct.Struct('@llHHi')
log = logging.getLogger('fedorizer.button')


def button_pressed(kind, code, value, vendor):
    # PH16-72's vendor interface uses ABS_MISC; old WMI devices use KEY_PROG3.
    return value == 1 and ((vendor and kind == 3 and code == 40) or
                           (not vendor and kind == 1 and code == 202))


def button_devices(root=Path('/sys/class/input')):
    devices = {}
    for event in root.glob('event*'):
        try:
            device = event / 'device'
            name = (device / 'name').read_text().strip()
            vendor = (name == 'ACER Keyboard' and '05AF:666A' in str(device.resolve()).upper()
                      and int((device / 'capabilities/abs').read_text(), 16) == 1 << 40)
            if vendor or name == 'Acer WMI hotkeys':
                devices[Path('/dev/input') / event.name] = vendor
        except (OSError, ValueError):
            continue
    return devices


def launch(uid):
    user = pwd.getpwuid(uid)
    runtime = f'/run/user/{uid}'
    if not Path(runtime, 'bus').exists():
        return
    # Switch to the desktop user directly instead of through runuser and PAM.
    # The user manager already has the graphical session's DISPLAY/XAUTHORITY.
    result = subprocess.run(
        ['/usr/bin/systemd-run', '--user', '--collect', '--quiet', '/usr/local/bin/acer-fedorizer'],
        user=uid, group=user.pw_gid, extra_groups=os.getgrouplist(user.pw_name, user.pw_gid), cwd='/',
        env={'XDG_RUNTIME_DIR': runtime, 'DBUS_SESSION_BUS_ADDRESS': f'unix:path={runtime}/bus'},
        capture_output=True, text=True, timeout=5, check=False)
    if result.returncode:
        log.warning('Desktop launch failed: %s', result.stderr.strip())


def monitor(uid):
    # Input devices are rescanned only when the kernel reports an input hotplug event.
    hotplug = uevents.open_socket()
    handles = {}
    last_press = 0.0
    rescan = True
    while True:
        if rescan:
            found = button_devices()
            for path in list(handles):
                if path not in found:
                    os.close(handles.pop(path)[0])
            for path, vendor in found.items():
                if path not in handles:
                    try:
                        handles[path] = (os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC), vendor)
                        log.info('Listening for Predator button on %s', path)
                    except OSError:
                        pass
        ready, _, _ = select.select([hotplug, *(fd for fd, _ in handles.values())], [], [])
        rescan = hotplug in ready and uevents.changed(hotplug, {'input'})
        for path, (fd, vendor) in list(handles.items()):
            if fd not in ready:
                continue
            try:
                data = os.read(fd, EVENT.size * 64)
                if not data:
                    raise OSError('Input device disconnected')
                for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    _, _, kind, code, value = EVENT.unpack_from(data, offset)
                    now = time.monotonic()
                    if button_pressed(kind, code, value, vendor) and now - last_press > 0.7:
                        last_press = now
                        try:
                            launch(uid)
                        except (OSError, subprocess.TimeoutExpired):
                            log.exception('Unable to launch desktop app')
            except OSError:
                os.close(fd)
                handles.pop(path)


def start(uid):
    if uid > 0 and os.geteuid() == 0:
        threading.Thread(target=monitor, args=(uid,), daemon=True, name='predator-button').start()
