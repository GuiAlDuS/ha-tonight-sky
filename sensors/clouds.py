#!/usr/bin/env python3
"""
Hourly cloud cover for the "Tonight" card. Runs inside Home Assistant as a
command_line sensor.

Many weather integrations give a condition ("partlycloudy") but no cloud cover
per hour, so this reads Open-Meteo (https://open-meteo.com, free for
non-commercial use, no key): total, low, mid and high cloud and the chance of
rain per hour at your location. The last good answer is cached beside this
script, so it survives an internet outage; hours already past are dropped and
the next 36 are kept.

Output: {"state": this hour's cloud cover (%), "hours": [["2026-10-28T19:00",
total, low, mid, high, rain %], ...], "checked"}

Usage:
  clouds.py [--config path/to/config.json]

Location and time zone come from Home Assistant itself (see settings.py).
"""
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import settings


def main():
    cfg = settings.load()
    cache_path = cfg['cache_dir'] / '.clouds_cache.json'
    url = ('https://api.open-meteo.com/v1/forecast?' + urllib.parse.urlencode({
        'latitude': cfg['latitude'], 'longitude': cfg['longitude'],
        'hourly': 'cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,precipitation_probability',
        'timezone': cfg['timezone'], 'forecast_days': 3}))
    now = datetime.now(ZoneInfo(cfg['timezone'])).replace(tzinfo=None)
    data = None
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            h = json.load(r)['hourly']
        data = {'checked': now.isoformat(timespec='minutes'),
                'hours': [list(x) for x in zip(h['time'], h['cloud_cover'], h['cloud_cover_low'], h['cloud_cover_mid'],
                                               h['cloud_cover_high'], h['precipitation_probability'])]}
        cache_path.write_text(json.dumps(data))
    except Exception as e:                      # offline or Open-Meteo down: use the cache
        print(f'Open-Meteo: {type(e).__name__}', file=sys.stderr)
        try:
            data = json.loads(cache_path.read_text())
        except Exception:
            data = {'checked': None, 'hours': []}
    hour = now.replace(minute=0, second=0, microsecond=0).isoformat(timespec='minutes')
    hours = [x for x in data['hours'] if x[0] >= hour and x[1] is not None][:36]
    print(json.dumps({'state': hours[0][1] if hours else None, 'hours': hours, 'checked': data['checked']},
                     separators=(',', ':')))


if __name__ == '__main__':
    main()
