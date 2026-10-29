# SPDX-License-Identifier: GPL-3.0-only
"""Read-only Linux sampling. NVIDIA is queried only on explicit opt-in."""
import math
import subprocess
import time
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


def text(path: str | Path, default: str = '') -> str:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def number(value: object) -> float | None:
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError):
        return None


def gpu_fields(output: str) -> dict[str, float | None]:
    values = output.strip().splitlines()[0].split(',') if output.strip() else []
    if len(values) != 9:
        raise ValueError('Incomplete GPU sample')
    temp, usage, used, total, average, instant, maximum, core, memory = map(number, values)
    bound = maximum * 1.15 if maximum and maximum > 0 else 500
    power = next((v for v in (average, instant) if v is not None and v <= bound), None)
    return {'temperature': temp, 'usage': usage, 'memory_used': used, 'memory_total': total,
                'power': power, 'core': core, 'memory_clock': memory}


class Telemetry:
    def __init__(self, sys_root: str | Path = '/sys', proc_root: str | Path = '/proc') -> None:
        self.sys = Path(sys_root)
        self.proc = Path(proc_root)
        self.previous = None
        self.gpu_queries = GPU_QUERIES

    def sample(self, gpu: bool = False) -> JsonDict:
        result = {'cpu_usage': None, 'cpu_temperature': None, 'memory_used': None,
                      'memory_total': None, 'cores': [], 'gpu': None, 'battery': {}}
        try:
            ticks = [int(v) for v in text(self.proc/'stat').splitlines()[0].split()[1:9]]
            total, idle, now = sum(ticks), sum(ticks[3:5]), time.monotonic()
            if self.previous and now - self.previous[2] <= MAX_SAMPLE_GAP:
                delta = total - self.previous[0]
                result['cpu_usage'] = 100 * (1 - (idle-self.previous[1])/delta) if delta > 0 else None
            self.previous = total, idle, now
        except (ValueError, IndexError):
            pass
        mem = {}
        for line in text(self.proc/'meminfo').splitlines():
            parts=line.split()
            if len(parts)>1: mem[parts[0].rstrip(':')]=number(parts[1])
        total, available=mem.get('MemTotal'),mem.get('MemAvailable')
        if total and available is not None:
            result.update(memory_total=total/1024**2,memory_used=(total-available)/1024**2)
        cores={}
        for cpu in self.sys.glob('devices/system/cpu/cpu[0-9]*'):
            identity=(text(cpu/'topology/physical_package_id'),text(cpu/'topology/core_id'))
            speed=number(text(cpu/'cpufreq/scaling_cur_freq'))
            if identity[1] and speed is not None: cores.setdefault(identity,[]).append(speed/1e6)
        result['cores']=[sum(v)/len(v) for _,v in sorted(cores.items(),key=lambda x:tuple(int(v or 0) for v in x[0]))]
        temperatures=[]
        for hwmon in self.sys.glob('class/hwmon/hwmon*'):
            if text(hwmon/'name') not in ('coretemp','k10temp','zenpower'): continue
            for path in hwmon.glob('temp*_input'):
                value=number(text(path))
                if value is not None and 0 < value < 150000: temperatures.append(value/1000)
        result['cpu_temperature']=max(temperatures,default=None)
        result['battery']=self.battery()
        if gpu:
            result['gpu']=self.gpu()
        return result

    def gpu(self) -> dict[str, float | None] | None:
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

    def battery(self) -> dict[str, float | str | None]:
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
            return {'capacity': capacity,'status': status,'health': min(100,full/design*100) if full and design else None,
                        'hours': hours,'cycles': number(text(battery/'cycle_count')),
                        'manufacturer': text(battery/'manufacturer','Unknown'),'model': text(battery/'model_name','Battery')}
        return {}
