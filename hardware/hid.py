# SPDX-License-Identifier: GPL-3.0-only
# Native PH16-72 edition; modified October 2026. Attribution and terms: NOTICE.md.
"""Direct Acer HID backends. No import-time hardware access.
Protocol references: Acer PredatorSense 5.0.1463 DLLs and
https://github.com/TensorRaya/acer-predator-helios-rgb/blob/main/protocol/PROTOCOL.md
(CC-BY-4.0 protocol documentation; implementation maintained in this project).
"""
import contextlib
import fcntl
import os
import re
import struct
import time
from pathlib import Path
from typing import ClassVar, TypedDict

OPEN_FLAGS = os.O_RDWR | os.O_CLOEXEC
_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS
_IOC_WRITE = 1
_IOC_READ = 2

RGB = tuple[int, int, int]


class Lamp(TypedDict):
    """One LampArray lamp: position in micrometers, whether the host may color it, and its HID key usage."""
    id: int
    x: int
    y: int
    z: int
    programmable: bool
    key_usage: int


def _IOC(direction: int, type_: str, nr: int, size: int) -> int:
    return (
        (direction << _IOC_DIRSHIFT)
        | (ord(type_) << _IOC_TYPESHIFT)
        | (nr << _IOC_NRSHIFT)
        | (size << _IOC_SIZESHIFT)
    )


def HIDIOCSFEATURE(length: int) -> int:
    # linux/hidraw.h: _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x06, len)
    return _IOC(_IOC_WRITE | _IOC_READ, 'H', 0x06, length)


def HIDIOCGFEATURE(length: int) -> int:
    # linux/hidraw.h: _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x07, len)
    return _IOC(_IOC_WRITE | _IOC_READ, 'H', 0x07, length)

def scale_rgb(rgb: RGB, pct: int) -> RGB:
    """Scale an (r,g,b) tuple by a brightness percentage (0-100)."""
    pct = max(0, min(100, pct))
    r, g, b = (min(255, round(c * pct / 100)) for c in rgb)
    return r, g, b


def _get_report(fd: int, rid: int, n: int) -> bytes:
    """Read an n-byte feature report, retrying while the device is busy."""
    buf = bytearray(n); buf[0] = rid
    for _ in range(7):
        with contextlib.suppress(OSError):
            fcntl.ioctl(fd, HIDIOCGFEATURE(n), buf, True)
            return bytes(buf)
        time.sleep(0.05)
    # The final attempt reports its error.
    fcntl.ioctl(fd, HIDIOCGFEATURE(n), buf, True)
    return bytes(buf)


class LampArrayDevice:
    """A HID LampArray keyboard reached directly through /dev/hidraw*.

    The Acer Predator PH16-72 (and related PH16/PH18/PHN16-7x) per-key RGB
    keyboard (USB 05af:666a, Sunrex) is not driven by the acer-wmi
    four_zone/per_zone WMI methods.  It is a standard
    USB-HID LampArray device (HID Usage Page 0x59, "Lighting And Illumination",
    a.k.a. Windows Dynamic Lighting).  The Windows PredatorSense app talks to it
    through windows.devices.lights.LampArray; here we speak the same protocol
    over hidraw feature reports.  Report IDs and the multi-update slot count are
    read from the HID report descriptor so any conforming device works.
    Lighting commands go through the LampArraySession that open() returns.
    """

    MAGIC = b"\x05\x59\x09\x01\xa1\x01"   # Usage Page 0x59, Usage 0x01, Collection(App)
    ATTRS, ATTR_REQ, ATTR_RESP, MULTI, RANGE, CONTROL = 0x02, 0x20, 0x22, 0x50, 0x60, 0x70
    LAMP_ID = 0x21
    FLAG_COMPLETE = 0x01

    def __init__(self, path: str, vid: int, pid: int, name: str, reports: dict[int, int], slots: int) -> None:
        self.path, self.vid, self.pid, self.name = path, vid, pid, name
        self.reports, self.slots = reports, slots
        self.lamp_cache: list[Lamp] | None = None

    @staticmethod
    def _parse_descriptor(desc: bytes) -> tuple[dict[int, int], int | None]:
        """Return ({report_usage: report_id}, multi_update_slots) for a LampArray."""
        i, page, rid, rcount = 0, None, None, None
        usages: list[tuple[int | None, int]] = []
        stack: list[tuple[int | None, int] | None] = []
        cur: int | None = None
        reports: dict[int, int] = {}
        slots: int | None = None
        want = (0x02, 0x20, 0x22, 0x50, 0x60, 0x70)
        while i < len(desc):
            b = desc[i]; i += 1
            if b == 0xFE:                                   # long item
                i += 2 + desc[i]; continue
            size = (0, 1, 2, 4)[b & 3]; tag = b & 0xFC
            val = int.from_bytes(desc[i:i + size], "little"); i += size
            if tag == 0x04:                                 # Usage Page
                page = val
            elif tag == 0x08:                               # Usage
                usages.append((val >> 16, val & 0xFFFF) if size == 4 else (page, val))
            elif tag == 0x84:                               # Report ID
                rid = val
            elif tag == 0x94:                               # Report Count
                rcount = val
            elif tag == 0xA0:                               # Collection
                u = usages[-1] if usages else None
                stack.append(u)
                if u and u[0] == 0x59 and u[1] in want:
                    cur = u[1]
                usages = []
            elif tag == 0xC0:                               # End Collection
                u = stack.pop() if stack else None
                if u and u[0] == 0x59 and u[1] == cur:
                    cur = None
            elif tag in (0x80, 0x90, 0xB0):                 # Input / Output / Feature
                # A report without an ID cannot be addressed, so such a device is not discovered.
                if cur is not None and rid is not None:
                    reports.setdefault(cur, rid)
                    if cur == 0x50 and (0x59, 0x21) in usages:
                        slots = rcount
                usages = []
        return reports, slots

    @classmethod
    def discover(cls, sys_root: str | Path = "/sys",
                 vendor_filter: tuple[int, ...] | None = (0x05AF, 0x04F2)) -> list['LampArrayDevice']:
        """Find internal LampArray keyboards. vendor_filter=None matches any vendor."""
        out = []
        for h in sorted(Path(sys_root, "class/hidraw").glob("hidraw*")):
            try:
                uevent = (h / "device/uevent").read_text()
                desc = (h / "device/report_descriptor").read_bytes()
            except OSError:
                continue
            if b"\x05\x59\x09\x01" not in desc:
                continue
            m = re.search(r"HID_ID=\w+:0*(\w+):0*(\w+)", uevent)
            if not m:
                continue
            vid, pid = int(m.group(1), 16), int(m.group(2), 16)
            if vendor_filter and vid not in vendor_filter:
                continue
            reports, slots = cls._parse_descriptor(desc)
            if not all(u in reports for u in (cls.ATTRS, cls.ATTR_REQ, cls.ATTR_RESP,
                                              cls.MULTI, cls.RANGE, cls.CONTROL)):
                continue
            nm = re.search(r"HID_NAME=(.*)", uevent)
            out.append(cls("/dev/" + h.name, vid, pid,
                           nm.group(1).strip() if nm else "?", reports, slots or 8))
        return out

    def open(self) -> 'LampArraySession':
        """Open the hidraw node and read the lamp count and size; the node is closed again on failure."""
        fd = os.open(self.path, OPEN_FLAGS)
        try:
            attrs = _get_report(fd, self.reports[self.ATTRS], 23)
            count, w, h = struct.unpack("<HII", attrs[1:11])
            if not 1 <= count <= 4096:
                raise ValueError("Invalid LampArray lamp count")
        except Exception:
            os.close(fd)
            raise
        return LampArraySession(self, fd, count, w, h)


class LampArraySession:
    """An open LampArray keyboard; leaving its context closes the hidraw node."""

    def __init__(self, device: LampArrayDevice, fd: int, count: int, w: int, h: int) -> None:
        self.device, self.fd, self.count, self.w, self.h = device, fd, count, w, h

    def __enter__(self) -> 'LampArraySession':
        return self

    def __exit__(self, *exc: object) -> None:
        os.close(self.fd)

    def _set(self, data: bytes) -> None:
        buf = bytearray(data)
        fcntl.ioctl(self.fd, HIDIOCSFEATURE(len(buf)), buf, True)

    def autonomous(self, on: bool) -> None:
        """True -> firmware runs its own effects; False -> host controls colours."""
        self._set(bytes([self.device.reports[LampArrayDevice.CONTROL], 1 if on else 0]))

    def fill(self, rgb: RGB) -> None:
        """Set every lamp to one colour via a single LampRangeUpdate."""
        self.autonomous(False)
        self._set(bytes([self.device.reports[LampArrayDevice.RANGE], LampArrayDevice.FLAG_COMPLETE])
                  + struct.pack("<HH", 0, max(self.count - 1, 0)) + bytes(rgb) + b"\xff")

    def lamps(self) -> list[Lamp]:
        """Read HID lamp geometry and keyboard usage bindings, not a guessed key map."""
        if self.device.lamp_cache is None:
            out: list[Lamp] = []
            reports = self.device.reports
            rreq, rresp = reports[LampArrayDevice.ATTR_REQ], reports[LampArrayDevice.ATTR_RESP]
            for i in range(self.count):
                self._set(bytes([rreq]) + struct.pack("<H", i))
                resp = _get_report(self.fd, rresp, 29)
                lid, x, y, z = struct.unpack("<HIII", resp[1:15])
                if lid != i:
                    raise OSError('Lamp attributes returned a different lamp ID')
                out.append({"id": lid, "x": x, "y": y, "z": z,
                            "programmable": bool(resp[27]), "key_usage": resp[28]})
            self.device.lamp_cache = out
        return self.device.lamp_cache

    def multi(self, mapping: dict[int, RGB]) -> None:
        """Set arbitrary per-lamp colours ({lamp_id: (r,g,b)}) via LampMultiUpdate."""
        self.autonomous(False)
        items = sorted(mapping.items())
        n = self.device.slots
        rid = self.device.reports[LampArrayDevice.MULTI]
        for i in range(0, len(items), n):
            chunk = items[i:i + n]
            last = i + n >= len(items)
            ids = b"".join(struct.pack("<H", lid) for lid, _ in chunk) + b"\0\0" * (n - len(chunk))
            cols = b"".join(bytes(c) + b"\xff" for _, c in chunk) + b"\0" * 4 * (n - len(chunk))
            self._set(bytes([rid, len(chunk), LampArrayDevice.FLAG_COMPLETE if last else 0]) + ids + cols)
            time.sleep(0.033)


def frame(op: int, *params: int) -> bytes:
    if len(params) > 6 or not all(isinstance(v, int) and 0 <= v <= 255 for v in (op, *params)):
        raise ValueError("Invalid Acer HID command")
    body = bytes([op, *params]) + bytes(6 - len(params))
    return bytes([0]) + body + bytes([(~sum(body)) & 255])


def send_feature(fd: int, data: bytes) -> None:
    fcntl.ioctl(fd, HIDIOCSFEATURE(len(data)), bytearray(data), True)
    time.sleep(0.015)


class VendorKeyboard:
    # Firmware IDs derived from the original DLL's mode switch and named
    # constructors. Omit undocumented modes previously guessed from UI indices.
    EFFECTS: ClassVar[dict[int, int]] = {0: 0x01, 1: 0x02, 2: 0x08, 3: 0x03, 4: 0x12,
               5: 0x29, 6: 0x2A, 7: 0x05, 8: 0x06, 9: 0x0A}

    def __init__(self, path: str) -> None:
        self.path = path

    @classmethod
    def discover(cls, sys_root: str | Path = '/sys') -> 'VendorKeyboard | None':
        for h in sorted(Path(sys_root, 'class/hidraw').glob('hidraw*')):
            try:
                u = (h / 'device/uevent').read_text()
                d = (h / 'device/report_descriptor').read_bytes()
            except OSError:
                continue
            # The PH16-72 vendor collection is a nine-byte feature report.
            if 'HID_NAME=ACER Keyboard' in u and d.startswith(b'\x06\x02\xff'):
                return cls('/dev/' + h.name)
        return None

    MAG_EFFECTS: ClassVar[dict[int, int]] = {0: 0x41, 1: 0x42, 2: 0x45, 3: 0x43, 7: 0x44}

    def effect(self, mode: int, rgb: RGB, speed: int, brightness: int, direction: int = 1, mag: bool = False) -> None:
        table = self.MAG_EFFECTS if mag else self.EFFECTS
        if mode not in table:
            raise ValueError('Unsupported native keyboard effect')
        fd = os.open(self.path, OPEN_FLAGS)
        try:
            # PredatorSense SunrexUSBKeyboard.dll RVA 0x1800, not the older
            # four-zone WMI format. The DLL inverts speed, prepares the mode,
            # applies it, and only then supplies the selected color.
            effect = table[mode]
            native_direction = direction if effect in (0x03, 0x43) else 0
            send_feature(fd, frame(0xB1))
            send_feature(fd, frame(0x08, 0x02))
            send_feature(fd, frame(0x08, 0x02, effect, 10 - speed, brightness, 0, native_direction))
            send_feature(fd, frame(0x14, 0, int(mag), *rgb, 0))
        finally:
            os.close(fd)


class CoverLogo:
    EFFECTS: ClassVar[dict[int, int]] = {0: 1, 1: 2, 2: 8, 9: 10}
    def __init__(self, path: str) -> None:
        self.path = path

    @classmethod
    def discover(cls, sys_root: str | Path = '/sys') -> 'CoverLogo | None':
        for h in sorted(Path(sys_root, 'class/hidraw').glob('hidraw*')):
            try:
                u = (h / 'device/uevent').read_text()
            except OSError:
                continue
            if re.search(r'HID_ID=\w+:0*0D62:0*BA51', u, re.IGNORECASE):
                return cls('/dev/' + h.name)
        return None

    def effect(self, mode: int, rgb: RGB, speed: int, brightness: int, direction: int = 1) -> None:
        if mode not in self.EFFECTS:
            raise ValueError('Unsupported logo effect')
        fd = os.open(self.path, OPEN_FLAGS)
        try:
            # DarfonUSBLogo.dll logo path RVA 0x1e20 (the 0x16c0 path is keyboard).
            # Logo commands use 08/03 and the fixed speed field 11.
            for packet in (frame(0xB1), frame(0x08, 0x02),
                           frame(0x14, 0, 0, *rgb, 0),
                           frame(0x08, 3, self.EFFECTS[mode], 11, brightness, 0, 0)):
                send_feature(fd, packet)
                time.sleep(0.15)
        finally:
            os.close(fd)
