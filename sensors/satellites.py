#!/usr/bin/env python3
"""
Visible passes of the brightest satellites for the "Tonight" card. Runs inside
Home Assistant as a command_line sensor. No account or API key.

A short list (SATS), not "every bright satellite": only a few have naked-eye
passes often enough to be worth a line on the card.

Orbits: CelesTrak's GP elements (https://celestrak.org, free), one small
request per satellite when the copy beside this script is older than HOURS.
The passes are computed here with SGP4 (orbits.py), every run, from that copy,
so they survive an internet outage; elements older than STALE days are not used.

A pass = the stretch where the satellite is sunlit, at least 10 degrees up and
the sky dark enough: Sun under -4 degrees for the bright ones (standard
magnitude 0 or brighter: they show in a still-blue sky), under -6 for the
others. Shorter than MIN_VISIBLE_S seconds: dropped.

Brightness (`mag`, lower = brighter): the brightest moment while it can be
seen, from the satellite's standard magnitude, its distance and the phase angle
(orbits.magnitude; checked against Heavens-Above, see docs/how-it-works.md).

What is kept: every ISS pass; of the others, passes of magnitude <= MAG_MAX
(fainter is lost in twilight) that reach EL_MIN degrees; and at most
MAX_PER_NIGHT passes a night (noon to noon), the ISS first, then the brightest.

Output: {"state": number of passes, "passes": [{id (NORAD), rise (over the
horizon, lit or not), visible (first seen), max (highest while seen), end
(local "2026-11-09T19:05"), az_start, az_max, az_end, el_max (highest while
seen), el_end (>= 10: where it enters the Earth's shadow; 0: it sets or the sky
gets light), mag, mag_est (always true), duration (s, the visible part)}],
"checked" (oldest element download)}

Usage:
  satellites.py [--config path/to/config.json]

Location and time zone come from Home Assistant itself (see settings.py).
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import settings
import orbits as O

GP = 'https://celestrak.org/NORAD/elements/gp.php?CATNR={}&FORMAT=json'
ISS = 25544
# NORAD id, standard magnitude (1000 km, half lit), days ahead. Names live in build_card.py.
SATS = [
    (ISS, -1.8, 10),      # International Space Station
    (48274, 0.0, 10),     # Tiangong (Chinese space station)
    (20580, 2.2, 10),     # Hubble Space Telescope
    (61047, 4.5, 10),     # BlueBird (AST SpaceMobile, 64 m2 antenna); 4.5 is Heavens-Above's figure
]
MAG_MAX, EL_MIN, MAX_PER_NIGHT = 5.5, 15, 5
MIN_VISIBLE_S = 60
HOURS = 8           # fetch the elements again when older than this
STALE = 7           # days: older elements are not used
SUN_BRIGHT = -4     # dark enough for satellites of standard magnitude <= 0


def elements(path, now):
    """{"25544": {"fetched": ts, "omm": {...}}}, refreshed from CelesTrak when old."""
    try:
        c = json.loads(path.read_text())
    except Exception:
        c = {}
    changed = False
    for sid, *_ in SATS:
        k = str(sid)
        if now.timestamp() - c.get(k, {}).get('fetched', 0) < HOURS * 3600:
            continue
        try:
            req = urllib.request.Request(GP.format(sid), headers={'User-Agent': 'python-urllib'})
            with urllib.request.urlopen(req, timeout=20) as r:
                x = json.load(r)[0]
            c[k] = {'fetched': round(now.timestamp()), 'omm': {key: x[key] for key in O.KEYS}}
            changed = True
        except urllib.error.HTTPError as e:      # this satellite only: keep its copy
            print(f'CelesTrak {sid}: HTTP {e.code}', file=sys.stderr)
        except Exception as e:                   # offline: stop asking, use the copy
            print(f'CelesTrak {sid}: {type(e).__name__}', file=sys.stderr)
            break
    if changed:
        try:
            path.write_text(json.dumps(c, separators=(',', ':')))
        except Exception as e:
            print(f'cache: {type(e).__name__}', file=sys.stderr)
    return c


def passes(sat, now, days, std):
    out = []
    for pts in O.visible_passes(sat, now, days, SUN_BRIGHT if std <= 0 else O.SUN_DARK):
        first, last, top = pts[0], pts[-1], max(pts, key=lambda p: p[1])
        dur = (last[0] - first[0]).total_seconds()
        if dur < MIN_VISIBLE_S:
            continue
        rise, az0 = O.horizon(sat, first[0], -O.STEP)
        after = O.where(sat, last[0] + O.STEP)
        if after and after[0] >= O.EL_HOR and not after[3]:     # into the Earth's shadow, still up
            end, az1, el1 = last[0], last[2], last[1]
        else:                                                   # down to the horizon, or the sky got light
            end, az1 = O.horizon(sat, last[0], O.STEP)
            el1 = 0
        mags = [m for m in (O.magnitude(sat, q[0], std) for q in pts) if m is not None]
        out.append({'rise': O.local(rise), 'visible': O.local(first[0]), 'max': O.local(top[0]), 'end': O.local(end),
                    'az_start': round(az0), 'az_max': round(top[2]), 'az_end': round(az1),
                    'el_max': round(top[1]), 'el_end': round(el1),
                    'mag': round(min(mags), 1), 'mag_est': True,
                    'duration': round(dur), '_t': first[0].timestamp()})
    return out


def main():
    cfg = settings.load()
    O.setup(cfg)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    el = elements(cfg['cache_dir'] / '.satellites_elements.json', now)
    found, got = [], []
    for sid, std, days in SATS:
        e = el.get(str(sid))
        if not e:
            continue
        epoch = datetime.fromisoformat(e['omm']['EPOCH'][:19]).replace(tzinfo=timezone.utc)
        if (now - epoch).total_seconds() > STALE * 86400:
            continue
        got.append(e['fetched'])
        for p in passes(O.satrec(e['omm']), now, days, std):
            if sid != ISS and (p['mag'] > MAG_MAX or p['el_max'] < EL_MIN):
                continue
            found.append({'id': sid, **p})
    # at most MAX_PER_NIGHT a night (noon to noon): the ISS first, then the brightest
    keep, per_night = [], {}
    for p in sorted(found, key=lambda p: (p['id'] != ISS, p['mag'])):
        night = (datetime.fromtimestamp(p['_t'], O.TZ) - timedelta(hours=12)).date()
        if per_night.get(night, 0) < MAX_PER_NIGHT:
            per_night[night] = per_night.get(night, 0) + 1
            keep.append(p)
    keep.sort(key=lambda p: p.pop('_t'))
    checked = O.local(datetime.fromtimestamp(min(got), timezone.utc)) if got else None
    print(json.dumps({'state': len(keep), 'passes': keep, 'checked': checked}, separators=(',', ':')))


if __name__ == '__main__':
    main()
