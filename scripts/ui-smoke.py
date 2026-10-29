#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise actual GTK widgets with preview services; no hardware access."""
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gi.repository import GLib

from control_center.app import Application
from control_center.models import ZONE_MODE, Settings
from control_center.widgets import color_rgba

app=Application(demo=True)
failures=[]

def when(ready: Callable[[], bool], verify: Callable[[], bool], timeout: float = 5) -> None:
    """Run verify once ready() is true or the timeout passes, so slow async applies do not fail at random."""
    deadline=time.monotonic()+timeout
    def poll() -> bool:
        if ready() or time.monotonic()>deadline:
            verify(); return False
        return True
    GLib.timeout_add(50,poll)

def checks() -> bool:
    try:
        window=app.window
        assert not any(command.startswith('set_') for command,_ in window.client.commands),'Startup wrote a setting'
        for name in window.nav_rows:
            window.nav.select_row(window.nav_rows[name])
            assert window.stack.get_visible_child_name()==name
        # Exercise actual tile clicks, including re-click and refresh of an unapplied draft.
        submitted=[]
        mutate=window.mutate
        window.mutate=lambda command,params:submitted.append((command,params))
        expected=[('Eco','low-power'),('Quiet','quiet'),('Balanced','balanced'),
                  ('Performance','balanced-performance'),('Turbo','performance')]
        for name,profile in expected:
            index=window.profile_choices.index(profile)
            tile=window.profile_tiles.buttons[index]
            assert tile.get_tooltip_text()==name
            tile.emit('clicked'); tile.emit('clicked')
            assert tile.get_active() and sum(b.get_active() for b in window.profile_tiles.buttons)==1
            window.receive_state(Settings.parse(window.client.command('get_all_settings')))
            assert window.profile_tiles.get_selected()==index,'Refresh discarded profile selection'
            window.apply_profile()
            assert submitted[-1]==('set_thermal_profile',{'profile':profile})
        window.mutate=mutate
        for index in (2,0,1,2,2):
            window.fan_mode.buttons[index].emit('clicked')
            assert sum(b.get_active() for b in window.fan_mode.buttons)==1
            assert window.cpu_slider.get_sensitive()==(index==2)
            assert window.gpu_slider.get_sensitive()==(index==2)
        credits_window=window.show_credits()
        def descendants(widget):
            yield widget
            child=widget.get_first_child()
            while child:
                yield from descendants(child)
                child=child.get_next_sibling()
        from gi.repository import Gtk
        credits=[widget for widget in descendants(credits_window) if isinstance(widget,Gtk.Label)]
        rendered='\n'.join(widget.get_text() for widget in credits)
        assert 'Licenses, attribution, and distribution' in rendered
        assert 'Div Acer Manager Max — PXDiv and its contributors.' in rendered
        assert 'GNU LGPL 2.1 or later;' in rendered,'License table missing'
        assert '**' not in rendered and '[OpenRGB issue' not in rendered,'Raw Markdown visible'
        assert any('<a href=' in widget.get_label() for widget in credits),'Links not rendered'
        credits_window.close()
        window.profile_tiles.set_selected(window.profile_choices.index('balanced'))
        window.fan_mode.choose(0)
        window.installation_failed('Timed out')
        assert 'failed' in window.status_group.get_description()
        assert all('Not checked' in row.get_subtitle() for row,_ in window.status_rows.values())
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
        window.receive_state(Settings.parse(window.client.command('get_all_settings')))
        assert window.color_entry.get_text()=='#FF2300','Refresh discarded edits'
        window.effect_combo.set_selected(window.effect_ids.index(3))
        assert not window.color_entry.get_sensitive(),'Palette color still editable'
        assert 'independently' in window.effect_note.get_text()
        window.color_entry.set_text('invalid')
        window.capture_draft()
        window.drafts['keyboard'].request('keyboard')
        window.color_entry.set_text('#FF2300')
        assert not any(command.startswith('set_') for command,_ in window.client.commands),'Draft editing wrote hardware'
        window.open_editor()
        window.editor.select_all()
        window.editor.paint()
        assert len(window.editor.colors)==len(window.editor.canvas.selected)
        window.editor.close()
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
        assert 'All checks passed' in window.status_group.get_description()
        assert all(indicator.get_icon_name()=='checkbox-checked-symbolic' for _,indicator in window.status_rows.values())
        assert not window.pending,'Apply did not finish'
        commands=[params for command,params in window.client.commands if command=='set_lighting']
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
    window=app.window
    saved={str(lamp.id):'112233' for lamp in window.layout}
    for brightness in (None,0,20,100):
        state={'colors':saved.copy()}
        if brightness is not None: state['brightness']=brightness
        window.client.lighting['per_key']=state
        window.receive_state(Settings.parse(window.client.command('get_all_settings')))
        window.open_editor()
        assert window.editor.brightness.get_value()==(80 if brightness is None else brightness),'Per-key brightness was reset'
        window.editor.close()
    window.client.lighting['per_key']={'colors':saved.copy(),'brightness':20}
    window.receive_state(Settings.parse(window.client.command('get_all_settings')))
    window.open_editor()
    window.editor.canvas.selected={window.layout[0].id}
    window.editor.picker.set_rgba(color_rgba('445566')); window.editor.paint()
    window.editor.submit()
    assert not window.editor.apply.get_sensitive()
    when(window.editor.apply.get_sensitive,verify_key_brightness)


def verify_key_brightness() -> bool:
    try:
        window=app.window
        calls=[params for command,params in window.client.commands if command=='set_per_key']
        assert len(calls)==1 and calls[0]['brightness']==20,'Editing one key changed brightness'
        first=str(window.layout[0].id)
        assert calls[0]['colors'][first]=='445566'
        assert all(color=='112233' for key,color in calls[0]['colors'].items() if key!=first),'Unselected key colors changed'
        assert window.editor.apply.get_sensitive(),'Per-key Apply did not recover'
        window.editor.close(); window.open_editor()
        assert window.editor.brightness.get_value()==20,'Saved brightness not restored after Apply'
        assert window.editor.colors[first]=='445566'
        window.editor.close()
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
        calls=[params for command,params in window.client.commands if command=='set_per_zone_mode']
        assert len(calls)==1 and calls[0]['zone2']=='102030','Zones were not applied'
        assert set(calls[0])=={'zone1','zone2','zone3','zone4'},'Zones sent extra settings'
        window.receive_state(Settings.parse(window.client.command('get_all_settings')))
        window.drafts.clear(); window.load_draft()
        assert window.effect_ids[window.effect_combo.get_selected()]==ZONE_MODE,'Saved zones not loaded'
        print('PASS: zones through the single Apply; per-key brightness/default/zero/apply round trip; status, credits, profile mappings, mode tiles, draft preservation, palette controls, and no startup writes',flush=True)
    except Exception as error:
        failures.append(str(error)); print('FAIL:',error,file=sys.stderr,flush=True)
    app.window.close(); app.quit()
    return False


GLib.timeout_add(1200,checks)
app.run([sys.argv[0]])
raise SystemExit(bool(failures))
