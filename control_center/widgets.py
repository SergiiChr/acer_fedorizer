# SPDX-License-Identifier: GPL-3.0-only
import itertools
import math
import time
from collections.abc import Callable, Iterable, Mapping, Sequence

import cairo
import gi

gi.require_version('Gtk','4.0')
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo

from .keyboard import keycaps
from .models import CoreKind, Lamp
from .telemetry import Core


def label(text: str = '', css: str | None = None, xalign: float = 0) -> Gtk.Label:
    widget=Gtk.Label(label=text,xalign=xalign,wrap=True)
    if css: widget.add_css_class(css)
    if css in ('preview-badge','status-pill'):
        widget.set_wrap(False); widget.set_valign(Gtk.Align.CENTER)
    return widget


def box(spacing: int = 12, horizontal: bool = False) -> Gtk.Box:
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if horizontal else Gtk.Orientation.VERTICAL,spacing=spacing)


def color_rgba(hex_value: str) -> Gdk.RGBA:
    rgba=Gdk.RGBA()
    rgba.parse('#'+hex_value.lstrip('#'))
    return rgba


def hex_rgba(rgba: Gdk.RGBA) -> str:
    return ''.join(f'{round(max(0,min(1,v))*255):02x}' for v in (rgba.red,rgba.green,rgba.blue))


def legend_markup(parts: Iterable[tuple[tuple[float, float, float], str]]) -> str:
    """Pango markup listing each text after a dot in its series color."""
    return '    '.join(f'<span foreground="#{"".join(f"{round(v*255):02x}" for v in color)}">●</span> {GLib.markup_escape_text(text)}'
                       for color,text in parts)


class ModeTiles(Gtk.FlowBox):
    """Single-selection icon tiles; changed() runs after every click."""
    def __init__(self, choices: Sequence[tuple[str, str]] = (), changed: Callable[[], None] | None = None) -> None:
        super().__init__(selection_mode=Gtk.SelectionMode.NONE,homogeneous=True,
                         min_children_per_line=1,max_children_per_line=5,
                         row_spacing=10,column_spacing=10)
        self.add_css_class('mode-selector')
        self.buttons: list[Gtk.ToggleButton]=[]; self.checks: list[Gtk.Image]=[]
        self.selected=Gtk.INVALID_LIST_POSITION; self.changed=changed
        self.set_choices(choices)

    def set_choices(self, choices: Sequence[tuple[str, str]]) -> None:
        while child:=self.get_first_child(): self.remove(child)
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

    def choose(self, index: int) -> None:
        self.set_selected(index)
        if self.changed: self.changed()

    def set_selected(self, index: int) -> None:
        self.selected=index if 0<=index<len(self.buttons) else Gtk.INVALID_LIST_POSITION
        for i,tile in enumerate(self.buttons):
            tile.set_active(i==self.selected)
            self.checks[i].set_opacity(1 if i==self.selected else 0)

    def get_selected(self) -> int:
        return self.selected


ACCENT=(.36,.75,.74)
GRID_COLOR=(.55,.6,.65,.12)
CPU_COLOR=(.36,.60,.96)
GPU_COLOR=(.38,.78,.45)
AVERAGE_COLOR=(.90,.71,.40)
TEXT_COLOR=(.6,.65,.7,.9)
# Samples kept in each chart; at the two-second poll this is the last two minutes.
HISTORY=60
# Vertical pixels each gridline step needs so axis labels never crowd.
GRID_SPACING=24
MAX_GRID_STEPS=5
SCALE_STEPS=(1,2,5)


def axis(top: float | None, peak: float, steps: int) -> tuple[float, float]:
    """Axis top and gridline step that split zero to top into at most `steps` equal whole-number parts.
    A fixed top uses as many parts as fit; without one, the top is the smallest 1, 2, or 5 × 10ⁿ multiple above peak.
    """
    if top is not None:
        return top,next((top/n for n in range(steps,1,-1) if (top/n).is_integer()),top)
    for step in (m*10**k for k in itertools.count() for m in SCALE_STEPS):
        if (count:=max(1,math.ceil(peak/step)))<=steps: return count*step,step
    raise AssertionError('unreachable')


class LineChart(Gtk.DrawingArea):
    """Recent samples of several series on one shared axis; hovering shows each series' value next to its point."""
    def __init__(self, colors: Sequence[tuple[float, float, float]], unit: str, digits: int = 0,
                 top: float | None = None, height: int = 150) -> None:
        super().__init__(content_height=height,hexpand=True)
        self.colors=colors; self.unit=unit; self.digits=digits; self.top=top
        self.values: list[tuple[float | None, ...]]=[]
        self.pointer: float | None=None
        motion=Gtk.EventControllerMotion()
        motion.connect('motion',self.moved); motion.connect('leave',self.left)
        self.add_controller(motion)
        self.set_draw_func(self.draw)
    def sample(self, values: Sequence[float | None]) -> None:
        """Add one value per series; None leaves a gap in that series' line."""
        self.values=[*self.values,tuple(values)][-HISTORY:]
        self.queue_draw()
    def moved(self, _: Gtk.EventControllerMotion, x: float, __: float) -> None:
        self.pointer=x; self.queue_draw()
    def left(self, _: Gtk.EventControllerMotion) -> None:
        self.pointer=None; self.queue_draw()
    def draw(self, _: Gtk.DrawingArea, cr: 'cairo.Context[cairo.Surface]', width: int, height: int) -> None:
        cr.set_font_size(11)
        above,below=10,6
        plot=height-above-below
        peak=max((v for row in self.values for v in row if v is not None),default=0)
        top,step=axis(self.top,peak,max(1,min(MAX_GRID_STEPS,plot//GRID_SPACING)))
        marks=[step*i for i in range(round(top/step)+1)]
        texts=[f'{mark:g}'+(self.unit if mark==marks[-1] else '') for mark in marks]
        left=max(cr.text_extents(text).x_advance for text in texts)+10
        def y(value: float) -> float: return above+plot*(1-max(0,min(value,top))/top)
        for mark,text in zip(marks,texts,strict=True):
            cr.set_source_rgba(*GRID_COLOR); cr.set_line_width(1)
            cr.move_to(left,y(mark)); cr.line_to(width,y(mark)); cr.stroke()
            cr.set_source_rgba(*TEXT_COLOR); cr.move_to(left-6-cr.text_extents(text).x_advance,y(mark)+4); cr.show_text(text)
        rows=self.values*2 if len(self.values)==1 else self.values
        if not rows: return
        def x(index: int) -> float: return left+index*(width-left)/max(1,len(rows)-1)
        for series,color in enumerate(self.colors):
            points=[(x(i),y(v)) if (v:=row[series]) is not None else None for i,row in enumerate(rows)]
            for present,group in itertools.groupby(points,key=lambda point:point is not None):
                segment=[point for point in group if point is not None]
                if not present or len(segment)<2: continue
                cr.move_to(segment[0][0],y(0))
                for point in segment: cr.line_to(*point)
                cr.line_to(segment[-1][0],y(0)); cr.close_path()
                cr.set_source_rgba(*color,.05); cr.fill()
                cr.move_to(*segment[0])
                for point in segment[1:]: cr.line_to(*point)
                cr.set_source_rgba(*color,.95); cr.set_line_width(1); cr.stroke()
        if self.pointer is None or self.pointer<left: return
        index=round((self.pointer-left)/(width-left)*(len(rows)-1))
        hovered=sorted(((y(v),v,color) for v,color in zip(rows[index],self.colors,strict=True) if v is not None),key=lambda item:item[0])
        if not hovered: return
        px=x(index)
        cr.set_source_rgba(*TEXT_COLOR[:3],.35); cr.set_line_width(1)
        cr.move_to(px,above); cr.line_to(px,y(0)); cr.stroke()
        # Labels sit beside their points, nudged apart so close values stay readable.
        label_y=-math.inf
        for point_y,value,color in hovered:
            cr.set_source_rgba(*color,1); cr.arc(px,point_y,2.5,0,2*math.pi); cr.fill()
            text=f'{value:.{self.digits}f}{self.unit}'
            extents=cr.text_extents(text)
            label_y=min(max(point_y+4,label_y+15,above+8),height-2)
            tx=px+9 if px+9+extents.x_advance+4<=width else px-9-extents.x_advance
            cr.set_source_rgba(.08,.09,.1,.8); KeyboardCanvas.rounded(cr,tx-4,label_y-11,extents.x_advance+8,15,4); cr.fill()
            cr.set_source_rgba(*color,1); cr.move_to(tx,label_y); cr.show_text(text)


# Cores of a CPU without core types use the performance color.
CORE_COLORS: dict[CoreKind | None, tuple[float, float, float]]={CoreKind.PERFORMANCE:ACCENT,CoreKind.EFFICIENCY:(.64,.57,.88)}
AVERAGE_SECONDS=10


class CoreBars(Gtk.DrawingArea):
    """One bar per physical core: a narrow bar for the current frequency in front of a wide bar for its AVERAGE_SECONDS average.
    Dashed lines show each core type's frequency cap.
    """
    def __init__(self, height: int = 240) -> None:
        super().__init__(content_height=height,hexpand=True)
        self.cores: list[Core]=[]; self.averages: list[float]=[]; self.history: list[tuple[float, list[float]]]=[]
        self.limits: Mapping[CoreKind, float]={}; self.top=1
        self.set_draw_func(self.draw)
    def sample(self, cores: list[Core], limits: Mapping[CoreKind, float], top: float) -> None:
        """Add a sample; limits maps core types to caps in GHz, and the axis runs from zero to at least top GHz."""
        now=time.monotonic(); values=[core.ghz for core in cores]
        self.history=[(t,v) for t,v in self.history if now-t<AVERAGE_SECONDS and len(v)==len(values)]+[(now,values)]
        self.averages=[sum(column)/len(column) for column in zip(*(v for _,v in self.history),strict=True)]
        self.cores,self.limits=cores,limits
        self.top=max(1,math.ceil(max([top,*values])))
        self.queue_draw()
    def draw(self, _: Gtk.DrawingArea, cr: 'cairo.Context[cairo.Surface]', width: int, height: int) -> None:
        cr.set_font_size(11)
        if not self.cores: return
        left,top,bottom=34,30,height-20
        def y(ghz: float) -> float: return bottom-(bottom-top)*max(0,min(ghz,self.top))/self.top
        for mark in range(self.top+1):
            cr.set_source_rgba(*GRID_COLOR); cr.set_line_width(1)
            cr.move_to(left,y(mark)); cr.line_to(width,y(mark)); cr.stroke()
            cr.set_source_rgba(*TEXT_COLOR); cr.move_to(4,y(mark)+4); cr.show_text(f'{mark} GHz' if mark==self.top else str(mark))
        slot=(width-left)/len(self.cores)
        counts: dict[CoreKind | None, int]={}
        for i,(core,average) in enumerate(zip(self.cores,self.averages,strict=True)):
            x=left+i*slot
            cr.set_source_rgba(*AVERAGE_COLOR,.45); cr.rectangle(x+slot*.12,y(average),slot*.76,bottom-y(average)); cr.fill()
            cr.set_source_rgba(*CORE_COLORS.get(core.kind,ACCENT),.95)
            cr.rectangle(x+slot*.32,y(core.ghz),slot*.36,bottom-y(core.ghz)); cr.fill()
            counts[core.kind]=counts.get(core.kind,0)+1
            if slot>=18:
                name=('E' if core.kind==CoreKind.EFFICIENCY else 'P')+str(counts[core.kind])
                extents=cr.text_extents(name)
                cr.set_source_rgba(*TEXT_COLOR); cr.move_to(x+(slot-extents.width)/2,height-4); cr.show_text(name)
        for kind,ghz in self.limits.items():
            indexes=[i for i,core in enumerate(self.cores) if core.kind==kind]
            if not indexes: continue
            start,end=left+indexes[0]*slot,left+(indexes[-1]+1)*slot
            cr.set_source_rgba(*CORE_COLORS[kind],.9); cr.set_line_width(1.5); cr.set_dash([5,4])
            cr.move_to(start,y(ghz)); cr.line_to(end,y(ghz)); cr.stroke(); cr.set_dash([])
            text=f'Cap {ghz:.1f} GHz'
            cr.move_to(end-cr.text_extents(text).width-4,y(ghz)-5); cr.show_text(text)
        legend: float=left
        for color,text in ((CORE_COLORS[CoreKind.PERFORMANCE],'Performance core now'),(CORE_COLORS[CoreKind.EFFICIENCY],'Efficiency core now'),
                           (AVERAGE_COLOR,f'Average, last {AVERAGE_SECONDS} s')):
            cr.set_source_rgba(*color,.95); cr.rectangle(legend,6,10,10); cr.fill()
            cr.set_source_rgba(*TEXT_COLOR); cr.move_to(legend+15,15); cr.show_text(text)
            legend+=cr.text_extents(text).x_advance+36


USAGES={4+i:chr(65+i) for i in range(26)}
USAGES.update({30+i:str((i+1)%10) for i in range(10)})
USAGES.update({40:'Enter',41:'Esc',42:'Back',43:'Tab',44:'Space',57:'Caps',79:'→',80:'←',81:'↓',82:'↑',224:'Ctrl',225:'Shift',226:'Alt',227:'Super',228:'Ctrl',229:'Shift',230:'Alt'})
USAGES.update({45:'−',46:'=',47:'[',48:']',49:'\\',51:';',52:"'",53:'`',54:',',55:'.',56:'/',70:'PrtSc',73:'Ins',76:'Del',83:'Num',84:'/',85:'×',86:'−',87:'+',88:'Enter',98:'0',99:'.',101:'Menu',114:'Mute'})
USAGES.update({89+i:str(i+1) for i in range(9)})
USAGES.update({58+i:'F'+str(i+1) for i in range(12)})


class KeyboardCanvas(Gtk.DrawingArea):
    """Keyboard preview drawn from HID lamp geometry; keys are clickable when on_selection is given."""
    def __init__(self, height: int = 220, on_selection: Callable[[int], None] | None = None) -> None:
        super().__init__(content_height=height,hexpand=True)
        self.caps: list[tuple[Lamp, float, float, float, float]]=[]; self.colors: dict[str, str]={}
        self.selected: frozenset[int]=frozenset(); self.rects: list[tuple[float, float, float, float, int]]=[]
        self.on_selection=on_selection
        self.set_draw_func(self.draw)
        if on_selection:
            click=Gtk.GestureClick()
            click.connect('pressed',self.clicked)
            self.add_controller(click)
            self.set_tooltip_text('Click keys to select them. LED geometry comes from the keyboard.')
    def set_layout(self, lamps: list[Lamp], colors: dict[str, str]) -> None:
        # Keycap geometry depends only on the lamps, so it is computed once rather than on every redraw.
        self.caps=keycaps(lamps)
        self.set_colors(colors)
    def set_colors(self, colors: dict[str, str]) -> None:
        self.colors=colors
        self.queue_draw()
    def select(self, ids: Iterable[int]) -> None:
        """Replace the selection and report its size to on_selection."""
        self.selected=frozenset(ids)
        self.queue_draw()
        if self.on_selection: self.on_selection(len(self.selected))
    def draw(self, _: Gtk.DrawingArea, cr: 'cairo.Context[cairo.Surface]', width: int, height: int) -> None:
        self.rects=[]
        if not self.caps:
            cr.set_source_rgba(.6,.65,.7,.8); cr.set_font_size(13)
            cr.move_to(24,height/2); cr.show_text('Keyboard layout is unavailable'); return
        caps=self.caps
        minx=min(x for _,x,y,w,h in caps); miny=min(y for _,x,y,w,h in caps)
        spanx=max(x+w for _,x,y,w,h in caps)-minx
        spany=max(y+h for _,x,y,w,h in caps)-miny
        scale=min((width-36)/spanx,(height-30)/spany)
        ox=(width-spanx*scale)/2; oy=(height-spany*scale)/2
        self.rounded(cr,ox-10,oy-10,spanx*scale+20,spany*scale+20,12)
        cr.set_source_rgba(.035,.045,.055,.7); cr.fill()
        layout=PangoCairo.create_layout(cr)
        for lamp,kx,ky,kw,kh in caps:
            lid=lamp.id; selected=lid in self.selected
            x=ox+(kx-minx)*scale; y=oy+(ky-miny)*scale
            w=kw*scale; h=kh*scale
            self.rects.append((x,y,w,h,lid))
            color=self.colors.get(str(lid),'4f9c9c')
            r,g,b=(channel/255 for channel in bytes.fromhex(color))
            self.rounded(cr,x,y+2,w,h,4)
            cr.set_source_rgba(0,0,0,.65); cr.fill()
            self.rounded(cr,x,y,w,h,4)
            cr.set_source_rgb(.12,.14,.16); cr.fill()
            self.rounded(cr,x,y,w,h,4)
            cr.set_source_rgba(r,g,b,.35 if selected else .13); cr.fill_preserve()
            cr.set_source_rgba(r,g,b,1 if selected else .48); cr.set_line_width(2 if selected else 1); cr.stroke()
            text=USAGES.get(lamp.key_usage,'LED '+str(lid))
            layout.set_text(text,-1)
            layout.set_font_description(Pango.FontDescription.from_string('Sans '+str(min(9,max(5.5,w/max(1,len(text))*1.1)))))
            tw,th=layout.get_pixel_size()
            cr.set_source_rgba(.88,.93,.94,.95)
            cr.move_to(x+(w-tw)/2,y+(h-th)/2); PangoCairo.show_layout(cr,layout)
    @staticmethod
    def rounded(cr: 'cairo.Context[cairo.Surface]', x: float, y: float, w: float, h: float, r: float) -> None:
        cr.new_sub_path()
        for cx,cy,a,b in ((x+w-r,y+r,-90,0),(x+w-r,y+h-r,0,90),(x+r,y+h-r,90,180),(x+r,y+r,180,270)):
            cr.arc(cx,cy,r,math.radians(a),math.radians(b))
        cr.close_path()
    def clicked(self, _: Gtk.GestureClick, count: int, x: float, y: float) -> None:
        for left,top,width,height,lid in self.rects:
            if left<=x<=left+width and top<=y<=top+height:
                self.select(self.selected^{lid})
                break
