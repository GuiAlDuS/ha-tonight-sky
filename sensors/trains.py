#!/usr/bin/env python3
"""
Optional: "Starlink trains" for the "Tonight" card. Runs inside Home Assistant
as a command_line sensor; leave its sensor out and the card shows no trains.

A train = the satellites of one Starlink launch in their first days, still
bunched and low, seen as a row of lights shortly after dusk or before dawn.
New satellites have no catalogue numbers yet, so the orbits come from
CelesTrak's supplemental Starlink file (SpaceX's own data, free, no key, about
5 MB), downloaded when the copy is older than HOURS hours. Only the newest
NEWEST launches are looked at, and only those still within KEEP degrees of
orbit are cached (a few kB), so the passes can be recomputed offline.

A pass is kept when, for the group's middle satellite, it is visible
(orbits.visible_passes: sunlit, 10 degrees up, Sun under -6), it reaches EL_MIN,
the whole group is still within TRAIN_MAX degrees of orbit at its highest
moment (a train spreads round its orbit within days), and the elements are not
older than STALE days. Trains are rare: most weeks the sensor is empty.

No brightness: not estimated (new satellites change attitude and height in
their first days). Elements of satellites raising their orbit go stale in 2-3
days, so passes two or three days ahead can be a minute or two off.

Output: {"state": number of passes, "passes": [{id (launch, "2026-256"), n
(satellites), sep (degrees of orbit between the farthest two at the highest
moment), row_min (minutes the row takes to go by), rise = visible, max, end
(local "...T18:05"), az_start, az_max, az_end, el_max, el_end, duration (s),
dist (km at the highest moment), age (days from the elements to the pass)}],
"trains": [{id, n, sep (now), alt (km)}], "checked"}
"""
import json
import math
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

import settings
import orbits as O

URL = 'https://celestrak.org/NORAD/elements/supplemental/sup-gp.php?FILE=starlink&FORMAT=json'
HOURS = 8          # download again when the copy is older than this
NEWEST = 8         # newest launches looked at
KEEP = 90          # degrees of orbit: launches more spread than this are not cached
TRAIN_MAX = 25     # degrees of orbit at the pass: more is no longer a train
EL_MIN = 20        # a pass must reach this
DAYS = 3           # days ahead
STALE = 3.5        # days: elements older than this at the pass are not trusted


def download(now, cache, path):
    """Refresh cache['groups'] from CelesTrak when the copy is old."""
    if now.timestamp() - cache.get('fetched', 0) < HOURS * 3600:
        return
    req = urllib.request.Request(URL, headers={'User-Agent': 'python-urllib'})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    by = defaultdict(list)
    for x in data:
        by[x['OBJECT_ID'][:8]].append({k: x[k] for k in O.KEYS})
    if not by:
        raise ValueError('empty file')
    groups = {}
    for k in sorted(by)[-NEWEST:]:
        if O.spread(O.positions([O.satrec(x, i) for i, x in enumerate(by[k])], now)) <= KEEP:
            groups[k] = by[k]
    cache.update(fetched=now.timestamp(), checked=O.local(now), groups=groups)
    path.write_text(json.dumps(cache, separators=(',', ':')))


def epoch(x):
    return datetime.fromisoformat(x['EPOCH'][:19]).replace(tzinfo=timezone.utc)


def passes(launch, elems, now):
    sats = [O.satrec(x, i) for i, x in enumerate(elems)]
    P = O.positions(sats, now)
    if len(P) < 3:
        return None, []
    c = [sum(p[i] for p in P) for i in range(3)]
    ref = sats[min(range(len(P)), key=lambda i: O.angle(P[i], c))]       # the middle of the group
    ep = sorted(epoch(x) for x in elems)[len(elems) // 2]
    info = {'id': launch, 'n': len(sats), 'sep': round(O.spread(P)),
            'alt': round(sum(math.sqrt(O.dot(p, p)) for p in P) / len(P) - O.RE)}
    out = []
    for pts in O.visible_passes(ref, now, DAYS):
        top = max(pts, key=lambda p: p[1])
        sep = O.spread(O.positions(sats, top[0]))
        age = (top[0] - ep).total_seconds() / 86400
        if top[1] < EL_MIN or sep > TRAIN_MAX or age > STALE:
            continue
        first, last = pts[0], pts[-1]
        out.append({
            'id': launch, 'n': len(sats), 'sep': round(sep), 'row_min': round(sep / (ref.no_kozai * 180 / math.pi), 1),
            'rise': O.local(first[0]), 'visible': O.local(first[0]), 'max': O.local(top[0]), 'end': O.local(last[0]),
            'az_start': round(first[2]), 'az_max': round(top[2]), 'az_end': round(last[2]),
            'el_max': round(top[1]), 'el_end': round(last[1]),
            'duration': round((last[0] - first[0]).total_seconds()), 'dist': round(top[3]), 'age': round(age, 1)})
    return info, out


def main():
    cfg = settings.load()
    O.setup(cfg)
    path = cfg['cache_dir'] / '.trains_cache.json'
    now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        cache = json.loads(path.read_text())
    except Exception:
        cache = {}
    try:
        download(now, cache, path)
    except Exception as e:                  # offline, or CelesTrak down: use the copy
        print(f'CelesTrak: {type(e).__name__}', file=sys.stderr)
    trains, found = [], []
    for launch, elems in sorted(cache.get('groups', {}).items()):
        info, p = passes(launch, elems, now)
        if info:
            trains.append(info)
            found += p
    found.sort(key=lambda p: p['visible'])
    print(json.dumps({'state': len(found), 'passes': found, 'trains': trains, 'checked': cache.get('checked')},
                     separators=(',', ':')))


if __name__ == '__main__':
    main()
