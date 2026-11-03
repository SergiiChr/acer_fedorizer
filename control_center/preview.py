# SPDX-License-Identifier: GPL-3.0-only
"""Explicit deterministic preview data. Never connects to hardware or session D-Bus."""
import copy
import json
import math
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from .client import JSON
from .display import PanelStatus
from .installation import CHECKS, Check, Report
from .models import FanMode
from .telemetry import Battery, Core, CoreKind, Gpu, Sample


def layout() -> JSON:
    # Measured PH16-72 HID geometry; labels for unbound lamps stay explicit IDs.
    data: JSON=json.loads(Path(__file__).with_name('keyboard-preview.json').read_text())
    return data


def fan(percent: int) -> JSON:
    """Fan state as the service reports it for a set_fan_speed percentage."""
    return {'mode': FanMode.AUTO if percent==0 else FanMode.MAX if percent==100 else FanMode.MANUAL,'percent': percent}


class PreviewClient:
    """Answers service commands from in-memory preview state and records every command it receives."""
    def __init__(self) -> None:
        # Window workers call in parallel, like the locked live client.
        self.lock=threading.Lock()
        self.commands: list[tuple[str, dict[str, JSON]]]=[]
        self.profile='balanced'
        self.fans: dict[str, JSON]={'cpu': fan(0),'gpu': fan(0)}
        self.switches: dict[str, JSON]={'battery_limiter': True,'backlight_timeout': True}
        self.cpu_limits: dict[str, int | None]={'performance': 4000000,'efficiency': 3000000}
        self.lighting: dict[str, JSON]={target:{'mode': 0,'color': '5bbfbd','brightness': 80,'speed': 5,'direction': 1,'link_wasd': True}
                                        for target in ('keyboard','wasd','logo','lightbar')}
        self.static: dict[str, JSON]={'version': '0.8.0','driver_version': 'Stock acer_wmi + USB HID','laptop_type': 'Predator PH16-72',
            'available_features': ['thermal_profile','fan_speed','cpu_frequency_limit','four_zone_mode','per_zone_mode','per_key_mode','usb_logo','lightbar','battery_limiter','backlight_timeout'],
            'fan_rpm': {'cpu': 2170,'gpu': 1890},'ac_online': True,
            'lighting_modes': {'keyboard': list(range(10)),'wasd': [0,1,2,3,7],'logo': [0,1,2,9],'lightbar': [0,1,2,3],'all': [0,1,2]}}

    def settings(self) -> JSON:
        """Return a get_all_settings reply that shares the static values, so callers must not change it."""
        limits: dict[str, JSON]={}
        for kind,maximum in (('performance',5600000),('efficiency',4100000)):
            cap=self.cpu_limits[kind] or maximum
            limits[kind]={'minimum': 800000,'maximum': maximum,'limit': self.cpu_limits[kind],'current': [cap,cap]}
        return {**self.static,**self.switches,'fans': self.fans,'lighting_state': copy.deepcopy(self.lighting),'cpu_limits': limits,
                'thermal_profile': {'current': self.profile,'available': ['low-power','quiet','balanced','balanced-performance','performance']}}

    def command(self, command: str, params: dict[str, JSON] | None=None) -> JSON:
        with self.lock: return self.answer(command,params or {})

    def answer(self, command: str, params: dict[str, JSON]) -> JSON:
        self.commands.append((command,copy.deepcopy(params)))
        if command=='get_keyboard_layout': return layout()
        if command=='set_thermal_profile':
            self.profile=str(params['profile'])
            return {'current': self.profile}
        if command=='set_lighting': self.lighting[str(params['target'])]=dict(params)
        elif command=='set_per_zone_mode': self.lighting['keyboard']={'kind': 'zones','colors': [params[f'zone{i}'] for i in range(1,5)]}
        elif command=='set_per_key': self.lighting['per_key']=copy.deepcopy(params)
        elif command=='set_cpu_limits': self.cpu_limits={kind:limit if isinstance(limit:=params[kind],int) else None for kind in ('performance','efficiency')}
        elif command=='set_fan_speed': self.fans={key:fan(percent if isinstance(percent:=params[key],int) else 0) for key in ('cpu','gpu')}
        elif command.startswith('set_') and 'enabled' in params: self.switches[command[4:]]=params['enabled'] is True
        return self.settings()

    def close(self) -> None: pass


class PreviewServices:
    """Preview data for every window data source; the display toggle only changes this in-memory state."""
    preview = True
    cpu_history = tuple(25+8*math.sin(i*.18)+3*math.sin(i*.7) for i in range(60))

    def __init__(self) -> None:
        self.client = PreviewClient()
        self.panel = PanelStatus(True, False, 'eDP-1', 'default', 'Built-in display · Native SDR supported')
        self.tick = 0

    def installation_status(self) -> Report:
        return Report(model='Predator PH16-72',kernel='7.2.11-200.fc44.x86_64',installed=True,healthy=True,
                      checks=[Check(key,title,True,
                                    'Running.' if key=='running' else 'Responding.' if key=='ping' else
                                    'Enabled.' if key=='enabled' else 'Loaded.' if key=='module' else
                                    'Installed for the running kernel.' if key=='dkms' else 'Available.' if key=='socket' else 'Installed.')
                              for key,title in CHECKS])

    def display_status(self) -> PanelStatus:
        return self.panel

    def set_display(self, connector: str, enabled: bool) -> PanelStatus:
        self.panel = replace(self.panel, enabled=enabled, mode='sdr-native' if enabled else 'default')
        return self.panel

    def watch_display(self, callback: Callable[[], None]) -> None:
        pass

    def sample(self, gpu: bool) -> Sample:
        return Sample(cpu_usage=18.4,cpu_temperature=54,memory_used=9.8,memory_total=31.1,
                      gpu=Gpu(temperature=42,usage=3,memory_used=486,memory_total=12282,power=5.2) if gpu else None,
                      battery=self.battery())

    def cores(self) -> list[Core]:
        # Each call moves the pattern, so the averages in the chart differ from the current values.
        self.tick+=1
        return ([Core(CoreKind.PERFORMANCE,round(2.6+1.2*math.sin(self.tick*.9+i),2)) for i in range(8)]+
                [Core(CoreKind.EFFICIENCY,round(1.9+.8*math.sin(self.tick*.7+i*1.3),2)) for i in range(16)])

    def battery(self) -> Battery:
        return Battery(capacity=78,status='Charging',health=97,hours=0.72,cycles=126,manufacturer='SMP',model='AP21D8M')
