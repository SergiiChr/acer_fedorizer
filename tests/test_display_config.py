# SPDX-License-Identifier: GPL-3.0-only
import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "display_config", Path(__file__).resolve().parents[1] / "control_center/display.py")
display = importlib.util.module_from_spec(spec)
spec.loader.exec_module(display)


def monitor(connector, builtin=False, color=0, active=True):
    identity = (connector, "vendor", "product", connector + "-serial")
    modes = [("exact-165.003-vrr", 2560, 1600, 165.003, 1.25, [1.0, 1.25],
              {"is-current": active, "refresh-rate-mode": "variable"})]
    return (identity, modes, {"is-builtin": builtin, "supported-color-modes": [0, 1, 2],
                              "color-mode": color, "rgb-range": 2, "is-underscanning": True})


def state():
    panel = monitor("eDP-3", builtin=True)
    external = monitor("DP-2", color=1)
    mirror = monitor("HDMI-1", color=2)
    inactive = monitor("DP-4", active=False)
    leased = monitor("DP-5", active=False)
    leased[2]["is-for-lease"] = True
    return (42, [panel, external, mirror, inactive, leased],
            [(0, 0, 1.25, 0, True, [panel[0], mirror[0]], {}),
             (2048, 20, 1.0, 3, False, [external[0]], {})],
            {"layout-mode": 2, "supports-changing-layout-mode": True})


class DisplayConfigTests(unittest.TestCase):
    def test_preserves_layout_modes_mirroring_and_properties(self):
        before = state()
        original = copy.deepcopy(before)
        serial, method, logical, props = display.build_configuration(before, "eDP-3", True)
        self.assertEqual((serial, method), (42, 2))
        self.assertEqual(logical[0][:5], before[2][0][:5])
        self.assertEqual(logical[1][:5], before[2][1][:5])
        self.assertEqual(len(logical[0][5]), 2)
        self.assertEqual(logical[0][5][0], ("eDP-3", "exact-165.003-vrr",
                         {"underscanning": True, "color-mode": 2, "rgb-range": 2}))
        self.assertEqual(logical[0][5][1][2]["color-mode"], 2)
        self.assertEqual(logical[1][5][0][2]["color-mode"], 1)
        self.assertEqual(props, {"layout-mode": 2, "monitors-for-lease": [before[1][4][0]]})
        self.assertNotIn("DP-4", [m[0] for lm in logical for m in lm[5]])
        self.assertEqual(before, original)

    def test_disable_restores_default(self):
        current = state()
        current[1][0][2]["color-mode"] = 2
        self.assertTrue(display.panel_status(current)["enabled"])
        result = display.build_configuration(current, "eDP-3", False)
        self.assertEqual(result[2][0][5][0][2]["color-mode"], 0)

    def test_refuses_unsupported_inactive_hdr_and_ambiguous_panels(self):
        for change in (lambda s: s[1][0][2].update({"supported-color-modes": [0]}),
                       lambda s: s[1][0][2].update({"is-builtin": False}),
                       lambda s: s[1][1][2].update({"is-builtin": True}),
                       lambda s: s[1][0][2].update({"color-mode": 1}),
                       lambda s: s[2].clear()):
            with self.subTest(change=change):
                current = state()
                change(current)
                self.assertFalse(display.panel_status(current)["available"])
                with self.assertRaises(ValueError):
                    display.build_configuration(current, "eDP-3", True)
        self.assertFalse(display.panel_status(state(), allowed=False)["available"])

    def test_refuses_connector_change_and_unknown_current_mode(self):
        with self.assertRaises(ValueError):
            display.build_configuration(state(), "eDP-1", True)
        current = state()
        current[1][1][1][0][6]["is-current"] = False
        with self.assertRaisesRegex(ValueError, "Cannot preserve"):
            display.build_configuration(current, "eDP-3", True)

    def test_no_layout_property_when_changes_are_unsupported(self):
        current = state()
        current[3].pop("supports-changing-layout-mode")
        self.assertNotIn("layout-mode", display.build_configuration(current, "eDP-3", True)[3])

    @unittest.skipUnless(importlib.util.find_spec("gi"), "PyGObject is optional outside GNOME")
    def test_real_glib_variant_and_persistent_dbus_call(self):
        from gi.repository import Gio, GLib
        initial = state()
        after = state()
        after[1][0][2]["color-mode"] = 2

        class Reply:
            def __init__(self, value): self.value = value
            def unpack(self): return self.value

        class Proxy:
            def __init__(self): self.calls = []
            def get_name_owner(self): return ":1.123"
            def set_default_timeout(self, value): pass
            def get_cached_property(self, name): return GLib.Variant("b", True)
            def call_sync(self, method, args, *unused):
                self.calls.append((method, args))
                return Reply(initial if len(self.calls) == 1 else after)

        proxy = Proxy()
        with patch.object(Gio.DBusProxy, "new_for_bus_sync", return_value=proxy):
            self.assertTrue(display.run("enable", "eDP-3")["enabled"])
        self.assertEqual([c[0] for c in proxy.calls],
                         ["GetCurrentState", "ApplyMonitorsConfig", "GetCurrentState"])
        args = proxy.calls[1][1]
        self.assertEqual(args.get_type_string(), "(uua(iiduba(ssa{sv}))a{sv})")
        self.assertEqual(args.unpack(), display.build_configuration(initial, "eDP-3", True))

        # A stale serial or compositor rejection must propagate, without retrying an old layout.
        def reject(method, *args):
            if method == "ApplyMonitorsConfig": raise RuntimeError("stale serial")
            return Reply(initial)
        proxy.call_sync = reject
        with patch.object(Gio.DBusProxy, "new_for_bus_sync", return_value=proxy):
            with self.assertRaisesRegex(RuntimeError, "stale serial"):
                display.run("enable", "eDP-3")


if __name__ == "__main__":
    unittest.main()
