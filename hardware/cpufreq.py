# SPDX-License-Identifier: GPL-3.0-only
"""Frequency caps per core type through stock cpufreq sysfs, saved and reasserted when other tools change them."""
import contextlib
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TypedDict

log = logging.getLogger('fedorizer')
# Caps use 100 MHz steps, so a written value reads back unchanged and reassertion never loops.
STEP = 100000


class CoreType(StrEnum):
    PERFORMANCE = 'performance'
    EFFICIENCY = 'efficiency'


# Hybrid Intel CPUs list each core type's logical CPUs here.
CORE_LISTS = {CoreType.PERFORMANCE: 'devices/cpu_core/cpus', CoreType.EFFICIENCY: 'devices/cpu_atom/cpus'}


class CoreLimit(TypedDict):
    minimum: int
    maximum: int
    limit: int | None
    current: list[int]


def cpu_list(text: str) -> list[int]:
    """Parse a kernel CPU list such as '0-7,16'."""
    cpus: list[int] = []
    for part in filter(None, text.strip().split(',')):
        first, _, last = part.partition('-')
        cpus.extend(range(int(first), int(last or first) + 1))
    return cpus


def khz(path: Path) -> int:
    value = path.read_text().strip()
    if not value.isdecimal():
        raise ValueError(f'Unreadable frequency in {path}')
    return int(value)


@dataclass(frozen=True)
class CoreGroup:
    """Logical CPUs of one core type with their hardware frequency range in kHz."""
    files: tuple[Path, ...]
    minimum: int
    maximum: int

    def current(self) -> list[int]:
        """Lowest and highest readable scaling_max_freq across the group, or an empty list if none is readable."""
        values = []
        for path in self.files:
            with contextlib.suppress(OSError, ValueError):
                values.append(khz(path))
        return [min(values), max(values)] if values else []

    def write(self, value: int, only_changed: bool = False) -> None:
        for path in self.files:
            if not only_changed or khz(path) != value:
                path.write_text(str(value))


class CpuLimits:
    def __init__(self, sys_root: Path, state_file: Path) -> None:
        self.state_file = state_file
        self.groups: dict[CoreType, CoreGroup] = {}
        for kind, listing in CORE_LISTS.items():
            try:
                cpus = cpu_list((sys_root / listing).read_text())
                files = tuple(sys_root / f'devices/system/cpu/cpu{cpu}/cpufreq/scaling_max_freq' for cpu in cpus)
                first = files[0].parent
                self.groups[kind] = CoreGroup(files, khz(first / 'cpuinfo_min_freq'), khz(first / 'cpuinfo_max_freq'))
            except (OSError, ValueError, IndexError):
                continue
        self.saved: dict[CoreType, int | None] = dict.fromkeys(self.groups)
        with contextlib.suppress(OSError, ValueError):
            if isinstance(saved := json.loads(state_file.read_text()), dict):
                self.saved = self.parse(saved)

    def parse(self, params: Mapping[str, object]) -> dict[CoreType, int | None]:
        """Validate a cap for every core type: None for no cap, else kHz in 100 MHz steps within the hardware range."""
        if not self.groups:
            raise ValueError('CPU frequency limits unavailable')
        limits: dict[CoreType, int | None] = {}
        for kind, group in self.groups.items():
            if kind not in params:
                raise ValueError(f'Expected a {kind} core limit')
            value = params[kind]
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value % STEP or
                                      not group.minimum <= value <= group.maximum):
                raise ValueError(f'Expected a {kind} core limit of {group.minimum}–{group.maximum} kHz in 100 MHz steps')
            limits[kind] = value
        return limits

    def state(self) -> dict[str, CoreLimit]:
        return {kind: {'minimum': group.minimum, 'maximum': group.maximum, 'limit': self.saved[kind],
                       'current': group.current()} for kind, group in self.groups.items()}

    def set(self, limits: dict[CoreType, int | None]) -> None:
        """Apply caps, writing the hardware maximum where there is none; on failure reapply the saved caps."""
        try:
            for kind, group in self.groups.items():
                group.write(limits[kind] or group.maximum)
        except OSError:
            with contextlib.suppress(OSError):
                for kind, group in self.groups.items():
                    group.write(self.saved[kind] or group.maximum)
            raise
        self.saved = limits
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(limits))
        os.replace(tmp, self.state_file)

    def enforce(self) -> None:
        """Rewrite saved caps on CPUs where another tool changed them; types without a cap are left alone."""
        for kind, group in self.groups.items():
            if (value := self.saved[kind]) is not None:
                try:
                    group.write(value, only_changed=True)
                except (OSError, ValueError) as error:
                    log.warning('Could not reassert %s core limit: %s', kind, error)
