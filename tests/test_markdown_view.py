# SPDX-License-Identifier: GPL-3.0-only
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from control_center.markdown_view import Bullet, Heading, Paragraph, Table, blocks, inline_markup


def markup_text(markup: str) -> str:
    return ''.join(ET.fromstring('<root>'+markup+'</root>').itertext())


class MarkdownTests(unittest.TestCase):
    def test_wrapped_lists_headings_and_table_structure(self) -> None:
        source='# Title\n\nA wrapped\nparagraph.\n\n- **Author**\n  attribution.\n\n## Libraries\n\n| Name | Terms |\n| --- | --- |\n| GTK | LGPL |\n'
        self.assertEqual(list(blocks(source)),[
            Heading(1,'Title'),Paragraph('A wrapped paragraph.'),
            Bullet('**Author** attribution.'),Heading(2,'Libraries'),
            Table([['Name','Terms'],['GTK','LGPL']])])

    def test_inline_formatting_links_escaping_and_url_punctuation(self) -> None:
        source='**A & B** uses `x < y` and *emphasis*. [Terms](https://example.com/?a=1&b=2). https://example.org/path.'
        markup=inline_markup(source)
        root=ET.fromstring('<root>'+markup+'</root>')
        self.assertEqual([a.attrib['href'] for a in root.findall('a')],
                         ['https://example.com/?a=1&b=2','https://example.org/path'])
        self.assertEqual(markup_text(markup),'A & B uses x < y and emphasis. Terms. https://example.org/path.')
        self.assertIn('<b>A &amp; B</b>',markup)
        self.assertIn('<tt>x &lt; y</tt>',markup)

    def test_source_markup_and_non_web_links_cannot_become_active(self) -> None:
        markup=inline_markup('<b>raw</b> [unsafe](javascript:alert) [local](file:///etc/passwd) `https://code.example`')
        root=ET.fromstring('<root>'+markup+'</root>')
        self.assertEqual(root.findall('a'),[])
        self.assertIn('<b>raw</b>',markup_text(markup))
        self.assertNotIn('<b>',markup)
        self.assertEqual(markup_text(inline_markup('https://[broken')), 'https://[broken')

    def test_real_notice_renders_all_blocks_from_single_source(self) -> None:
        source=(Path(__file__).resolve().parents[1]/'NOTICE.md').read_text()
        rendered: list[str]=[]; tables=0
        source_bullets=sum(bool(re.match(r'^[-*]\s+\S',line)) for line in source.splitlines())
        self.assertEqual(sum(isinstance(block,Bullet) for block in blocks(source)),source_bullets)
        for block in blocks(source):
            if isinstance(block,Table):
                tables+=1
                rendered.extend(markup_text(inline_markup(cell)) for row in block.rows for cell in row)
            else: rendered.append(markup_text(inline_markup(block.text)))
        text='\n'.join(rendered)
        self.assertEqual(tables,1)
        for credit in ('PXDiv','0x7375646F','TensorRaya','Carlos Corbacho','E.M. Smith','Python Software Foundation License'):
            self.assertIn(credit,text)
        self.assertNotIn('**',text)
        self.assertNotIn('| --- |',text)
