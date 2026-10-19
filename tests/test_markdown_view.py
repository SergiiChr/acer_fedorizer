# SPDX-License-Identifier: GPL-3.0-only
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET
from control_center.markdown_view import blocks, inline_markup


def markup_text(markup):
    return ''.join(ET.fromstring('<root>'+markup+'</root>').itertext())


class MarkdownTests(unittest.TestCase):
    def test_wrapped_lists_headings_and_table_structure(self):
        source='# Title\n\nA wrapped\nparagraph.\n\n- **Author**\n  attribution.\n\n## Libraries\n\n| Name | Terms |\n| --- | --- |\n| GTK | LGPL |\n'
        self.assertEqual(list(blocks(source)),[
            ('heading',1,'Title'),('paragraph','A wrapped paragraph.'),
            ('bullet','**Author** attribution.'),('heading',2,'Libraries'),
            ('table',[['Name','Terms'],['GTK','LGPL']])])

    def test_inline_formatting_links_escaping_and_url_punctuation(self):
        source='**A & B** uses `x < y` and *emphasis*. [Terms](https://example.com/?a=1&b=2). https://example.org/path.'
        markup=inline_markup(source)
        root=ET.fromstring('<root>'+markup+'</root>')
        self.assertEqual([a.attrib['href'] for a in root.findall('a')],
                         ['https://example.com/?a=1&b=2','https://example.org/path'])
        self.assertEqual(markup_text(markup),'A & B uses x < y and emphasis. Terms. https://example.org/path.')
        self.assertIn('<b>A &amp; B</b>',markup)
        self.assertIn('<tt>x &lt; y</tt>',markup)

    def test_source_markup_and_non_web_links_cannot_become_active(self):
        markup=inline_markup('<b>raw</b> [unsafe](javascript:alert) [local](file:///etc/passwd) `https://code.example`')
        root=ET.fromstring('<root>'+markup+'</root>')
        self.assertEqual(root.findall('a'),[])
        self.assertIn('<b>raw</b>',markup_text(markup))
        self.assertNotIn('<b>',markup)
        self.assertEqual(markup_text(inline_markup('https://[broken')), 'https://[broken')

    def test_real_notice_renders_all_blocks_from_single_source(self):
        source=(Path(__file__).resolve().parents[1]/'NOTICE.md').read_text()
        rendered=[]; tables=0
        for block in blocks(source):
            if block[0]=='table':
                tables+=1
                rendered.extend(markup_text(inline_markup(cell)) for row in block[1] for cell in row)
            else: rendered.append(markup_text(inline_markup(block[-1])))
        text='\n'.join(rendered)
        self.assertEqual(tables,1)
        for credit in ('PXDiv','0x7375646F','TensorRaya','Carlos Corbacho','E.M. Smith','Python Software Foundation License'):
            self.assertIn(credit,text)
        self.assertNotIn('**',text)
        self.assertNotIn('| --- |',text)
