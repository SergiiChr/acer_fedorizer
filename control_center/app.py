# SPDX-License-Identifier: GPL-3.0-only
"""GTK4/libadwaita control center; hardware requests stay in the existing daemon."""
import contextlib
import copy
import dataclasses
import math
import queue
import threading
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version('Gtk','4.0')
gi.require_version('Adw','1')
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from . import display, installation, preview
from .client import ControlClient, JsonDict
from .markdown_view import markdown_view
from .models import (
    EFFECT_NAMES,
    PROFILES,
    TARGETS,
    ZONE_COLORS,
    ZONE_MODE,
    FanMode,
    LightingDraft,
    PerKey,
    Settings,
    full_key_map,
    parse_lamps,
    rgb_hex,
    uses_palette,
)
from .telemetry import Telemetry
from .widgets import HistoryChart, KeyboardCanvas, ModeTiles, box, color_rgba, hex_rgba, label

PAGES=[('overview','Dashboard','view-grid-symbolic','CPU, GPU, memory, and power status'),
       ('performance','Power & Performance','power-profile-performance-symbolic','Performance profiles and fan speed control'),
       ('lighting','Lighting','keyboard-brightness-symbolic','Keyboard, WASD, lid logo, and rear light bar settings'),
       ('battery','Battery','battery-good-symbolic','Charge level, battery health, and charging controls'),
       ('display','Display','video-display-symbolic','Built-in display color management'),
       ('diagnostics','System Settings','preferences-system-symbolic','Capabilities, connection details, and credits')]


PROFILE_ICONS={'low-power':'power-profile-power-saver-symbolic','quiet':'audio-volume-low-symbolic',
               'balanced':'power-profile-balanced-symbolic','balanced-performance':'power-profile-performance-symbolic',
               'performance':'weather-storm-symbolic'}

def button(text: str, callback: Callable[[Gtk.Button], None], css: str = '') -> Gtk.Button:
    widget=Gtk.Button(label=text,valign=Gtk.Align.CENTER)
    widget.add_css_class('control-button')
    if css: widget.add_css_class(css)
    widget.connect('clicked',callback)
    return widget


def suffix_row(title: str, value: str = '', subtitle: str | None = None) -> tuple[Adw.ActionRow, Gtk.Label]:
    row=Adw.ActionRow(title=title,subtitle=subtitle or '')
    value_label=label(value,'dim-label')
    value_label.set_wrap(False)
    row.add_suffix(value_label)
    return row,value_label


def number_text(value: float | None, unit: str = '', digits: int = 0, missing: str = 'Unavailable') -> str:
    return f'{value:.{digits}f}{unit}' if value is not None else missing


class Workers:
    """A few reused daemon threads; closing the window never waits for an in-flight call."""
    def __init__(self, count: int = 4) -> None:
        self.jobs=queue.SimpleQueue()
        for _ in range(count): threading.Thread(target=self.run,daemon=True).start()
    def run(self) -> None:
        while True: self.jobs.get()()
    def submit(self, job: Callable[[], None]) -> None:
        self.jobs.put(job)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application: 'Application', demo: bool = False) -> None:
        super().__init__(application=application,title='Acer Fedorizer',default_width=1160,default_height=900)
        self.demo=demo; self.closed=False; self.pending=False; self.polling=False; self.display_pending=False
        self.client=preview.PreviewClient() if demo else ControlClient()
        self.telemetry=Telemetry(); self.state=None; self.connected=False; self.updating=False
        self.drafts={}; self.current_target=None; self.lighting_loading=False; self.layout=None
        self.gpu_enabled=False; self.status_pending=False; self.editor=None
        self.fan_draft_loaded=False; self.display_watched=False
        self.workers=Workers()
        self.build()
        self.connect('realize',lambda *_: self.get_surface().connect('notify::state',self.surface_changed))
        if demo:
            self.receive_state(Settings.parse(self.client.command('get_all_settings')),None)
            sample=preview.sample()
            self.receive_sample(sample); self.receive_battery(sample.battery)
            self.set_layout(parse_lamps(preview.layout()))
            self.receive_installation_status(preview.installation_status(),None)
            self.receive_display(display.PanelStatus(True,False,'eDP-1','default','Built-in display · Native SDR supported'))
            for i in range(60):
                self.cpu_chart.sample(25+8*math.sin(i*.18)+3*math.sin(i*.7))
                self.gpu_chart.sample(None)
        else: self.refresh()
        self.timer=GLib.timeout_add_seconds(2,self.refresh)
        self.connect('close-request',self.on_close)

    def build(self) -> None:
        css=Gtk.CssProvider()
        css.load_from_path(str(Path(__file__).with_name('style.css')))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(),css,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.toast=Adw.ToastOverlay()
        self.set_content(self.toast)
        split=Adw.NavigationSplitView(min_sidebar_width=220,max_sidebar_width=230,sidebar_width_fraction=.2)
        self.split=split
        self.toast.set_child(split)
        sidebar=Adw.ToolbarView()
        header=Adw.HeaderBar(show_end_title_buttons=False)
        header.set_title_widget(label('Fedorizer','brand'))
        sidebar.add_top_bar(header)
        sidebox=box(0)
        nav=Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        nav.add_css_class('navigation-sidebar')
        self.nav_rows={}
        for key,title,icon,_ in PAGES:
            row=Gtk.ListBoxRow()
            line=box(12,True)
            line.append(Gtk.Image.new_from_icon_name(icon)); line.append(label(title))
            row.set_child(line); nav.append(row); self.nav_rows[key]=row
        nav.connect('row-selected',self.navigate)
        sidebox.append(nav)
        spacer=box(); spacer.set_vexpand(True); sidebox.append(spacer)
        footer=box(6); footer.add_css_class('sidebar-footer')
        footer.append(label('PREDATOR PH16-72','eyebrow'))
        self.connection_label=label('Connecting to hardware service…')
        footer.append(self.connection_label)
        sidebox.append(footer)
        sidebar.set_content(sidebox)
        split.set_sidebar(Adw.NavigationPage.new(sidebar,'Acer Fedorizer'))
        content=Adw.ToolbarView()
        top=Adw.HeaderBar(show_start_title_buttons=False)
        self.window_title=Adw.WindowTitle(title='Dashboard',subtitle='Acer Fedorizer')
        top.set_title_widget(self.window_title)
        if self.demo: top.pack_start(label('Preview data','preview-badge'))
        menu=Gio.Menu()
        menu.append('Licenses and credits','app.credits')
        menu_button=Gtk.MenuButton(icon_name='open-menu-symbolic',menu_model=menu)
        top.pack_end(menu_button)
        content.add_top_bar(top)
        column=box(0)
        self.banner=Adw.Banner(title='Hardware service unavailable.',button_label='Check status')
        self.banner.connect('button-clicked',self.open_installation_status)
        column.append(self.banner)
        self.stack=Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,transition_duration=140,vexpand=True)
        column.append(self.stack); content.set_content(column)
        split.set_content(Adw.NavigationPage.new(content,'Controls'))
        self.pages={}
        for key,title,_,description in PAGES:
            page=box(24)
            page.set_margin_top(30); page.set_margin_bottom(30); page.set_margin_start(32); page.set_margin_end(32)
            heading=box(7); heading.append(label(title,'page-heading')); heading.append(label(description,'page-description')); page.append(heading)
            scroll=Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,vexpand=True)
            clamp=Adw.Clamp(maximum_size=1040,tightening_threshold=850,child=page)
            scroll.set_child(clamp)
            self.stack.add_named(scroll,key); self.pages[key]=page
        self.build_overview(); self.build_performance(); self.build_lighting()
        self.build_battery(); self.build_display(); self.build_diagnostics()
        self.nav=nav
        self.show_page('overview')

    def show_page(self, name):
        self.nav.select_row(self.nav_rows[name])

    def navigate(self, _: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None: return
        name,title,*_=PAGES[row.get_index()]
        self.stack.set_visible_child_name(name)
        self.window_title.set_title(title)
        self.split.set_show_content(True)
        if name=='lighting' and not self.layout and self.connected: self.load_layout()
        if name=='display' and not self.demo:
            if not self.display_watched:
                self.display_watched=True
                display.watch(self.refresh_display)
            self.refresh_display()

    def build_overview(self) -> None:
        page=self.pages['overview']
        hero=box(12); hero.add_css_class('hero')
        line=box(12,True); heading=label('CURRENT PERFORMANCE PROFILE','eyebrow'); heading.set_hexpand(True); line.append(heading)
        self.ac_label=label('AC power','status-pill'); self.ac_label.set_valign(Gtk.Align.CENTER); self.ac_label.set_hexpand(False); self.ac_label.set_halign(Gtk.Align.END); line.append(self.ac_label)
        hero.append(line)
        self.profile_hero=label('Balanced','hero-value'); hero.append(self.profile_hero)
        hero.append(label('Current profile reported by the platform driver.','dim-label'))
        page.append(hero)
        cards=box(16,True)
        cpu=box(12); cpu.add_css_class('metric-card'); cpu.set_hexpand(True)
        cpu.append(label('PROCESSOR','eyebrow'))
        self.cpu_value=label('—','metric'); cpu.append(self.cpu_value)
        self.cpu_detail=label('Waiting for a sample','dim-label'); cpu.append(self.cpu_detail)
        self.cpu_chart=HistoryChart(); cpu.append(self.cpu_chart)
        self.cpu_memory=label('Memory · —','dim-label'); cpu.append(self.cpu_memory)
        cards.append(cpu)
        gpu=box(12); gpu.add_css_class('metric-card'); gpu.set_hexpand(True)
        gpu.append(label('NVIDIA GRAPHICS','eyebrow'))
        self.gpu_value=label('Paused','metric'); gpu.append(self.gpu_value)
        self.gpu_detail=label('Monitoring is off to save power','dim-label'); gpu.append(self.gpu_detail)
        self.gpu_chart=HistoryChart((.64,.57,.88)); gpu.append(self.gpu_chart)
        self.vram=Gtk.ProgressBar(show_text=True,text='VRAM · monitoring paused'); gpu.append(self.vram)
        cards.append(gpu); page.append(cards)
        group=Adw.PreferencesGroup()
        self.gpu_switch=Adw.SwitchRow(title='Monitor NVIDIA GPU',subtitle='Shows temperature, VRAM, and power. Queries may wake the discrete GPU.')
        self.gpu_switch.connect('notify::active',self.gpu_toggled)
        group.add(self.gpu_switch)
        cores=Adw.ExpanderRow(title='Per-core frequencies',subtitle='Sampled frequencies, grouped by physical CPU core')
        self.core_grid=Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,max_children_per_line=8,min_children_per_line=4,row_spacing=6,column_spacing=6)
        row=Adw.PreferencesRow(child=self.core_grid)
        cores.add_row(row); group.add(cores)
        self.core_labels=[]
        page.append(group)

    def build_performance(self) -> None:
        page=self.pages['performance']
        self.profile_group=Adw.PreferencesGroup(title='Performance Profiles',description='Select a performance profile, then apply it.')
        self.profile_tiles=ModeTiles()
        self.profile_choices=[]
        self.profile_group.add(Adw.PreferencesRow(child=self.profile_tiles))
        row=Adw.ActionRow(title='Current profile',subtitle='Changes made by the hardware button appear automatically.')
        self.current_profile=row
        row.set_subtitle('Unavailable')
        row.add_suffix(button('Apply profile',self.apply_profile,'suggested-action'))
        self.profile_group.add(row); page.append(self.profile_group)
        self.fan_group=Adw.PreferencesGroup(title='Fan Speed Control',description='Manual settings are drafts until applied. Failed writes restore automatic cooling.')
        self.fan_mode=ModeTiles([('Auto','view-refresh-symbolic'),('Max','power-profile-performance-symbolic'),('Manual','preferences-system-symbolic')],changed=self.update_fan_sensitivity)
        self.fan_group.add(Adw.PreferencesRow(child=self.fan_mode))
        self.cpu_slider,self.cpu_rpm=self.fan_row('CPU fan',45)
        self.gpu_slider,self.gpu_rpm=self.fan_row('GPU fan',45)
        row=Adw.ActionRow(title='Current cooling',subtitle='Reading firmware state…')
        self.fan_current=row
        row.add_suffix(button('Apply fan settings',self.apply_fans,'suggested-action')); self.fan_group.add(row)
        page.append(self.fan_group)
        self.extras=Adw.PreferencesGroup(title='Device options',description='Only controls exposed by the stock driver appear here.')
        self.extra_switches={}
        for key,title in [('backlight_timeout','Backlight Timeout'),('boot_animation_sound','Boot Sound and Animation'),('lcd_override','LCD Override')]:
            row=Adw.SwitchRow(title=title)
            row.connect('notify::active',self.extra_toggled,key)
            self.extra_switches[key]=row; self.extras.add(row)
        self.usb_combo=Adw.ComboRow(title='USB Power Delivery',model=Gtk.StringList.new(['Off','10%','20%','30%']))
        self.usb_combo.connect('notify::selected',self.usb_changed); self.extras.add(self.usb_combo)
        page.append(self.extras)
        self.update_fan_sensitivity()

    def fan_row(self, title: str, value: float) -> tuple[Gtk.Scale, Gtk.Label]:
        row=Adw.ActionRow(title=title)
        slider=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,1,99,1)
        slider.set_value(value); slider.set_draw_value(True); slider.set_value_pos(Gtk.PositionType.RIGHT)
        slider.set_size_request(220,-1); slider.set_valign(Gtk.Align.CENTER)
        rpm=label('— RPM','dim-label'); rpm.set_width_chars(11)
        row.add_suffix(slider); row.add_suffix(rpm); self.fan_group.add(row)
        return slider,rpm

    def build_lighting(self) -> None:
        page=self.pages['lighting']
        keyboard_box=box(12); keyboard_box.add_css_class('keyboard-card')
        line=box(12,True); heading=label('KEYBOARD LAYOUT','eyebrow'); heading.set_hexpand(True); line.append(heading)
        per_key=button('Edit per-key colors',self.open_editor,'flat'); per_key.set_hexpand(False); per_key.set_halign(Gtk.Align.END)
        self.per_key_button=per_key; line.append(per_key); keyboard_box.append(line)
        self.keyboard_canvas=KeyboardCanvas(195); keyboard_box.append(self.keyboard_canvas)
        keyboard_box.append(label('Layout preview · colors are not hardware readback','dim-label'))
        page.append(keyboard_box)
        self.light_group=Adw.PreferencesGroup(title='Lighting effect',description='Apply a supported effect to one device, or coordinate all detected lights.')
        self.target_combo=Adw.ComboRow(title='Device',model=Gtk.StringList.new([]))
        self.targets=[]; self.effect_ids=[]
        self.target_combo.connect('notify::selected',self.target_changed)
        self.light_group.add(self.target_combo)
        self.effect_combo=Adw.ComboRow(title='Effect',model=Gtk.StringList.new([]))
        self.effect_combo.connect('notify::selected',self.effect_changed); self.light_group.add(self.effect_combo)
        color_row=Adw.ActionRow(title='Color'); self.color_row=color_row
        self.color_entry=Gtk.Entry(text='#5BBFBD',max_length=7,width_chars=10,valign=Gtk.Align.CENTER)
        self.color_button=Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(),rgba=color_rgba('5bbfbd'),valign=Gtk.Align.CENTER)
        self.color_button.connect('notify::rgba',lambda *_: self.color_entry.set_text('#'+hex_rgba(self.color_button.get_rgba()).upper()))
        self.color_entry.connect('activate',self.color_entered)
        color_row.add_suffix(self.color_entry); color_row.add_suffix(self.color_button); self.light_group.add(color_row)
        self.zone_rows=[]; self.zone_buttons=[]
        for i,color in enumerate(ZONE_COLORS,1):
            row=Adw.ActionRow(title=f'Zone {i}',subtitle='Static color for this quarter of the keyboard' if i==1 else '')
            picker=Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(),rgba=color_rgba(color),valign=Gtk.Align.CENTER)
            row.add_suffix(picker); row.set_visible(False); self.light_group.add(row)
            self.zone_rows.append(row); self.zone_buttons.append(picker)
        self.brightness_row,self.brightness=self.scale_row('Brightness',0,100,80)
        self.speed_row,self.speed=self.scale_row('Animation speed',1,9,5)
        self.direction=Adw.ComboRow(title='Wave direction',model=Gtk.StringList.new(['Left to right','Right to left']))
        self.light_group.add(self.direction)
        self.link_wasd=Adw.SwitchRow(title='Also update WASD',subtitle='Match supported settings. Firmware animations have independent timing.')
        self.link_wasd.set_active(True); self.light_group.add(self.link_wasd)
        page.append(self.light_group)
        bottom=box(12,True)
        self.effect_note=label('Changes are applied only when you press Apply.','dim-label'); self.effect_note.set_hexpand(True)
        bottom.append(self.effect_note)
        self.light_apply=button('Apply lighting',self.apply_lighting,'suggested-action'); bottom.append(self.light_apply); page.append(bottom)

    def scale_row(self, title: str, minimum: float, maximum: float, value: float) -> tuple[Adw.ActionRow, Gtk.Scale]:
        row=Adw.ActionRow(title=title)
        slider=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,minimum,maximum,1)
        slider.set_value(value); slider.set_draw_value(True); slider.set_value_pos(Gtk.PositionType.RIGHT)
        slider.set_size_request(280,-1); slider.set_valign(Gtk.Align.CENTER)
        row.add_suffix(slider); self.light_group.add(row)
        return row,slider

    def build_battery(self) -> None:
        page=self.pages['battery']
        hero=box(12); hero.add_css_class('hero'); hero.append(label('BATTERY CHARGE','eyebrow'))
        self.battery_value=label('—','hero-value'); hero.append(self.battery_value)
        self.battery_progress=Gtk.ProgressBar(); hero.append(self.battery_progress)
        self.battery_status=label('Battery information is unavailable','dim-label'); hero.append(self.battery_status); page.append(hero)
        health=Adw.PreferencesGroup(title='Battery health')
        self.battery_labels={}
        for key,title in [('health','Full-charge capacity'),('cycles','Charge cycles'),('model','Battery'),('manufacturer','Manufacturer')]:
            row,value=suffix_row(title,'—'); self.battery_labels[key]=value; health.add(row)
        page.append(health)
        controls=Adw.PreferencesGroup(title='Battery controls')
        self.charge_limit=Adw.SwitchRow(title='Battery Charge Limit',subtitle='Limit maximum battery charge to 80%.')
        self.charge_limit.connect('notify::active',self.charge_changed); controls.add(self.charge_limit)
        self.calibration=Adw.ActionRow(title='Battery Calibration',subtitle='Only available when the stock driver exposes calibration.')
        self.calibration.add_suffix(button('Start',lambda *_: self.mutate('set_battery_calibration',{'enabled': True})))
        self.calibration.add_suffix(button('Stop',lambda *_: self.mutate('set_battery_calibration',{'enabled': False}),'flat'))
        controls.add(self.calibration); page.append(controls)

    def build_display(self) -> None:
        page=self.pages['display']
        hero=box(12); hero.add_css_class('hero'); hero.append(label('BUILT-IN DISPLAY','eyebrow'))
        hero.append(label('Native SDR color management','title-1'))
        hero.append(label('Reduce oversaturated SDR colors on supported built-in displays.','page-description')); page.append(hero)
        group=Adw.PreferencesGroup(title='Color management')
        self.display_switch=Adw.SwitchRow(title='Native SDR color management',subtitle='Requires an active built-in panel with Mutter sdr-native support.')
        self.display_switch.connect('notify::active',self.display_toggled); group.add(self.display_switch)
        row,self.display_connector=suffix_row('Built-in panel','Detecting…'); group.add(row)
        row,self.display_mode=suffix_row('Current color mode','—'); group.add(row); page.append(group)
        self.display_note=label('Checking GNOME session support…','dim-label'); page.append(self.display_note)
        line=box(horizontal=True)
        line.append(button('Refresh display status',lambda *_: self.refresh_display(),'flat')); page.append(line)
        note=Adw.PreferencesGroup(title='About this setting',description='Changes are saved by GNOME for future sessions. This does not select an ICC profile or enable HDR. The control is unavailable while HDR is selected or the built-in panel is inactive.')
        page.append(note)
        self.display_state=display.PanelStatus()

    def build_diagnostics(self) -> None:
        page=self.pages['diagnostics']
        self.status_group=Adw.PreferencesGroup(title='Installation status',description='Not checked. Refresh to check the installed files, service, and driver.')
        actions=box(8,True)
        self.status_spinner=Gtk.Spinner(valign=Gtk.Align.CENTER)
        actions.append(self.status_spinner)
        self.status_button=button('Refresh status',self.refresh_installation)
        action_content=box(7,True); action_content.append(Gtk.Image.new_from_icon_name('view-refresh-symbolic'))
        action_content.append(label('Refresh status')); self.status_button.set_child(action_content)
        actions.append(self.status_button); self.status_group.set_header_suffix(actions)
        self.status_rows={}
        for key,title in installation.CHECKS:
            row=Adw.ActionRow(title=title,subtitle='Not checked',use_markup=False)
            row.set_subtitle_lines(3)
            indicator=Gtk.Image.new_from_icon_name('checkbox-symbolic'); indicator.set_pixel_size(20)
            indicator.add_css_class('status-indicator'); indicator.add_css_class('dim-label')
            row.add_prefix(indicator); self.status_group.add(row); self.status_rows[key]=(row,indicator)
        page.append(self.status_group)
        group=Adw.PreferencesGroup(title='Hardware connection')
        self.system_labels={}
        for key,title in [('model','Laptop'),('driver','Control interface'),('version','Service version'),('socket','Connection')]:
            row,value=suffix_row(title,'—'); self.system_labels[key]=value; group.add(row)
        page.append(group)
        self.capability_group=Adw.PreferencesGroup(title='Detected capabilities')
        self.capability_text=label('Connecting…','dim-label'); self.capability_text.set_margin_top(12); self.capability_text.set_margin_bottom(12)
        self.capability_group.add(self.capability_text); page.append(self.capability_group)
        group=Adw.PreferencesGroup(title='Acer Fedorizer',description='A native Linux control center built with GTK4 and libadwaita. The user interface runs without administrator privileges.')
        row=Adw.ActionRow(title='Licenses and credits',subtitle='Application GPLv3 · separate kernel bridge GPLv2')
        row.add_suffix(button('View notices',lambda *_: self.show_credits(),'flat')); group.add(row); page.append(group)


    def open_installation_status(self,*_):
        self.show_page('diagnostics')
        self.refresh_installation()

    def refresh_installation(self, *_: object) -> None:
        if self.status_pending: return
        self.status_pending=True
        self.status_button.set_sensitive(False); self.status_spinner.start()
        self.status_group.set_description('Checking installation…')
        self.async_call(preview.installation_status if self.demo else installation.collect_status,self.receive_installation_status)

    def receive_installation_status(self, report: JsonDict | None, error: str | None) -> None:
        self.status_pending=False
        self.status_button.set_sensitive(True); self.status_spinner.stop()
        if error:
            self.status_group.set_description('Status check failed: '+error)
            for row,indicator in self.status_rows.values():
                row.set_subtitle('Not checked · status could not be refreshed')
                indicator.set_from_icon_name('checkbox-mixed-symbolic')
                for css in ('success','error'): indicator.remove_css_class(css)
                indicator.add_css_class('dim-label')
            return
        visible={check.key for check in report.checks}
        for key,(row,_) in self.status_rows.items(): row.set_visible(key in visible)
        for check in report.checks:
            row,indicator=self.status_rows[check.key]
            ok=check.ok
            indicator.set_from_icon_name('checkbox-checked-symbolic' if ok is True else 'checkbox-symbolic' if ok is False else 'checkbox-mixed-symbolic')
            for css in ('success','error','dim-label'): indicator.remove_css_class(css)
            indicator.add_css_class('success' if ok is True else 'error' if ok is False else 'dim-label')
            row.set_subtitle(('OK' if ok is True else 'Failed' if ok is False else 'Info')+' · '+check.detail)
        summary='All checks passed' if report.healthy else 'Some checks need attention'
        timestamp='10:30:00' if self.demo else GLib.DateTime.new_now_local().format('%H:%M:%S')
        self.status_group.set_description(summary+' · Checked '+timestamp+(' · Preview data' if self.demo else ''))

    def async_call[T](self, function: Callable[[], T], callback: Callable[[T | None, str | None], None]) -> None:
        def work() -> None:
            try: result,error=function(),None
            # Worker boundary: any failure is reported in the window instead of ending the thread.
            except Exception as exc: result,error=None,str(exc)  # noqa: BLE001
            def deliver() -> bool:
                if not self.closed: callback(result,error)
                return False
            GLib.idle_add(deliver)
        self.workers.submit(work)

    def refresh(self) -> bool:
        if self.closed: return False
        if self.polling or self.pending or not self.on_screen(): return True
        if self.demo:
            self.receive_state(Settings.parse(self.client.command('get_all_settings')),None)
            self.receive_sample(preview.sample(self.gpu_enabled))
            return True
        self.polling=True
        overview=self.stack.get_visible_child_name()=='overview'
        gpu=self.gpu_enabled and overview
        def work():
            try: state,error=Settings.parse(self.client.command('get_all_settings')),None
            except (OSError,ValueError,RuntimeError) as exc: state,error=None,str(exc)
            sample=self.telemetry.sample(gpu) if overview else None
            return state,error,sample,sample.battery if sample else self.telemetry.battery()
        def received(result,error):
            self.polling=False
            if error: self.receive_state(None,error); return
            state,error,sample,battery=result
            self.receive_state(state,error)
            if sample: self.receive_sample(sample)
            self.receive_battery(battery)
        self.async_call(work,received)
        return True

    def on_screen(self) -> bool:
        surface=self.get_surface()
        if surface is None: return True
        hidden=Gdk.ToplevelState.MINIMIZED|getattr(Gdk.ToplevelState,'SUSPENDED',0)
        return not surface.get_state()&hidden

    def surface_changed(self, *_: object) -> None:
        # Polling pauses while minimized or suspended; catch up as soon as the window is shown.
        if self.on_screen(): self.refresh()

    def update_sensitivity(self) -> None:
        """Disable every control that could start a second change while one is pending."""
        features=self.state.features if self.state and self.connected else ()
        ready=self.connected and not self.pending
        self.profile_group.set_sensitive(ready and 'thermal_profile' in features)
        self.fan_group.set_sensitive(ready and 'fan_speed' in features)
        self.light_group.set_sensitive(ready)
        self.light_apply.set_sensitive(ready and bool(self.state and self.state.lighting_modes))
        self.per_key_button.set_sensitive(ready and 'per_key_mode' in features)
        for widget in (self.charge_limit,self.calibration,self.extras): widget.set_sensitive(ready)
        if self.editor: self.editor.apply.set_sensitive(ready)

    def receive_state(self, state: JsonDict | None, error: str | None) -> None:
        self.connected=state is not None
        self.banner.set_revealed(not self.connected)
        self.connection_label.set_text('Preview · no hardware access' if self.demo else 'Hardware service connected' if self.connected else 'Hardware service unavailable')
        if state is not None: self.state=state
        self.update_sensitivity()
        if state is None: return
        self.updating=True
        try:
            features=state.features
            choices=list(state.profiles)
            current=state.profile
            if choices!=self.profile_choices:
                self.profile_choices=choices
                self.profile_tiles.set_choices([(PROFILES.get(v,v),PROFILE_ICONS.get(v,'preferences-system-symbolic')) for v in choices])
                if current in choices: self.profile_tiles.set_selected(choices.index(current))
            self.current_profile.set_subtitle(PROFILES.get(current,current or 'Unavailable'))
            self.profile_hero.set_text(PROFILES.get(current,current or 'Monitoring'))
            ac=state.ac_online
            self.ac_label.set_text('AC power' if ac is True else 'Battery power' if ac is False else 'Power source unknown')
            for key,widget in (('cpu',self.cpu_rpm),('gpu',self.gpu_rpm)):
                widget.set_text(number_text(state.fan_rpm.get(key),' RPM'))
            modes={state.fans.cpu.mode,state.fans.gpu.mode} if state.fans else set()
            confirmed='Automatic' if modes=={FanMode.AUTO} else 'Maximum' if modes=={FanMode.MAX} else 'Manual or mixed control'
            self.fan_current.set_subtitle(confirmed+' · selection above is an editing draft')
            if not self.fan_draft_loaded:
                self.fan_draft_loaded=True
                self.load_fan_draft(state.fans)
            self.charge_limit.set_visible('battery_limiter' in features)
            self.charge_limit.set_active(state.battery_limiter)
            self.calibration.set_visible('battery_calibration' in features)
            switches={'backlight_timeout':state.backlight_timeout,'boot_animation_sound':state.boot_animation_sound,'lcd_override':state.lcd_override}
            for key,row in self.extra_switches.items():
                row.set_visible(key in features); row.set_active(switches[key])
            self.usb_combo.set_visible('usb_charging' in features)
            self.usb_combo.set_selected({0:0,10:1,20:2,30:3}.get(state.usb_charging,0))
            self.extras.set_visible(any(row.get_visible() for row in self.extra_switches.values()) or 'usb_charging' in features)
            targets=[key for key in TARGETS if state.lighting_modes.get(key)]
            if targets!=self.targets:
                self.lighting_loading=True
                self.targets=targets
                self.target_combo.set_model(Gtk.StringList.new([TARGETS[t] for t in targets]))
                self.target_combo.set_selected(0)
                self.current_target=targets[0] if targets else None
                self.lighting_loading=False
                self.load_draft()
            self.system_labels['model'].set_text(state.laptop_type)
            self.system_labels['driver'].set_text(state.driver_version)
            self.system_labels['version'].set_text(state.version)
            self.system_labels['socket'].set_text('Preview' if self.demo else 'Connected · local Unix socket')
            self.capability_text.set_text('  ·  '.join(feature.replace('_',' ').title() for feature in features))
        finally: self.updating=False

    def receive_sample(self,sample):
        self.cpu_value.set_text(number_text(sample.cpu_usage,'%',1,missing='Sampling…'))
        self.cpu_detail.set_text('Temperature '+number_text(sample.cpu_temperature,'°C'))
        self.cpu_memory.set_text('Memory · '+number_text(sample.memory_used,' GiB',1)+' / '+number_text(sample.memory_total,' GiB',1))
        self.cpu_chart.sample(sample.cpu_usage)
        gpu=sample.gpu if self.gpu_enabled else None
        self.gpu_value.set_text(number_text(gpu.temperature,'°C') if gpu else 'Unavailable' if self.gpu_enabled else 'Paused')
        self.gpu_detail.set_text(('Usage '+number_text(gpu.usage,'%')+' · '+number_text(gpu.power,' W',1)) if gpu else 'Waiting for NVIDIA telemetry' if self.gpu_enabled else 'Monitoring is off to save power')
        self.gpu_chart.sample(gpu.usage if gpu else None)
        used,total=(gpu.memory_used,gpu.memory_total) if gpu else (None,None)
        self.vram.set_fraction(min(1,used/total) if used is not None and total else 0)
        self.vram.set_text(f'VRAM · {used/1024:.1f} / {total/1024:.1f} GiB' if used is not None and total else 'VRAM · unavailable' if self.gpu_enabled else 'VRAM · monitoring paused')
        if len(sample.cores)!=len(self.core_labels):
            while child:=self.core_grid.get_first_child(): self.core_grid.remove(child)
            self.core_labels=[]
            for _ in sample.cores:
                value=label('','core-pill'); self.core_labels.append(value); self.core_grid.append(value)
        for i,(widget,value) in enumerate(zip(self.core_labels,sample.cores,strict=True)):
            widget.set_text(f'Core {i+1:02d}  {value:.2f} GHz')

    def receive_battery(self,battery):
        capacity=battery.capacity if battery else None
        hours=battery.hours if battery else None
        self.battery_value.set_text(number_text(capacity,'%',0,missing='No battery'))
        self.battery_progress.set_fraction(max(0,min(1,capacity/100)) if capacity is not None else 0)
        estimate=f' · {int(hours)}h {int(hours*60)%60:02d}m '+('until full' if battery and battery.status=='Charging' else 'remaining') if hours is not None else ''
        self.battery_status.set_text((battery.status if battery else 'Unavailable')+estimate)
        self.battery_labels['health'].set_text(number_text(battery.health if battery else None,'%',1))
        self.battery_labels['cycles'].set_text(number_text(battery.cycles if battery else None,'',0))
        self.battery_labels['model'].set_text(battery.model if battery and battery.model else 'Unavailable')
        self.battery_labels['manufacturer'].set_text(battery.manufacturer if battery and battery.manufacturer else 'Unavailable')

    def gpu_toggled(self, *_: object) -> None:
        self.gpu_enabled=self.gpu_switch.get_active()
        if not self.gpu_enabled:
            self.gpu_value.set_text('Paused')
            self.gpu_detail.set_text('Monitoring is off to save power')
            self.gpu_chart.sample(None)
            self.vram.set_fraction(0); self.vram.set_text('VRAM · monitoring paused')
        self.refresh()

    def mutate(self, command: str, params: JsonDict, callback: Callable[[object, str | None], None] | None = None) -> None:
        """Apply one change at a time; callback(result, error) runs after the shared handling."""
        if self.pending: return
        self.pending=True
        self.update_sensitivity()
        def done(result: object, error: str | None) -> None:
            self.pending=False
            if error: self.toast.add_toast(Adw.Toast(title='Could not apply: '+error,timeout=8))
            else:
                self.toast.add_toast(Adw.Toast(title='Settings applied' if not self.demo else 'Preview updated · no hardware changed'))
                if result: self.receive_state(result,None)
            # Also resets switches that were toggled for a change that failed.
            self.receive_state(self.state if self.connected else None,None)
            if callback: callback(result,error)
            if not self.closed: self.refresh()
        def work():
            # Setting commands reply with the settings they produced.
            reply=self.client.command(command,params)
            return Settings.parse(reply) if isinstance(reply,dict) and 'available_features' in reply else None
        self.async_call(work,done)

    def apply_profile(self, *_: object) -> None:
        index=self.profile_tiles.get_selected()
        if index<len(self.profile_choices): self.mutate('set_thermal_profile',{'profile': self.profile_choices[index]})
    def load_fan_draft(self,fans):
        # Seeds the editing draft once from firmware; later refreshes must not discard edits.
        modes={fans.cpu.mode,fans.gpu.mode} if fans else {FanMode.AUTO}
        self.fan_mode.set_selected(0 if modes=={FanMode.AUTO} else 1 if modes=={FanMode.MAX} else 2)
        for slider,fan in zip((self.cpu_slider,self.gpu_slider),(fans.cpu,fans.gpu) if fans else (),strict=False):
            if fan.mode==FanMode.MANUAL and 0<fan.percent<100: slider.set_value(fan.percent)
        self.update_fan_sensitivity()
    def update_fan_sensitivity(self):
        manual=self.fan_mode.get_selected()==2
        self.cpu_slider.set_sensitive(manual); self.gpu_slider.set_sensitive(manual)
    def apply_fans(self, *_: object) -> None:
        mode=self.fan_mode.get_selected()
        values=(0,0) if mode==0 else (100,100) if mode==1 else (round(self.cpu_slider.get_value()),round(self.gpu_slider.get_value()))
        self.mutate('set_fan_speed',{'cpu': values[0],'gpu': values[1]})
    def charge_changed(self, row: Adw.SwitchRow, *_: object) -> None:
        if not self.updating: self.mutate('set_battery_limiter',{'enabled': row.get_active()})
    def extra_toggled(self, row: Adw.SwitchRow, _: GObject.ParamSpec, key: str) -> None:
        if not self.updating: self.mutate('set_'+key,{'enabled': row.get_active()})
    def usb_changed(self, row: Adw.ComboRow, *_: object) -> None:
        if not self.updating: self.mutate('set_usb_charging',{'level': [0,10,20,30][row.get_selected()]})

    def capture_draft(self) -> None:
        if self.current_target and self.effect_ids:
            index=self.effect_combo.get_selected()
            mode=self.effect_ids[min(index,len(self.effect_ids)-1)]
            color=hex_rgba(self.color_button.get_rgba()) if uses_palette(self.current_target,mode) else self.color_entry.get_text()
            zones=tuple(hex_rgba(picker.get_rgba()) for picker in self.zone_buttons)
            self.drafts[self.current_target]=LightingDraft(mode,color,round(self.brightness.get_value()),round(self.speed.get_value()),self.direction.get_selected()+1,self.link_wasd.get_active(),zones)
    def target_changed(self, *_: object) -> None:
        if self.lighting_loading: return
        self.capture_draft()
        index=self.target_combo.get_selected()
        self.current_target=self.targets[index] if index<len(self.targets) else None
        self.load_draft()
    def load_draft(self) -> None:
        if not self.current_target: return
        if not self.state: return
        modes=self.state.lighting_modes.get(self.current_target,[])
        if not modes: return
        if self.current_target=='keyboard' and 'per_zone_mode' in self.state.features: modes=[*modes,ZONE_MODE]
        draft=self.drafts.get(self.current_target) or LightingDraft.from_state(self.state.lighting.get(self.current_target,{}),modes)
        self.lighting_loading=True
        self.effect_ids=modes
        self.effect_combo.set_model(Gtk.StringList.new([EFFECT_NAMES.get(i,str(i)) for i in modes]))
        self.effect_combo.set_selected(modes.index(draft.mode) if draft.mode in modes else 0)
        self.color_entry.set_text('#'+draft.color.lstrip('#').upper())
        with contextlib.suppress(ValueError): self.color_button.set_rgba(color_rgba(rgb_hex(draft.color)))
        self.brightness.set_value(draft.brightness); self.speed.set_value(draft.speed)
        self.direction.set_selected(draft.direction-1); self.link_wasd.set_active(draft.link_wasd)
        for picker,zone in zip(self.zone_buttons,draft.zones,strict=True): picker.set_rgba(color_rgba(zone))
        self.lighting_loading=False
        self.effect_changed()
    def effect_changed(self, *_: object) -> None:
        if not self.effect_ids: return
        index=self.effect_combo.get_selected()
        if index>=len(self.effect_ids): return
        mode=self.effect_ids[index]; palette=uses_palette(self.current_target,mode); zones=mode==ZONE_MODE
        self.color_entry.set_sensitive(not palette); self.color_button.set_sensitive(not palette)
        for row in self.zone_rows: row.set_visible(zones)
        for row in (self.color_row,self.brightness_row,self.speed_row,self.direction): row.set_visible(not zones)
        self.link_wasd.set_visible(self.current_target=='keyboard' and not zones)
        self.direction.set_sensitive(mode==3 and self.current_target!='logo')
        self.speed.set_sensitive(mode!=0 and self.current_target!='logo')
        self.effect_note.set_text('Four static zones from left to right. WASD keys use the zone 1 color.' if zones else
            'WASD Wave uses the selected color and runs independently from keyboard Wave.' if mode==3 and self.current_target=='wasd' else
            'Wave uses a firmware palette. Linked WASD and keyboard animations run independently.' if mode==3 else
            'This effect uses its firmware color palette.' if palette else
            'All lights share settings; their animation timing can differ.' if self.current_target=='all' else 'Last successful command is saved; hardware effect readback is unavailable.')
    def color_entered(self, *_: object) -> None:
        try: self.color_button.set_rgba(color_rgba(rgb_hex(self.color_entry.get_text())))
        except ValueError as error: self.toast.add_toast(Adw.Toast(title=str(error)))
    def apply_lighting(self, *_: object) -> None:
        self.capture_draft()
        target=self.current_target
        if not target or target not in self.drafts: return
        try: command,params=self.drafts[target].request(target)
        except ValueError as error: self.toast.add_toast(Adw.Toast(title=str(error))); return
        def applied(_: object, error: str | None) -> None:
            if error: return
            self.drafts.pop(target,None)
            # Zones and linked keyboard effects also set WASD; 'all' sets every device.
            if target=='keyboard' and (command=='set_per_zone_mode' or params['link_wasd']): self.drafts.pop('wasd',None)
            if target=='all': self.drafts.clear()
        self.mutate(command,params,applied)
    def load_layout(self):
        self.async_call(self.read_layout,lambda result,error:self.set_layout(result) if not error else None)
    def read_layout(self):
        return parse_lamps(self.client.command('get_keyboard_layout'))
    def set_layout(self,layout):
        self.layout=layout
        saved=self.state.per_key.colors if self.state else {}
        self.keyboard_canvas.set_layout(layout,full_key_map(layout,saved))
    def open_editor(self,*_):
        """Open the per-key editor and return it, or return None while the keyboard layout is still loading."""
        if not self.layout:
            self.async_call(self.read_layout,self.editor_layout)
            return None
        return self.editor_layout(self.layout,None)
    def editor_layout(self,layout,error):
        if error: self.toast.add_toast(Adw.Toast(title='Could not read keyboard layout: '+error)); return None
        self.set_layout(layout)
        self.editor=KeyEditor(self,layout)
        self.update_sensitivity()
        self.editor.present()
        return self.editor

    def refresh_display(self) -> None:
        if self.display_pending: return
        if self.demo:
            self.receive_display(self.display_state); return
        self.display_pending=True
        def done(result: JsonDict | None, error: str | None) -> None:
            self.display_pending=False
            self.receive_display(result or display.PanelStatus(message=error or 'Unavailable'))
        self.async_call(lambda:display.run('status'),done)
    def receive_display(self, state: JsonDict) -> None:
        self.display_state=state
        self.updating=True
        self.display_switch.set_active(state.enabled)
        self.display_switch.set_sensitive(state.available)
        self.display_connector.set_text(state.connector or 'Unavailable')
        self.display_mode.set_text({'default':'Default SDR','sdr-native':'Native SDR','bt2100':'HDR'}.get(state.mode,'Unavailable'))
        self.display_note.set_text(state.message)
        self.updating=False
    def display_toggled(self, row: Adw.SwitchRow, *_: object) -> None:
        if self.updating: return
        enabled=row.get_active()
        if self.demo:
            self.receive_display(dataclasses.replace(self.display_state,enabled=enabled,mode='sdr-native' if enabled else 'default')); return
        row.set_sensitive(False)
        self.display_pending=True
        def done(result: JsonDict | None, error: str | None) -> None:
            self.display_pending=False
            if error:
                self.toast.add_toast(Adw.Toast(title='Display change failed: '+error,timeout=8))
                self.refresh_display()
            else: self.receive_display(result)
        self.async_call(lambda:display.run('enable' if enabled else 'disable',self.display_state.connector),done)

    def show_credits(self) -> None:
        window=Adw.Window(title='Licenses and credits',transient_for=self,modal=True,default_width=760,default_height=660)
        toolbar=Adw.ToolbarView(); toolbar.add_top_bar(Adw.HeaderBar())
        path=Path(__file__).resolve().parents[1]/'NOTICE.md'
        text=path.read_text() if path.exists() else 'License notices are missing. Reinstall from a complete source package.'
        content=markdown_view(text)
        clamp=Adw.Clamp(maximum_size=860,tightening_threshold=700,child=content)
        scroll=Gtk.ScrolledWindow(child=clamp,hscrollbar_policy=Gtk.PolicyType.NEVER)
        toolbar.set_content(scroll); window.set_content(toolbar)
        content.set_focusable(True); window.set_focus(content); window.present()
        return window

    def on_close(self, *_: object) -> bool:
        self.closed=True
        GLib.source_remove(self.timer)
        # Closing never sends a hardware command. In-flight workers are daemon threads.
        self.workers.submit(self.client.close)
        return False


class KeyEditor(Adw.Window):
    def __init__(self, parent: MainWindow, layout: JsonDict) -> None:
        super().__init__(title='Per-key lighting',transient_for=parent,modal=True,default_width=1020,default_height=600)
        self.parent=parent
        per_key=parent.state.per_key if parent.state else PerKey()
        self.colors=full_key_map(layout,per_key.colors)
        toolbar=Adw.ToolbarView(); header=Adw.HeaderBar()
        if parent.demo: header.pack_start(label('Preview data','preview-badge'))
        toolbar.add_top_bar(header)
        content=box(20)
        for setter in (content.set_margin_start,content.set_margin_end,content.set_margin_top,content.set_margin_bottom): setter(28)
        content.append(label('Per-key lighting','page-heading'))
        content.append(label('Select keys, set their colors, then apply the static layout.','page-description'))
        self.canvas=KeyboardCanvas(250,selectable=True); self.canvas.set_layout(layout,self.colors)
        self.canvas.add_css_class('keyboard-card'); content.append(self.canvas)
        controls=box(12,True)
        controls.append(button('Select all',lambda *_:self.select_all(),'flat'))
        controls.append(button('Clear selection',lambda *_:self.clear_selection(),'flat'))
        self.selection=label('No keys selected','dim-label'); self.selection.set_hexpand(True); controls.append(self.selection)
        self.picker=Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(),rgba=color_rgba('dfb678'),valign=Gtk.Align.CENTER)
        controls.append(self.picker)
        controls.append(button('Set selected color',self.paint))
        content.append(controls)
        self.canvas.on_selection=lambda count:self.selection.set_text(f'{count} keys selected' if count else 'No keys selected')
        row=box(12,True); row.append(label('Brightness','dim-label'))
        self.brightness=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,100,1)
        self.brightness.set_value(per_key.brightness); self.brightness.set_draw_value(True); self.brightness.set_hexpand(True)
        row.append(self.brightness)
        self.apply=button('Apply keyboard colors',self.submit,'suggested-action'); row.append(self.apply); content.append(row)
        self.result=label('The current preview is an editing draft, not a hardware readback.','dim-label'); content.append(self.result)
        toolbar.set_content(content); self.set_content(toolbar)
    def select_all(self) -> None:
        self.canvas.selected={int(key) for key in self.colors}; self.canvas.queue_draw()
        self.canvas.on_selection(len(self.canvas.selected))
    def clear_selection(self) -> None:
        self.canvas.selected.clear(); self.canvas.queue_draw(); self.canvas.on_selection(0)
    def paint(self, *_: object) -> None:
        color=hex_rgba(self.picker.get_rgba())
        for lid in self.canvas.selected:
            if str(lid) in self.colors: self.colors[str(lid)]=color
        self.canvas.colors=self.colors; self.canvas.queue_draw()
    def submit(self, *_: object) -> None:
        colors=copy.deepcopy(self.colors)
        params={'colors':colors,'brightness':round(self.brightness.get_value())}
        def done(_: object, error: str | None) -> None:
            self.result.set_text('Could not apply: '+error if error else 'Preview updated · no hardware changed' if self.parent.demo else 'Static layout applied. Confirm the visible result on your keyboard.')
            if not error: self.parent.keyboard_canvas.set_layout(self.parent.layout,colors)
        self.parent.mutate('set_per_key',params,done)


class Application(Adw.Application):
    capture_error=None
    def __init__(self,demo=False,screenshots=None):
        super().__init__(application_id='io.github.SergiiChr.AcerFedorizer'+('.Preview' if demo else ''),flags=Gio.ApplicationFlags.NON_UNIQUE if demo else Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.demo=demo; self.screenshots=screenshots
    def do_activate(self) -> None:
        window=self.get_active_window()
        if window: window.present(); return
        manager=Adw.StyleManager.get_default()
        manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK if self.demo else Adw.ColorScheme.PREFER_DARK)
        Gtk.Window.set_default_icon_name('acer-fedorizer')
        self.window=MainWindow(self,self.demo)
        action=Gio.SimpleAction.new('credits',None)
        action.connect('activate',lambda *_:self.window.show_credits()); self.add_action(action)
        self.window.present()
        if self.screenshots:
            from .screenshots import capture_pages
            GLib.timeout_add(1000,capture_pages,self,self.screenshots)
