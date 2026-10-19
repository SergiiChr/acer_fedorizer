# SPDX-License-Identifier: GPL-3.0-only
"""GTK4/libadwaita control center; hardware requests stay in the existing daemon."""
import copy
import math
from pathlib import Path
import threading
import gi
gi.require_version('Gtk','4.0')
gi.require_version('Adw','1')
from gi.repository import Gtk, Adw, Gio, GLib, Gdk
from .client import ControlClient
from .models import LightingDraft, EFFECTS, PROFILES, TARGETS, full_key_map, rgb_hex
from .telemetry import Telemetry
from .widgets import label, box, HistoryChart, KeyboardCanvas, color_rgba, hex_rgba
from . import preview, display

PAGES=[('overview','Overview','view-grid-symbolic','Your laptop at a glance'),
       ('performance','Performance','power-profile-performance-symbolic','Balance performance, acoustics, and cooling'),
       ('lighting','Lighting','keyboard-brightness-symbolic','Make your keyboard and chassis your own'),
       ('battery','Battery','battery-good-symbolic','Keep an eye on charge and long-term health'),
       ('display','Display','video-display-symbolic','Native color management for your built-in panel'),
       ('diagnostics','System','preferences-system-symbolic','Capabilities, connection details, and credits')]


def button(text, callback, css='suggested-action'):
    widget=Gtk.Button(label=text,valign=Gtk.Align.CENTER)
    if css: widget.add_css_class(css)
    widget.connect('clicked',callback)
    return widget


def suffix_row(title, value='', subtitle=None):
    row=Adw.ActionRow(title=title,subtitle=subtitle or '')
    value_label=label(value,'dim-label')
    value_label.set_wrap(False)
    row.add_suffix(value_label)
    return row,value_label


def number_text(value, unit='', digits=0, missing='Unavailable'):
    return f'{value:.{digits}f}{unit}' if value is not None else missing


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application, demo=False):
        super().__init__(application=application,title='Acer Fedorizer',default_width=1160,default_height=900)
        self.demo=demo; self.closed=False; self.pending=False; self.polling=False; self.display_pending=False
        self.client=preview.PreviewClient() if demo else ControlClient()
        self.telemetry=Telemetry(); self.state={}; self.connected=False; self.updating=False
        self.drafts={}; self.current_target=None; self.lighting_loading=False; self.layout=None
        self.gpu_enabled=False; self.manual_dirty=False
        self.build()
        self.connect('close-request',self.on_close)
        if demo:
            self.receive_state(self.client.command('get_all_settings'),None)
            self.receive_metrics(preview.sample())
            self.set_layout(preview.layout())
            self.receive_display(dict(available=True,enabled=False,connector='eDP-1',mode='default',message='Built-in display · Native SDR supported'))
            for i in range(60):
                self.cpu_chart.sample(25+8*math.sin(i*.18)+3*math.sin(i*.7))
                self.gpu_chart.sample(None)
        else: self.refresh()
        self.timer=GLib.timeout_add_seconds(2,self.refresh)

    def build(self):
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
        header.set_title_widget(label('FEDORIZER','brand'))
        sidebar.add_top_bar(header)
        sidebox=box(0)
        nav=Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        nav.add_css_class('navigation-sidebar')
        self.nav_rows={}
        for key,title,icon,_ in PAGES:
            row=Gtk.ListBoxRow()
            line=box(12,True)
            line.append(Gtk.Image.new_from_icon_name(icon)); line.append(label(title))
            row.set_child(line); row.page_name=key; nav.append(row); self.nav_rows[key]=row
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
        self.window_title=Adw.WindowTitle(title='Overview',subtitle='Acer Fedorizer')
        top.set_title_widget(self.window_title)
        if self.demo: top.pack_start(label('Preview data','preview-badge'))
        menu=Gio.Menu()
        menu.append('Licenses and credits','app.credits')
        menu_button=Gtk.MenuButton(icon_name='open-menu-symbolic',menu_model=menu)
        self.header_apply=button('Apply lighting',self.apply_lighting)
        self.header_apply.set_visible(False)
        top.pack_end(menu_button)
        top.pack_end(self.header_apply)
        content.add_top_bar(top)
        column=box(0)
        self.banner=Adw.Banner(title='Hardware service unavailable. Run ./setup.sh status to check your installation.')
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
        nav.select_row(self.nav_rows['overview'])

    def navigate(self, _, row):
        if row is None: return
        self.stack.set_visible_child_name(row.page_name)
        self.header_apply.set_visible(row.page_name=='lighting')
        self.window_title.set_title(next(p[1] for p in PAGES if p[0]==row.page_name))
        self.split.set_show_content(True)
        if row.page_name=='lighting' and not self.layout and self.connected: self.load_layout()
        if row.page_name=='display' and not self.demo: self.refresh_display()

    def build_overview(self):
        page=self.pages['overview']
        hero=box(12); hero.add_css_class('hero')
        line=box(12,True); heading=label('READY FOR YOUR NEXT SESSION','eyebrow'); heading.set_hexpand(True); line.append(heading)
        self.ac_label=label('AC power','status-pill'); self.ac_label.set_hexpand(False); self.ac_label.set_halign(Gtk.Align.END); line.append(self.ac_label)
        hero.append(line)
        self.profile_hero=label('Balanced','hero-value'); hero.append(self.profile_hero)
        hero.append(label('Stock kernel controls. Your hardware stays in charge.','dim-label'))
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

    def build_performance(self):
        page=self.pages['performance']
        self.profile_group=Adw.PreferencesGroup(title='Power profile',description='Available profiles come from the stock Acer platform driver.')
        self.profile_combo=Adw.ComboRow(title='Choose a profile',model=Gtk.StringList.new([]))
        self.profile_choices=[]
        self.profile_group.add(self.profile_combo)
        row=Adw.ActionRow(title='Current profile',subtitle='Changes made by the hardware button appear automatically.')
        self.current_profile=label('Unavailable','status-pill'); row.add_suffix(self.current_profile)
        row.add_suffix(button('Apply profile',self.apply_profile))
        self.profile_group.add(row); page.append(self.profile_group)
        self.fan_group=Adw.PreferencesGroup(title='Cooling',description='Manual settings are drafts until applied. Failed writes restore automatic cooling.')
        self.fan_mode=Adw.ComboRow(title='Choose a fan mode',model=Gtk.StringList.new(['Automatic','Maximum','Manual']))
        self.fan_group.add(self.fan_mode)
        self.fan_mode.connect('notify::selected',lambda *_: self.update_fan_sensitivity())
        self.cpu_slider,self.cpu_rpm=self.fan_row('CPU fan',45)
        self.gpu_slider,self.gpu_rpm=self.fan_row('GPU fan',45)
        row=Adw.ActionRow(title='Current cooling',subtitle='Reading firmware state…')
        self.fan_current=row
        row.add_suffix(button('Apply fan settings',self.apply_fans)); self.fan_group.add(row)
        page.append(self.fan_group)
        self.extras=Adw.PreferencesGroup(title='Device options',description='Only controls exposed by the stock driver appear here.')
        self.extra_switches={}
        for key,title in [('backlight_timeout','Keyboard backlight timeout'),('boot_animation_sound','Boot animation and sound'),('lcd_override','LCD overdrive')]:
            row=Adw.SwitchRow(title=title)
            row.connect('notify::active',self.extra_toggled,key)
            self.extra_switches[key]=row; self.extras.add(row)
        self.usb_combo=Adw.ComboRow(title='USB charging threshold',model=Gtk.StringList.new(['Off','10%','20%','30%']))
        self.usb_combo.connect('notify::selected',self.usb_changed); self.extras.add(self.usb_combo)
        page.append(self.extras)
        self.update_fan_sensitivity()

    def fan_row(self,title,value):
        row=Adw.ActionRow(title=title)
        slider=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,1,99,1)
        slider.set_value(value); slider.set_draw_value(True); slider.set_value_pos(Gtk.PositionType.RIGHT)
        slider.set_size_request(220,-1); slider.set_valign(Gtk.Align.CENTER)
        rpm=label('— RPM','dim-label'); rpm.set_width_chars(11)
        row.add_suffix(slider); row.add_suffix(rpm); self.fan_group.add(row)
        return slider,rpm

    def build_lighting(self):
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
        color_row=Adw.ActionRow(title='Color')
        self.color_entry=Gtk.Entry(text='#5BBFBD',max_length=7,width_chars=10,valign=Gtk.Align.CENTER)
        self.color_button=Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(),rgba=color_rgba('5bbfbd'),valign=Gtk.Align.CENTER)
        self.color_button.connect('notify::rgba',lambda *_: self.color_entry.set_text('#'+hex_rgba(self.color_button.get_rgba()).upper()))
        self.color_entry.connect('activate',self.color_entered)
        color_row.add_suffix(self.color_entry); color_row.add_suffix(self.color_button); self.light_group.add(color_row)
        self.brightness=self.scale_row('Brightness',0,100,80)
        self.speed=self.scale_row('Animation speed',1,9,5)
        self.direction=Adw.ComboRow(title='Wave direction',model=Gtk.StringList.new(['Left to right','Right to left']))
        self.light_group.add(self.direction)
        self.link_wasd=Adw.SwitchRow(title='Also update WASD',subtitle='Match supported settings. Firmware animations have independent timing.')
        self.link_wasd.set_active(True); self.light_group.add(self.link_wasd)
        page.append(self.light_group)
        bottom=box(12,True)
        self.effect_note=label('Changes are applied only when you press Apply.','dim-label'); self.effect_note.set_hexpand(True)
        bottom.append(self.effect_note)
        self.light_apply=button('Apply lighting',self.apply_lighting); bottom.append(self.light_apply); page.append(bottom)
        zones=Adw.PreferencesGroup()
        self.zones=Adw.ExpanderRow(title='Four-zone static colors',subtitle='Paint four keyboard regions with independent static colors.')
        self.zone_buttons=[]
        for i,color in enumerate(('5bbfbd','73a7d8','a691d9','d6a46e')):
            row=Adw.ActionRow(title=f'Zone {i+1}')
            picker=Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(),rgba=color_rgba(color),valign=Gtk.Align.CENTER)
            row.add_suffix(picker); self.zones.add_row(row); self.zone_buttons.append(picker)
        row=Adw.ActionRow(title='Apply four zones')
        row.add_suffix(button('Apply zones',self.apply_zones)); self.zones.add_row(row)
        zones.add(self.zones); page.append(zones)

    def scale_row(self,title,minimum,maximum,value):
        row=Adw.ActionRow(title=title)
        slider=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,minimum,maximum,1)
        slider.set_value(value); slider.set_draw_value(True); slider.set_value_pos(Gtk.PositionType.RIGHT)
        slider.set_size_request(280,-1); slider.set_valign(Gtk.Align.CENTER)
        row.add_suffix(slider); self.light_group.add(row)
        return slider

    def build_battery(self):
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
        controls=Adw.PreferencesGroup(title='Battery care')
        self.charge_limit=Adw.SwitchRow(title='Limit charging to 80%',subtitle='Reduce time at full charge when the laptop is usually plugged in.')
        self.charge_limit.connect('notify::active',self.charge_changed); controls.add(self.charge_limit)
        self.calibration=Adw.ActionRow(title='Battery calibration',subtitle='Only available when the stock driver exposes calibration.')
        self.calibration.add_suffix(button('Start',lambda *_: self.mutate('set_battery_calibration',dict(enabled=True))))
        self.calibration.add_suffix(button('Stop',lambda *_: self.mutate('set_battery_calibration',dict(enabled=False)),'flat'))
        controls.add(self.calibration); page.append(controls)

    def build_display(self):
        page=self.pages['display']
        hero=box(12); hero.add_css_class('hero'); hero.append(label('BUILT-IN DISPLAY','eyebrow'))
        hero.append(label('Colors, as intended','title-1'))
        hero.append(label('Use your panel’s native SDR color space while preserving your monitor layout.','page-description')); page.append(hero)
        group=Adw.PreferencesGroup(title='Color management')
        self.display_switch=Adw.SwitchRow(title='Native SDR color',subtitle='Requires an active built-in panel with Mutter sdr-native support.')
        self.display_switch.connect('notify::active',self.display_toggled); group.add(self.display_switch)
        row,self.display_connector=suffix_row('Built-in panel','Detecting…'); group.add(row)
        row,self.display_mode=suffix_row('Current color mode','—'); group.add(row); page.append(group)
        self.display_note=label('Checking GNOME session support…','dim-label'); page.append(self.display_note)
        line=box(horizontal=True)
        line.append(button('Refresh display status',lambda *_: self.refresh_display(),'flat')); page.append(line)
        note=Adw.PreferencesGroup(title='About this setting',description='Changes are saved by GNOME for future sessions. This does not select an ICC profile or enable HDR. The control is unavailable while HDR is selected or the built-in panel is inactive.')
        page.append(note)
        self.display_state={}

    def build_diagnostics(self):
        page=self.pages['diagnostics']
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
        page.append(label('For installation health, run: ./setup.sh status\nFor service logs: journalctl -u fedorizer-daemon.service -b','dim-label'))

    def async_call(self, function, callback):
        def work():
            try: result,error=function(),None
            except Exception as exc: result,error=None,str(exc)
            def deliver():
                if not self.closed: callback(result,error)
                return False
            GLib.idle_add(deliver)
        threading.Thread(target=work,daemon=True).start()

    def refresh(self):
        if self.closed: return False
        if self.polling or self.pending: return True
        if self.demo:
            self.receive_state(self.client.command('get_all_settings'),None)
            self.receive_metrics(preview.sample(self.gpu_enabled))
            return True
        self.polling=True
        overview=self.stack.get_visible_child_name()=='overview'
        gpu=self.gpu_enabled and overview
        def work():
            try: state,error=self.client.command('get_all_settings'),None
            except Exception as exc: state,error=None,str(exc)
            metrics=self.telemetry.sample(gpu) if overview else dict(battery=self.telemetry.battery())
            return state,error,metrics
        def received(result,error):
            self.polling=False
            if error: self.receive_state(None,error); return
            state,error,metrics=result
            self.receive_state(state,error); self.receive_metrics(metrics)
        self.async_call(work,received)
        if self.stack.get_visible_child_name()=='display': self.refresh_display()
        return True

    def receive_state(self,state,error):
        self.connected=state is not None
        self.banner.set_revealed(not self.connected)
        self.connection_label.set_text('Preview · no hardware access' if self.demo else 'Hardware service connected' if self.connected else 'Hardware service unavailable')
        self.profile_group.set_sensitive(self.connected and not self.pending and 'thermal_profile' in (state or {}).get('available_features',[]))
        self.fan_group.set_sensitive(self.connected and not self.pending and 'fan_speed' in (state or {}).get('available_features',[]))
        self.light_group.set_sensitive(self.connected and not self.pending)
        self.light_apply.set_sensitive(self.connected and not self.pending and bool((state or {}).get('lighting_modes')))
        self.header_apply.set_sensitive(self.light_apply.get_sensitive())
        self.charge_limit.set_sensitive(self.connected and not self.pending)
        self.extras.set_sensitive(self.connected and not self.pending)
        if state is None: return
        self.state=state; self.updating=True
        try:
            features=state.get('available_features',[])
            profile=state.get('thermal_profile',{})
            choices=profile.get('available',[])
            current=profile.get('current','')
            if choices!=self.profile_choices:
                self.profile_choices=choices
                self.profile_combo.set_model(Gtk.StringList.new([PROFILES.get(v,v) for v in choices]))
                if current in choices: self.profile_combo.set_selected(choices.index(current))
            self.current_profile.set_text(PROFILES.get(current,current or 'Unavailable'))
            self.profile_hero.set_text(PROFILES.get(current,current or 'Monitoring'))
            ac=state.get('ac_online')
            self.ac_label.set_text('AC power' if ac is True else 'Battery power' if ac is False else 'Power source unknown')
            for key,widget in (('cpu',self.cpu_rpm),('gpu',self.gpu_rpm)):
                widget.set_text(number_text(state.get('fan_rpm',{}).get(key),' RPM'))
            fan_values=state.get('fan_speed',{})
            confirmed='Automatic' if fan_values.get('cpu')==fan_values.get('gpu')=='0' else 'Maximum' if fan_values.get('cpu')==fan_values.get('gpu')=='100' else 'Manual or mixed control'
            self.fan_current.set_subtitle(confirmed+' · selection above is an editing draft')
            self.charge_limit.set_visible('battery_limiter' in features)
            self.charge_limit.set_active(state.get('battery_limiter')=='1')
            self.calibration.set_visible('battery_calibration' in features)
            for key,row in self.extra_switches.items():
                row.set_visible(key in features); row.set_active(state.get(key)=='1')
            self.usb_combo.set_visible('usb_charging' in features)
            self.usb_combo.set_selected({'0':0,'10':1,'20':2,'30':3}.get(state.get('usb_charging','0'),0))
            self.extras.set_visible(any(row.get_visible() for row in self.extra_switches.values()) or 'usb_charging' in features)
            self.per_key_button.set_sensitive('per_key_mode' in features)
            self.zones.set_visible('per_zone_mode' in features)
            modes=state.get('lighting_modes',{})
            targets=[key for key in TARGETS if key in modes and modes[key]]
            if targets!=self.targets:
                self.lighting_loading=True
                self.targets=targets
                self.target_combo.set_model(Gtk.StringList.new([TARGETS[t] for t in targets]))
                self.target_combo.set_selected(0)
                self.current_target=targets[0] if targets else None
                self.lighting_loading=False
                self.load_draft()
            self.system_labels['model'].set_text(state.get('laptop_type','Unknown'))
            self.system_labels['driver'].set_text(state.get('driver_version','Stock kernel + HID'))
            self.system_labels['version'].set_text(state.get('version','—'))
            self.system_labels['socket'].set_text('Preview' if self.demo else 'Connected · local Unix socket')
            self.capability_text.set_text('  ·  '.join(feature.replace('_',' ').title() for feature in features))
        finally: self.updating=False

    def receive_metrics(self,metrics):
        if 'cpu_usage' in metrics:
            self.cpu_value.set_text(number_text(metrics.get('cpu_usage'),'%',1,missing='Sampling…'))
            self.cpu_detail.set_text('Temperature '+number_text(metrics.get('cpu_temperature'),'°C'))
            self.cpu_memory.set_text('Memory · '+number_text(metrics.get('memory_used'),' GiB',1)+' / '+number_text(metrics.get('memory_total'),' GiB',1))
            self.cpu_chart.sample(metrics.get('cpu_usage'))
            gpu=metrics.get('gpu') if self.gpu_enabled else None
            self.gpu_value.set_text(number_text(gpu.get('temperature'),'°C') if gpu else 'Unavailable' if self.gpu_enabled else 'Paused')
            self.gpu_detail.set_text(('Usage '+number_text(gpu.get('usage'),'%')+' · '+number_text(gpu.get('power'),' W',1)) if gpu else 'Waiting for NVIDIA telemetry' if self.gpu_enabled else 'Monitoring is off to save power')
            self.gpu_chart.sample(gpu.get('usage') if gpu else None)
            used,total=(gpu.get('memory_used'),gpu.get('memory_total')) if gpu else (None,None)
            self.vram.set_fraction(min(1,used/total) if used is not None and total else 0)
            self.vram.set_text(f'VRAM · {used/1024:.1f} / {total/1024:.1f} GiB' if used is not None and total else 'VRAM · unavailable' if self.gpu_enabled else 'VRAM · monitoring paused')
            cores=metrics.get('cores',[])
            if len(cores)!=len(self.core_labels):
                while self.core_grid.get_first_child(): self.core_grid.remove(self.core_grid.get_first_child())
                self.core_labels=[]
                for _ in cores:
                    value=label('','core-pill'); self.core_labels.append(value); self.core_grid.append(value)
            for i,(widget,value) in enumerate(zip(self.core_labels,cores)):
                widget.set_text(f'Core {i+1:02d}  {value:.2f} GHz')
        battery=metrics.get('battery',{})
        capacity=battery.get('capacity')
        self.battery_value.set_text(number_text(capacity,'%',0,missing='No battery'))
        self.battery_progress.set_fraction(max(0,min(1,capacity/100)) if capacity is not None else 0)
        hours=battery.get('hours')
        estimate=f' · {int(hours)}h {int(hours*60)%60:02d}m '+('until full' if battery.get('status')=='Charging' else 'remaining') if hours is not None else ''
        self.battery_status.set_text(battery.get('status','Unavailable')+estimate)
        for key,widget in self.battery_labels.items():
            value=battery.get(key)
            widget.set_text(number_text(value,'%',1) if key=='health' else number_text(value,'',0) if key=='cycles' else str(value or 'Unavailable'))

    def gpu_toggled(self,*_):
        self.gpu_enabled=self.gpu_switch.get_active()
        if not self.gpu_enabled:
            self.gpu_value.set_text('Paused')
            self.gpu_detail.set_text('Monitoring is off to save power')
            self.gpu_chart.sample(None)
            self.vram.set_fraction(0); self.vram.set_text('VRAM · monitoring paused')
        self.refresh()

    def mutate(self,command,params,callback=None):
        if self.pending: return
        self.pending=True
        self.light_apply.set_sensitive(False); self.header_apply.set_sensitive(False)
        for group in (self.light_group,self.profile_group,self.fan_group,self.extras,self.charge_limit): group.set_sensitive(False)
        def done(result,error):
            self.pending=False
            if error: self.toast.add_toast(Adw.Toast(title='Could not apply: '+error,timeout=8))
            else:
                self.toast.add_toast(Adw.Toast(title='Settings applied' if not self.demo else 'Preview updated · no hardware changed'))
                if isinstance(result,dict) and 'available_features' in result: self.receive_state(result,None)
                if callback: callback(result)
            if self.state: self.receive_state(self.state,None)
            if not self.closed: self.refresh()
        self.async_call(lambda:self.client.command(command,params),done)

    def apply_profile(self,*_):
        index=self.profile_combo.get_selected()
        if index<len(self.profile_choices): self.mutate('set_thermal_profile',dict(profile=self.profile_choices[index]))
    def update_fan_sensitivity(self):
        if not hasattr(self,'cpu_slider'): return
        manual=self.fan_mode.get_selected()==2
        self.cpu_slider.set_sensitive(manual); self.gpu_slider.set_sensitive(manual)
    def apply_fans(self,*_):
        mode=self.fan_mode.get_selected()
        values=(0,0) if mode==0 else (100,100) if mode==1 else (round(self.cpu_slider.get_value()),round(self.gpu_slider.get_value()))
        self.mutate('set_fan_speed',dict(cpu=values[0],gpu=values[1]))
    def charge_changed(self,row,*_):
        if not self.updating: self.mutate('set_battery_limiter',dict(enabled=row.get_active()))
    def extra_toggled(self,row,_,key):
        if not self.updating: self.mutate('set_'+key,dict(enabled=row.get_active()))
    def usb_changed(self,row,*_):
        if not self.updating: self.mutate('set_usb_charging',dict(level=[0,10,20,30][row.get_selected()]))

    def capture_draft(self):
        if self.current_target and self.effect_ids:
            index=self.effect_combo.get_selected()
            mode=self.effect_ids[min(index,len(self.effect_ids)-1)]
            color=hex_rgba(self.color_button.get_rgba()) if mode in (2,3) else self.color_entry.get_text()
            self.drafts[self.current_target]=LightingDraft(mode,color,round(self.brightness.get_value()),round(self.speed.get_value()),self.direction.get_selected()+1,self.link_wasd.get_active())
    def target_changed(self,*_):
        if self.lighting_loading: return
        self.capture_draft()
        index=self.target_combo.get_selected()
        self.current_target=self.targets[index] if index<len(self.targets) else None
        self.load_draft()
    def load_draft(self):
        if not self.current_target: return
        modes=self.state.get('lighting_modes',{}).get(self.current_target,[])
        if not modes: return
        draft=self.drafts.get(self.current_target) or LightingDraft.from_state(self.state.get('lighting_state',{}).get(self.current_target,{}),modes)
        self.lighting_loading=True
        self.effect_ids=modes
        self.effect_combo.set_model(Gtk.StringList.new([EFFECTS.get(i,str(i)) for i in modes]))
        self.effect_combo.set_selected(modes.index(draft.mode) if draft.mode in modes else 0)
        self.color_entry.set_text('#'+draft.color.lstrip('#').upper())
        try: self.color_button.set_rgba(color_rgba(rgb_hex(draft.color)))
        except ValueError: pass
        self.brightness.set_value(draft.brightness); self.speed.set_value(draft.speed)
        self.direction.set_selected(draft.direction-1); self.link_wasd.set_active(draft.link_wasd)
        self.link_wasd.set_visible(self.current_target=='keyboard')
        self.lighting_loading=False
        self.effect_changed()
    def effect_changed(self,*_):
        if not self.effect_ids: return
        index=self.effect_combo.get_selected()
        if index>=len(self.effect_ids): return
        mode=self.effect_ids[index]; palette=mode in (2,3)
        self.color_entry.set_sensitive(not palette); self.color_button.set_sensitive(not palette)
        self.direction.set_sensitive(mode==3 and self.current_target!='logo')
        self.speed.set_sensitive(mode!=0 and self.current_target!='logo')
        self.effect_note.set_text('Wave uses a firmware palette. Linked WASD and keyboard animations run independently.' if mode==3 else
            'This effect uses its firmware color palette.' if palette else
            'All lights share settings; their animation timing can differ.' if self.current_target=='all' else 'Last successful command is saved; hardware effect readback is unavailable.')
    def color_entered(self,*_):
        try: self.color_button.set_rgba(color_rgba(rgb_hex(self.color_entry.get_text())))
        except ValueError as error: self.toast.add_toast(Adw.Toast(title=str(error)))
    def apply_lighting(self,*_):
        self.capture_draft()
        if not self.current_target or self.current_target not in self.drafts: return
        try: params=self.drafts[self.current_target].params(self.current_target)
        except ValueError as error: self.toast.add_toast(Adw.Toast(title=str(error))); return
        def applied(_):
            self.drafts.pop(self.current_target,None)
            if params['target']=='keyboard' and params['link_wasd']: self.drafts.pop('wasd',None)
            if params['target']=='all': self.drafts.clear()
        self.mutate('set_lighting',params,applied)
    def apply_zones(self,*_):
        params={f'zone{i+1}':hex_rgba(picker.get_rgba()) for i,picker in enumerate(self.zone_buttons)}
        params['brightness']=round(self.brightness.get_value())
        self.mutate('set_per_zone_mode',params)
    def load_layout(self):
        self.async_call(lambda:self.client.command('get_keyboard_layout'),lambda result,error:self.set_layout(result) if not error else None)
    def set_layout(self,layout):
        self.layout=layout
        saved=self.state.get('lighting_state',{}).get('per_key',{}).get('colors',{})
        self.keyboard_canvas.set_layout(layout.get('lamps',[]),full_key_map(layout.get('lamps',[]),saved))
    def open_editor(self,*_):
        if not self.layout:
            self.async_call(lambda:self.client.command('get_keyboard_layout'),lambda result,error:self.editor_layout(result,error))
        else: self.editor_layout(self.layout,None)
    def editor_layout(self,layout,error):
        if error: self.toast.add_toast(Adw.Toast(title='Could not read keyboard layout: '+error)); return
        self.set_layout(layout)
        self.editor=KeyEditor(self,layout)
        self.editor.present()

    def refresh_display(self):
        if self.display_pending: return
        if self.demo:
            self.receive_display(self.display_state or dict(available=True,enabled=False,connector='eDP-1',mode='default',message='Preview panel')); return
        self.display_pending=True
        def done(result,error):
            self.display_pending=False
            self.receive_display(result or dict(available=False,enabled=False,message=error or 'Unavailable'))
        self.async_call(lambda:display.run('status'),done)
    def receive_display(self,state):
        self.display_state=state
        self.updating=True
        self.display_switch.set_active(state.get('enabled',False))
        self.display_switch.set_sensitive(state.get('available',False))
        self.display_connector.set_text(state.get('connector') or 'Unavailable')
        self.display_mode.set_text({'default':'Default SDR','sdr-native':'Native SDR','bt2100':'HDR'}.get(state.get('mode'),'Unavailable'))
        self.display_note.set_text(state.get('message',''))
        self.updating=False
    def display_toggled(self,row,*_):
        if self.updating: return
        enabled=row.get_active()
        if self.demo:
            self.receive_display(dict(self.display_state,enabled=enabled,mode='sdr-native' if enabled else 'default')); return
        row.set_sensitive(False)
        self.display_pending=True
        def done(result,error):
            self.display_pending=False
            if error:
                self.toast.add_toast(Adw.Toast(title='Display change failed: '+error,timeout=8))
                self.refresh_display()
            else: self.receive_display(result)
        self.async_call(lambda:display.run('enable' if enabled else 'disable',self.display_state.get('connector')),done)

    def show_credits(self):
        window=Adw.Window(title='Licenses and credits',transient_for=self,modal=True,default_width=760,default_height=660)
        toolbar=Adw.ToolbarView(); toolbar.add_top_bar(Adw.HeaderBar())
        path=Path(__file__).resolve().parents[1]/'NOTICE.md'
        text=path.read_text() if path.exists() else 'License notices are missing. Reinstall from a complete source package.'
        view=Gtk.TextView(editable=False,cursor_visible=False,wrap_mode=Gtk.WrapMode.WORD_CHAR,left_margin=24,right_margin=24,top_margin=24,bottom_margin=24)
        view.get_buffer().set_text(text)
        scroll=Gtk.ScrolledWindow(child=view); toolbar.set_content(scroll); window.set_content(toolbar); window.present()
    def on_close(self,*_):
        self.closed=True
        if hasattr(self,'timer'): GLib.source_remove(self.timer)
        # Closing never sends a hardware command. In-flight workers are daemon threads.
        threading.Thread(target=self.client.close,daemon=True).start()
        return False


class KeyEditor(Adw.Window):
    def __init__(self,parent,layout):
        super().__init__(title='Per-key lighting',transient_for=parent,modal=True,default_width=1020,default_height=600)
        self.parent=parent
        self.colors=full_key_map(layout['lamps'],parent.state.get('lighting_state',{}).get('per_key',{}).get('colors',{}))
        toolbar=Adw.ToolbarView(); header=Adw.HeaderBar()
        if parent.demo: header.pack_start(label('Preview data','preview-badge'))
        toolbar.add_top_bar(header)
        content=box(20)
        for setter in (content.set_margin_start,content.set_margin_end,content.set_margin_top,content.set_margin_bottom): setter(28)
        content.append(label('Paint your keyboard','page-heading'))
        content.append(label('Select keys, choose a color, then apply the complete static layout.','page-description'))
        self.canvas=KeyboardCanvas(250); self.canvas.set_layout(layout['lamps'],self.colors)
        self.canvas.add_css_class('keyboard-card'); content.append(self.canvas)
        controls=box(12,True)
        controls.append(button('Select all',lambda *_:self.select_all(),'flat'))
        controls.append(button('Clear selection',lambda *_:self.clear_selection(),'flat'))
        self.selection=label('No keys selected','dim-label'); self.selection.set_hexpand(True); controls.append(self.selection)
        self.picker=Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(),rgba=color_rgba('dfb678'))
        controls.append(self.picker)
        controls.append(button('Paint selection',self.paint))
        content.append(controls)
        self.canvas.on_selection=lambda count:self.selection.set_text(f'{count} keys selected' if count else 'No keys selected')
        row=box(12,True); row.append(label('Brightness','dim-label'))
        self.brightness=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,0,100,1)
        self.brightness.set_value(80); self.brightness.set_draw_value(True); self.brightness.set_hexpand(True)
        row.append(self.brightness)
        self.apply=button('Apply keyboard colors',self.submit); row.append(self.apply); content.append(row)
        self.result=label('The current preview is an editing draft, not a hardware readback.','dim-label'); content.append(self.result)
        toolbar.set_content(content); self.set_content(toolbar)
    def select_all(self):
        self.canvas.selected={int(key) for key in self.colors}; self.canvas.queue_draw()
        self.canvas.on_selection(len(self.canvas.selected))
    def clear_selection(self):
        self.canvas.selected.clear(); self.canvas.queue_draw(); self.canvas.on_selection(0)
    def paint(self,*_):
        color=hex_rgba(self.picker.get_rgba())
        for lid in self.canvas.selected:
            if str(lid) in self.colors: self.colors[str(lid)]=color
        self.canvas.colors=self.colors; self.canvas.queue_draw()
    def submit(self,*_):
        self.apply.set_sensitive(False)
        colors=copy.deepcopy(self.colors)
        params=dict(colors=colors,brightness=round(self.brightness.get_value()))
        def done(result,error):
            self.apply.set_sensitive(True)
            self.result.set_text('Could not apply: '+error if error else 'Preview updated · no hardware changed' if self.parent.demo else 'Static layout applied. Confirm the visible result on your keyboard.')
            if not error:
                self.parent.keyboard_canvas.set_layout(self.parent.layout['lamps'],colors)
                if 'available_features' in result: self.parent.receive_state(result,None)
        self.parent.async_call(lambda:self.parent.client.command('set_per_key',params),done)


class Application(Adw.Application):
    def __init__(self,demo=False,screenshots=None):
        super().__init__(application_id='io.github.SergiiChr.AcerFedorizer'+('.Preview' if demo else ''),flags=Gio.ApplicationFlags.NON_UNIQUE if demo else Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.demo=demo; self.screenshots=screenshots
    def do_activate(self):
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
