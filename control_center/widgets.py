# SPDX-License-Identifier: GPL-3.0-only
import math
import gi
gi.require_version('Gtk','4.0')
from gi.repository import Gtk, Gdk, Pango, PangoCairo
from .keyboard import keycaps


def label(text='', css=None, xalign=0):
    widget=Gtk.Label(label=text,xalign=xalign,wrap=True)
    if css: widget.add_css_class(css)
    if css in ('preview-badge','status-pill'):
        widget.set_wrap(False); widget.set_valign(Gtk.Align.CENTER)
    return widget


def box(spacing=12, horizontal=False):
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if horizontal else Gtk.Orientation.VERTICAL,spacing=spacing)


def color_rgba(hex_value):
    rgba=Gdk.RGBA()
    rgba.parse('#'+hex_value.lstrip('#'))
    return rgba


def hex_rgba(rgba):
    return ''.join(f'{round(max(0,min(1,v))*255):02x}' for v in (rgba.red,rgba.green,rgba.blue))


class ModeTiles(Gtk.FlowBox):
    """Single-selection icon tiles; selections remain drafts until explicitly applied."""
    def __init__(self, choices=(), changed=None):
        super().__init__(selection_mode=Gtk.SelectionMode.NONE,homogeneous=True,
                         min_children_per_line=1,max_children_per_line=5,
                         row_spacing=10,column_spacing=10)
        self.add_css_class('mode-selector')
        self.buttons=[]; self.checks=[]; self.selected=Gtk.INVALID_LIST_POSITION; self.changed=changed
        self.set_choices(choices)

    def set_choices(self, choices):
        while self.get_first_child(): self.remove(self.get_first_child())
        self.buttons=[]; self.checks=[]; self.selected=Gtk.INVALID_LIST_POSITION
        for index,(title,icon) in enumerate(choices):
            tile=Gtk.ToggleButton(hexpand=True)
            tile.add_css_class('mode-tile')
            tile.set_tooltip_text(title)
            tile.update_property([Gtk.AccessibleProperty.LABEL],[title])
            content=box(10); content.set_halign(Gtk.Align.CENTER); content.set_valign(Gtk.Align.CENTER)
            well=box(); well.add_css_class('mode-icon'); well.set_halign(Gtk.Align.CENTER)
            well.set_size_request(48,48)
            image=Gtk.Image.new_from_icon_name(icon); image.set_pixel_size(28)
            image.set_halign(Gtk.Align.CENTER); image.set_valign(Gtk.Align.CENTER); image.set_vexpand(True)
            well.append(image); content.append(well)
            caption=label(title,xalign=.5); caption.add_css_class('mode-caption'); content.append(caption)
            overlay=Gtk.Overlay(child=content)
            check=Gtk.Image.new_from_icon_name('object-select-symbolic'); check.set_pixel_size(14)
            check.add_css_class('mode-check'); check.set_halign(Gtk.Align.END); check.set_valign(Gtk.Align.START)
            overlay.add_overlay(check); self.checks.append(check)
            tile.set_child(overlay)
            tile.connect('clicked',lambda _,i=index:self.choose(i))
            self.buttons.append(tile); self.append(tile)
        if self.buttons: self.set_selected(0)

    def choose(self, index):
        self.set_selected(index)
        if self.changed: self.changed()

    def set_selected(self, index):
        self.selected=index if 0<=index<len(self.buttons) else Gtk.INVALID_LIST_POSITION
        for i,tile in enumerate(self.buttons):
            tile.set_active(i==self.selected)
            self.checks[i].set_opacity(1 if i==self.selected else 0)

    def get_selected(self):
        return self.selected


class HistoryChart(Gtk.DrawingArea):
    def __init__(self, color=(.36,.75,.74), height=90):
        super().__init__(content_height=height,hexpand=True)
        self.values=[]
        self.color=color
        self.set_draw_func(self.draw)
    def sample(self, value):
        self.values=(self.values+[value])[-60:]
        self.queue_draw()
    def draw(self, _, cr, width, height):
        cr.set_source_rgba(.55,.6,.65,.12)
        cr.set_line_width(1)
        for y in (height*.25,height*.5,height*.75):
            cr.move_to(0,y); cr.line_to(width,y)
        cr.stroke()
        if not any(v is not None for v in self.values): return
        values=self.values
        if len(values)==1: values=values*2
        points=[(i*width/max(1,len(values)-1), height-8-(max(0,min(100,v))/100)*(height-16)) if v is not None else None for i,v in enumerate(values)]
        for segment in self.segments(points):
            if len(segment)<2: continue
            cr.move_to(segment[0][0],height)
            for x,y in segment: cr.line_to(x,y)
            cr.line_to(segment[-1][0],height); cr.close_path()
            cr.set_source_rgba(*self.color,.12); cr.fill()
            cr.move_to(*segment[0])
            for point in segment[1:]: cr.line_to(*point)
            cr.set_source_rgba(*self.color,.95); cr.set_line_width(2); cr.stroke()
    @staticmethod
    def segments(points):
        result=[]; segment=[]
        for point in points:
            if point is None:
                if segment: result.append(segment); segment=[]
            else: segment.append(point)
        if segment: result.append(segment)
        return result


USAGES={4+i:chr(65+i) for i in range(26)}
USAGES.update({30+i:str((i+1)%10) for i in range(10)})
USAGES.update({40:'Enter',41:'Esc',42:'Back',43:'Tab',44:'Space',57:'Caps',79:'→',80:'←',81:'↓',82:'↑',224:'Ctrl',225:'Shift',226:'Alt',227:'Super',228:'Ctrl',229:'Shift',230:'Alt'})
USAGES.update({45:'−',46:'=',47:'[',48:']',49:'\\',51:';',52:"'",53:'`',54:',',55:'.',56:'/',70:'PrtSc',73:'Ins',76:'Del',83:'Num',84:'/',85:'×',86:'−',87:'+',88:'Enter',98:'0',99:'.',101:'Menu',114:'Mute'})
USAGES.update({89+i:str(i+1) for i in range(9)})
USAGES.update({58+i:'F'+str(i+1) for i in range(12)})


class KeyboardCanvas(Gtk.DrawingArea):
    def __init__(self, height=220):
        super().__init__(content_height=height,hexpand=True)
        self.lamps=[]; self.colors={}; self.selected=set(); self.rects=[]; self.on_selection=None
        self.set_draw_func(self.draw)
        click=Gtk.GestureClick()
        click.connect('pressed',self.clicked)
        self.add_controller(click)
        self.set_tooltip_text('Click keys to select them. LED geometry comes from the keyboard.')
    def set_layout(self, lamps, colors=None):
        self.lamps=lamps
        self.colors=colors or {}
        self.queue_draw()
    def draw(self, _, cr, width, height):
        self.rects=[]
        if not self.lamps:
            cr.set_source_rgba(.6,.65,.7,.8); cr.set_font_size(13)
            cr.move_to(24,height/2); cr.show_text('Keyboard layout is unavailable'); return
        caps=keycaps(self.lamps)
        minx=min(x for _,x,y,w,h in caps); miny=min(y for _,x,y,w,h in caps)
        spanx=max(x+w for _,x,y,w,h in caps)-minx
        spany=max(y+h for _,x,y,w,h in caps)-miny
        scale=min((width-36)/spanx,(height-30)/spany)
        ox=(width-spanx*scale)/2; oy=(height-spany*scale)/2
        self.rounded(cr,ox-10,oy-10,spanx*scale+20,spany*scale+20,12)
        cr.set_source_rgba(.035,.045,.055,.7); cr.fill()
        for lamp,kx,ky,kw,kh in caps:
            lid=lamp['id']; selected=lid in self.selected
            x=ox+(kx-minx)*scale; y=oy+(ky-miny)*scale
            w=kw*scale; h=kh*scale
            self.rects.append((x,y,w,h,lid))
            rgb=self.colors.get(str(lid),'4f9c9c')
            if isinstance(rgb,str): rgb=tuple(int(rgb[i:i+2],16)/255 for i in (0,2,4))
            else: rgb=tuple(v/255 for v in rgb)
            self.rounded(cr,x,y+2,w,h,4)
            cr.set_source_rgba(0,0,0,.65); cr.fill()
            self.rounded(cr,x,y,w,h,4)
            cr.set_source_rgb(.12,.14,.16); cr.fill()
            self.rounded(cr,x,y,w,h,4)
            cr.set_source_rgba(*rgb,.35 if selected else .13); cr.fill_preserve()
            cr.set_source_rgba(*rgb,1 if selected else .48); cr.set_line_width(2 if selected else 1); cr.stroke()
            text=lamp.get('label') or USAGES.get(lamp.get('key_usage'),'LED '+str(lid))
            layout=PangoCairo.create_layout(cr)
            layout.set_text(text,-1)
            layout.set_font_description(Pango.FontDescription.from_string('Sans '+str(min(9,max(5.5,w/max(1,len(text))*1.1)))))
            tw,th=layout.get_pixel_size()
            cr.set_source_rgba(.88,.93,.94,.95)
            cr.move_to(x+(w-tw)/2,y+(h-th)/2); PangoCairo.show_layout(cr,layout)
    @staticmethod
    def rounded(cr,x,y,w,h,r):
        cr.new_sub_path()
        for cx,cy,a,b in ((x+w-r,y+r,-90,0),(x+w-r,y+h-r,0,90),(x+r,y+h-r,90,180),(x+r,y+r,180,270)):
            cr.arc(cx,cy,r,math.radians(a),math.radians(b))
        cr.close_path()
    def clicked(self, _, count, x, y):
        for left,top,width,height,lid in self.rects:
            if left<=x<=left+width and top<=y<=top+height:
                self.selected.symmetric_difference_update({lid})
                self.queue_draw()
                if self.on_selection: self.on_selection(len(self.selected))
                break
