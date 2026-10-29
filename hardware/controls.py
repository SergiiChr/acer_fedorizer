# SPDX-License-Identifier: GPL-3.0-only
# Native PH16-72 edition; modified October 2026. Attribution and terms: NOTICE.md.
"""Stock kernel and HID controls, with injectable sysfs roots for testing."""
import contextlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Literal, Required, TypedDict, get_args

from .hid import RGB, CoverLogo, Lamp, LampArrayDevice, VendorKeyboard, scale_rgb

VERSION = '0.7.0'
WASD_USAGES = (4, 7, 22, 26)
log = logging.getLogger('fedorizer')
JsonObject = dict[str, object]
Switch = Literal['backlight_timeout', 'battery_calibration', 'battery_limiter', 'boot_animation_sound', 'lcd_override']
SWITCHES: tuple[Switch, ...] = get_args(Switch)


class FanState(TypedDict):
    mode: Literal['auto', 'max', 'manual']
    percent: int


class ThermalProfile(TypedDict):
    current: str
    available: list[str]


class KeyboardLayout(TypedDict):
    width: int
    height: int
    lamps: list[Lamp]


class Settings(TypedDict, total=False):
    """The get_all_settings reply, also returned by set_* commands except set_thermal_profile, which replies {'current': profile}.
    Optional keys exist only with their hardware.
    """
    version: Required[str]
    driver_version: Required[str]
    laptop_type: Required[str]
    available_features: Required[list[str]]
    ac_online: Required[bool | None]
    thermal_profile: Required[ThermalProfile]
    fan_rpm: Required[dict[str, int | None]]
    lighting_modes: Required[dict[str, list[int]]]
    lighting_state: Required[JsonObject]
    fans: dict[str, FanState]
    backlight_timeout: bool
    battery_calibration: bool
    battery_limiter: bool
    boot_animation_sound: bool
    lcd_override: bool
    usb_charging: int


def read(path: Path, default: str = '') -> str:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def decimal(value: str) -> int | None:
    """Return a non-negative sysfs integer, or None when the attribute is unreadable or not a number."""
    return int(value) if value.isascii() and value.isdecimal() else None


def fan_state(enable: str, pwm: str) -> FanState:
    """Describe a fan from its hwmon pwmN_enable and pwmN values: firmware auto, full speed, or a manual percent."""
    match enable:
        case '0':
            return {'mode': 'max', 'percent': 100}
        case '1':
            return {'mode': 'manual', 'percent': round((decimal(pwm) or 0) * 100 / 255)}
        case _:
            return {'mode': 'auto', 'percent': 0}


def integer(value: object, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f'Expected integer {lo}–{hi}')
    return value


def color(value: object) -> RGB:
    if not isinstance(value, str) or not re.fullmatch(r'#?[0-9a-fA-F]{6}', value):
        raise ValueError('Expected six-digit RGB color')
    r, g, b = bytes.fromhex(value.lstrip('#'))
    return r, g, b


def color_hex(rgb: RGB) -> str:
    """Return the six-digit hex form that color() reads."""
    return bytes(rgb).hex()


def key_colors(value: object) -> dict[int, RGB]:
    """Parse a {"lamp id": "rrggbb"} map into lamp IDs and colors."""
    if not isinstance(value, dict) or not 1 <= len(value) <= 4096:
        raise ValueError('Expected per-key color map')
    mapping: dict[int, RGB] = {}
    for key, rgb in value.items():
        if not isinstance(key, str) or not key.isascii() or not key.isdecimal():
            raise ValueError('Invalid lamp ID')
        lamp = integer(int(key), 0, 4095)
        if lamp in mapping:
            raise ValueError('Duplicate lamp ID')
        mapping[lamp] = color(rgb)
    return mapping


def boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f'Expected boolean {name}')
    return value


class Target(StrEnum):
    """A lighting device that commands can address one at a time."""
    KEYBOARD = 'keyboard'
    WASD = 'wasd'
    LOGO = 'logo'
    LIGHTBAR = 'lightbar'

    @classmethod
    def parse(cls, value: object) -> 'Target':
        if isinstance(value, str) and value in cls:
            return cls(value)
        raise ValueError('Unsupported lighting target')


@dataclass(frozen=True)
class Effect:
    """A lighting effect with validated mode, color, speed (1-9), brightness (0-100), and direction (1-2)."""
    mode: int
    rgb: RGB
    speed: int = 5
    brightness: int = 100
    direction: int = 1

    @classmethod
    def parse(cls, p: Mapping[str, object]) -> 'Effect':
        return cls(integer(p.get('mode', 0), 0, 9), color(p.get('color')), integer(p.get('speed', 5), 1, 9),
                   integer(p.get('brightness', 100), 0, 100), integer(p.get('direction', 1), 1, 2))

    def to_json(self) -> JsonObject:
        return {'mode': self.mode, 'color': color_hex(self.rgb), 'brightness': self.brightness,
                'speed': self.speed, 'direction': self.direction}


@dataclass(frozen=True)
class Zones:
    """Four keyboard zone colors, left to right."""
    colors: tuple[RGB, RGB, RGB, RGB]


@dataclass(frozen=True)
class KeyColors:
    """Static per-lamp colors shown at one brightness."""
    colors: dict[int, RGB]
    brightness: int

    def colors_json(self) -> dict[str, str]:
        return {str(key): color_hex(rgb) for key, rgb in self.colors.items()}


def zone_colors(value: object) -> tuple[RGB, RGB, RGB, RGB]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError('Expected four zone colors')
    return color(value[0]), color(value[1]), color(value[2]), color(value[3])


def saved_effect(entry: Mapping[str, object]) -> Effect:
    if 'mode' not in entry:
        raise ValueError('Expected a saved effect')
    return Effect.parse(entry)


def key_colors_entry(entry: Mapping[str, object]) -> KeyColors:
    return KeyColors(key_colors(entry.get('colors')), integer(entry.get('brightness', 100), 0, 100))


@dataclass
class Lighting:
    """Lighting applied successfully, as saved in the state file and replayed after start, resume, or reconnect.
    The keyboard shows either an effect, four zones, or the saved per_key layout; WASD shows an effect or its share of that layout.
    """
    keyboard: Effect | Zones | Literal['per_key'] | None = None
    link_wasd: bool = True
    wasd: Effect | KeyColors | None = None
    logo: Effect | None = None
    lightbar: Effect | None = None
    all: Effect | None = None
    per_key: KeyColors | None = None

    @classmethod
    def parse(cls, data: object) -> 'Lighting':
        """Read the state file contents, dropping entries that are not valid lighting."""
        lighting = cls()
        if not isinstance(data, dict):
            return lighting
        for target in ('per_key', 'keyboard', 'wasd', 'logo', 'lightbar', 'all'):
            if target in data:
                try:
                    lighting._parse_entry(target, data[target])
                except ValueError as error:
                    log.warning('Ignoring saved %s lighting: %s', target, error)
        if lighting.keyboard == 'per_key' and not lighting.per_key:
            log.warning('Ignoring saved keyboard lighting: Saved per-key layout missing')
            lighting.keyboard = None
        return lighting

    def _parse_entry(self, target: str, entry: object) -> None:
        if not isinstance(entry, dict):
            raise ValueError('Expected a saved lighting object')
        match target, entry.get('kind'):
            case 'per_key', _:
                self.per_key = key_colors_entry(entry)
            case 'keyboard', 'zones':
                self.keyboard = Zones(zone_colors(entry.get('colors')))
            case 'keyboard', 'per_key':
                self.keyboard = 'per_key'
            case 'keyboard', _:
                effect, link_wasd = saved_effect(entry), boolean(entry.get('link_wasd', True), 'link_wasd')
                self.keyboard, self.link_wasd = effect, link_wasd
            case 'wasd', 'per_key':
                self.wasd = key_colors_entry(entry)
            case 'wasd', _:
                self.wasd = saved_effect(entry)
            case 'logo', _:
                self.logo = saved_effect(entry)
            case 'lightbar', _:
                self.lightbar = saved_effect(entry)
            case 'all', _:
                self.all = saved_effect(entry)

    def to_json(self) -> JsonObject:
        """Return the state file form, which the desktop app also reads as lighting_state."""
        out: JsonObject = {}
        match self.keyboard:
            case Effect():
                out['keyboard'] = self.keyboard.to_json() | {'link_wasd': self.link_wasd}
            case Zones():
                out['keyboard'] = {'kind': 'zones', 'colors': [color_hex(rgb) for rgb in self.keyboard.colors]}
            case 'per_key' if self.per_key:
                out['keyboard'] = {'kind': 'per_key', 'brightness': self.per_key.brightness}
        match self.wasd:
            case Effect():
                out['wasd'] = self.wasd.to_json()
            case KeyColors():
                out['wasd'] = {'kind': 'per_key', 'brightness': self.wasd.brightness, 'colors': self.wasd.colors_json()}
        for target, effect in (('logo', self.logo), ('lightbar', self.lightbar), ('all', self.all)):
            if effect:
                out[target] = effect.to_json()
        if self.per_key:
            out['per_key'] = {'colors': self.per_key.colors_json(), 'brightness': self.per_key.brightness}
        return out


class NativeControls:
    def __init__(self, sys_root: str = '/sys', state_file: str = '/var/lib/acer-fedorizer/lighting.json',
                 discover_hid: bool = True) -> None:
        self.root = Path(sys_root)
        self.state_file = Path(state_file)
        self.lock = threading.RLock()
        self.profile_dir = next((p for p in sorted((self.root / 'class/platform-profile').glob('*'))
                                 if read(p / 'name') == 'acer-wmi'), None)
        self.hwmon = next((p for p in sorted((self.root / 'class/hwmon').glob('*'))
                           if read(p / 'name') == 'acer' and (p / 'fan1_input').exists()), None)
        self.static_features: set[str] = set()
        if self.profile_dir:
            self.static_features.add('thermal_profile')
        if self.hwmon and all((self.hwmon / f'pwm{i}').exists() and
                              (self.hwmon / f'pwm{i}_enable').exists() for i in (1, 2)):
            self.static_features.add('fan_speed')
        self.bar_bridge = next(iter((self.root / 'bus/wmi/devices').glob(
            '7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56*/color')), None)
        if self.bar_bridge:
            self.static_features.add('lightbar')
        self.extra_files: dict[str, Path] = {}
        # Only expose stock kernel attributes that actually exist.
        for key in (*SWITCHES, 'usb_charging'):
            p = self.root / 'devices/platform/acer-wmi' / key
            if p.exists():
                self.extra_files[key] = p
                self.static_features.add(key)
        self.threshold = next(iter((self.root / 'class/power_supply').glob('*/charge_control_end_threshold')), None)
        if self.threshold:
            self.static_features.add('battery_limiter')
        self.discover_hid = discover_hid
        self.keyboard: LampArrayDevice | None = None
        self.vendor: VendorKeyboard | None = None
        self.logo: CoverLogo | None = None
        if discover_hid:
            self.find_hid()
        try:
            saved = json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            saved = {}
        self.lighting = Lighting.parse(saved)
        self.lighting_json = self.lighting.to_json()

    def find_hid(self) -> None:
        """Refresh HID handles; device nodes change after a reconnect or resume."""
        self.keyboard = next(iter(LampArrayDevice.discover(self.root)), None)
        self.vendor = VendorKeyboard.discover(self.root)
        self.logo = CoverLogo.discover(self.root)

    @property
    def features(self) -> set[str]:
        features = set(self.static_features)
        if self.keyboard:
            features.update(('per_zone_mode', 'per_key_mode'))
        if self.keyboard or self.vendor:
            features.add('four_zone_mode')
        if self.logo:
            features.add('usb_logo')
        return features

    def _write(self, path: Path, value: object) -> None:
        Path(path).write_text(str(value))

    def _save(self) -> None:
        """Write the lighting state file and refresh the lighting_json that settings() reports."""
        self.lighting_json = self.lighting.to_json()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.lighting_json))
        os.replace(tmp, self.state_file)

    def ac_online(self) -> bool | None:
        supplies = list((self.root / 'class/power_supply').glob('*'))
        mains = [p for p in supplies if read(p / 'type') in ('Mains', 'USB', 'USB_C') and (p / 'online').exists()]
        return any(read(p / 'online') == '1' for p in mains) if mains else None

    def settings(self) -> Settings:
        with self.lock:
            profile = read(self.profile_dir / 'profile') if self.profile_dir else ''
            choices = read(self.profile_dir / 'choices').split() if self.profile_dir else []
            rpm = {name: decimal(read(self.hwmon / f'fan{i}_input')) if self.hwmon else None
                   for i, name in ((1, 'cpu'), (2, 'gpu'))}
            out: Settings = {
                'version': VERSION, 'driver_version': 'Stock Linux acer_wmi + HID',
                'laptop_type': read(self.root / 'class/dmi/id/product_name', 'Acer'),
                'available_features': sorted(self.features), 'ac_online': self.ac_online(),
                'thermal_profile': {'current': profile, 'available': choices}, 'fan_rpm': rpm,
                'lighting_modes': self.lighting_modes(), 'lighting_state': self.lighting_json}
            if self.hwmon:
                out['fans'] = {name: fan_state(read(self.hwmon / f'pwm{i}_enable'), read(self.hwmon / f'pwm{i}', '0'))
                               for i, name in ((1, 'cpu'), (2, 'gpu'))}
            for key in SWITCHES:
                if key in self.extra_files:
                    out[key] = read(self.extra_files[key]) == '1'
            if 'usb_charging' in self.extra_files:
                out['usb_charging'] = decimal(read(self.extra_files['usb_charging'])) or 0
            if self.threshold:
                threshold = decimal(read(self.threshold))
                out['battery_limiter'] = threshold is not None and threshold <= 80
            return out

    def set_profile(self, profile: str) -> str:
        if not self.profile_dir or profile not in read(self.profile_dir / 'choices').split():
            raise ValueError('Unsupported performance profile')
        # Firmware owns AC restrictions. Read its accepted state after writing.
        self._write(self.profile_dir / 'profile', profile)
        actual = read(self.profile_dir / 'profile')
        if actual != profile:
            raise RuntimeError(f'Firmware selected {actual!r} instead of {profile!r}')
        return actual

    def auto_fans(self) -> None:
        """Hand both fans back to firmware control; each fan is attempted even if the other fails."""
        if not self.hwmon:
            return
        for i in (1, 2):
            with contextlib.suppress(OSError):
                self._write(self.hwmon / f'pwm{i}_enable', 2)

    def set_fans(self, cpu: int, gpu: int) -> None:
        """Set both fans to validated 0-100 percentages, where 0 is automatic and 100 is full speed."""
        if 'fan_speed' not in self.features or not self.hwmon:
            raise ValueError('Stock Acer fan control unavailable')
        # If a write fails, restore automatic cooling rather than leave a half-applied mode.
        try:
            for i, speed in enumerate((cpu, gpu), 1):
                if speed in (0, 100):
                    self._write(self.hwmon / f'pwm{i}_enable', 2 if speed == 0 else 0)
                else:
                    self._write(self.hwmon / f'pwm{i}', round(speed * 255 / 100))
                    self._write(self.hwmon / f'pwm{i}_enable', 1)
        except Exception:
            self.auto_fans()
            raise

    def _apply_keyboard(self, effect: Effect) -> None:
        if effect.mode == 0 and self.keyboard:
            with self.keyboard.open() as kb:
                kb.fill(scale_rgb(effect.rgb, effect.brightness))
        elif self.vendor:
            if self.keyboard:
                with self.keyboard.open() as kb:
                    kb.autonomous(True)
            self.vendor.effect(effect.mode, effect.rgb, effect.speed, effect.brightness, effect.direction)
        else:
            raise ValueError('Native effects unavailable; static color is supported')

    def _apply_zones(self, keyboard: LampArrayDevice, colors: tuple[RGB, RGB, RGB, RGB]) -> None:
        with keyboard.open() as kb:
            kb.multi({lamp['id']: colors[min(lamp['x'] * 4 // max(kb.w, 1), 3)] for lamp in kb.lamps()})
        if self.vendor:
            self.vendor.effect(0, colors[0], 5, 100, mag=True)

    def _apply_per_key(self, keyboard: LampArrayDevice, layout: KeyColors) -> list[Lamp]:
        """Send a full static layout and return the lamp list it was validated against."""
        with keyboard.open() as kb:
            lamps = kb.lamps()
            if set(layout.colors) != {lamp['id'] for lamp in lamps if lamp['programmable']}:
                raise ValueError('Send one color for every programmable keyboard lamp')
            kb.multi({key: scale_rgb(rgb, layout.brightness) for key, rgb in layout.colors.items()})
        return lamps

    def _apply(self, target: Target, effect: Effect) -> None:
        """Send an effect to one lighting device; raise if that device is missing."""
        match target:
            case Target.KEYBOARD:
                self._apply_keyboard(effect)
            case Target.WASD if self.vendor:
                self.vendor.effect(effect.mode, effect.rgb, effect.speed, effect.brightness, effect.direction, mag=True)
            case Target.LOGO if self.logo:
                self.logo.effect(effect.mode, effect.rgb, effect.speed, effect.brightness, effect.direction)
            case Target.LIGHTBAR if self.bar_bridge:
                self._set_bar(self.bar_bridge, effect)
            case _:
                raise ValueError(f'No {target} lighting device')

    def set_zones(self, colors: tuple[RGB, RGB, RGB, RGB]) -> None:
        if not self.keyboard:
            raise ValueError('Per-lamp keyboard unavailable')
        self._apply_zones(self.keyboard, colors)
        self.lighting.keyboard = Zones(colors)
        if self.vendor:
            self.lighting.wasd = Effect(0, colors[0])
        self._save()

    def _set_bar(self, bar_bridge: Path, effect: Effect) -> None:
        native_effect = bar_bridge.with_name('effect')
        if not native_effect.exists():
            self._write(bar_bridge, ' '.join(map(str, (*effect.rgb, effect.brightness))))
            return
        def apply(native_mode: int) -> None:
            self._write(native_effect, ' '.join(map(str,
                (native_mode, 1 + (effect.speed - 1)//2, effect.brightness, effect.direction, *effect.rgb))))
        # PH16-72 Static retains the previous RGB. Hardware testing confirmed
        # that loading RGB through Breathing before Static sets the steady color.
        if effect.mode == 0:
            apply(1)
            time.sleep(0.2)
        apply(effect.mode)

    def lighting_modes(self) -> dict[str, list[int]]:
        modes = {}
        if self.keyboard or self.vendor:
            modes['keyboard'] = list(VendorKeyboard.EFFECTS) if self.vendor else [0]
        if self.vendor:
            modes['wasd'] = list(VendorKeyboard.MAG_EFFECTS)
        if self.logo:
            modes['logo'] = list(CoverLogo.EFFECTS)
        if self.bar_bridge:
            modes['lightbar'] = [0, 1, 2, 3] if self.bar_bridge.with_name('effect').exists() else [0]
        if len(modes) > 1:
            modes['all'] = sorted(set.intersection(*(set(values) for values in modes.values())))
        return modes

    def keyboard_layout(self) -> KeyboardLayout:
        if not self.keyboard:
            raise ValueError('Per-key keyboard control unavailable')
        with self.keyboard.open() as kb:
            return {'width': kb.w, 'height': kb.h, 'lamps': kb.lamps()}

    def set_per_key(self, layout: KeyColors) -> None:
        if not self.keyboard:
            raise ValueError('Per-key keyboard control unavailable')
        lamps = self._apply_per_key(self.keyboard, layout)
        self.lighting.per_key, self.lighting.keyboard = layout, 'per_key'
        wasd = {lamp['id'] for lamp in lamps if lamp.get('key_usage') in WASD_USAGES}
        if self.vendor and wasd and wasd <= layout.colors.keys():
            self.lighting.wasd = KeyColors({key: layout.colors[key] for key in wasd}, layout.brightness)
        self._save()

    def set_global_lighting(self, effect: Effect) -> None:
        """Apply one effect to every device in turn, saving whatever succeeded even when a later device fails."""
        modes = self.lighting_modes()
        if effect.mode not in modes.get('all', []):
            raise ValueError('Choose an effect supported by every lighting device')
        applied: list[Target] = []
        try:
            for target in [target for target in Target if target in modes]:
                try:
                    self._set_lighting(target, effect, False, modes)
                except (OSError, ValueError, RuntimeError) as error:
                    raise RuntimeError(f"Sync failed on {target}; applied to {', '.join(applied) or 'none'}: {error}") from error
                applied.append(target)
            self.lighting.all = effect
        finally:
            self._save()

    def set_lighting(self, target: Target, effect: Effect, link_wasd: bool) -> None:
        self._set_lighting(target, effect, link_wasd, self.lighting_modes())
        self._save()

    def _set_lighting(self, target: Target, effect: Effect, link_wasd: bool, modes: Mapping[str, list[int]]) -> None:
        """Apply an effect to one device and record it in self.lighting without saving."""
        if effect.mode not in modes.get(target, []):
            raise ValueError('This device does not support the selected effect')
        self._apply(target, effect)
        match target:
            case Target.KEYBOARD:
                if link_wasd and self.vendor:
                    wasd = replace(effect, mode=effect.mode if effect.mode in self.vendor.MAG_EFFECTS else 0)
                    self._apply(Target.WASD, wasd)
                    self.lighting.wasd = wasd
                self.lighting.keyboard, self.lighting.link_wasd = effect, link_wasd
            case Target.WASD:
                self.lighting.wasd = effect
            case Target.LOGO:
                self.lighting.logo = effect
            case Target.LIGHTBAR:
                self.lighting.lightbar = effect

    def restore_lighting(self) -> None:
        """Replay saved lighting after start, resume, or a HID reconnect.
        Saved state is left unchanged: it records what was applied, not what the replay achieved.
        """
        with self.lock:
            if self.discover_hid:
                self.find_hid()
            saved = self.lighting
            keyboard = saved.per_key if saved.keyboard == 'per_key' else saved.keyboard
            for target, entry in ((Target.KEYBOARD, keyboard), (Target.WASD, saved.wasd),
                                  (Target.LOGO, saved.logo), (Target.LIGHTBAR, saved.lightbar)):
                try:
                    self._restore(target, entry)
                except (OSError, ValueError, RuntimeError) as error:
                    log.warning('Could not restore %s lighting: %s', target, error)

    def _restore(self, target: Target, entry: Effect | Zones | KeyColors | None) -> None:
        # A WASD entry recorded by a per-key layout has no mode; the keyboard layout already covers it.
        match entry:
            case Zones() if self.keyboard:
                self._apply_zones(self.keyboard, entry.colors)
            case KeyColors() if target == Target.KEYBOARD and self.keyboard:
                self._apply_per_key(self.keyboard, entry)
            case Effect() if entry.mode in self.lighting_modes().get(target, []):
                self._apply(target, entry)

    def command(self, name: str, p: Mapping[str, object]) -> Mapping[str, object]:
        with self.lock:
            if name == 'ping':
                return {'version': VERSION}
            if name == 'get_all_settings':
                return self.settings()
            if name == 'set_lighting':
                target = p.get('target')
                if target == 'all':
                    self.set_global_lighting(Effect.parse(p))
                else:
                    self.set_lighting(Target.parse(target), Effect.parse(p), boolean(p.get('link_wasd', True), 'link_wasd'))
                return self.settings()
            if name == 'get_keyboard_layout':
                return self.keyboard_layout()
            if name == 'set_per_key':
                self.set_per_key(key_colors_entry(p))
                return self.settings()
            if name == 'set_thermal_profile':
                profile = p.get('profile')
                if not isinstance(profile, str):
                    raise ValueError('Unsupported performance profile')
                return {'current': self.set_profile(profile)}
            if name == 'set_fan_speed':
                self.set_fans(integer(p.get('cpu'), 0, 100), integer(p.get('gpu'), 0, 100))
            elif name == 'set_per_zone_mode':
                self.set_zones(zone_colors([p.get(f'zone{i}') for i in range(1, 5)]))
            elif name == 'set_battery_limiter' and self.threshold:
                self._write(self.threshold, 80 if boolean(p.get('enabled'), 'enabled') else 100)
            elif name.startswith('set_') and name[4:] in self.extra_files:
                key = name[4:]
                if key == 'usb_charging':
                    value = p.get('level')
                    if value not in (0, 10, 20, 30):
                        raise ValueError('Invalid USB charging threshold')
                else:
                    value = int(boolean(p.get('enabled'), 'enabled'))
                self._write(self.extra_files[key], value)
            else:
                raise ValueError(f'Unsupported command: {name}')
            return self.settings()
