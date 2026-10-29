# SPDX-License-Identifier: GPL-3.0-only
"""Read-only Linux sampling. NVIDIA is queried only on explicit opt-in."""
import math
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .client import JsonDict

# Newer drivers report average and instant power; older ones only power.draw.
GPU_QUERIES = (
    ('temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw.average,power.draw.instant,'
     'power.max_limit,clocks.gr,clocks.mem'),
    ('temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,power.draw,'
     'power.max_limit,clocks.gr,clocks.mem'))
# A longer gap between CPU samples would average over time the dashboard was not shown.
MAX_SAMPLE_GAP = 5.0


@dataclass(frozen=True)
class Gpu:
    temperature: float | None
    usage: float | None
    memory_used: float | None
    memory_total: float | None
    power: float | None
    core: float | None
    memory_clock: float | None


@dataclass(frozen=True)
class Battery:
    capacity: float | None
    status: str
    health: float | None
    hours: float | None
    cycles: float | None
    manufacturer: str
    model: str


@dataclass(frozen=True)
class Sample:
    """One dashboard sample; values are None when the system does not report them."""
    cpu_usage: float | None
    cpu_temperature: float | None
    memory_used: float | None
    memory_total: float | None
    cores: list[float]
    gpu: Gpu | None
    battery: Battery | None


@dataclass(frozen=True)
class CpuTicks:
    total: int
    idle: int
    time: float


def text(path: str | Path, default: str='') -> str:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def number(value: str) -> float | None:
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) and result >= 0 else None


def gpu_fields(output: str) -> Gpu:
    values = output.strip().splitlines()[0].split(',') if output.strip() else []
    if len(values) != 9:
        raise ValueError('Incomplete GPU sample')
    temp, usage, used, total, average, instant, maximum, core, memory = map(number, values)
    bound = maximum * 1.15 if maximum and maximum > 0 else 500
    power = next((v for v in (average, instant) if v is not None and v <= bound), None)
    return Gpu(temp, usage, used, total, power, core, memory)


class Telemetry:
    def __init__(self, sys_root: str | Path='/sys', proc_root: str | Path='/proc') -> None:
        self.sys = Path(sys_root)
        self.proc = Path(proc_root)
        self.previous: CpuTicks | None = None
        self.gpu_queries: tuple[str, ...] = GPU_QUERIES

    def sample(self, gpu: bool=False) -> Sample:
        return Sample(self.cpu_usage(), self.cpu_temperature(), *self.memory(), self.cores(),
                      self.gpu() if gpu else None, self.battery())

    def cpu_usage(self) -> float | None:
        """Busy share since the previous call, or None on the first call and after a long gap."""
        try:
            ticks = [int(v) for v in text(self.proc/'stat').splitlines()[0].split()[1:9]]
        except (ValueError, IndexError):
            return None
        previous, self.previous = self.previous, CpuTicks(sum(ticks), sum(ticks[3:5]), time.monotonic())
        if not previous or self.previous.time - previous.time > MAX_SAMPLE_GAP:
            return None
        delta = self.previous.total - previous.total
        return 100 * (1 - (self.previous.idle-previous.idle)/delta) if delta > 0 else None

    def memory(self) -> tuple[float | None, float | None]:
        """Used and total memory in GiB."""
        mem = {}
        for line in text(self.proc/'meminfo').splitlines():
            parts=line.split()
            if len(parts)>1: mem[parts[0].rstrip(':')]=number(parts[1])
        total, available=mem.get('MemTotal'),mem.get('MemAvailable')
        if total and available is not None: return (total-available)/1024**2,total/1024**2
        return None,None

    def cores(self) -> list[float]:
        """Average frequency in GHz of each physical core, in topology order."""
        cores: dict[tuple[str, str], list[float]]={}
        for cpu in self.sys.glob('devices/system/cpu/cpu[0-9]*'):
            identity=(text(cpu/'topology/physical_package_id'),text(cpu/'topology/core_id'))
            speed=number(text(cpu/'cpufreq/scaling_cur_freq'))
            if identity[1] and speed is not None: cores.setdefault(identity,[]).append(speed/1e6)
        return [sum(v)/len(v) for _,v in sorted(cores.items(),key=lambda x:tuple(int(v or 0) for v in x[0]))]

    def cpu_temperature(self) -> float | None:
        temperatures=[]
        for hwmon in self.sys.glob('class/hwmon/hwmon*'):
            if text(hwmon/'name') not in ('coretemp','k10temp','zenpower'): continue
            for path in hwmon.glob('temp*_input'):
                value=number(text(path))
                if value is not None and 0 < value < 150000: temperatures.append(value/1000)
        return max(temperatures,default=None)

    def gpu(self) -> Gpu | None:
        try:
            for query in self.gpu_queries:
                process=subprocess.run(['nvidia-smi','--query-gpu='+query,'--format=csv,noheader,nounits'],
                                       capture_output=True,text=True,timeout=3,check=False)
                if process.returncode == 0:
                    self.gpu_queries=(query,)  # The driver accepted it; skip failing variants from now on.
                    return gpu_fields(process.stdout)
        except (OSError,ValueError,subprocess.TimeoutExpired):
            pass
        return None

    def battery(self) -> Battery | None:
        for battery in self.sys.glob('class/power_supply/*'):
            if text(battery/'type') != 'Battery': continue
            status=text(battery/'status','Unknown')
            capacity=number(text(battery/'capacity'))
            energy=number(text(battery/'energy_now'))
            full=number(text(battery/'energy_full'))
            design=number(text(battery/'energy_full_design'))
            power=number(text(battery/'power_now'))
            if energy is None:
                energy=number(text(battery/'charge_now'))
                full=number(text(battery/'charge_full'))
                design=number(text(battery/'charge_full_design'))
                power=number(text(battery/'current_now'))
            remaining=(full-energy if status=='Charging' else energy) if full and energy is not None else None
            hours=remaining/power if power and remaining is not None and remaining>=0 else None
            return Battery(capacity,status,min(100,full/design*100) if full and design else None,hours,
                           number(text(battery/'cycle_count')),text(battery/'manufacturer','Unknown'),
                           text(battery/'model_name','Battery'))
        return None
