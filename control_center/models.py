# SPDX-License-Identifier: GPL-3.0-only
"""UI-independent editing and validation; no GTK or hardware imports."""
import contextlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum

from .client import JSON

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
SWITCHES = ('battery_limiter', 'battery_calibration', 'backlight_timeout', 'boot_animation_sound', 'lcd_override')


def uses_palette(target: str | None, mode: int) -> bool:
    # MAG/WASD Wave has a mode-specific RGB color in the PH16-72 controller.
    return mode in (2,3) and not (target=='wasd' and mode==3)


def rgb_hex(value: object) -> str:
    value = str(value).strip().removeprefix('#')
    if not re.fullmatch('[a-fA-F0-9]{6}', value):
        raise ValueError('Enter a color as #RRGGBB')
    return value.lower()


def mapping(value: JSON) -> dict[str, JSON]:
    return value if isinstance(value, dict) else {}


def integer(value: JSON) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def integers(value: JSON) -> dict[str, int]:
    """The integer entries of a JSON object, without the others."""
    return {key: number for key, item in mapping(value).items() if (number := integer(item)) is not None}


def text(value: JSON, default: str) -> str:
    return value if isinstance(value, str) else default


def strings(value: JSON) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


class CoreKind(StrEnum):
    PERFORMANCE = 'performance'
    EFFICIENCY = 'efficiency'


class FanMode(StrEnum):
    AUTO = 'auto'
    MAX = 'max'
    MANUAL = 'manual'


@dataclass(frozen=True)
class Fan:
    mode: FanMode
    percent: int

    @property
    def speed(self) -> int:
        """The set_fan_speed percentage that selects this state: 0 for automatic, 100 for full speed."""
        return 0 if self.mode == FanMode.AUTO else 100 if self.mode == FanMode.MAX else self.percent

    @classmethod
    def parse(cls, value: JSON) -> 'Fan | None':
        data = mapping(value)
        mode, percent = data.get('mode'), integer(data.get('percent'))
        return cls(FanMode(mode), percent) if isinstance(mode, str) and mode in FanMode and percent is not None else None


@dataclass(frozen=True)
class Fans:
    cpu: Fan
    gpu: Fan

    @classmethod
    def parse(cls, value: JSON) -> 'Fans | None':
        data = mapping(value)
        cpu, gpu = Fan.parse(data.get('cpu')), Fan.parse(data.get('gpu'))
        return cls(cpu, gpu) if cpu and gpu else None


@dataclass(frozen=True)
class PerKey:
    """Saved per-key colors by lamp ID and the brightness they were applied with."""
    colors: dict[str, str] = field(default_factory=dict)
    brightness: float = 80

    @classmethod
    def parse(cls, value: JSON) -> 'PerKey':
        data = mapping(value)
        brightness = data.get('brightness')
        if isinstance(brightness, bool) or not isinstance(brightness, int | float) or not math.isfinite(brightness):
            brightness = 80
        colors = {key: color for key, color in mapping(data.get('colors')).items() if isinstance(color, str)}
        return cls(colors, max(0, min(100, brightness)))


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
    def from_state(cls, state: Mapping[str, JSON], modes: Sequence[int]) -> 'LightingDraft':
        draft = cls()
        for name in ('mode','brightness','speed','direction'):
            value = integer(state.get(name))
            if value is not None:
                setattr(draft, name, value)
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

    def request(self, target: str) -> tuple[str, dict[str, JSON]]:
        """Return the (command, params) pair that applies this draft."""
        if self.mode == ZONE_MODE:
            return 'set_per_zone_mode', {f'zone{i}': rgb_hex(zone) for i, zone in enumerate(self.zones, 1)}
        result: dict[str, JSON] = asdict(self)
        del result['zones']
        result['color'] = rgb_hex(self.color)
        result['target'] = target
        return 'set_lighting', result


@dataclass(frozen=True)
class CoreLimit:
    """Frequency cap of one core type in kHz: hardware range, saved cap or None, and the lowest and highest cap in effect."""
    minimum: int
    maximum: int
    limit: int | None
    current: tuple[int, int] | None

    @classmethod
    def parse(cls, value: JSON) -> 'CoreLimit | None':
        data = mapping(value)
        minimum, maximum, limit = integer(data.get('minimum')), integer(data.get('maximum')), integer(data.get('limit'))
        raw = data.get('current')
        low, high = (integer(item) for item in raw) if isinstance(raw, list) and len(raw) == 2 else (None, None)
        if minimum is None or maximum is None or not 0 < minimum <= maximum:
            return None
        return cls(minimum, maximum, limit if limit is not None and minimum <= limit <= maximum else None,
                   (low, high) if low is not None and high is not None and low <= high else None)


@dataclass(frozen=True)
class Settings:
    """A get_all_settings reply, with defaults for anything the service did not report."""
    version: str = '—'
    driver_version: str = 'Stock kernel + HID'
    laptop_type: str = 'Unknown'
    features: tuple[str, ...] = ()
    ac_online: bool | None = None
    profile: str = ''
    profiles: tuple[str, ...] = ()
    fans: Fans | None = None
    fan_rpm: Mapping[str, int] = field(default_factory=dict)
    # Current fan speed as a share of top speed, also in automatic and full-speed modes.
    fan_percent: Mapping[str, int] = field(default_factory=dict)
    # The manual percents the firmware can hold; empty when the service did not report them.
    fan_steps: tuple[int, ...] = ()
    # Every name in SWITCHES; False when the service did not report it as on.
    switches: Mapping[str, bool] = field(default_factory=lambda: dict.fromkeys(SWITCHES, False))
    usb_charging: int = 0
    # Effect choices per target, plus the UI-only ZONE_MODE for keyboards with per-zone control.
    lighting_modes: Mapping[str, list[int]] = field(default_factory=dict)
    # Editing draft per target in lighting_modes, seeded from its last successful command.
    lighting: Mapping[str, LightingDraft] = field(default_factory=dict)
    per_key: PerKey = field(default_factory=PerKey)
    # Frequency caps by core type, 'performance' and 'efficiency', when the CPU reports core types.
    cpu_limits: Mapping[CoreKind, CoreLimit] = field(default_factory=dict)
    # CPU package power in watts, averaged by the service; None until it has two energy readings.
    cpu_power: float | None = None

    @classmethod
    def parse(cls, value: JSON) -> 'Settings':
        if not isinstance(value, dict):
            raise ValueError('Invalid settings reply')
        profile = mapping(value.get('thermal_profile'))
        ac_online = value.get('ac_online')
        power = value.get('cpu_power')
        steps = value.get('fan_steps')
        lighting = mapping(value.get('lighting_state'))
        features = tuple(strings(value.get('available_features')))
        modes = {target: [mode for item in items if (mode := integer(item)) is not None]
                 for target, items in mapping(value.get('lighting_modes')).items() if isinstance(items, list)}
        if modes.get('keyboard') and 'per_zone_mode' in features:
            modes['keyboard'].append(ZONE_MODE)
        return cls(
            version=text(value.get('version'), cls.version),
            driver_version=text(value.get('driver_version'), cls.driver_version),
            laptop_type=text(value.get('laptop_type'), cls.laptop_type),
            features=features,
            ac_online=ac_online if isinstance(ac_online, bool) else None,
            profile=text(profile.get('current'), ''),
            profiles=tuple(strings(profile.get('available'))),
            fans=Fans.parse(value.get('fans')),
            fan_rpm=integers(value.get('fan_rpm')),
            fan_percent=integers(value.get('fan_percent')),
            fan_steps=tuple(step for item in steps if (step := integer(item)) is not None) if isinstance(steps, list) else (),
            switches={key: value.get(key) is True for key in SWITCHES},
            usb_charging=integer(value.get('usb_charging')) or 0,
            lighting_modes=modes,
            lighting={target: LightingDraft.from_state(mapping(lighting.get(target)), target_modes)
                      for target, target_modes in modes.items()},
            per_key=PerKey.parse(lighting.get('per_key')),
            cpu_limits={CoreKind(kind): limit for kind, item in mapping(value.get('cpu_limits')).items()
                        if kind in CoreKind and (limit := CoreLimit.parse(item))},
            cpu_power=float(power) if isinstance(power, int | float) and not isinstance(power, bool) and power >= 0 else None)


@dataclass(frozen=True)
class Lamp:
    """One keyboard LED as reported by HID: position in micrometers and its key usage binding."""
    id: int
    x: int
    y: int
    key_usage: int
    programmable: bool


def parse_lamps(value: JSON) -> list[Lamp]:
    """Lamps from a get_keyboard_layout reply."""
    items = mapping(value).get('lamps', [])
    if not isinstance(items, list):
        raise ValueError('Invalid keyboard layout')
    lamps = []
    for item in items:
        lamp = mapping(item)
        lid, x, y = integer(lamp.get('id')), integer(lamp.get('x')), integer(lamp.get('y'))
        if lid is None or x is None or y is None:
            raise ValueError('Invalid keyboard layout')
        lamps.append(Lamp(lid, x, y, integer(lamp.get('key_usage')) or 0, lamp.get('programmable') is True))
    return lamps


def full_key_map(lamps: Sequence[Lamp], saved: Mapping[str, str] | None = None, default: str = '5bbfbd') -> dict[str, str]:
    saved = saved or {}
    return {str(lamp.id): rgb_hex(saved.get(str(lamp.id), default)) for lamp in lamps if lamp.programmable}
