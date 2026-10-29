# SPDX-License-Identifier: GPL-3.0-only
"""UI-independent editing and validation; no GTK or hardware imports."""
import contextlib
import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Self

from .client import JsonDict

EFFECTS = {0:'Static', 1:'Breathing', 2:'Neon', 3:'Wave', 4:'Fireball',
           5:'Heartbeat', 6:'Dazzling', 7:'Snake', 8:'Ripple', 9:'Rain'}
PROFILES = {'low-power':'Eco', 'quiet':'Quiet', 'balanced':'Balanced',
            'balanced-performance':'Performance', 'performance':'Turbo'}
# UI-only keyboard choice: four static zones, applied with set_per_zone_mode instead of an effect.
ZONE_MODE = 10
EFFECT_NAMES = {**EFFECTS, ZONE_MODE: 'Four zones'}
ZONE_COLORS = ('5bbfbd', '73a7d8', 'a691d9', 'd6a46e')
TARGETS = {'keyboard':'Keyboard', 'wasd':'WASD keys', 'logo':'Lid logo',
           'lightbar':'Rear light bar', 'all':'All lights (sync)'}


def uses_palette(target: str, mode: int) -> bool:
    # MAG/WASD Wave has a mode-specific RGB color in the PH16-72 controller.
    return mode in (2,3) and not (target=='wasd' and mode==3)


def rgb_hex(value: object) -> str:
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
    zones: tuple[str, ...] = ZONE_COLORS

    @classmethod
    def from_state(cls, state: Mapping[str, object], modes: Collection[int]) -> Self:
        draft = cls()
        for field in ('mode','brightness','speed','direction'):
            value = state.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                setattr(draft, field, value)
        with contextlib.suppress(ValueError):
            draft.color = rgb_hex(state.get('color', draft.color))
        draft.mode = draft.mode if draft.mode in modes else next(iter(modes), 0)
        draft.brightness = max(0, min(100, draft.brightness))
        draft.speed = max(1, min(9, draft.speed))
        draft.direction = draft.direction if draft.direction in (1,2) else 1
        draft.link_wasd = state.get('link_wasd') is not False
        zones = state.get('colors') if state.get('kind') == 'zones' else None
        if ZONE_MODE in modes and isinstance(zones, list) and len(zones) == 4:
            try:
                draft.zones = tuple(rgb_hex(zone) for zone in zones)
                draft.mode = ZONE_MODE
            except ValueError:
                pass
        return draft

    def request(self, target: str) -> tuple[str, JsonDict]:
        """Return the (command, params) pair that applies this draft."""
        if self.mode == ZONE_MODE:
            return 'set_per_zone_mode', {f'zone{i}': rgb_hex(zone) for i, zone in enumerate(self.zones, 1)}
        result = asdict(self)
        del result['zones']
        result['color'] = rgb_hex(self.color)
        result['target'] = target
        return 'set_lighting', result


def full_key_map(lamps: Iterable[Mapping[str, object]], saved: Mapping[str, object] | None = None,
                 default: str = '5bbfbd') -> dict[str, str]:
    saved = saved or {}
    return {str(lamp['id']): rgb_hex(saved.get(str(lamp['id']), default))
            for lamp in lamps if lamp.get('programmable')}
