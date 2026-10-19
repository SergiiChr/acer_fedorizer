# SPDX-License-Identifier: GPL-3.0-only
"""Keycap geometry from HID LED centers; never changes lamp identities/bindings."""
from statistics import median


def keycaps(lamps):
    if not lamps:
        return []
    # Letter/digit spacing is stable even when LED positions have tiny offsets.
    letters=sorted((l for l in lamps if 4 <= l.get('key_usage',0) <= 39),key=lambda l:l['y'])
    # Use nearest horizontal neighbors, not every pairwise gap.
    nearest=[min(abs(a['x']-b['x']) for b in letters
                 if abs(a['y']-b['y']) < 100 and a['id'] != b['id'])
             for a in letters if any(abs(a['y']-b['y']) < 100 and a['id'] != b['id'] for b in letters)]
    pitch=median(nearest) if nearest else 100
    rows=[]
    for lamp in sorted(lamps,key=lambda l:l['y']):
        if lamp.get('key_usage')==88: continue  # Tall keypad Enter spans two rows.
        if not rows or lamp['y']-rows[-1][0]['y'] > pitch*.4: rows.append([])
        rows[-1].append(lamp)
    centers=[median(l['y'] for l in row) for row in rows]
    left=min(l['x'] for l in lamps)-pitch*.48
    right=max(l['x'] for l in lamps)+pitch*.43
    result=[]
    wide={40,42,43,44,57,225,229}
    for lamp in lamps:
        usage=lamp.get('key_usage',0)
        row=min(range(len(centers)),key=lambda i:abs(centers[i]-lamp['y']))
        peers=sorted(rows[row],key=lambda l:l['x'])
        before=[l['x'] for l in peers if l['x']<lamp['x']]
        after=[l['x'] for l in peers if l['x']>lamp['x']]
        x=lamp['x']; y=centers[row]
        x0=x-pitch*.43; x1=x+pitch*.43
        if usage in wide:
            x0=max(before)+pitch*.52 if before else left
            x1=min(after)-pitch*.52 if after else right
        else:
            if before: x0=max(x0,(max(before)+x)/2+pitch*.05)
            if after: x1=min(x1,(min(after)+x)/2-pitch*.05)
        h=pitch*(.64 if row==0 else .84)
        if usage==88:
            y=lamp['y']; h=pitch*1.78
            x0=x-pitch*.36; x1=x+pitch*.36
        result.append((lamp,x0,y-h/2,max(pitch*.45,x1-x0),h))
    return result
