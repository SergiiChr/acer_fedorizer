# SPDX-License-Identifier: GPL-3.0-only
"""CPU package power from the stock intel-rapl powercap energy counter, which only root can read."""
import time
from pathlib import Path

# Readings closer than this repeat the last average, so the socket never exposes the counter at fine time resolution.
MIN_INTERVAL = 1.0
# A longer gap, such as sleep or a minimized window, gives a stale average or misses counter wraps, so it starts over.
MAX_INTERVAL = 10.0


class PackagePower:
    def __init__(self, sys_root: Path) -> None:
        try:
            self.domain = next((p for p in sorted((sys_root / 'class/powercap').glob('intel-rapl:*'))
                                if (p / 'name').is_file() and (p / 'name').read_text().strip() == 'package-0'), None)
            self.wrap = int((self.domain / 'max_energy_range_uj').read_text()) + 1 if self.domain else 0
        except (OSError, ValueError):
            self.domain, self.wrap = None, 0
        self.last: tuple[float, int] | None = None
        self.watts: float | None = None

    def read(self) -> float | None:
        """Average package power in watts since the previous reading at least MIN_INTERVAL ago, rounded to 0.1 W.
        None until two readings at most MAX_INTERVAL apart exist, or when the counter is unreadable.
        """
        if not self.domain:
            return None
        # Boot time keeps counting during sleep, while the energy counter may count on or reset.
        now = time.clock_gettime(time.CLOCK_BOOTTIME)
        if self.last and now - self.last[0] < MIN_INTERVAL:
            return self.watts
        try:
            energy = int((self.domain / 'energy_uj').read_text())
        except (OSError, ValueError):
            self.last, self.watts = None, None
            return None
        if self.last and now - self.last[0] <= MAX_INTERVAL:
            self.watts = round((energy - self.last[1]) % self.wrap / 1e6 / (now - self.last[0]), 1)
        else:
            self.watts = None
        self.last = (now, energy)
        return self.watts
