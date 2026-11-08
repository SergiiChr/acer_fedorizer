# SPDX-License-Identifier: GPL-3.0-only
"""Frequency caps per core type through stock cpufreq sysfs, saved and reasserted when other tools raise them."""
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
    current: tuple[int, int] | None


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


def online(path: Path) -> bool:
    """Whether the CPU owning a cpufreq file is online; CPUs that cannot go offline have no online file."""
    try:
        return path.parents[1].joinpath('online').read_text().strip() != '0'
    except OSError:
        return True


@dataclass(frozen=True)
class CoreGroup:
    """Logical CPUs of one core type: each scaling_max_freq file with that CPU's maximum, and the group's kHz range.
    Favored cores can reach a higher maximum than the rest of their type.
    """
    cpus: tuple[tuple[Path, int], ...]
    minimum: int
    maximum: int

    def current(self) -> tuple[int, int] | None:
        """Lowest and highest readable scaling_max_freq across the group, or None if none is readable."""
        values = []
        for path, _ in self.cpus:
            with contextlib.suppress(OSError, ValueError):
                values.append(khz(path))
        return (min(values), max(values)) if values else None

    def write(self, cap: int | None, only_raised: bool = False) -> None:
        """Cap every online CPU at its own maximum or lower, where None means its maximum.
        With only_raised, CPUs at or below the cap are left alone, so lower caps from tools such as nvidia-powerd stay.
        cpufreq rejects writes to offline CPUs, such as threads with SMT off.
        """
        for path, maximum in self.cpus:
            value = maximum if cap is None else min(cap, maximum)
            if only_raised:
                # Offline CPUs refuse reads too, so the online check runs only for a cap that may be raised.
                with contextlib.suppress(OSError, ValueError):
                    if khz(path) <= value:
                        continue
            if online(path):
                path.write_text(str(value))


class CpuLimits:
    def __init__(self, sys_root: Path, state_file: Path) -> None:
        self.state_file = state_file
        self.groups: dict[CoreType, CoreGroup] = {}
        for kind, listing in CORE_LISTS.items():
            try:
                cpus = cpu_list((sys_root / listing).read_text())
            except (OSError, ValueError):
                continue
            folders = [sys_root / f'devices/system/cpu/cpu{cpu}/cpufreq' for cpu in cpus]
            ranges: dict[Path, tuple[int, int]] = {}
            for folder in folders:
                with contextlib.suppress(OSError, ValueError):
                    ranges[folder] = khz(folder / 'cpuinfo_min_freq'), khz(folder / 'cpuinfo_max_freq')
            if ranges:
                # A CPU offline at startup has no readable range; the group maximum stands in, which cpufreq clamps.
                maximum = max(high for _, high in ranges.values())
                files = tuple((folder / 'scaling_max_freq', ranges.get(folder, (0, maximum))[1]) for folder in folders)
                self.groups[kind] = CoreGroup(files, min(low for low, _ in ranges.values()), maximum)
        self.saved: dict[CoreType, int | None] = dict.fromkeys(self.groups)
        with contextlib.suppress(OSError, ValueError):
            if isinstance(saved := json.loads(state_file.read_text()), dict):
                self.saved = self.parse(saved)

    def parse(self, params: Mapping[str, object]) -> dict[CoreType, int | None]:
        """Validate a cap for every core type: None or the maximum for no cap, else kHz in 100 MHz steps in range."""
        if not self.groups:
            raise ValueError('CPU frequency limits unavailable')
        limits: dict[CoreType, int | None] = {}
        for kind, group in self.groups.items():
            if kind not in params:
                raise ValueError(f'Expected a {kind} core limit')
            value = params[kind]
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value % STEP or
                                      not group.minimum <= value <= group.maximum):
                raise ValueError(
                    f'Expected a {kind} core limit of {group.minimum}–{group.maximum} kHz in 100 MHz steps')
            limits[kind] = None if value == group.maximum else value
        return limits

    def state(self) -> dict[str, CoreLimit]:
        return {kind: {'minimum': group.minimum, 'maximum': group.maximum, 'limit': self.saved[kind],
                       'current': group.current()} for kind, group in self.groups.items()}

    def set(self, limits: dict[CoreType, int | None]) -> None:
        """Apply and save caps, restoring each CPU's own maximum where there is none; on failure reapply saved caps."""
        try:
            for kind, group in self.groups.items():
                group.write(limits[kind])
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_suffix('.tmp')
            tmp.write_text(json.dumps(limits))
            os.replace(tmp, self.state_file)
        except OSError:
            with contextlib.suppress(OSError):
                for kind, group in self.groups.items():
                    group.write(self.saved[kind])
            raise
        self.saved = limits

    def enforce(self) -> None:
        """Rewrite saved caps on CPUs where another tool raised them above; types without a cap are left alone."""
        for kind, group in self.groups.items():
            if (value := self.saved[kind]) is not None:
                try:
                    group.write(value, only_raised=True)
                except (OSError, ValueError) as error:
                    log.warning('Could not reassert %s core limit: %s', kind, error)
