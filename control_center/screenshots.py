# SPDX-License-Identifier: GPL-3.0-only
"""Render screenshots of our actual GTK windows with explicitly labelled preview data."""
from pathlib import Path

import gi

gi.require_version('Gtk','4.0')
from gi.repository import GLib, Gtk

from .app import PAGES, Application


def save_window(window: Gtk.Window, path: str | Path) -> None:
    paintable=Gtk.WidgetPaintable.new(window)
    snapshot=Gtk.Snapshot()
    paintable.snapshot(snapshot,window.get_width(),window.get_height())
    node=snapshot.to_node()
    if node is None: raise RuntimeError('Window has not been rendered')
    renderer=window.get_renderer()
    if renderer is None: raise RuntimeError('Window has no renderer')
    texture=renderer.render_texture(node,None)
    if not texture.save_to_png(str(path)): raise RuntimeError('Unable to save screenshot')


def invalidate(widget: Gtk.Widget) -> None:
    # Rebuild cached text/child nodes before offscreen rendering each page.
    widget.queue_draw()
    child=widget.get_first_child()
    while child:
        invalidate(child)
        child=child.get_next_sibling()


def capture_pages(app: Application, directory: str | Path) -> bool:
    directory=Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    names=[key for key,*_ in PAGES]+['keyboard','credits']
    def next_page(index: int = 0) -> bool:
        if index>=len(names):
            app.window.close(); app.quit(); return False
        name=names[index]
        app.window.set_default_size(1160,1120 if name=='lighting' else 900)
        target: Gtk.Window | None
        if name=='keyboard': target=app.window.open_editor()
        elif name=='credits': target=app.window.show_credits()
        else: app.window.show_page(name); target=app.window
        if target: invalidate(target)
        def capture(attempts: int = 50) -> bool:
            # The lighting page loads the keyboard layout asynchronously; the keyboard editor needs it too.
            if name=='lighting' and app.window.layout is None and attempts:
                GLib.timeout_add(100,capture,attempts-1); return False
            try:
                if target is None: raise RuntimeError('Keyboard layout is not loaded')
                save_window(target,directory/(name+'.png'))
                print(directory/(name+'.png'),flush=True)
                if name in ('keyboard','credits'): target.close()
            except Exception as error:  # noqa: BLE001 - any capture failure must end the run.
                app.capture_error=str(error)
                print('Screenshot failed:',error,flush=True)
                app.quit(); return False
            GLib.timeout_add(100,next_page,index+1)
            return False
        GLib.timeout_add(500,capture)
        return False
    next_page()
    return False
