# SPDX-License-Identifier: GPL-3.0-only
"""Data sources behind the window: the live hardware service and desktop session, or labelled preview data."""
from collections.abc import Callable
from typing import Protocol

from . import display, installation
from .client import JSON, ControlClient
from .telemetry import Battery, Sample, Telemetry


class Client(Protocol):
    def command(self, command: str, params: dict[str, JSON] | None = None) -> JSON: ...
    def close(self) -> None: ...


class Services(Protocol):
    """Everything the window reads or changes; every method except watch_display may block and runs on a worker."""
    # True for labelled preview data that never reaches the hardware service or Mutter.
    preview: bool
    # Check the installation as soon as the window opens instead of on request.
    check_installation_on_start: bool
    # CPU usage history shown before the first sample arrives.
    cpu_history: tuple[float, ...]

    @property
    def client(self) -> Client: ...

    def installation_status(self) -> installation.Report: ...
    def display_status(self) -> display.PanelStatus: ...
    def set_display(self, connector: str, enabled: bool) -> display.PanelStatus: ...
    def watch_display(self, callback: Callable[[], None]) -> None: ...
    def sample(self, gpu: bool) -> Sample: ...
    def battery(self) -> Battery | None: ...


class LiveServices:
    """The local hardware service socket, Linux sysfs/proc telemetry, and the GNOME session's Mutter."""
    preview = False
    check_installation_on_start = False
    cpu_history: tuple[float, ...] = ()

    def __init__(self) -> None:
        self.client = ControlClient()
        self.telemetry = Telemetry()

    def installation_status(self) -> installation.Report:
        return installation.collect_status()

    def display_status(self) -> display.PanelStatus:
        return display.run('status')

    def set_display(self, connector: str, enabled: bool) -> display.PanelStatus:
        return display.run('enable' if enabled else 'disable', connector)

    def watch_display(self, callback: Callable[[], None]) -> None:
        display.watch(callback)

    def sample(self, gpu: bool) -> Sample:
        return self.telemetry.sample(gpu)

    def battery(self) -> Battery | None:
        return self.telemetry.battery()
