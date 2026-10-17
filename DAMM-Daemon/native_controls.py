# SPDX-License-Identifier: GPL-3.0-only
# Native PH16-72 edition; modified October 2026. Attribution and terms: NOTICE.md.
"""Stock kernel and HID controls, with injectable sysfs roots for testing."""
import json
import os
import re
import threading
import time
from pathlib import Path
from acer_hid import LampArrayDevice, VendorKeyboard, CoverLogo, _scale_rgb

VERSION = '0.7.0'


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


class NativeControls:
    def __init__(self, sys_root='/sys', state_file='/var/lib/damx/lighting.json', discover_hid=True):
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
        self.arrays = LampArrayDevice.discover() if discover_hid else []
        self.keyboard = next((d for d in self.arrays if d.vid in (0x05AF, 0x04F2)), None)
        self.vendor = VendorKeyboard.discover() if discover_hid else None
        self.logo = CoverLogo.discover() if discover_hid else None
        self.other_arrays = {}
        for d in self.arrays:
            if d.vid == 0x0D62:
                phys = read(self.root / 'class/hidraw' / Path(d.path).name / 'device/uevent')
                # These PIDs identify the separate Darfon lightbar/cover devices.
                if d.pid == 0xA20A:
                    self.other_arrays['lightbar'] = d
                elif d.pid == 0xA00A:
                    self.other_arrays['glass' if '/input2' in phys else 'logo'] = d
        self.features = set()
        if self.profile_dir:
            self.features.add('thermal_profile')
        if self.hwmon and all((self.hwmon / f'pwm{i}').exists() and
                              (self.hwmon / f'pwm{i}_enable').exists() for i in (1, 2)):
            self.features.add('fan_speed')
        if self.keyboard:
            self.features.add('per_zone_mode')
            self.features.add('per_key_mode')
        if self.keyboard or self.vendor:
            self.features.add('four_zone_mode')
        if self.logo or 'logo' in self.other_arrays:
            self.features.add('usb_logo')
        self.features.update(self.other_arrays)
        self.bar_bridge = next(iter((self.root / 'bus/wmi/devices').glob(
            '7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56*/color')), None)
        if self.bar_bridge:
            self.features.add('lightbar')
        self.extra_files = {}
        # Only expose stock kernel attributes that actually exist.
        for key in ('backlight_timeout', 'battery_calibration', 'battery_limiter',
                    'boot_animation_sound', 'lcd_override', 'usb_charging'):
            p = self.root / 'devices/platform/acer-wmi' / key
            if p.exists():
                self.extra_files[key] = p
                self.features.add(key)
        self.threshold = next(iter((self.root / 'class/power_supply').glob('*/charge_control_end_threshold')), None)
        if self.threshold:
            self.features.add('battery_limiter')
        try:
            self.lighting = json.loads(self.state_file.read_text())
            if not isinstance(self.lighting, dict):
                self.lighting = {}
        except (OSError, ValueError):
            self.lighting = {}

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
            out = dict(version=VERSION, driver_version='Stock Linux acer_wmi + HID',
                       laptop_type=read(self.root / 'class/dmi/id/product_name', 'Acer'),
                       has_four_zone_kb=bool(self.keyboard or self.vendor),
                       available_features=sorted(self.features), ac_online=self.ac_online(),
                       thermal_profile=dict(current=profile, available=choices), fan_speed=fan, fan_rpm=rpm,
                       per_zone_mode=self.lighting.get('per_zone_mode', ''),
                       four_zone_mode=self.lighting.get('four_zone_mode', ''),
                       lighting_modes=self.lighting_modes(), lighting_state=dict(self.lighting), lighting_state_source='last successful command',
                       lighting_devices=[dict(target='keyboard', path=self.keyboard.path)] if self.keyboard else [],
                       effect_color_supported=[0, 1, 4, 5, 6, 7, 8, 9],
                       lightbar_status='available' if 'lightbar' in self.features else
                       'No direct lightbar interface detected on this firmware')
            out['lighting_devices'] += [dict(target=k, path=v.path) for k, v in self.other_arrays.items()]
            if self.logo:
                out['lighting_devices'].append(dict(target='logo', path=self.logo.path))
            if self.bar_bridge:
                out['lighting_devices'].append(dict(target='lightbar', path=str(self.bar_bridge)))
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
            for i in (1, 2):
                try:
                    self._write(self.hwmon / f'pwm{i}_enable', 2)
                except OSError:
                    pass
            raise

    def set_zones(self, p):
        if not self.keyboard:
            raise ValueError('Per-lamp keyboard unavailable')
        colors = [color(p[f'zone{i}']) for i in range(1, 5)]
        brightness = integer(p.get('brightness', 100), 0, 100)
        with self.keyboard as kb:
            lamps = kb.lamps()
            mapping = {l['id']: _scale_rgb(colors[min(l['x'] * 4 // max(kb.w, 1), 3)], brightness)
                       for l in lamps}
            kb.multi(mapping)
        if self.vendor:
            self.vendor.effect(0, colors[0], 5, brightness, mag=True)
        self.lighting['per_zone_mode'] = ','.join([*(bytes(c).hex() for c in colors), str(brightness)])
        self.lighting['four_zone_mode'] = ''
        self.lighting.pop('keyboard', None)
        if self.vendor:
            self.lighting['wasd'] = dict(mode=0, color=bytes(colors[0]).hex(),
                brightness=brightness, speed=5, direction=1)
        self._save()

    def set_effect(self, p, persist=True):
        mode = integer(p.get('mode', 0), 0, 9)
        brightness = integer(p.get('brightness', 100), 0, 100)
        speed = integer(p.get('speed', 5), 1, 9)
        direction = integer(p.get('direction', 1), 1, 2)
        rgb = tuple(integer(p.get(k, 0), 0, 255) for k in ('red', 'green', 'blue'))
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
        # The original DLL uses direction for Wave. Other modes have no
        # direction field. Neon/Rainbow use a firmware palette.
        if persist:
            self.lighting['four_zone_mode'] = ','.join(map(str, [mode, speed, brightness, direction, *rgb]))
            self.lighting['per_zone_mode'] = ''
            self.lighting['keyboard'] = dict(mode=mode, color=bytes(rgb).hex(),
                brightness=brightness, speed=speed, direction=direction)
            self._save()

    def set_light(self, target, rgb, brightness):
        brightness = integer(brightness, 0, 100)
        if target == 'lightbar' and self.bar_bridge:
            self._set_bar(0, rgb, 5, brightness, 1)
        elif target in self.other_arrays:
            with self.other_arrays[target] as dev:
                dev.fill(_scale_rgb(rgb, brightness))
        elif target == 'logo' and self.logo:
            self.logo.color(rgb, brightness)
        else:
            raise ValueError(f'No direct {target} controller detected')
        self.lighting[target] = dict(color=bytes(rgb).hex(), brightness=brightness)
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
            return dict(width=kb.w, height=kb.h, lamps=kb.lamps())

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
        with self.keyboard as kb:
            lamps = kb.lamps()
            valid = {lamp['id'] for lamp in lamps if lamp['programmable']}
            if set(mapping) != valid:
                raise ValueError('Send one color for every programmable keyboard lamp')
            kb.multi({key: _scale_rgb(rgb, brightness) for key, rgb in mapping.items()})
        self.lighting['per_key'] = dict(colors={str(k): bytes(v).hex() for k,v in mapping.items()}, brightness=brightness)
        self.lighting['keyboard'] = dict(kind='per_key', brightness=brightness)
        wasd = {lamp['id'] for lamp in lamps if lamp.get('key_usage') in (4, 7, 22, 26)}
        if self.vendor and wasd and wasd <= mapping.keys():
            self.lighting['wasd'] = dict(kind='per_key', brightness=brightness,
                colors={str(key): bytes(mapping[key]).hex() for key in wasd})
        self.lighting['four_zone_mode'] = self.lighting['per_zone_mode'] = ''
        self._save()

    def set_global_lighting(self, p):
        mode = integer(p.get('mode', 0), 0, 9)
        if mode not in self.lighting_modes().get('all', []):
            raise ValueError('Choose an effect supported by every lighting device')
        color(p.get('color'))
        integer(p.get('brightness', 100), 0, 100)
        integer(p.get('speed', 5), 1, 9)
        integer(p.get('direction', 1), 1, 2)
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
        mode = integer(p.get('mode', 0), 0, 9)
        if mode not in self.lighting_modes().get(target, []):
            raise ValueError('This device does not support the selected effect')
        rgb = color(p.get('color'))
        brightness = integer(p.get('brightness', 100), 0, 100)
        speed = integer(p.get('speed', 5), 1, 9)
        direction = integer(p.get('direction', 1), 1, 2)
        link_wasd = p.get('link_wasd', True)
        if not isinstance(link_wasd, bool):
            raise ValueError('Expected boolean link_wasd')
        if target == 'keyboard':
            self.set_effect(dict(mode=mode, brightness=brightness, speed=speed,
                                 direction=direction, **dict(zip(('red','green','blue'), rgb))), persist=False)
            if link_wasd and self.vendor:
                mag_mode = mode if mode in self.vendor.MAG_EFFECTS else 0
                self.vendor.effect(mag_mode, rgb, speed, brightness, direction, mag=True)
                self.lighting['wasd'] = dict(mode=mag_mode, color=bytes(rgb).hex(), brightness=brightness,
                                            speed=speed, direction=direction)
            self.lighting['four_zone_mode'] = ','.join(map(str, [mode, speed, brightness, direction, *rgb]))
            self.lighting['per_zone_mode'] = ''
        elif target == 'wasd':
            self.vendor.effect(mode, rgb, speed, brightness, direction, mag=True)
        elif target == 'logo':
            self.logo.effect(mode, rgb, speed, brightness, direction)
        elif target == 'lightbar':
            self._set_bar(mode, rgb, speed, brightness, direction)
        self.lighting[target] = dict(mode=mode, color=bytes(rgb).hex(), brightness=brightness,
                                     speed=speed, direction=direction)
        if target == 'keyboard':
            self.lighting[target]['link_wasd'] = link_wasd
        self._save()

    def command(self, name, p):
        with self.lock:
            if name in ('ping', 'get_version'):
                return dict(version=VERSION)
            if name == 'get_all_settings':
                return self.settings()
            if name == 'get_supported_features':
                return dict(available_features=sorted(self.features))
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
                return dict(current=self.set_profile(p.get('profile')))
            if name == 'set_fan_speed':
                self.set_fans(p.get('cpu'), p.get('gpu'))
            elif name == 'set_per_zone_mode':
                self.set_zones(p)
            elif name == 'set_four_zone_mode':
                self.set_effect(p)
            elif name in ('set_logo_color', 'set_light_color'):
                rgb = tuple(integer(p.get(k), 0, 255) for k in ('red', 'green', 'blue'))
                self.set_light('logo' if name == 'set_logo_color' else p.get('target'), rgb, p.get('brightness', 100))
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
