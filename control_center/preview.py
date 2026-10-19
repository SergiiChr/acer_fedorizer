# SPDX-License-Identifier: GPL-3.0-only
"""Explicit deterministic preview data. Never connects to hardware or session D-Bus."""
import copy


def layout():
    rows=[['Esc']+[f'F{i}' for i in range(1,13)]+['Del'],
          ['`','1','2','3','4','5','6','7','8','9','0','−','=','Back'],
          ['Tab','Q','W','E','R','T','Y','U','I','O','P','[',']','\\'],
          ['Caps','A','S','D','F','G','H','J','K','L',';','\'','Enter'],
          ['Shift','Z','X','C','V','B','N','M',',','.','/','Shift','↑'],
          ['Ctrl','Fn','Super','Alt','Space','Alt','Ctrl','←','↓','→']]
    lamps=[]
    usages={'A':4,'D':7,'S':22,'W':26,'Esc':41}
    for row,keys in enumerate(rows):
        x=0
        for key in keys:
            width=4 if key=='Space' else 1.45 if key in ('Tab','Caps','Shift','Enter','Back') else 1
            lamps.append(dict(id=len(lamps),x=x*100,y=row*100,programmable=True,key_usage=usages.get(key,0),label=key,width=width))
            x+=width
    return dict(width=1600,height=600,lamps=lamps)


STATE=dict(version='0.8.0',driver_version='Stock acer_wmi + USB HID',laptop_type='Predator PH16-72',
    thermal_profile=dict(current='balanced',available=['low-power','quiet','balanced','balanced-performance','performance']),
    available_features=['thermal_profile','fan_speed','four_zone_mode','per_zone_mode','per_key_mode','usb_logo','lightbar','battery_limiter','backlight_timeout'],
    fan_speed=dict(cpu='0',gpu='0'),fan_rpm=dict(cpu=2170,gpu=1890),ac_online=True,battery_limiter='1',backlight_timeout='1',
    lighting_modes=dict(keyboard=list(range(10)),wasd=[0,1,2,3,7],logo=[0,1,2,9],lightbar=[0,1,2,3],all=[0,1,2]),
    lighting_state={target:dict(mode=0,color='5bbfbd',brightness=80,speed=5,direction=1,link_wasd=True) for target in ('keyboard','wasd','logo','lightbar')},
    lightbar_status='available',lighting_devices=[dict(target='keyboard',path='Preview LampArray'),dict(target='logo',path='Preview lid controller')])


class PreviewClient:
    def __init__(self): self.state=copy.deepcopy(STATE); self.commands=[]
    def command(self, command, params=None):
        params=params or {}
        self.commands.append((command,copy.deepcopy(params)))
        if command=='get_keyboard_layout': return layout()
        if command=='set_thermal_profile': self.state['thermal_profile']['current']=params['profile']
        elif command=='set_lighting': self.state['lighting_state'][params['target']]=dict(params)
        elif command=='set_fan_speed': self.state['fan_speed']={k:str(params[k]) for k in ('cpu','gpu')}
        elif command.startswith('set_') and 'enabled' in params: self.state[command[4:]]='1' if params['enabled'] else '0'
        return copy.deepcopy(self.state)
    def close(self): pass


def sample(gpu=False):
    return dict(cpu_usage=18.4,cpu_temperature=54,memory_used=9.8,memory_total=31.1,
                cores=[2.1,2.3,2.2,2.5,2.1,2.4,2.2,2.3]+[1.3+(i%4)/10 for i in range(16)],
                gpu=dict(temperature=42,usage=3,memory_used=486,memory_total=12282,power=5.2,core=210,memory_clock=405) if gpu else None,
                battery=dict(capacity=78,status='Charging',health=97,hours=0.72,cycles=126,manufacturer='SMP',model='AP21D8M'))
