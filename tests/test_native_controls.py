import json
import os
import socket
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import errno
from unittest.mock import MagicMock, Mock

from hardware import daemon, uevents
from hardware.controls import Effect, KeyColors, Lighting, NativeControls, Target
from hardware.hid import CoverLogo, LampArrayDevice, VendorKeyboard, frame
from hardware.hotkey import button_pressed, launch

CHOICES = ['low-power', 'quiet', 'balanced', 'balanced-performance', 'performance']


class NativeTests(unittest.TestCase):
    def test_button_only_accepts_dedicated_press(self) -> None:
        self.assertTrue(button_pressed(3, 40, 1, True))
        self.assertTrue(button_pressed(1, 202, 1, False))
        for args in [(3, 40, 0, True), (3, 40, 2, True), (1, 30, 1, True),
                     (1, 202, 2, False), (3, 40, 1, False)]:
            self.assertFalse(button_pressed(*args))

    def test_button_launch_does_not_check_user_runtime_folder(self) -> None:
        # Without CAP_DAC_READ_SEARCH the daemon cannot stat /run/user/<uid>; launching must not depend on it.
        with patch('hardware.hotkey.subprocess.run', return_value=Mock(returncode=0)) as run, \
             patch('hardware.hotkey.Path.exists', side_effect=AssertionError('runtime folder checked')):
            launch(os.getuid())
        self.assertEqual('/usr/local/bin/acer-fedorizer', run.call_args.args[0][-1])

    def test_fan_rpm_unavailable_is_not_stopped(self) -> None:
        self.assertEqual({'cpu': 2000, 'gpu': None}, self.controls.settings()['fan_rpm'])
        (self.hwmon / 'fan2_input').write_text('0')
        self.assertEqual({'cpu': 2000, 'gpu': 0}, self.controls.settings()['fan_rpm'])
        (self.hwmon / 'fan2_input').write_text('bad')
        self.assertEqual({'cpu': 2000, 'gpu': None}, self.controls.settings()['fan_rpm'])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.profile = self.root / 'class/platform-profile/platform-profile-0'
        self.hwmon = self.root / 'class/hwmon/hwmon0'
        for p, value in [(self.profile / 'name', 'acer-wmi'), (self.profile / 'profile', 'balanced'),
                         (self.profile / 'choices', ' '.join(CHOICES)),
                         (self.hwmon / 'name', 'acer'), (self.hwmon / 'fan1_input', '2000')]:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(value)
        for i in (1, 2):
            (self.hwmon / f'pwm{i}').write_text('128')
            (self.hwmon / f'pwm{i}_enable').write_text('2')
        self.controls = NativeControls(str(self.root), str(self.root / 'state.json'), discover_hid=False)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_discovery_accepts_stock_acer_and_rejects_unrelated_provider(self) -> None:
        self.assertIn('thermal_profile', self.controls.features)
        self.assertIn('fan_speed', self.controls.features)
        (self.profile / 'name').write_text('unrelated-driver')
        other = NativeControls(str(self.root), str(self.root / 'state.json'), discover_hid=False)
        self.assertNotIn('thermal_profile', other.features)

    def test_profile_reads_external_changes_and_reads_do_not_write(self) -> None:
        for choice in CHOICES:
            (self.profile / 'profile').write_text(choice)
            with patch.object(self.controls, '_write', side_effect=AssertionError('read caused write')):
                self.assertEqual({'current': choice, 'available': CHOICES}, self.controls.settings()['thermal_profile'])
        with self.assertRaises(ValueError):
            self.controls.command('set_thermal_profile', {'profile': 'turbo'})

    def test_rejected_profile_does_not_change_fans(self) -> None:
        with patch.object(self.controls, '_write', side_effect=PermissionError('firmware rejected')), \
             self.assertRaises(PermissionError):
            self.controls.command('set_thermal_profile', {'profile': 'performance'})
        self.assertEqual('2', (self.hwmon / 'pwm1_enable').read_text())

    def test_unified_lighting_validates_before_hardware_and_saves_only_success(self) -> None:
        from unittest.mock import Mock
        self.controls.logo = Mock()
        params = {'target': 'logo', 'mode': 1, 'color': 'ff2300', 'brightness': 90, 'speed': 4, 'direction': 1}
        self.controls.command('set_lighting', params)
        self.controls.logo.effect.assert_called_once_with(1, (255,35,0), 4, 90, 1)
        self.assertEqual(Effect(1, (255, 35, 0), 4, 90, 1), self.controls.lighting.logo)
        old = self.controls.state_file.read_text()
        self.controls.logo.effect.side_effect = OSError('failed')
        with self.assertRaises(OSError): self.controls.command('set_lighting', dict(params, color='00ff00'))
        self.assertEqual(old, self.controls.state_file.read_text())
        self.controls.logo.effect.reset_mock()
        with self.assertRaises(ValueError): self.controls.command('set_lighting', dict(params, mode=3))
        self.controls.logo.effect.assert_not_called()

    def test_linked_wasd_failure_does_not_persist_partial_keyboard_success(self) -> None:
        from unittest.mock import Mock
        c = self.controls
        c.vendor = Mock()
        c.vendor.MAG_EFFECTS = VendorKeyboard.MAG_EFFECTS
        c.vendor.effect.side_effect = [None, OSError('WASD failed')]
        c.lighting = Lighting(keyboard=Effect(0, (0, 0, 255)))
        c._save()
        previous = c.state_file.read_text()
        with self.assertRaises(OSError):
            c.command('set_lighting', {'target': 'keyboard', 'mode': 1, 'color': 'ff0000'})
        self.assertEqual(previous, c.state_file.read_text())
        self.assertEqual(Lighting(keyboard=Effect(0, (0, 0, 255))), c.lighting)

    def test_unknown_target_or_missing_device_is_rejected(self) -> None:
        c = self.controls
        c.vendor = Mock()
        for target in ('lid', None, ['logo']):
            with self.assertRaisesRegex(ValueError, 'Unsupported lighting target'):
                c.command('set_lighting', {'target': target, 'mode': 0, 'color': 'ff0000'})
        with self.assertRaisesRegex(ValueError, 'No logo lighting device'):
            c._apply(Target.LOGO, Effect(0, (255, 0, 0)))
        c.vendor.effect.assert_not_called()

    def test_link_option_validates_before_any_keyboard_write(self) -> None:
        from unittest.mock import Mock
        c = self.controls
        c.vendor = Mock()
        with self.assertRaises(ValueError):
            c.command('set_lighting', {'target': 'keyboard', 'mode': 1, 'color': 'ff0000', 'link_wasd': 'false'})
        c.vendor.effect.assert_not_called()

    def test_global_sync_exposes_only_common_effects_and_reports_partial_failure(self) -> None:
        from unittest.mock import Mock
        c = self.controls
        c.vendor = Mock()
        c.vendor.MAG_EFFECTS = VendorKeyboard.MAG_EFFECTS
        c.logo = Mock()
        self.assertEqual([0, 1, 2], c.lighting_modes()['all'])
        with self.assertRaises(ValueError):
            c.command('set_lighting', {'target': 'all', 'mode': 7, 'color': 'ff0000'})
        c.vendor.effect.assert_not_called()
        c.logo.effect.side_effect = OSError('logo disconnected')
        with self.assertRaisesRegex(RuntimeError, 'applied to keyboard, wasd'):
            c.command('set_lighting', {'target': 'all', 'mode': 1, 'color': 'ff0000'})
        self.assertEqual(Effect(1, (255, 0, 0)), c.lighting.keyboard)
        self.assertEqual(Effect(1, (255, 0, 0)), c.lighting.wasd)
        self.assertNotIn('logo', c.lighting.to_json())
        self.assertNotIn('all', c.lighting.to_json())
        self.assertEqual(c.lighting.to_json(), json.loads(c.state_file.read_text()))
        self.assertEqual(c.lighting.to_json(), c.settings()['lighting_state'])

    def test_per_key_validates_full_map_and_scales_brightness(self) -> None:
        from unittest.mock import MagicMock
        c = self.controls
        keyboard = MagicMock()
        keyboard.open.return_value.__enter__.return_value = keyboard
        keyboard.lamps.return_value = [{'id': 0, 'programmable': True}, {'id': 1, 'programmable': True}]
        c.keyboard = keyboard
        with self.assertRaises(ValueError):
            c.command('set_per_key', {'colors': {'0':'ff0000'}})
        keyboard.multi.assert_not_called()
        c.command('set_per_key', {'colors': {'0':'ff0000','1':'0000ff'},'brightness': 50})
        keyboard.multi.assert_called_once_with({0:(128,0,0),1:(0,0,128)})
        self.assertEqual(KeyColors({0: (255, 0, 0), 1: (0, 0, 255)}, 50), c.lighting.per_key)
        self.assertEqual('per_key', c.lighting.keyboard)
        previous = c.state_file.read_text()
        keyboard.multi.side_effect = OSError('transfer failed')
        with self.assertRaises(OSError):
            c.command('set_per_key', {'colors': {'0':'00ff00','1':'00ff00'}})
        self.assertEqual(previous, c.state_file.read_text())

    def test_logo_uses_logo_specific_mode_path(self) -> None:
        from hardware.hid import CoverLogo
        sent = []
        with patch('hardware.hid.os.open', return_value=3), patch('hardware.hid.os.close'), patch('hardware.hid.time.sleep'), patch('hardware.hid.send_feature', side_effect=lambda fd, data: sent.append(data)):
            CoverLogo('/dev/fake').effect(0, (255,35,0), 5, 100)
        self.assertEqual(frame(0x08, 3, 1, 11, 100, 0, 0), sent[-1])
        self.assertEqual(frame(0x14, 0, 0, 255,35,0,0), sent[-2])

    def test_mag_color_scope_and_mode(self) -> None:
        kb = VendorKeyboard('/dev/fake')
        sent = []
        with patch('hardware.hid.os.open', return_value=3), patch('hardware.hid.os.close'), patch('hardware.hid.send_feature', side_effect=lambda fd, data: sent.append(data)):
            kb.effect(1, (255,35,0), 4, 90, mag=True)
        self.assertEqual(frame(0x08, 2, 0x42, 6, 90, 0, 0), sent[2])
        self.assertEqual(frame(0x14, 0, 1, 255,35,0,0), sent[3])

    def test_manual_max_and_auto_fans(self) -> None:
        self.controls.set_fans(50, 100)
        self.assertEqual('128', (self.hwmon / 'pwm1').read_text())
        self.assertEqual('1', (self.hwmon / 'pwm1_enable').read_text())
        self.assertEqual('0', (self.hwmon / 'pwm2_enable').read_text())
        self.assertEqual({'cpu': {'mode': 'manual', 'percent': 50}, 'gpu': {'mode': 'max', 'percent': 100}},
                         self.controls.settings()['fans'])
        self.controls.set_fans(0, 0)
        self.assertEqual('2', (self.hwmon / 'pwm1_enable').read_text())
        self.assertEqual({'cpu': {'mode': 'auto', 'percent': 0}, 'gpu': {'mode': 'auto', 'percent': 0}},
                         self.controls.settings()['fans'])

    def test_settings_reply_types(self) -> None:
        self.assertIn('fan_speed', self.controls.settings()['available_features'])
        self.assertNotIn('fan_speed', self.controls.settings())
        acer_wmi = self.root / 'devices/platform/acer-wmi'
        acer_wmi.mkdir(parents=True)
        for key, value in (('backlight_timeout', '1'), ('battery_calibration', '0'), ('battery_limiter', '1'),
                           ('boot_animation_sound', 'bad'), ('lcd_override', '1'), ('usb_charging', '20')):
            (acer_wmi / key).write_text(value)
        c = NativeControls(str(self.root), str(self.root / 'state.json'), discover_hid=False)
        settings = c.settings()
        self.assertEqual((True, False, True, False, True, 20),
                         tuple(settings[key] for key in ('backlight_timeout', 'battery_calibration', 'battery_limiter',
                                                         'boot_animation_sound', 'lcd_override', 'usb_charging')))
        (acer_wmi / 'usb_charging').write_text('off')
        self.assertEqual(0, c.settings()['usb_charging'])
        battery = self.root / 'class/power_supply/BAT1/charge_control_end_threshold'
        battery.parent.mkdir(parents=True)
        for threshold, limited in (('80', True), ('100', False)):
            battery.write_text(threshold)
            settings = NativeControls(str(self.root), str(self.root / 'state.json'), discover_hid=False).settings()
            self.assertIs(limited, settings['battery_limiter'])
        for path in self.hwmon.iterdir():
            path.unlink()
        settings = NativeControls(str(self.root), str(self.root / 'state.json'), discover_hid=False).settings()
        self.assertNotIn('fans', settings)
        self.assertEqual({'cpu': None, 'gpu': None}, settings['fan_rpm'])

    def test_invalid_second_fan_cannot_partially_apply_first(self) -> None:
        with self.assertRaises(ValueError):
            self.controls.command('set_fan_speed', {'cpu': 100, 'gpu': 200})
        self.assertEqual('2', (self.hwmon / 'pwm1_enable').read_text())

    def test_bar_bridge_discovery_validation_and_failed_state(self) -> None:
        p = self.root / 'bus/wmi/devices/7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56/color'
        p.parent.mkdir(parents=True)
        p.touch()
        c = NativeControls(str(self.root), str(self.root / 'state.json'), discover_hid=False)
        self.assertIn('lightbar', c.features)
        params = {'target': 'lightbar', 'mode': 0, 'color': '0050ff', 'brightness': 80}
        c.command('set_lighting', params)
        self.assertEqual('0 80 255 80', p.read_text())
        previous = c.state_file.read_text()
        with patch.object(c, '_write', side_effect=OSError('firmware rejected')), self.assertRaises(OSError):
            c.command('set_lighting', dict(params, color='ff50ff'))
        self.assertEqual(previous, c.state_file.read_text())
        with self.assertRaises(ValueError):
            c.command('set_lighting', dict(params, color='zz50ff'))

    def test_partial_fan_failure_restores_automatic_cooling(self) -> None:
        original = self.controls._write
        def fail_second(path: Path, value: object) -> None:
            if Path(path).name == 'pwm2' and value != 2:
                raise OSError('second fan failed')
            original(path, value)
        with patch.object(self.controls, '_write', side_effect=fail_second), self.assertRaises(OSError):
            self.controls.set_fans(50, 60)
        self.assertEqual('2', (self.hwmon / 'pwm1_enable').read_text())
        self.assertEqual('2', (self.hwmon / 'pwm2_enable').read_text())

    def test_bar_static_loads_color_before_switching_and_preserves_state_on_failure(self) -> None:
        bar = self.root / 'bar/color'
        bar.parent.mkdir()
        bar.touch()
        bar.with_name('effect').touch()
        c = self.controls
        c.bar_bridge = bar
        params = {'target': 'lightbar', 'mode': 0, 'color': 'ff2300', 'speed': 5,
                      'brightness': 90, 'direction': 1}
        with patch.object(c, '_write') as write, patch('hardware.controls.time.sleep'):
            c.command('set_lighting', params)
        self.assertEqual(['1 3 90 1 255 35 0', '0 3 90 1 255 35 0'],
                         [call.args[1] for call in write.call_args_list])
        previous = c.state_file.read_text()
        with patch.object(c, '_write', side_effect=[None, OSError('static failed')]), \
             patch('hardware.controls.time.sleep'), self.assertRaises(OSError):
            c.command('set_lighting', dict(params, color='0000ff'))
        self.assertEqual(previous, c.state_file.read_text())
        with patch.object(c, '_write') as write, patch('hardware.controls.time.sleep'):
            c.command('set_lighting', {'target': 'lightbar', 'mode': 0, 'color': '0032ff'})
        self.assertEqual(['1 3 100 1 0 50 255', '0 3 100 1 0 50 255'],
                         [call.args[1] for call in write.call_args_list])

    def test_original_dll_effect_sequence_and_color_order(self) -> None:
        reports = []
        with patch('hardware.hid.os.open', return_value=7), patch('hardware.hid.os.close'), \
             patch('hardware.hid.send_feature', side_effect=lambda fd, data: reports.append(data)):
            VendorKeyboard('/dev/test').effect(1, (255, 20, 80), 7, 60)
        self.assertEqual([frame(0xB1), frame(8, 2), frame(8, 2, 2, 3, 60, 0, 0),
                          frame(0x14, 0, 0, 255, 20, 80, 0)], reports)
        self.assertTrue(all(sum(r[1:]) % 256 == 255 for r in reports))

    def test_lamp_array_session_report_bytes_and_order(self) -> None:
        reports = []
        def ioctl(fd: int, request: int, buf: bytearray, mutate: bool) -> None:
            reports.append((fd, request, bytes(buf)))
            if buf[0] == 0x02:
                buf[1:11] = struct.pack('<HII', 3, 400, 150)
            elif buf[0] == 0x22:
                lamp = sum(report[0] == 0x22 for _, _, report in reports) - 1
                buf[1:15] = struct.pack('<HIII', lamp, lamp * 100, 10, 0)
                buf[27], buf[28] = 1, 4 + lamp
        device = LampArrayDevice('/dev/test', 0x5AF, 0x666A, 'k', {u: u for u in (2, 0x20, 0x22, 0x50, 0x60, 0x70)}, 2)
        with patch('hardware.hid.os.open', return_value=9), patch('hardware.hid.os.close') as close, \
             patch('hardware.hid.fcntl.ioctl', side_effect=ioctl), patch('hardware.hid.time.sleep'):
            with device.open() as kb:
                kb.fill((1, 2, 3))
                lamps = kb.lamps()
                kb.multi({2: (7, 8, 9), 0: (1, 2, 3), 1: (4, 5, 6)})
                kb.autonomous(True)
            close.assert_called_once_with(9)
        self.assertEqual((400, 150), (kb.w, kb.h))
        self.assertEqual({'id': 2, 'x': 200, 'y': 10, 'z': 0, 'programmable': True, 'key_usage': 6}, lamps[2])
        self.assertEqual([(0xC0174807, '02' + '00' * 22), (0xC0024806, '7000'), (0xC00A4806, '600100000200010203ff'),
                          (0xC0034806, '200000'), (0xC01D4807, '22' + '00' * 28),
                          (0xC0034806, '200100'), (0xC01D4807, '22' + '00' * 28),
                          (0xC0034806, '200200'), (0xC01D4807, '22' + '00' * 28),
                          (0xC0024806, '7000'), (0xC00F4806, '50020000000100010203ff040506ff'),
                          (0xC00F4806, '50010102000000070809ff00000000'), (0xC0024806, '7001')],
                         [(request, data.hex()) for _, request, data in reports])
        self.assertTrue(all(fd == 9 for fd, _, _ in reports))

    def test_lamp_array_open_closes_node_on_invalid_count(self) -> None:
        device = LampArrayDevice('/dev/test', 0x5AF, 0x666A, 'k', {u: u for u in (2, 0x20, 0x22, 0x50, 0x60, 0x70)}, 2)
        with patch('hardware.hid.os.open', return_value=9), patch('hardware.hid.os.close') as close, \
             patch('hardware.hid.fcntl.ioctl'), self.assertRaises(ValueError):
            device.open()
        close.assert_called_once_with(9)

    def test_effect_failure_is_not_saved_as_success(self) -> None:
        with self.assertRaises(ValueError):
            self.controls.command('set_lighting', {'target': 'keyboard', 'mode': 1, 'color': 'ff0000'})
        self.assertEqual({}, self.controls.lighting.to_json())
        self.assertFalse((self.root / 'state.json').exists())

    def test_fragmented_and_coalesced_requests(self) -> None:
        path = str(self.root / 'rpc.sock')
        server = daemon.NativeServer(path, self.controls)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(2)
                client.connect(path)
                client.sendall(b'{"command":"get_all_')
                client.sendall(b'settings"}\n{"command":"ping"}\n')
                stream = client.makefile('rb')
                first, second = json.loads(stream.readline()), json.loads(stream.readline())
                self.assertTrue(first['success'])
                self.assertEqual('balanced', first['data']['thermal_profile']['current'])
                self.assertTrue(second['success'])
                client.sendall(b'not-json\n{"command":"ping"}\n')
                self.assertFalse(json.loads(stream.readline())['success'])
                self.assertTrue(json.loads(stream.readline())['success'])
                stream.close()
        finally:
            server.shutdown(); server.server_close(); thread.join(2)

    def lamp_keyboard(self) -> MagicMock:
        keyboard = MagicMock()
        keyboard.open.return_value.__enter__.return_value = keyboard
        keyboard.w = 400
        keyboard.lamps.return_value = [{'id': i, 'x': i * 100 + 50, 'programmable': True, 'key_usage': 4 + i} for i in range(4)]
        return keyboard

    def test_zones_apply_full_color_without_brightness(self) -> None:
        c = self.controls
        c.keyboard = keyboard = self.lamp_keyboard()
        c.vendor = Mock()
        c.command('set_per_zone_mode', {'zone1': 'ff0000', 'zone2': '00ff00', 'zone3': '0000ff', 'zone4': 'ffffff'})
        keyboard.multi.assert_called_once_with({0: (255, 0, 0), 1: (0, 255, 0), 2: (0, 0, 255), 3: (255, 255, 255)})
        c.vendor.effect.assert_called_once_with(0, (255, 0, 0), 5, 100, mag=True)
        self.assertEqual({'kind': 'zones', 'colors': ['ff0000', '00ff00', '0000ff', 'ffffff']}, c.lighting.to_json()['keyboard'])

    def test_restore_replays_saved_lighting_without_changing_it(self) -> None:
        c = self.controls
        c.keyboard = keyboard = self.lamp_keyboard()
        c.vendor, c.logo = Mock(), Mock()
        c.vendor.MAG_EFFECTS = VendorKeyboard.MAG_EFFECTS
        c.command('set_per_key', {'colors': {str(i): 'ff0000' for i in range(4)}, 'brightness': 50})
        c.command('set_lighting', {'target': 'wasd', 'mode': 1, 'color': '00ff00', 'speed': 3, 'brightness': 70})
        c.command('set_lighting', {'target': 'logo', 'mode': 0, 'color': '0000ff', 'brightness': 60})
        saved = c.state_file.read_text()
        for device in (keyboard, c.vendor, c.logo):
            device.reset_mock()
        c.logo.effect.side_effect = OSError('logo disconnected')
        with self.assertLogs('fedorizer', 'WARNING'):
            c.restore_lighting()
        keyboard.multi.assert_called_once_with(dict.fromkeys(range(4), (128, 0, 0)))
        c.vendor.effect.assert_called_once_with(1, (0, 255, 0), 3, 70, 1, mag=True)
        c.logo.effect.assert_called_once_with(0, (0, 0, 255), 5, 60, 1)
        self.assertEqual(saved, c.state_file.read_text())

    def test_restore_replays_zones_and_effects(self) -> None:
        c = self.controls
        c.keyboard = keyboard = self.lamp_keyboard()
        c.vendor = Mock()
        c.lighting = Lighting.parse({'keyboard': {'kind': 'zones', 'colors': ['ff0000'] * 4}})
        c.restore_lighting()
        keyboard.multi.assert_called_once()
        c.lighting = Lighting.parse({'keyboard': {'mode': 1, 'color': '102030', 'brightness': 40, 'speed': 2, 'direction': 1}})
        c.vendor.reset_mock()
        c.restore_lighting()
        c.vendor.effect.assert_called_once_with(1, (16, 32, 48), 2, 40, 1)

    def test_saved_state_from_earlier_versions_loads_unchanged_and_replays(self) -> None:
        saved = {'per_key': {'colors': {str(i): 'ff0000' for i in range(4)}, 'brightness': 50},
                 'keyboard': {'kind': 'per_key', 'brightness': 50},
                 'wasd': {'kind': 'per_key', 'brightness': 50, 'colors': {'0': 'ff0000'}},
                 'logo': {'mode': 0, 'color': '0000ff', 'brightness': 60, 'speed': 5, 'direction': 1},
                 'all': {'mode': 1, 'color': '00ff00', 'brightness': 100, 'speed': 5, 'direction': 1}}
        self.controls.state_file.write_text(json.dumps(saved))
        c = NativeControls(str(self.root), str(self.controls.state_file), discover_hid=False)
        self.assertEqual(saved, c.lighting.to_json())
        self.assertEqual(saved, c.settings()['lighting_state'])
        c.keyboard = keyboard = self.lamp_keyboard()
        c.vendor, c.logo = Mock(), Mock()
        c.vendor.MAG_EFFECTS = VendorKeyboard.MAG_EFFECTS
        c.restore_lighting()
        keyboard.multi.assert_called_once_with(dict.fromkeys(range(4), (128, 0, 0)))
        c.vendor.effect.assert_not_called()
        c.logo.effect.assert_called_once_with(0, (0, 0, 255), 5, 60, 1)
        effect = {'mode': 1, 'color': '102030', 'brightness': 40, 'speed': 2, 'direction': 1, 'link_wasd': False}
        self.assertEqual({'keyboard': effect}, Lighting.parse({'keyboard': effect}).to_json())
        zones = {'kind': 'zones', 'colors': ['ff0000', '00ff00', '0000ff', 'ffffff']}
        self.assertEqual({'keyboard': zones}, Lighting.parse({'keyboard': zones}).to_json())

    def test_invalid_saved_entries_are_dropped_at_load(self) -> None:
        valid = {'mode': 0, 'color': '00ff00', 'brightness': 100, 'speed': 5, 'direction': 1}
        saved = {'keyboard': {'kind': 'per_key', 'brightness': 50}, 'wasd': valid,
                 'logo': {'mode': 1, 'color': 'zz0000'}, 'lightbar': 'red', 'all': {'color': '00ff00'},
                 'per_key': {'colors': {'-1': 'ff0000'}}, 'unknown': {}}
        self.controls.state_file.write_text(json.dumps(saved))
        with self.assertLogs('fedorizer', 'WARNING') as logs:
            c = NativeControls(str(self.root), str(self.controls.state_file), discover_hid=False)
        self.assertEqual({'wasd': valid}, c.lighting.to_json())
        self.assertEqual(5, len(logs.output))
        for broken in ('[]', 'not json'):
            self.controls.state_file.write_text(broken)
            self.assertEqual(Lighting(), NativeControls(str(self.root), str(self.controls.state_file),
                                                        discover_hid=False).lighting)
        effect = dict(valid, link_wasd='yes')
        with self.assertLogs('fedorizer', 'WARNING'):
            self.assertEqual(Lighting(), Lighting.parse({'keyboard': effect}))

    def test_fans_return_to_automatic_even_if_one_write_fails(self) -> None:
        (self.hwmon / 'pwm2_enable').write_text('1')
        original = self.controls._write
        def fail_first(path: Path, value: object) -> None:
            if Path(path).name == 'pwm1_enable':
                raise OSError('busy')
            original(path, value)
        with patch.object(self.controls, '_write', side_effect=fail_first):
            self.controls.auto_fans()
        self.assertEqual('2', (self.hwmon / 'pwm2_enable').read_text())

    def test_daemon_auto_fans_option_restores_firmware_control(self) -> None:
        for i in (1, 2):
            (self.hwmon / f'pwm{i}_enable').write_text('1')
        with patch('sys.argv', ['daemon', '--auto-fans', '--state-file', str(self.root / 'state.json')]), \
             patch.object(daemon, 'NativeControls', lambda **kw: NativeControls(str(self.root), **kw)):
            daemon.main()
        self.assertEqual(['2', '2'], [(self.hwmon / f'pwm{i}_enable').read_text() for i in (1, 2)])

    def test_hid_discovery_reads_the_injected_sysfs_root(self) -> None:
        for name, uevent, descriptor in (('hidraw3', 'HID_NAME=ACER Keyboard\n', b'\x06\x02\xff\x09'),
                                         ('hidraw5', 'HID_ID=0003:00000D62:0000BA51\n', b'')):
            device = self.root / 'class/hidraw' / name / 'device'
            device.mkdir(parents=True)
            (device / 'uevent').write_text(uevent)
            (device / 'report_descriptor').write_bytes(descriptor)
        vendor, logo = VendorKeyboard.discover(self.root), CoverLogo.discover(self.root)
        assert vendor and logo
        self.assertEqual(('/dev/hidraw3', '/dev/hidraw5'), (vendor.path, logo.path))

    def test_uevents_report_subsystem_and_treat_overflow_as_change(self) -> None:
        message = b'add@/devices/x/hidraw/hidraw3\0ACTION=add\0SUBSYSTEM=hidraw\0DEVNAME=hidraw3\0'
        self.assertEqual('hidraw', uevents.parse(message)['SUBSYSTEM'])
        self.assertEqual({}, uevents.parse(b'libudev\0SUBSYSTEM=hidraw\0'))
        sock = Mock()
        sock.recv.return_value = message
        self.assertTrue(uevents.changed(sock, {'hidraw'}))
        self.assertFalse(uevents.changed(sock, {'input'}))
        sock.recv.side_effect = OSError(errno.ENOBUFS, 'overflow')
        self.assertTrue(uevents.changed(sock, {'input'}))


if __name__ == '__main__':
    unittest.main()
