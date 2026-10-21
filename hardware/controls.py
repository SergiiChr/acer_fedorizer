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
from pathlib import Path

from .hid import CoverLogo, LampArrayDevice, VendorKeyboard, _scale_rgb

VERSION = '0.7.0'
WASD_USAGES = (4, 7, 22, 26)
log = logging.getLogger('fedorizer')


def read(path, default=''):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def integer(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f'Expected integer {lo}–{hi}')
    return value


def color(value):
    if not isinstance(value, str) or not re.fullmatch(r'#?[0-9a-fA-F]{6}', value):
        raise ValueError('Expected six-digit RGB color')
    return tuple(bytes.fromhex(value.lstrip('#')))


def effect_params(p):
    """Validate (mode, rgb, speed, brightness, direction) from a request or saved state."""
    return (integer(p.get('mode', 0), 0, 9), color(p.get('color')), integer(p.get('speed', 5), 1, 9),
            integer(p.get('brightness', 100), 0, 100), integer(p.get('direction', 1), 1, 2))


class NativeControls:
    def __init__(self, sys_root='/sys', state_file='/var/lib/acer-fedorizer/lighting.json', discover_hid=True):
        self.root = Path(sys_root)
        self.state_file = Path(state_file)
        self.lock = threading.RLock()
        self.profile_dir = None
        for p in sorted((self.root / 'class/platform-profile').glob('*')):
            if read(p / 'name') == 'acer-wmi':
                self.profile_dir = p
                break
        self.hwmon = next((p for p in sorted((self.root / 'class/hwmon').glob('*'))
                           if read(p / 'name') == 'acer' and (p / 'fan1_input').exists()), None)
        self.static_features = set()
        if self.profile_dir:
            self.static_features.add('thermal_profile')
        if self.hwmon and all((self.hwmon / f'pwm{i}').exists() and
                              (self.hwmon / f'pwm{i}_enable').exists() for i in (1, 2)):
            self.static_features.add('fan_speed')
        self.bar_bridge = next(iter((self.root / 'bus/wmi/devices').glob(
            '7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56*/color')), None)
        if self.bar_bridge:
            self.static_features.add('lightbar')
        self.extra_files = {}
        # Only expose stock kernel attributes that actually exist.
        for key in ('backlight_timeout', 'battery_calibration', 'battery_limiter',
                    'boot_animation_sound', 'lcd_override', 'usb_charging'):
            p = self.root / 'devices/platform/acer-wmi' / key
            if p.exists():
                self.extra_files[key] = p
                self.static_features.add(key)
        self.threshold = next(iter((self.root / 'class/power_supply').glob('*/charge_control_end_threshold')), None)
        if self.threshold:
            self.static_features.add('battery_limiter')
        self.discover_hid = discover_hid
        self.keyboard = self.vendor = self.logo = None
        if discover_hid:
            self.find_hid()
        try:
            self.lighting = json.loads(self.state_file.read_text())
            if not isinstance(self.lighting, dict):
                self.lighting = {}
        except (OSError, ValueError):
            self.lighting = {}

    def find_hid(self):
        """Refresh HID handles; device nodes change after a reconnect or resume."""
        self.keyboard = next(iter(LampArrayDevice.discover(self.root)), None)
        self.vendor = VendorKeyboard.discover(self.root)
        self.logo = CoverLogo.discover(self.root)

    @property
    def features(self):
        features = set(self.static_features)
        if self.keyboard:
            features.update(('per_zone_mode', 'per_key_mode'))
        if self.keyboard or self.vendor:
            features.add('four_zone_mode')
        if self.logo:
            features.add('usb_logo')
        return features

    def _write(self, path, value):
        Path(path).write_text(str(value))

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.lighting))
        os.replace(tmp, self.state_file)

    def ac_online(self):
        supplies = list((self.root / 'class/power_supply').glob('*'))
        mains = [p for p in supplies if read(p / 'type') in ('Mains', 'USB', 'USB_C') and (p / 'online').exists()]
        return any(read(p / 'online') == '1' for p in mains) if mains else None

    def settings(self):
        with self.lock:
            profile = read(self.profile_dir / 'profile') if self.profile_dir else ''
            choices = read(self.profile_dir / 'choices').split() if self.profile_dir else []
            fan = {}
            for i, name in ((1, 'cpu'), (2, 'gpu')):
                if self.hwmon:
                    enabled = read(self.hwmon / f'pwm{i}_enable')
                    raw = read(self.hwmon / f'pwm{i}', '0')
                    fan[name] = '100' if enabled == '0' else str(round(int(raw) * 100 / 255)) if enabled == '1' else '0'
            rpm = {}
            for i, name in ((1, 'cpu'), (2, 'gpu')):
                value = read(self.hwmon / f'fan{i}_input') if self.hwmon else ''
                rpm[name] = int(value) if value.isascii() and value.isdecimal() else None
            out = {'version': VERSION, 'driver_version': 'Stock Linux acer_wmi + HID',
                   'laptop_type': read(self.root / 'class/dmi/id/product_name', 'Acer'),
                   'available_features': sorted(self.features), 'ac_online': self.ac_online(),
                   'thermal_profile': {'current': profile, 'available': choices}, 'fan_speed': fan, 'fan_rpm': rpm,
                   'lighting_modes': self.lighting_modes(), 'lighting_state': dict(self.lighting)}
            for k, p in self.extra_files.items():
                out[k] = read(p)
            if self.threshold:
                out['battery_limiter'] = '1' if int(read(self.threshold, '100')) <= 80 else '0'
            return out

    def set_profile(self, profile):
        if not self.profile_dir or profile not in read(self.profile_dir / 'choices').split():
            raise ValueError('Unsupported performance profile')
        # Firmware owns AC restrictions. Read its accepted state after writing.
        self._write(self.profile_dir / 'profile', profile)
        actual = read(self.profile_dir / 'profile')
        if actual != profile:
            raise RuntimeError(f'Firmware selected {actual!r} instead of {profile!r}')
        return actual

    def auto_fans(self):
        """Hand both fans back to firmware control; each fan is attempted even if the other fails."""
        if not self.hwmon:
            return
        for i in (1, 2):
            with contextlib.suppress(OSError):
                self._write(self.hwmon / f'pwm{i}_enable', 2)

    def set_fans(self, cpu, gpu):
        if 'fan_speed' not in self.features:
            raise ValueError('Stock Acer fan control unavailable')
        speeds = [integer(cpu, 0, 100), integer(gpu, 0, 100)]
        # Both values are validated before either fan is changed. If a write
        # fails, restore automatic cooling rather than leave a half-applied mode.
        try:
            for i, speed in enumerate(speeds, 1):
                if speed in (0, 100):
                    self._write(self.hwmon / f'pwm{i}_enable', 2 if speed == 0 else 0)
                else:
                    self._write(self.hwmon / f'pwm{i}', round(speed * 255 / 100))
                    self._write(self.hwmon / f'pwm{i}_enable', 1)
        except Exception:
            self.auto_fans()
            raise

    def _apply_keyboard(self, mode, rgb, speed, brightness, direction):
        if mode == 0 and self.keyboard:
            with self.keyboard as kb:
                kb.fill(_scale_rgb(rgb, brightness))
        elif self.vendor:
            if self.keyboard:
                with self.keyboard as kb:
                    kb.autonomous(True)
            self.vendor.effect(mode, rgb, speed, brightness, direction)
        else:
            raise ValueError('Native effects unavailable; static color is supported')

    def _apply_zones(self, colors):
        with self.keyboard as kb:
            kb.multi({lamp['id']: colors[min(lamp['x'] * 4 // max(kb.w, 1), 3)] for lamp in kb.lamps()})
        if self.vendor:
            self.vendor.effect(0, colors[0], 5, 100, mag=True)

    def _apply_per_key(self, mapping, brightness):
        """Send a full static layout and return the lamp list it was validated against."""
        with self.keyboard as kb:
            lamps = kb.lamps()
            if set(mapping) != {lamp['id'] for lamp in lamps if lamp['programmable']}:
                raise ValueError('Send one color for every programmable keyboard lamp')
            kb.multi({key: _scale_rgb(rgb, brightness) for key, rgb in mapping.items()})
        return lamps

    def _apply_device(self, target, mode, rgb, speed, brightness, direction):
        if target == 'wasd':
            self.vendor.effect(mode, rgb, speed, brightness, direction, mag=True)
        elif target == 'logo':
            self.logo.effect(mode, rgb, speed, brightness, direction)
        elif target == 'lightbar':
            self._set_bar(mode, rgb, speed, brightness, direction)

    def set_zones(self, p):
        if not self.keyboard:
            raise ValueError('Per-lamp keyboard unavailable')
        colors = [color(p[f'zone{i}']) for i in range(1, 5)]
        self._apply_zones(colors)
        self.lighting['keyboard'] = {'kind': 'zones', 'colors': [bytes(c).hex() for c in colors]}
        if self.vendor:
            self.lighting['wasd'] = {'mode': 0, 'color': bytes(colors[0]).hex(), 'brightness': 100,
                                     'speed': 5, 'direction': 1}
        self._save()

    def _set_bar(self, mode, rgb, speed, brightness, direction):
        effect = self.bar_bridge.with_name('effect')
        if not effect.exists():
            self._write(self.bar_bridge, ' '.join(map(str, (*rgb, brightness))))
            return
        def apply(native_mode):
            self._write(effect, ' '.join(map(str,
                (native_mode, 1 + (speed - 1)//2, brightness, direction, *rgb))))
        # PH16-72 Static retains the previous RGB. Hardware testing confirmed
        # that loading RGB through Breathing before Static sets the steady color.
        if mode == 0:
            apply(1)
            time.sleep(0.2)
        apply(mode)

    def lighting_modes(self):
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

    def keyboard_layout(self):
        if not self.keyboard:
            raise ValueError('Per-key keyboard control unavailable')
        with self.keyboard as kb:
            return {'width': kb.w, 'height': kb.h, 'lamps': kb.lamps()}

    def set_per_key(self, p):
        brightness = integer(p.get('brightness', 100), 0, 100)
        colors = p.get('colors')
        if not isinstance(colors, dict) or not 1 <= len(colors) <= 4096:
            raise ValueError('Expected per-key color map')
        mapping = {}
        for key, value in colors.items():
            if not isinstance(key, str) or not key.isascii() or not key.isdecimal():
                raise ValueError('Invalid lamp ID')
            lamp = integer(int(key), 0, 4095)
            if lamp in mapping:
                raise ValueError('Duplicate lamp ID')
            mapping[lamp] = color(value)
        if not self.keyboard:
            raise ValueError('Per-key keyboard control unavailable')
        lamps = self._apply_per_key(mapping, brightness)
        self.lighting['per_key'] = {'colors': {str(k): bytes(v).hex() for k, v in mapping.items()},
                                    'brightness': brightness}
        self.lighting['keyboard'] = {'kind': 'per_key', 'brightness': brightness}
        wasd = {lamp['id'] for lamp in lamps if lamp.get('key_usage') in WASD_USAGES}
        if self.vendor and wasd and wasd <= mapping.keys():
            self.lighting['wasd'] = {'kind': 'per_key', 'brightness': brightness,
                                     'colors': {str(key): bytes(mapping[key]).hex() for key in wasd}}
        self._save()

    def set_global_lighting(self, p):
        mode = integer(p.get('mode', 0), 0, 9)
        if mode not in self.lighting_modes().get('all', []):
            raise ValueError('Choose an effect supported by every lighting device')
        effect_params(p)
        applied = []
        for target in self.lighting_modes():
            if target == 'all':
                continue
            try:
                self.set_lighting(dict(p, target=target, link_wasd=False))
            except (OSError, ValueError, RuntimeError) as error:
                raise RuntimeError(f"Sync failed on {target}; applied to {', '.join(applied) or 'none'}: {error}") from error
            applied.append(target)
        self.lighting['all'] = dict(self.lighting[applied[-1]])
        self._save()

    def set_lighting(self, p):
        target = p.get('target')
        mode, rgb, speed, brightness, direction = params = effect_params(p)
        if mode not in self.lighting_modes().get(target, []):
            raise ValueError('This device does not support the selected effect')
        link_wasd = p.get('link_wasd', True)
        if not isinstance(link_wasd, bool):
            raise ValueError('Expected boolean link_wasd')
        if target == 'keyboard':
            self._apply_keyboard(*params)
            if link_wasd and self.vendor:
                mag_mode = mode if mode in self.vendor.MAG_EFFECTS else 0
                self.vendor.effect(mag_mode, rgb, speed, brightness, direction, mag=True)
                self.lighting['wasd'] = {'mode': mag_mode, 'color': bytes(rgb).hex(), 'brightness': brightness,
                                         'speed': speed, 'direction': direction}
        else:
            self._apply_device(target, *params)
        self.lighting[target] = {'mode': mode, 'color': bytes(rgb).hex(), 'brightness': brightness,
                                 'speed': speed, 'direction': direction}
        if target == 'keyboard':
            self.lighting[target]['link_wasd'] = link_wasd
        self._save()

    def restore_lighting(self):
        """Replay saved lighting after start, resume, or a HID reconnect.
        Saved state is left unchanged: it records what was applied, not what the replay achieved.
        """
        with self.lock:
            if self.discover_hid:
                self.find_hid()
            for target in ('keyboard', 'wasd', 'logo', 'lightbar'):
                try:
                    self._restore(target, self.lighting.get(target, {}))
                except (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError) as error:
                    log.warning('Could not restore %s lighting: %s', target, error)

    def _restore(self, target, saved):
        # A WASD entry recorded by a per-key layout has no mode; the keyboard layout already covers it.
        if target == 'keyboard' and saved.get('kind') == 'zones' and self.keyboard:
            self._apply_zones([color(c) for c in saved['colors']])
        elif target == 'keyboard' and saved.get('kind') == 'per_key' and self.keyboard:
            per_key = self.lighting['per_key']
            self._apply_per_key({int(k): color(v) for k, v in per_key['colors'].items()},
                                integer(per_key.get('brightness', 100), 0, 100))
        elif saved.get('mode') in self.lighting_modes().get(target, []):
            if target == 'keyboard':
                self._apply_keyboard(*effect_params(saved))
            else:
                self._apply_device(target, *effect_params(saved))

    def command(self, name, p):
        with self.lock:
            if name == 'ping':
                return {'version': VERSION}
            if name == 'get_all_settings':
                return self.settings()
            if name == 'set_lighting':
                if p.get('target') == 'all':
                    self.set_global_lighting(p)
                    return self.settings()
                self.set_lighting(p)
                return self.settings()
            if name == 'get_keyboard_layout':
                return self.keyboard_layout()
            if name == 'set_per_key':
                self.set_per_key(p)
                return self.settings()
            if name == 'set_thermal_profile':
                return {'current': self.set_profile(p.get('profile'))}
            if name == 'set_fan_speed':
                self.set_fans(p.get('cpu'), p.get('gpu'))
            elif name == 'set_per_zone_mode':
                self.set_zones(p)
            elif name == 'set_battery_limiter' and self.threshold:
                if not isinstance(p.get('enabled'), bool):
                    raise ValueError('enabled must be boolean')
                self._write(self.threshold, 80 if p['enabled'] else 100)
            elif name.startswith('set_') and name[4:] in self.extra_files:
                key = name[4:]
                if key == 'usb_charging':
                    value = p.get('level')
                    if value not in (0, 10, 20, 30):
                        raise ValueError('Invalid USB charging threshold')
                else:
                    if not isinstance(p.get('enabled'), bool):
                        raise ValueError('enabled must be boolean')
                    value = int(p['enabled'])
                self._write(self.extra_files[key], value)
            else:
                raise ValueError(f'Unsupported command: {name}')
            return self.settings()
