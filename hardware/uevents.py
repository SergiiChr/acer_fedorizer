# SPDX-License-Identifier: GPL-3.0-only
"""Kernel hotplug notifications over netlink, so device changes need no polling or udev library."""
import errno
import socket

NETLINK_KOBJECT_UEVENT = 15
KERNEL_GROUP = 1


def open_socket() -> socket.socket:
    sock = socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC, NETLINK_KOBJECT_UEVENT)
    # Resume and docking produce bursts; the kernel caps this at net.core.rmem_max.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    sock.bind((0, KERNEL_GROUP))
    return sock


def parse(message: bytes) -> dict[str, str]:
    """Return the fields of a kernel uevent ("action@devpath" header, then KEY=value fields)."""
    header, *fields = message.split(b'\0')
    if b'@' not in header:
        return {}
    return dict(field.decode(errors='replace').split('=', 1) for field in fields if b'=' in field)


def changed(sock: socket.socket, subsystems: set[str]) -> bool:
    """Read one uevent and report whether it concerns one of the subsystems.
    A receive-buffer overflow means events were lost, so it counts as a change.
    """
    try:
        message = sock.recv(65536)
    except OSError as error:
        if error.errno == errno.ENOBUFS:
            return True
        raise
    return parse(message).get('SUBSYSTEM') in subsystems
