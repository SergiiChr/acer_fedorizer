# SPDX-License-Identifier: GPL-3.0-only
"""Unprivileged Mutter session-bus bridge. No gdctl output parsing."""
import json
import sys
from collections.abc import Callable
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gi.repository import GLib

DEFAULT = 0
SDR_NATIVE = 2
INTERFACE = "org.gnome.Mutter.DisplayConfig"
PATH = "/org/gnome/Mutter/DisplayConfig"

# Shapes of Mutter GetCurrentState and ApplyMonitorsConfig D-Bus values after unpacking.
MonitorSpec = tuple[str, str, str, str]
Mode = tuple[str, int, int, float, float, list[float], dict[str, object]]
Monitor = tuple[MonitorSpec, list[Mode], dict[str, object]]
LogicalMonitor = tuple[int, int, float, int, bool, list[MonitorSpec], dict[str, object]]
DisplayState = tuple[int, list[Monitor], list[LogicalMonitor], dict[str, object]]
MonitorConfig = tuple[str, str, dict[str, object]]
LogicalConfig = tuple[int, int, float, int, bool, list[MonitorConfig]]
Configuration = tuple[int, int, list[LogicalConfig], dict[str, object]]
PanelStatus = dict[str, bool | str]


def panel_status(state: DisplayState, allowed: bool = True) -> PanelStatus:
    _, monitors, logical, _ = state
    panels = [m for m in monitors if m[2].get("is-builtin", False)]
    result = {"available": False, "enabled": False, "connector": "", "mode": "", "message": ""}
    if len(panels) != 1:
        result["message"] = "No unique built-in display was found."
        return result
    spec, _, props = panels[0]
    mode = props.get("color-mode")
    result.update(connector=spec[0], enabled=mode == SDR_NATIVE,
                  mode={0: "default", 1: "bt2100", 2: "sdr-native"}.get(mode, "unknown"))
    if SDR_NATIVE not in props.get("supported-color-modes", []):
        result["message"] = "The built-in display does not support Native SDR color management."
    elif not any(spec in lm[5] for lm in logical):
        result["message"] = "Enable the built-in display in GNOME Settings first."
    elif not allowed:
        result["message"] = "This session does not allow display configuration changes."
    elif mode not in (DEFAULT, SDR_NATIVE):
        result["message"] = "Select the default SDR mode in GNOME Settings before using this toggle."
    elif DEFAULT not in props.get("supported-color-modes", []):
        result["message"] = "The display does not support restoring the default color mode."
    else:
        result.update(available=True, message=f"{spec[0]} · {result['mode']}")
    return result


def build_configuration(state: DisplayState, connector: str | None, enabled: bool) -> Configuration:
    """Rebuild only writable API fields, keeping exact current mode IDs (incl. VRR)."""
    serial, monitors, logical, props = state
    status = panel_status(state)
    if not status["available"] or status["connector"] != connector:
        raise ValueError(status["message"] if not status["available"] else
                         "The built-in display changed. Refresh and try again.")
    by_spec = {tuple(m[0]): m for m in monitors}
    configs = []
    for x, y, scale, transform, primary, specs, _ in logical:
        members = []
        for spec in specs:
            _, modes, monitor_props = by_spec[tuple(spec)]
            current = [m for m in modes if m[6].get("is-current", False)]
            if len(current) != 1:
                raise ValueError(f"Cannot preserve the current mode for {spec[0]}.")
            settings = {}
            for source, dest in (("is-underscanning", "underscanning"),
                                 ("color-mode", "color-mode"), ("rgb-range", "rgb-range")):
                if source in monitor_props:
                    settings[dest] = monitor_props[source]
            if spec[0] == connector:
                settings["color-mode"] = SDR_NATIVE if enabled else DEFAULT
            members.append((spec[0], current[0][0], settings))
        configs.append((x, y, scale, transform, primary, members))
    config_props = {}
    if props.get("supports-changing-layout-mode", False) and "layout-mode" in props:
        config_props["layout-mode"] = props["layout-mode"]
    leased = [tuple(m[0]) for m in monitors if m[2].get("is-for-lease", False)]
    if leased:
        config_props["monitors-for-lease"] = leased
    return serial, 2, configs, config_props  # persistent, equivalent to gdctl set -P


def configuration_variant(configuration: Configuration, GLib: ModuleType) -> "GLib.Variant":
    serial, method, logical, props = configuration
    typed_logical = []
    for x, y, scale, transform, primary, members in logical:
        typed_members = []
        for connector, mode, settings in members:
            typed = {k: GLib.Variant("b" if k == "underscanning" else "u", v)
                     for k, v in settings.items()}
            typed_members.append((connector, mode, typed))
        typed_logical.append((x, y, scale, transform, primary, typed_members))
    typed_props = {k: GLib.Variant("a(ssss)" if k == "monitors-for-lease" else "u", v)
                   for k, v in props.items()}
    return GLib.Variant("(uua(iiduba(ssa{sv}))a{sv})",
                        (serial, method, typed_logical, typed_props))


def watch(callback: Callable[[], object]) -> None:
    """Call callback on the main loop whenever Mutter reports a monitor change; replaces polling."""
    from gi.repository import Gio, GLib

    def connected(_: object, result: Gio.AsyncResult) -> None:
        try:
            bus = Gio.bus_get_finish(result)
        except GLib.Error:
            return
        bus.signal_subscribe(INTERFACE, INTERFACE, "MonitorsChanged", PATH, None,
                             Gio.DBusSignalFlags.NONE, lambda *_: callback())

    Gio.bus_get(Gio.BusType.SESSION, None, connected)


def run(action: str, connector: str | None = None) -> PanelStatus:
    try:
        from gi.repository import Gio, GLib
    except ImportError as exc:
        raise RuntimeError("Display controls require Python 3 with PyGObject (python3-gobject / python3-gi).") from exc
    proxy = Gio.DBusProxy.new_for_bus_sync(
        Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
        INTERFACE, PATH, INTERFACE, None)
    if not proxy.get_name_owner():
        raise RuntimeError("Display controls require a GNOME session with Mutter DisplayConfig support.")
    proxy.set_default_timeout(5000)

    def read() -> DisplayState:
        return proxy.call_sync("GetCurrentState", None, Gio.DBusCallFlags.NONE, 5000, None).unpack()

    state = read()  # Always take a fresh snapshot immediately before applying.
    permission = proxy.get_cached_property("ApplyMonitorsConfigAllowed")
    status = panel_status(state, permission is None or permission.unpack())
    if action != "status":
        if not status["available"]:
            raise ValueError(status["message"])
        configuration = build_configuration(state, connector, action == "enable")
        proxy.call_sync("ApplyMonitorsConfig", configuration_variant(configuration, GLib),
                        Gio.DBusCallFlags.NONE, 5000, None)
        status = panel_status(read())
        if status["connector"] != connector or status["enabled"] != (action == "enable"):
            raise RuntimeError("Mutter did not report the requested color mode. Refresh to check the display state.")
    return status


if __name__ == "__main__":
    try:
        action = sys.argv[1] if len(sys.argv) > 1 else "status"
        if action not in ("status", "enable", "disable"):
            raise ValueError("Unknown display action.")
        print(json.dumps(run(action, sys.argv[2] if len(sys.argv) > 2 else None)))
    except Exception as exc:  # noqa: BLE001 - every failure is reported as JSON status.
        print(json.dumps({"available": False, "enabled": False, "message": str(exc)}))
        sys.exit(1)
