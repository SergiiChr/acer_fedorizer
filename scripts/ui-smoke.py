#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Exercise actual GTK widgets with preview services; no hardware access."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from control_center.app import Application
from gi.repository import GLib

app=Application(demo=True)
failures=[]

def checks():
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
            window.receive_state(window.client.command('get_all_settings'),None)
            assert window.profile_tiles.get_selected()==index,'Refresh discarded profile selection'
            window.apply_profile()
            assert submitted[-1]==('set_thermal_profile',{'profile':profile})
        window.mutate=mutate
        for index in (2,0,1,2,2):
            window.fan_mode.buttons[index].emit('clicked')
            assert sum(b.get_active() for b in window.fan_mode.buttons)==1
            assert window.cpu_slider.get_sensitive()==(index==2)
            assert window.gpu_slider.get_sensitive()==(index==2)
        window.show_credits()
        def descendants(widget):
            yield widget
            child=widget.get_first_child()
            while child:
                yield from descendants(child)
                child=child.get_next_sibling()
        from gi.repository import Gtk
        credits=[widget for widget in descendants(window.credits_window) if isinstance(widget,Gtk.Label)]
        rendered='\n'.join(widget.get_text() for widget in credits)
        assert 'Licenses, attribution, and distribution' in rendered
        assert 'Div Acer Manager Max — PXDiv and its contributors.' in rendered
        assert 'GNU LGPL 2.1 or later;' in rendered,'License table missing'
        assert '**' not in rendered and '[OpenRGB issue' not in rendered,'Raw Markdown visible'
        assert any('<a href=' in widget.get_label() for widget in credits),'Links not rendered'
        window.credits_window.close()
        window.profile_tiles.set_selected(window.profile_choices.index('balanced'))
        window.fan_mode.choose(0)
        window.nav.select_row(window.nav_rows['lighting'])
        window.color_entry.set_text('#FF2300')
        window.brightness.set_value(47)
        window.target_combo.set_selected(window.targets.index('wasd'))
        window.color_entry.set_text('#1234AA')
        window.target_combo.set_selected(window.targets.index('keyboard'))
        assert window.color_entry.get_text()=='#FF2300','Keyboard draft lost'
        assert window.brightness.get_value()==47,'Brightness draft lost'
        window.receive_state(window.client.command('get_all_settings'),None)
        assert window.color_entry.get_text()=='#FF2300','Refresh discarded edits'
        window.effect_combo.set_selected(window.effect_ids.index(3))
        assert not window.color_entry.get_sensitive(),'Palette color still editable'
        assert 'independently' in window.effect_note.get_text()
        window.color_entry.set_text('invalid')
        window.capture_draft()
        window.drafts['keyboard'].params('keyboard')
        window.color_entry.set_text('#FF2300')
        assert not any(command.startswith('set_') for command,_ in window.client.commands),'Draft editing wrote hardware'
        window.open_editor()
        window.editor.select_all()
        window.editor.paint()
        assert len(window.editor.colors)==len(window.editor.canvas.selected)
        window.editor.close()
        window.effect_combo.set_selected(window.effect_ids.index(0))
        window.apply_lighting()
        assert window.pending,'Explicit apply was not scheduled'
        assert not window.light_group.get_sensitive(),'Editor remained active during apply'
        GLib.timeout_add(250,verify_apply)
        return False
    except Exception as error:
        failures.append(str(error)); print('FAIL:',error,file=sys.stderr,flush=True)
    app.window.close(); app.quit()
    return False

def verify_apply():
    try:
        window=app.window
        assert not window.pending,'Apply did not finish'
        commands=[params for command,params in window.client.commands if command=='set_lighting']
        assert len(commands)==1 and commands[0]['color']=='ff2300'
        assert commands[0]['brightness']==47
        assert window.light_group.get_sensitive(),'Editor did not recover after apply'
        print('PASS: rendered credits and clickable links, profile names and hardware mappings, exclusive mode tiles, fan sensitivity, real GTK pages, independent drafts, refresh preservation, palette controls, keyboard editor, no startup writes, and explicit async apply',flush=True)
    except Exception as error:
        failures.append(str(error)); print('FAIL:',error,file=sys.stderr,flush=True)
    app.window.close(); app.quit()
    return False

GLib.timeout_add(1200,checks)
app.run([sys.argv[0]])
raise SystemExit(bool(failures))
