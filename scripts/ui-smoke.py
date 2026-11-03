#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise actual GTK widgets with preview services; no hardware access."""
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import gi

gi.require_version('Gtk','4.0')
from gi.repository import GLib, Gtk

from control_center.app import Application, KeyEditor
from control_center.client import JSON
from control_center.models import ZONE_MODE, CoreKind, Lamp, Settings, mapping
from control_center.preview import PreviewServices
from control_center.widgets import color_rgba

services=PreviewServices()
client=services.client
app=Application(services)
failures: list[str]=[]

def when(ready: Callable[[], bool], verify: Callable[[], object], timeout: float = 5) -> None:
    """Run verify once ready() is true or the timeout passes, so slow async applies do not fail at random."""
    deadline=time.monotonic()+timeout
    def poll() -> bool:
        if ready() or time.monotonic()>deadline:
            verify(); return False
        return True
    GLib.timeout_add(50,poll)

def refresh_state() -> None:
    app.window.receive_state(Settings.parse(client.command('get_all_settings')))

def layout() -> list[Lamp]:
    assert app.window.layout,'Keyboard layout not loaded'
    return app.window.layout

def open_editor() -> KeyEditor:
    # The layout is already loaded here, so the editor opens at once.
    app.window.editor=None
    app.window.open_editor()
    assert app.window.editor,'Per-key editor did not open'
    return app.window.editor

def fail(message: str) -> None:
    failures.append(message); print('FAIL:',message,file=sys.stderr,flush=True)
    app.window.close(); app.quit()

def start() -> bool:
    when(lambda:app.window.connected,lambda:app.window.ensure_layout(lambda _:checks(),lambda error:fail('Keyboard layout did not load: '+error)))
    return False

def checks() -> bool:
    try:
        window=app.window
        assert not any(command.startswith('set_') for command,_ in client.commands),'Startup wrote a setting'
        for name in window.nav_rows:
            window.nav.select_row(window.nav_rows[name])
            assert window.stack.get_visible_child_name()==name
        # One click applies a profile; clicking the profile already in effect sends nothing.
        expected=[('Eco','low-power'),('Quiet','quiet'),('Balanced','balanced'),
                  ('Performance','balanced-performance'),('Turbo','performance')]
        with patch.object(window,'mutate') as mutate:
            window.profile_tiles.buttons[window.profile_choices.index('balanced')].emit('clicked')
            mutate.assert_not_called()
            for name,profile in expected:
                index=window.profile_choices.index(profile)
                tile=window.profile_tiles.buttons[index]
                assert tile.get_tooltip_text()==name
                tile.emit('clicked')
                mutate.assert_called_once_with('set_thermal_profile',{'profile':profile})
                assert tile.get_active() and sum(b.get_active() for b in window.profile_tiles.buttons)==1
                mutate.reset_mock()
                client.profile=profile; refresh_state()
            client.profile='quiet'; refresh_state()
            assert window.profile_tiles.get_selected()==window.profile_choices.index('quiet'),'Hardware button change not shown'
            client.profile='balanced'; refresh_state()
            # One click applies a fan mode; manual speeds apply once a slider settles, and refreshes keep the unsettled value.
            window.fan_mode.buttons[1].emit('clicked')
            mutate.assert_called_once_with('set_fan_speed',{'cpu':100,'gpu':100}); mutate.reset_mock()
            window.fan_mode.buttons[2].emit('clicked')
            mutate.assert_called_once_with('set_fan_speed',{'cpu':45,'gpu':45}); mutate.reset_mock()
            assert window.cpu_slider.get_sensitive() and window.gpu_slider.get_sensitive()
            window.cpu_slider.set_value(60)
            refresh_state()
            assert window.cpu_slider.get_value()==60 and window.fan_mode.get_selected()==2,'Refresh reset an unsettled fan speed'
            mutate.assert_not_called()
            while window.fan_timer: GLib.MainContext.default().iteration(True)
            mutate.assert_called_once_with('set_fan_speed',{'cpu':60,'gpu':45}); mutate.reset_mock()
            window.fan_mode.buttons[0].emit('clicked')
            mutate.assert_not_called()
            assert not window.cpu_slider.get_sensitive() and not window.gpu_slider.get_sensitive()
            # Frequency limits apply only with the button.
            window.nav.select_row(window.nav_rows['cpu'])
            performance,efficiency=window.limit_rows[CoreKind.PERFORMANCE],window.limit_rows[CoreKind.EFFICIENCY]
            assert performance.get_value()==4.0 and efficiency.get_value()==3.0,'Saved caps not shown'
            performance.set_value(4.5); efficiency.set_value(4.1)
            refresh_state()
            assert performance.get_value()==4.5,'Refresh reset the limit fields'
            mutate.assert_not_called()
            window.apply_limits()
            mutate.assert_called_once_with('set_cpu_limits',{'performance':4500000,'efficiency':4100000}); mutate.reset_mock()
            window.remove_limits()
            assert mutate.call_args.args[:2]==('set_cpu_limits',{'performance':None,'efficiency':None})
        for _ in range(2): window.receive_cores(services.cores())
        bars=window.core_bars
        assert len(bars.cores)==24 and bars.averages!=[core.ghz for core in bars.cores],'Chart shows no averages'
        credits_window=window.show_credits()
        def descendants(widget: Gtk.Widget) -> Iterator[Gtk.Widget]:
            yield widget
            child=widget.get_first_child()
            while child:
                yield from descendants(child)
                child=child.get_next_sibling()
        credits=[widget for widget in descendants(credits_window) if isinstance(widget,Gtk.Label)]
        rendered='\n'.join(widget.get_text() for widget in credits)
        assert 'Licenses, attribution, and distribution' in rendered
        assert 'Div Acer Manager Max — PXDiv and its contributors.' in rendered
        assert 'GNU LGPL 2.1 or later;' in rendered,'License table missing'
        assert '**' not in rendered and '[OpenRGB issue' not in rendered,'Raw Markdown visible'
        assert any('<a href=' in widget.get_label() for widget in credits),'Links not rendered'
        credits_window.close()
        window.installation_failed('Timed out')
        assert 'failed' in (window.status_group.get_description() or '')
        assert all('Not checked' in (row.get_subtitle() or '') for row,_ in window.status_rows.values())
        window.banner.emit('button-clicked')
        assert window.stack.get_visible_child_name()=='diagnostics'
        assert window.status_pending and not window.status_button.get_sensitive()
        window.nav.select_row(window.nav_rows['lighting'])
        window.color_entry.set_text('#FF2300')
        window.brightness.set_value(47)
        window.target_combo.set_selected(window.targets.index('wasd'))
        window.color_entry.set_text('#1234AA')
        window.target_combo.set_selected(window.targets.index('keyboard'))
        assert window.color_entry.get_text()=='#FF2300','Keyboard draft lost'
        assert window.brightness.get_value()==47,'Brightness draft lost'
        refresh_state()
        assert window.color_entry.get_text()=='#FF2300','Refresh discarded edits'
        window.effect_combo.set_selected(window.effect_ids.index(3))
        assert not window.color_entry.get_sensitive(),'Palette color still editable'
        assert 'independently' in window.effect_note.get_text()
        window.color_entry.set_text('invalid')
        window.capture_draft()
        window.drafts['keyboard'].request('keyboard')
        window.color_entry.set_text('#FF2300')
        assert not any(command.startswith('set_') for command,_ in client.commands),'Draft editing wrote hardware'
        editor=open_editor()
        editor.select_all()
        editor.paint()
        assert len(editor.colors)==len(editor.canvas.selected)
        editor.close()
        window.target_combo.set_selected(window.targets.index('wasd'))
        window.effect_combo.set_selected(window.effect_ids.index(3))
        assert window.color_entry.get_sensitive(),'WASD Wave color is incorrectly disabled'
        window.color_entry.set_text('#EE4400'); window.capture_draft()
        assert window.drafts['wasd'].request('wasd')[1]['color']=='ee4400'
        window.target_combo.set_selected(window.targets.index('keyboard'))
        window.effect_combo.set_selected(window.effect_ids.index(0))
        window.apply_lighting()
        assert window.pending,'Explicit apply was not scheduled'
        assert not window.light_group.get_sensitive(),'Editor remained active during apply'
        when(lambda:not window.pending and not window.status_pending,verify_apply)
        return False
    except Exception as error:
        failures.append(str(error)); print('FAIL:',error,file=sys.stderr,flush=True)
    app.window.close(); app.quit()
    return False

def verify_apply() -> bool:
    try:
        window=app.window
        assert not window.status_pending and window.status_button.get_sensitive()
        assert 'All checks passed' in (window.status_group.get_description() or '')
        assert all(indicator.get_icon_name()=='checkbox-checked-symbolic' for _,indicator in window.status_rows.values())
        assert not window.pending,'Apply did not finish'
        commands=[params for command,params in client.commands if command=='set_lighting']
        assert len(commands)==1 and commands[0]['color']=='ff2300'
        assert commands[0]['brightness']==47
        assert window.light_group.get_sensitive(),'Editor did not recover after apply'
        check_key_brightness()
        return False
    except Exception as error:
        failures.append(str(error)); print('FAIL:',error,file=sys.stderr,flush=True)
    app.window.close(); app.quit()
    return False

def check_key_brightness() -> None:
    saved: dict[str, JSON]={str(lamp.id):'112233' for lamp in layout()}
    for brightness in (None,0,20,100):
        state: dict[str, JSON]={'colors':saved.copy()}
        if brightness is not None: state['brightness']=brightness
        client.lighting['per_key']=state
        refresh_state()
        editor=open_editor()
        assert editor.brightness.get_value()==(80 if brightness is None else brightness),'Per-key brightness was reset'
        editor.close()
    client.lighting['per_key']={'colors':saved.copy(),'brightness':20}
    refresh_state()
    editor=open_editor()
    editor.canvas.select({layout()[0].id})
    editor.picker.set_rgba(color_rgba('445566')); editor.paint()
    editor.submit()
    assert not editor.apply_button.get_sensitive()
    when(editor.apply_button.get_sensitive,lambda:verify_key_brightness(editor))


def verify_key_brightness(editor: KeyEditor) -> bool:
    try:
        calls=[params for command,params in client.commands if command=='set_per_key']
        assert len(calls)==1 and calls[0]['brightness']==20,'Editing one key changed brightness'
        first=str(layout()[0].id)
        colors=mapping(calls[0]['colors'])
        assert colors[first]=='445566'
        assert all(color=='112233' for key,color in colors.items() if key!=first),'Unselected key colors changed'
        assert editor.apply_button.get_sensitive(),'Per-key Apply did not recover'
        editor.close(); editor=open_editor()
        assert editor.brightness.get_value()==20,'Saved brightness not restored after Apply'
        assert editor.colors[first]=='445566'
        editor.close()
        check_zones()
        return False
    except Exception as error:
        failures.append(str(error)); print('FAIL:',error,file=sys.stderr,flush=True)
    app.window.close(); app.quit()
    return False


def check_zones() -> None:
    window=app.window
    assert window.light_apply.get_visible() and not hasattr(window,'header_apply'),'Lighting has more than one Apply button'
    window.target_combo.set_selected(window.targets.index('keyboard'))
    window.effect_combo.set_selected(window.effect_ids.index(ZONE_MODE))
    assert all(row.get_visible() for row in window.zone_rows),'Zone colors hidden'
    assert not window.brightness_row.get_visible() and not window.color_row.get_visible(),'Zone mode shows effect controls'
    window.zone_buttons[1].set_rgba(color_rgba('102030'))
    window.apply_lighting()
    when(lambda:not window.pending,verify_zones)


def verify_zones() -> bool:
    try:
        window=app.window
        calls=[params for command,params in client.commands if command=='set_per_zone_mode']
        assert len(calls)==1 and calls[0]['zone2']=='102030','Zones were not applied'
        assert set(calls[0])=={'zone1','zone2','zone3','zone4'},'Zones sent extra settings'
        refresh_state()
        window.drafts.clear(); window.load_draft()
        assert window.effect_ids[window.effect_combo.get_selected()]==ZONE_MODE,'Saved zones not loaded'
        check_external_per_key()
        return False
    except Exception as error:
        failures.append(str(error)); print('FAIL:',error,file=sys.stderr,flush=True)
    app.window.close(); app.quit()
    return False


def check_external_per_key() -> None:
    window=app.window
    first=str(layout()[0].id)
    client.lighting['per_key']={'colors':{first:'abcdef'},'brightness':20}
    refresh_state()
    assert window.keyboard_canvas.colors[first]=='abcdef','Lighting preview ignored saved per-key colors'
    # A failed layout load reaches every waiting caller instead of leaving it waiting.
    loaded=window.layout; window.layout=None
    answer=client.answer
    def broken(command: str, params: dict[str, JSON]) -> JSON:
        if command=='get_keyboard_layout': raise OSError('keyboard unplugged')
        return answer(command,params)
    errors: list[str]=[]
    # The load runs on a worker, so the patch stays until verify_layout_failure removes it.
    patch.object(client,'answer',side_effect=broken).start()
    window.ensure_layout(lambda _:errors.append('loaded'),errors.append)
    when(lambda:bool(errors),lambda:verify_layout_failure(errors,loaded))


def verify_layout_failure(errors: list[str], loaded: list[Lamp] | None) -> bool:
    try:
        patch.stopall()
        app.window.layout=loaded
        assert errors==['keyboard unplugged'],'Layout failure was not reported: '+repr(errors)
        print('PASS: zones through the single Apply; per-key brightness/default/zero/apply round trip; status, credits, one-click profile and fan tiles, CPU limits, draft preservation, palette controls, external per-key colors, layout load failure, and no startup writes',flush=True)
    except Exception as error:
        failures.append(str(error)); print('FAIL:',error,file=sys.stderr,flush=True)
    app.window.close(); app.quit()
    return False


GLib.timeout_add(1200,start)
app.run([sys.argv[0]])
raise SystemExit(bool(failures))
