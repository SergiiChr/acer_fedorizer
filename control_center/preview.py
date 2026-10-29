# SPDX-License-Identifier: GPL-3.0-only
"""Explicit deterministic preview data. Never connects to hardware or session D-Bus."""
import copy
import json
from pathlib import Path

from .installation import CHECKS

from .client import JsonDict


def layout() -> JsonDict:
    # Measured PH16-72 HID geometry; labels for unbound lamps stay explicit IDs.
    return json.loads(Path(__file__).with_name('keyboard-preview.json').read_text())


STATE={'version': '0.8.0','driver_version': 'Stock acer_wmi + USB HID','laptop_type': 'Predator PH16-72',
    'thermal_profile': {'current': 'balanced','available': ['low-power','quiet','balanced','balanced-performance','performance']},
    'available_features': ['thermal_profile','fan_speed','four_zone_mode','per_zone_mode','per_key_mode','usb_logo','lightbar','battery_limiter','backlight_timeout'],
    'fan_speed': {'cpu': '0','gpu': '0'},'fan_rpm': {'cpu': 2170,'gpu': 1890},'ac_online': True,'battery_limiter': '1','backlight_timeout': '1',
    'lighting_modes': {'keyboard': list(range(10)),'wasd': [0,1,2,3,7],'logo': [0,1,2,9],'lightbar': [0,1,2,3],'all': [0,1,2]},
    'lighting_state': {target:{'mode': 0,'color': '5bbfbd','brightness': 80,'speed': 5,'direction': 1,'link_wasd': True} for target in ('keyboard','wasd','logo','lightbar')}}


class PreviewClient:
    def __init__(self) -> None: self.state=copy.deepcopy(STATE); self.commands=[]
    def command(self, command: str, params: JsonDict | None = None) -> JsonDict:
        params=params or {}
        self.commands.append((command,copy.deepcopy(params)))
        if command=='get_keyboard_layout': return layout()
        if command=='set_thermal_profile': self.state['thermal_profile']['current']=params['profile']
        elif command=='set_lighting': self.state['lighting_state'][params['target']]=dict(params)
        elif command=='set_per_zone_mode': self.state['lighting_state']['keyboard']={'kind': 'zones','colors': [params[f'zone{i}'] for i in range(1,5)]}
        elif command=='set_per_key': self.state['lighting_state']['per_key']=copy.deepcopy(params)
        elif command=='set_fan_speed': self.state['fan_speed']={k:str(params[k]) for k in ('cpu','gpu')}
        elif command.startswith('set_') and 'enabled' in params: self.state[command[4:]]='1' if params['enabled'] else '0'
        return copy.deepcopy(self.state)
    def close(self) -> None: pass


def sample(gpu: bool = False) -> JsonDict:
    return {'cpu_usage': 18.4,'cpu_temperature': 54,'memory_used': 9.8,'memory_total': 31.1,
                'cores': [2.1,2.3,2.2,2.5,2.1,2.4,2.2,2.3]+[1.3+(i%4)/10 for i in range(16)],
                'gpu': {'temperature': 42,'usage': 3,'memory_used': 486,'memory_total': 12282,'power': 5.2,'core': 210,'memory_clock': 405} if gpu else None,
                'battery': {'capacity': 78,'status': 'Charging','health': 97,'hours': 0.72,'cycles': 126,'manufacturer': 'SMP','model': 'AP21D8M'}}


def installation_status():
    return {'model': 'Predator PH16-72','kernel': '7.2.11-200.fc44.x86_64','installed': True,'healthy': True,
                'checks': [{'key': key,'title': title,'ok': True,
                             'detail': 'Running.' if key=='running' else 'Responding.' if key=='ping' else
                             'Enabled.' if key=='enabled' else 'Loaded.' if key=='module' else
                             'Installed for the running kernel.' if key=='dkms' else 'Available.' if key=='socket' else 'Installed.'}
                        for key,title in CHECKS]}
