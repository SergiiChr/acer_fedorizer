# SPDX-License-Identifier: GPL-3.0-only
"""UI-independent editing and validation; no GTK or hardware imports."""
from dataclasses import dataclass, asdict
import re

EFFECTS = {0:'Static', 1:'Breathing', 2:'Neon', 3:'Wave', 4:'Fireball',
           5:'Heartbeat', 6:'Dazzling', 7:'Snake', 8:'Ripple', 9:'Rain'}
PROFILES = {'low-power':'Eco', 'quiet':'Quiet', 'balanced':'Balanced',
            'balanced-performance':'Balanced performance', 'performance':'Performance'}
TARGETS = {'keyboard':'Keyboard', 'wasd':'WASD', 'logo':'Lid logo',
           'lightbar':'Rear lightbar', 'all':'All lights'}


def rgb_hex(value):
    value = str(value).strip().removeprefix('#')
    if not re.fullmatch('[a-fA-F0-9]{6}', value):
        raise ValueError('Enter a color as #RRGGBB')
    return value.lower()


@dataclass
class LightingDraft:
    mode: int = 0
    color: str = '5bbfbd'
    brightness: int = 80
    speed: int = 5
    direction: int = 1
    link_wasd: bool = True

    @classmethod
    def from_state(cls, state, modes):
        draft = cls()
        for field in ('mode','brightness','speed','direction'):
            value = state.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                setattr(draft, field, value)
        try:
            draft.color = rgb_hex(state.get('color', draft.color))
        except ValueError:
            pass
        draft.mode = draft.mode if draft.mode in modes else next(iter(modes), 0)
        draft.brightness = max(0, min(100, draft.brightness))
        draft.speed = max(1, min(9, draft.speed))
        draft.direction = draft.direction if draft.direction in (1,2) else 1
        draft.link_wasd = state.get('link_wasd') is not False
        return draft

    def params(self, target):
        result = asdict(self)
        result['color'] = rgb_hex(self.color)
        result['target'] = target
        return result


def full_key_map(lamps, saved=None, default='5bbfbd'):
    saved = saved or {}
    return {str(lamp['id']): rgb_hex(saved.get(str(lamp['id']), default))
            for lamp in lamps if lamp.get('programmable')}
