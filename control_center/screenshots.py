# SPDX-License-Identifier: GPL-3.0-only
"""Render screenshots of our actual GTK windows with explicitly labelled preview data."""
from pathlib import Path
import gi
gi.require_version('Gtk','4.0')
from gi.repository import Gtk, GLib
from .app import PAGES


def save_window(window,path):
    paintable=Gtk.WidgetPaintable.new(window)
    snapshot=Gtk.Snapshot()
    paintable.snapshot(snapshot,window.get_width(),window.get_height())
    node=snapshot.to_node()
    if node is None: raise RuntimeError('Window has not been rendered')
    texture=window.get_renderer().render_texture(node,None)
    if not texture.save_to_png(str(path)): raise RuntimeError('Unable to save screenshot')


def invalidate(widget):
    # Rebuild cached text/child nodes before offscreen rendering each page.
    widget.queue_draw()
    child=widget.get_first_child()
    while child:
        invalidate(child)
        child=child.get_next_sibling()


def capture_pages(app,directory):
    directory=Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    names=[key for key,*_ in PAGES]+['keyboard','credits']
    def next_page(index=0):
        if index>=len(names):
            app.window.close(); app.quit(); return False
        name=names[index]
        app.window.set_default_size(1160,1120 if name=='lighting' else 900)
        if name=='keyboard': app.window.open_editor()
        elif name=='credits': app.window.show_credits()
        else: app.window.nav.select_row(app.window.nav_rows[name])
        target=app.window.editor if name=='keyboard' else app.window.credits_window if name=='credits' else app.window
        invalidate(target)
        def capture():
            try:
                save_window(target,directory/(name+'.png'))
                print(directory/(name+'.png'),flush=True)
                if name in ('keyboard','credits'): target.close()
            except Exception as error:
                app.capture_error=str(error)
                print('Screenshot failed:',error,flush=True)
                app.quit(); return False
            GLib.timeout_add(100,next_page,index+1)
            return False
        GLib.timeout_add(500,capture)
        return False
    next_page()
    return False
