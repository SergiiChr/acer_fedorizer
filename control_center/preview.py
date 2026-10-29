# SPDX-License-Identifier: GPL-3.0-only
"""Explicit deterministic preview data. Never connects to hardware or session D-Bus."""
import copy
import json
from pathlib import Path

from .client import JSON
from .installation import CHECKS, Check, Report
from .telemetry import Battery, Gpu, Sample

from .client import JsonDict

def layout() -> JSON:
    # Measured PH16-72 HID geometry; labels for unbound lamps stay explicit IDs.
    data: JSON=json.loads(Path(__file__).with_name('keyboard-preview.json').read_text())
    return data


def fan(percent: int) -> JSON:
    """Fan state as the service reports it for a set_fan_speed percentage."""
    return {'mode': 'auto' if percent==0 else 'max' if percent==100 else 'manual','percent': percent}


class PreviewClient:
    """Answers service commands from in-memory preview state and records every command it receives."""
    def __init__(self) -> None:
        self.commands: list[tuple[str, dict[str, JSON]]]=[]
        self.profile='balanced'
        self.fans: dict[str, JSON]={'cpu': fan(0),'gpu': fan(0)}
        self.switches: dict[str, JSON]={'battery_limiter': True,'backlight_timeout': True}
        self.lighting: dict[str, JSON]={target:{'mode': 0,'color': '5bbfbd','brightness': 80,'speed': 5,'direction': 1,'link_wasd': True}
                                        for target in ('keyboard','wasd','logo','lightbar')}

    def settings(self) -> JSON:
        state: dict[str, JSON]={'version': '0.8.0','driver_version': 'Stock acer_wmi + USB HID','laptop_type': 'Predator PH16-72',
            'thermal_profile': {'current': self.profile,'available': ['low-power','quiet','balanced','balanced-performance','performance']},
            'available_features': ['thermal_profile','fan_speed','four_zone_mode','per_zone_mode','per_key_mode','usb_logo','lightbar','battery_limiter','backlight_timeout'],
            'fans': self.fans,'fan_rpm': {'cpu': 2170,'gpu': 1890},'ac_online': True,**self.switches,
            'lighting_modes': {'keyboard': list(range(10)),'wasd': [0,1,2,3,7],'logo': [0,1,2,9],'lightbar': [0,1,2,3],'all': [0,1,2]},
            'lighting_state': self.lighting}
        return copy.deepcopy(state)

    def command(self, command: str, params: dict[str, JSON] | None=None) -> JSON:
        params=params or {}
        self.commands.append((command,copy.deepcopy(params)))
        if command=='get_keyboard_layout': return layout()
        if command=='set_thermal_profile': self.profile=str(params['profile'])
        elif command=='set_lighting': self.lighting[str(params['target'])]=dict(params)
        elif command=='set_per_zone_mode': self.lighting['keyboard']={'kind': 'zones','colors': [params[f'zone{i}'] for i in range(1,5)]}
        elif command=='set_per_key': self.lighting['per_key']=copy.deepcopy(params)
        elif command=='set_fan_speed': self.fans={key:fan(percent if isinstance(percent:=params[key],int) else 0) for key in ('cpu','gpu')}
        elif command.startswith('set_') and 'enabled' in params: self.switches[command[4:]]=params['enabled'] is True
        return self.settings()

    def close(self) -> None: pass


BATTERY=Battery(capacity=78,status='Charging',health=97,hours=0.72,cycles=126,manufacturer='SMP',model='AP21D8M')


def sample(gpu: bool=False) -> Sample:
    return Sample(cpu_usage=18.4,cpu_temperature=54,memory_used=9.8,memory_total=31.1,
                  cores=[2.1,2.3,2.2,2.5,2.1,2.4,2.2,2.3]+[1.3+(i%4)/10 for i in range(16)],
                  gpu=Gpu(temperature=42,usage=3,memory_used=486,memory_total=12282,power=5.2,core=210,memory_clock=405) if gpu else None,
                  battery=BATTERY)


def installation_status() -> Report:
    return Report(model='Predator PH16-72',kernel='7.2.11-200.fc44.x86_64',installed=True,healthy=True,
                  checks=[Check(key,title,True,
                                'Running.' if key=='running' else 'Responding.' if key=='ping' else
                                'Enabled.' if key=='enabled' else 'Loaded.' if key=='module' else
                                'Installed for the running kernel.' if key=='dkms' else 'Available.' if key=='socket' else 'Installed.')
                          for key,title in CHECKS])
