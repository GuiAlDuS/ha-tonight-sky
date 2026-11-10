#!/usr/bin/env python3
"""
Visible passes of the brightest satellites for the "Tonight" card. Runs inside
Home Assistant as a command_line sensor.

A short list (SATS), not "every bright satellite": only a few have naked-eye
passes often enough to be worth a line on the card. N2YO's `visualpasses`
(https://www.n2yo.com/api/) is asked for each one; you need your own free API
key as `n2yo_api_key` in Home Assistant's secrets.yaml. Without a key the sensor reports no
passes and the card simply shows no satellites.

Brightness: N2YO gives a magnitude for some satellites (ISS, Hubble) and none
for others. It is then estimated from the satellite's standard magnitude (at
1000 km, half lit) and its distance at the highest point of the pass:
mag = std + 5 log10(d / 1000). Rough: good for "very bright / bright / faint",
not for more (`mag_est` is true on those).

What is kept: every ISS pass; of the others, passes of magnitude <= MAG_MAX
that reach EL_MIN degrees; and at most MAX_PER_NIGHT passes a night (noon to
noon), the ISS first, then the brightest.

The last good answer for each satellite is cached beside this script, so the
passes survive an internet outage; passes already over are dropped.

Output: {"state": number of passes, "passes": [{id (NORAD), rise, visible (from
when it can be seen), max, end (local "2026-11-09T19:05"), az_start, az_max,
az_end, el_max, el_end, mag, mag_est, duration (s, visible part)}], "checked"}

Usage:
  satellites.py [--config path/to/config.json]

Location and time zone come from Home Assistant itself (see settings.py).
"""
import json
import math
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import settings

ISS = 25544
# NORAD id, standard magnitude, height (km), days ahead (10 is N2YO's most; the card says
# when each satellite is next seen).  Names live in build_card.py.
SATS = [
    (ISS, -1.8, 420, 10),      # International Space Station
    (48274, 0.0, 385, 10),      # Tiangong (Chinese space station)
    (20580, 2.2, 525, 10),      # Hubble Space Telescope
    (61047, 3.8, 520, 10),      # BlueBird (AST SpaceMobile, 64 m2 antenna)
]
MAG_MAX, EL_MIN, MAX_PER_NIGHT = 3.0, 25, 5
MIN_VISIBLE_S = 120
RE = 6371.0


def estimate(std, h, el):
    """Magnitude at elevation `el` (deg) of a satellite `h` km up with standard magnitude `std`."""
    e = math.radians(max(el, 1))
    d = math.sqrt((RE + h) ** 2 - (RE * math.cos(e)) ** 2) - RE * math.sin(e)
    return round(std + 5 * math.log10(d / 1000), 1)


def main():
    cfg = settings.load()
    tz = ZoneInfo(cfg['timezone'])
    cache_path = cfg['cache_dir'] / '.satellites_cache.json'

    def local(ts):
        return datetime.fromtimestamp(ts, tz).replace(tzinfo=None).isoformat(timespec='minutes')

    now = datetime.now(tz).timestamp()
    try:
        cache = json.loads(cache_path.read_text())
    except Exception:
        cache = {}
    key = (cfg.get('n2yo_api_key') or '').strip()
    online = bool(key)
    for sid, _, _, days in SATS:
        if not online:
            break
        url = (f"https://api.n2yo.com/rest/v1/satellite/visualpasses/{sid}/{cfg['latitude']}/{cfg['longitude']}"
               f"/{cfg.get('elevation_m', 0)}/{days}/{MIN_VISIBLE_S}/&apiKey={key}")
        try:
            with urllib.request.urlopen(url, timeout=12) as r:
                d = json.load(r)
            if 'passes' in d or d.get('info', {}).get('passescount') == 0:
                cache[str(sid)] = {'checked': local(now), 'passes': d.get('passes', [])}
            elif d.get('error'):
                print(f'N2YO {sid}: {d["error"]}', file=sys.stderr)
        except urllib.error.HTTPError as e:     # this satellite only: keep its cached answer
            print(f'N2YO {sid}: HTTP {e.code}', file=sys.stderr)
        except Exception as e:                  # offline: stop asking, use the cache
            print(f'N2YO {sid}: {type(e).__name__}', file=sys.stderr)
            online = False
    try:
        cache_path.write_text(json.dumps(cache))
    except Exception as e:
        print(f'cache: {type(e).__name__}', file=sys.stderr)

    passes = []
    for sid, std, h, _ in SATS:
        for p in cache.get(str(sid), {}).get('passes', []):
            if p['endUTC'] <= now:
                continue
            est = not isinstance(p.get('mag'), (int, float)) or abs(p['mag']) > 50
            mag = estimate(std, h, p['maxEl']) if est else p['mag']
            if sid != ISS and (mag > MAG_MAX or p['maxEl'] < EL_MIN):
                continue
            # startUTC is when it rises; it is visible from startVisibility (sunlit, sky dark)
            passes.append({
                'id': sid, 'rise': local(p['startUTC']), 'visible': local(p.get('startVisibility', p['startUTC'])),
                'max': local(p['maxUTC']), 'end': local(p['endUTC']),
                'az_start': round(p['startAz']), 'az_max': round(p['maxAz']), 'az_end': round(p['endAz']),
                'el_max': round(p['maxEl']), 'el_end': round(p['endEl']), 'mag': mag, 'mag_est': est,
                'duration': p['duration'], '_t': p['startUTC']})
    # at most MAX_PER_NIGHT a night (noon to noon): the ISS first, then the brightest
    keep, per_night = [], {}
    for p in sorted(passes, key=lambda p: (p['id'] != ISS, p['mag'])):
        night = (datetime.fromtimestamp(p['_t'], tz) - timedelta(hours=12)).date()
        if per_night.get(night, 0) < MAX_PER_NIGHT:
            per_night[night] = per_night.get(night, 0) + 1
            keep.append(p)
    keep.sort(key=lambda p: p.pop('_t'))
    asked = [c['checked'] for c in cache.values() if c.get('checked')]
    print(json.dumps({'state': len(keep), 'passes': keep, 'checked': min(asked) if asked else None},
                     separators=(',', ':')))


if __name__ == '__main__':
    main()
