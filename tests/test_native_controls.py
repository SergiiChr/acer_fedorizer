import importlib.util
import json
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'DAMM-Daemon'))
from native_controls import NativeControls
from acer_hid import frame, VendorKeyboard
from predator_button import button_pressed
spec = importlib.util.spec_from_file_location('damx_server', ROOT / 'DAMM-Daemon/DAMX-Daemon.py')
daemon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daemon)


class NativeTests(unittest.TestCase):
    def test_button_only_accepts_dedicated_press(self):
        self.assertTrue(button_pressed(3, 40, 1, True))
        self.assertTrue(button_pressed(1, 202, 1, False))
        for args in [(3, 40, 0, True), (3, 40, 2, True), (1, 30, 1, True),
                     (1, 202, 2, False), (3, 40, 1, False)]:
            self.assertFalse(button_pressed(*args))

    def test_fan_rpm_unavailable_is_not_stopped(self):
        self.assertEqual(self.controls.settings()['fan_rpm'], {'cpu': 2000, 'gpu': None})
        (self.hwmon / 'fan2_input').write_text('0')
        self.assertEqual(self.controls.settings()['fan_rpm']['gpu'], 0)
        (self.hwmon / 'fan2_input').write_text('bad')
        self.assertIsNone(self.controls.settings()['fan_rpm']['gpu'])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.profile = self.root / 'class/platform-profile/platform-profile-0'
        self.hwmon = self.root / 'class/hwmon/hwmon0'
        for p, value in [(self.profile / 'name', 'acer-wmi'), (self.profile / 'profile', 'balanced'),
                         (self.profile / 'choices', 'low-power quiet balanced balanced-performance performance'),
                         (self.hwmon / 'name', 'acer'), (self.hwmon / 'fan1_input', '2000')]:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(value)
        for i in (1, 2):
            (self.hwmon / f'pwm{i}').write_text('128')
            (self.hwmon / f'pwm{i}_enable').write_text('2')
        self.controls = NativeControls(str(self.root), str(self.root / 'state.json'), discover_hid=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_discovery_accepts_stock_acer_and_rejects_unrelated_provider(self):
        self.assertIn('thermal_profile', self.controls.features)
        self.assertIn('fan_speed', self.controls.features)
        (self.profile / 'name').write_text('unrelated-driver')
        other = NativeControls(str(self.root), str(self.root / 'state.json'), discover_hid=False)
        self.assertNotIn('thermal_profile', other.features)

    def test_profile_reads_external_changes_and_reads_do_not_write(self):
        for choice in self.controls.settings()['thermal_profile']['available']:
            (self.profile / 'profile').write_text(choice)
            with patch.object(self.controls, '_write', side_effect=AssertionError('read caused write')):
                self.assertEqual(choice, self.controls.settings()['thermal_profile']['current'])
        with self.assertRaises(ValueError):
            self.controls.command('set_thermal_profile', {'profile': 'turbo'})

    def test_rejected_profile_does_not_change_fans(self):
        with patch.object(self.controls, '_write', side_effect=PermissionError('firmware rejected')):
            with self.assertRaises(PermissionError):
                self.controls.command('set_thermal_profile', {'profile': 'performance'})
        self.assertEqual('2', (self.hwmon / 'pwm1_enable').read_text())

    def test_unified_lighting_validates_before_hardware_and_saves_only_success(self):
        from unittest.mock import Mock
        self.controls.logo = Mock()
        params = dict(target='logo', mode=1, color='ff2300', brightness=90, speed=4, direction=1)
        self.controls.command('set_lighting', params)
        self.controls.logo.effect.assert_called_once_with(1, (255,35,0), 4, 90, 1)
        self.assertEqual('ff2300', self.controls.lighting['logo']['color'])
        old = self.controls.state_file.read_text()
        self.controls.logo.effect.side_effect = OSError('failed')
        with self.assertRaises(OSError): self.controls.command('set_lighting', dict(params, color='00ff00'))
        self.assertEqual(old, self.controls.state_file.read_text())
        self.controls.logo.effect.reset_mock()
        with self.assertRaises(ValueError): self.controls.command('set_lighting', dict(params, mode=3))
        self.controls.logo.effect.assert_not_called()

    def test_linked_wasd_failure_does_not_persist_partial_keyboard_success(self):
        from unittest.mock import Mock
        c = self.controls
        c.vendor = Mock()
        c.vendor.MAG_EFFECTS = VendorKeyboard.MAG_EFFECTS
        c.vendor.effect.side_effect = [None, OSError('WASD failed')]
        c.lighting = {'keyboard': {'color': '0000ff'}}
        c._save()
        previous = c.state_file.read_text()
        with self.assertRaises(OSError):
            c.command('set_lighting', dict(target='keyboard', mode=1, color='ff0000'))
        self.assertEqual(previous, c.state_file.read_text())
        self.assertEqual({'keyboard': {'color': '0000ff'}}, c.lighting)

    def test_link_option_validates_before_any_keyboard_write(self):
        from unittest.mock import Mock
        c = self.controls
        c.vendor = Mock()
        with self.assertRaises(ValueError):
            c.command('set_lighting', dict(target='keyboard', mode=1, color='ff0000', link_wasd='false'))
        c.vendor.effect.assert_not_called()

    def test_global_sync_exposes_only_common_effects_and_reports_partial_failure(self):
        from unittest.mock import Mock
        c = self.controls
        c.vendor = Mock()
        c.vendor.MAG_EFFECTS = VendorKeyboard.MAG_EFFECTS
        c.logo = Mock()
        self.assertEqual([0, 1, 2], c.lighting_modes()['all'])
        with self.assertRaises(ValueError):
            c.command('set_lighting', dict(target='all', mode=7, color='ff0000'))
        c.vendor.effect.assert_not_called()
        c.logo.effect.side_effect = OSError('logo disconnected')
        with self.assertRaisesRegex(RuntimeError, 'applied to keyboard, wasd'):
            c.command('set_lighting', dict(target='all', mode=1, color='ff0000'))
        self.assertEqual('ff0000', c.lighting['keyboard']['color'])
        self.assertEqual('ff0000', c.lighting['wasd']['color'])
        self.assertNotIn('logo', c.lighting)
        self.assertNotIn('all', c.lighting)

    def test_per_key_validates_full_map_and_scales_brightness(self):
        from unittest.mock import MagicMock
        c = self.controls
        keyboard = MagicMock()
        keyboard.__enter__.return_value = keyboard
        keyboard.lamps.return_value = [dict(id=0, programmable=True), dict(id=1, programmable=True)]
        c.keyboard = keyboard
        with self.assertRaises(ValueError):
            c.command('set_per_key', dict(colors={'0':'ff0000'}))
        keyboard.multi.assert_not_called()
        c.command('set_per_key', dict(colors={'0':'ff0000','1':'0000ff'},brightness=50))
        keyboard.multi.assert_called_once_with({0:(128,0,0),1:(0,0,128)})
        self.assertEqual('per_key', c.lighting['keyboard']['kind'])
        self.assertEqual('ff0000', c.lighting['per_key']['colors']['0'])
        previous = c.state_file.read_text()
        keyboard.multi.side_effect = OSError('transfer failed')
        with self.assertRaises(OSError):
            c.command('set_per_key', dict(colors={'0':'00ff00','1':'00ff00'}))
        self.assertEqual(previous, c.state_file.read_text())

    def test_logo_uses_logo_specific_mode_path(self):
        from acer_hid import CoverLogo
        sent = []
        with patch('acer_hid.os.open', return_value=3), patch('acer_hid.os.close'), patch('acer_hid.time.sleep'), patch('acer_hid.send_feature', side_effect=lambda fd, data: sent.append(data)):
            CoverLogo('/dev/fake').effect(0, (255,35,0), 5, 100)
        self.assertEqual(frame(0x08, 3, 1, 11, 100, 0, 0), sent[-1])
        self.assertEqual(frame(0x14, 0, 0, 255,35,0,0), sent[-2])

    def test_mag_color_scope_and_mode(self):
        kb = VendorKeyboard('/dev/fake')
        sent = []
        with patch('acer_hid.os.open', return_value=3), patch('acer_hid.os.close'), patch('acer_hid.send_feature', side_effect=lambda fd, data: sent.append(data)):
            kb.effect(1, (255,35,0), 4, 90, mag=True)
        self.assertEqual(frame(0x08, 2, 0x42, 6, 90, 0, 0), sent[2])
        self.assertEqual(frame(0x14, 0, 1, 255,35,0,0), sent[3])

    def test_manual_max_and_auto_fans(self):
        self.controls.set_fans(50, 100)
        self.assertEqual('128', (self.hwmon / 'pwm1').read_text())
        self.assertEqual('1', (self.hwmon / 'pwm1_enable').read_text())
        self.assertEqual('0', (self.hwmon / 'pwm2_enable').read_text())
        self.assertEqual('100', self.controls.settings()['fan_speed']['gpu'])
        self.controls.set_fans(0, 0)
        self.assertEqual('2', (self.hwmon / 'pwm1_enable').read_text())

    def test_invalid_second_fan_cannot_partially_apply_first(self):
        with self.assertRaises(ValueError):
            self.controls.set_fans(100, 200)
        self.assertEqual('2', (self.hwmon / 'pwm1_enable').read_text())

    def test_bar_bridge_discovery_validation_and_failed_state(self):
        p = self.root / 'bus/wmi/devices/7A4DDFE7-5B5D-40B4-8595-4408E0CC7F56/color'
        p.parent.mkdir(parents=True)
        p.touch()
        c = NativeControls(str(self.root), str(self.root / 'state.json'), discover_hid=False)
        self.assertIn('lightbar', c.features)
        params = dict(target='lightbar', red=0, green=80, blue=255, brightness=80)
        c.command('set_light_color', params)
        self.assertEqual('0 80 255 80', p.read_text())
        previous = c.state_file.read_text()
        with patch.object(c, '_write', side_effect=OSError('firmware rejected')):
            with self.assertRaises(OSError):
                c.command('set_light_color', dict(params, red=255))
        self.assertEqual(previous, c.state_file.read_text())
        with self.assertRaises(ValueError):
            c.command('set_light_color', dict(params, red=256))

    def test_partial_fan_failure_restores_automatic_cooling(self):
        original = self.controls._write
        def fail_second(path, value):
            if Path(path).name == 'pwm2' and value != 2:
                raise OSError('second fan failed')
            original(path, value)
        with patch.object(self.controls, '_write', side_effect=fail_second):
            with self.assertRaises(OSError):
                self.controls.set_fans(50, 60)
        self.assertEqual('2', (self.hwmon / 'pwm1_enable').read_text())
        self.assertEqual('2', (self.hwmon / 'pwm2_enable').read_text())

    def test_bar_static_loads_color_before_switching_and_preserves_state_on_failure(self):
        bar = self.root / 'bar/color'
        bar.parent.mkdir()
        bar.touch()
        bar.with_name('effect').touch()
        c = self.controls
        c.bar_bridge = bar
        params = dict(target='lightbar', mode=0, color='ff2300', speed=5,
                      brightness=90, direction=1)
        with patch.object(c, '_write') as write, patch('native_controls.time.sleep'):
            c.command('set_lighting', params)
        self.assertEqual(['1 3 90 1 255 35 0', '0 3 90 1 255 35 0'],
                         [call.args[1] for call in write.call_args_list])
        previous = c.state_file.read_text()
        with patch.object(c, '_write', side_effect=[None, OSError('static failed')]), \
             patch('native_controls.time.sleep'):
            with self.assertRaises(OSError):
                c.command('set_lighting', dict(params, color='0000ff'))
        self.assertEqual(previous, c.state_file.read_text())
        with patch.object(c, '_write') as write, patch('native_controls.time.sleep'):
            c.command('set_light_color', dict(target='lightbar', red=0, green=50, blue=255))
        self.assertEqual(['1 3 100 1 0 50 255', '0 3 100 1 0 50 255'],
                         [call.args[1] for call in write.call_args_list])

    def test_original_dll_effect_sequence_and_color_order(self):
        reports = []
        with patch('acer_hid.os.open', return_value=7), patch('acer_hid.os.close'), \
             patch('acer_hid.send_feature', side_effect=lambda fd, data: reports.append(data)):
            VendorKeyboard('/dev/test').effect(1, (255, 20, 80), 7, 60)
        self.assertEqual([frame(0xB1), frame(8, 2), frame(8, 2, 2, 3, 60, 0, 0),
                          frame(0x14, 0, 0, 255, 20, 80, 0)], reports)
        self.assertTrue(all(sum(r[1:]) % 256 == 255 for r in reports))

    def test_effect_failure_is_not_saved_as_success(self):
        with self.assertRaises(ValueError):
            self.controls.command('set_four_zone_mode', dict(mode=1, speed=5, brightness=50, direction=1))
        self.assertEqual({}, self.controls.lighting)
        self.assertFalse((self.root / 'state.json').exists())

    def test_fragmented_and_coalesced_requests(self):
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


if __name__ == '__main__':
    unittest.main()
