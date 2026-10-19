# SPDX-License-Identifier: GPL-3.0-only
"""Render the Markdown used by NOTICE.md without generated copies or dependencies.

Supports headings, paragraphs, bullet lists, tables, code, emphasis, and web links.
Source text is escaped before passing it to Pango; raw HTML is never executed.
"""
import html
import re
from urllib.parse import urlsplit


INLINE=re.compile(r'(`[^`]+`|\*\*.+?\*\*|\[[^\]]+\]\([^\s]+\)|https?://[^\s<>]+|\*[^*]+\*)')


def inline_markup(text):
    parts=[]; offset=0
    for match in INLINE.finditer(text):
        parts.append(html.escape(text[offset:match.start()]))
        token=match.group(); offset=match.end()
        if token.startswith('`'):
            parts.append('<tt>'+html.escape(token[1:-1])+'</tt>')
        elif token.startswith('**'):
            parts.append('<b>'+inline_markup(token[2:-2])+'</b>')
        elif token.startswith('*'):
            parts.append('<i>'+html.escape(token[1:-1])+'</i>')
        else:
            if token.startswith('['):
                title,url=token[1:].split('](',1); url=url[:-1]; suffix=''
            else:
                url=token.rstrip('.,;:')
                while url.endswith(')') and url.count(')')>url.count('('): url=url[:-1]
                title=url; suffix=token[len(url):]
            try: parsed=urlsplit(url)
            except ValueError: parsed=urlsplit('')
            if parsed.scheme in ('https','http') and parsed.netloc:
                parts.append('<a href="'+html.escape(url,quote=True)+'">'+html.escape(title)+'</a>')
            else: parts.append(html.escape(title))
            parts.append(html.escape(suffix))
    parts.append(html.escape(text[offset:]))
    return ''.join(parts)


def blocks(source):
    """Yield semantic blocks; join wrapped Markdown lines into whole paragraphs."""
    lines=source.splitlines(); index=0
    while index<len(lines):
        line=lines[index].strip()
        if not line:
            index+=1; continue
        heading=re.match(r'^(#{1,6})\s+(.+)$',line)
        if heading:
            yield ('heading',len(heading[1]),heading[2]); index+=1; continue
        if line.startswith('|') and index+1<len(lines) and re.fullmatch(r'\s*\|(?:\s*:?-+:?\s*\|)+\s*',lines[index+1]):
            rows=[[cell.strip() for cell in line.strip('|').split('|')]]
            index+=2
            while index<len(lines) and lines[index].strip().startswith('|'):
                rows.append([cell.strip() for cell in lines[index].strip().strip('|').split('|')]); index+=1
            yield ('table',rows); continue
        bullet=re.match(r'^[-*]\s+(.+)$',line)
        content=[bullet[1] if bullet else line]; index+=1
        while index<len(lines):
            following=lines[index].strip()
            if not following or re.match(r'^(#{1,6}\s|[-*]\s|\|)',following): break
            content.append(following); index+=1
        yield ('bullet' if bullet else 'paragraph',' '.join(content))


def markdown_view(source):
    # GTK imports are local so formatting/escaping can be tested without a display.
    import gi
    gi.require_version('Gtk','4.0')
    from gi.repository import Gtk, Pango
    from .widgets import box

    def text(value, css=None):
        widget=Gtk.Label(xalign=0,wrap=True,wrap_mode=Pango.WrapMode.WORD_CHAR,
                         selectable=True,hexpand=True)
        widget.set_markup('<span line_height="1.25">'+inline_markup(value)+'</span>')
        if css: widget.add_css_class(css)
        return widget

    content=box(14); content.add_css_class('credits-content')
    for block in blocks(source):
        kind=block[0]
        if kind=='heading':
            content.append(text(block[2],'credits-title' if block[1]==1 else 'credits-heading'))
        elif kind=='table':
            grid=Gtk.Grid(column_spacing=18,row_spacing=0,hexpand=True)
            grid.add_css_class('credits-table')
            for row,cells in enumerate(block[1]):
                for col,cell in enumerate(cells):
                    widget=text(cell,'credits-table-header' if row==0 else 'credits-table-cell')
                    widget.set_valign(Gtk.Align.START)
                    if col==0: widget.set_size_request(140,-1); widget.set_hexpand(False)
                    grid.attach(widget,col,row,1,1)
            content.append(grid)
        elif kind=='bullet':
            row=box(10,True)
            marker=Gtk.Label(label='•',valign=Gtk.Align.START)
            marker.add_css_class('credits-bullet'); row.append(marker); row.append(text(block[1]))
            content.append(row)
        else: content.append(text(block[1]))
    return content
