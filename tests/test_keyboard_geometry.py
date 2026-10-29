# SPDX-License-Identifier: GPL-3.0-only
import unittest

from control_center.keyboard import keycaps
from control_center.models import parse_lamps
from control_center.preview import layout


class KeyboardGeometryTests(unittest.TestCase):
    def test_measured_offsets_do_not_create_spurious_rows(self) -> None:
        lamps=parse_lamps(layout())
        caps=keycaps(lamps)
        rows={round(y+h/2,2) for lamp,x,y,w,h in caps if lamp.key_usage!=88}
        self.assertEqual(len(rows),6)
        self.assertEqual({lamp.id for lamp,*_ in caps},{lamp.id for lamp in lamps})
        space=next(c for c in caps if c[0].key_usage==44)
        letter=next(c for c in caps if c[0].key_usage==4)
        enter=next(c for c in caps if c[0].key_usage==88)
        self.assertGreater(space[3],letter[3]*4)
        self.assertGreater(enter[4],letter[4]*2)
        for i,(_,x,y,w,h) in enumerate(caps):
            for _,xx,yy,ww,hh in caps[i+1:]:
                self.assertFalse(x<xx+ww and xx<x+w and y<yy+hh and yy<y+h,
                                 'Key hit regions overlap')
