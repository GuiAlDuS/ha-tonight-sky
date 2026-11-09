#!/usr/bin/env python3
"""
Tonight's sky for the "Tonight" card: which planets are up, where and when, and
the Moon. Runs inside Home Assistant as a command_line sensor. Standard library
only, no network.

Positions come from Paul Schlyter's low-precision orbital elements ("How to
compute planetary positions", stjarnhimlen.se), with his Jupiter / Saturn
perturbations and the main lunar perturbations: about 1-2 arcminutes for the
planets and 0.1 degrees for the Moon, far better than the card shows (whole
degrees, 8-point compass). Checked against skyfield + JPL DE421 at 10 deg N.

Tonight = from the end of civil twilight (sun 6 deg below the horizon) to the
start of it at dawn. A planet counts as visible while it is at least 10 deg up
during that time. Uranus and Neptune are left out (not naked-eye).

Output (one JSON document):
  state     number of planets visible tonight
  night     {start, end}: dusk and dawn, local time "2026-10-28T17:39"
            (null where it does not get dark, or the sun does not rise)
  planets   [{id, start, end, t_max, alt_max, az_max, az_start, mag, path}] in
            order of appearance; start/end = first and last moment >= 10 deg in
            the night; t_max/alt_max/az_max = highest point; path =
            [["HH:MM", alt, az], ...] at dusk, every 20 min on the clock and at
            dawn, while above the horizon
  moon      {lit (%), waxing, path (same sampling)}
  upcoming  [{id, start, az_start, when, mag}] for each planet not visible
            tonight: the first later moment it is >= 10 deg up in the dark;
            when = "dawn" / "dusk" if that is within an hour of one, else ""
  updated   time of this run

Usage:
  tonight.py [--now 2026-10-28T12:00] [--config path/to/config.json]

Location and time zone come from Home Assistant itself (see settings.py).
"""
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import settings

MIN_ALT = 10.0
DUSK = -6.0
STEP = timedelta(minutes=5)
TZ = timezone.utc          # set from the settings in main()

rad, deg = math.radians, math.degrees


def sind(x): return math.sin(rad(x))
def cosd(x): return math.cos(rad(x))
def rev(x): return x % 360.0


# orbital elements: N, i, w, a, e, M as (value at d=0, rate per day)
ELEMENTS = {
    'sun':      ((0, 0), (0, 0), (282.9404, 4.70935e-5), (1.0, 0), (0.016709, -1.151e-9), (356.0470, 0.9856002585)),
    'mercury': ((48.3313, 3.24587e-5), (7.0047, 5.00e-8), (29.1241, 1.01444e-5), (0.387098, 0), (0.205635, 5.59e-10), (168.6562, 4.0923344368)),
    'venus':    ((76.6799, 2.46590e-5), (3.3946, 2.75e-8), (54.8910, 1.38374e-5), (0.723330, 0), (0.006773, -1.302e-9), (48.0052, 1.6021302244)),
    'mars':    ((49.5574, 2.11081e-5), (1.8497, -1.78e-8), (286.5016, 2.92961e-5), (1.523688, 0), (0.093405, 2.516e-9), (18.6021, 0.5240207766)),
    'jupiter':  ((100.4542, 2.76854e-5), (1.3030, -1.557e-7), (273.8777, 1.64505e-5), (5.20256, 0), (0.048498, 4.469e-9), (19.8950, 0.0830853001)),
    'saturn':  ((113.6634, 2.38980e-5), (2.4886, -1.081e-7), (339.3939, 2.97661e-5), (9.55475, 0), (0.055546, -9.499e-9), (316.9670, 0.0334442282)),
}
PLANETS = ['mercury', 'venus', 'mars', 'jupiter', 'saturn']


def day_number(t):
    """Schlyter's d: days since 1999-12-31 00:00 UT."""
    return (t - datetime(1999, 12, 31, tzinfo=timezone.utc)).total_seconds() / 86400


def orbit(name, d):
    """Heliocentric ecliptic x, y, z (AU), plus r, longitude, M for perturbations."""
    N, i, w, a, e, M = (v0 + v1 * d for v0, v1 in ELEMENTS[name])
    M = rev(M)
    E = M + deg(e * sind(M) * (1 + e * cosd(M)))
    for _ in range(10):
        E = E - (E - deg(e * sind(E)) - M) / (1 - e * cosd(E))
    xv, yv = a * (cosd(E) - e), a * math.sqrt(1 - e * e) * sind(E)
    v, r = deg(math.atan2(yv, xv)), math.hypot(xv, yv)
    x = r * (cosd(N) * cosd(v + w) - sind(N) * sind(v + w) * cosd(i))
    y = r * (sind(N) * cosd(v + w) + cosd(N) * sind(v + w) * cosd(i))
    z = r * sind(v + w) * sind(i)
    return x, y, z, r, M, w


def helio(name, d):
    x, y, z, r, M, _ = orbit(name, d)
    if name in ('jupiter', 'saturn'):
        Mj, Ms = orbit('jupiter', d)[4], orbit('saturn', d)[4]
        lon, lat = rev(deg(math.atan2(y, x))), deg(math.atan2(z, math.hypot(x, y)))
        if name == 'jupiter':
            lon += (-0.332 * sind(2 * Mj - 5 * Ms - 67.6) - 0.056 * sind(2 * Mj - 2 * Ms + 21)
                    + 0.042 * sind(3 * Mj - 5 * Ms + 21) - 0.036 * sind(Mj - 2 * Ms)
                    + 0.022 * cosd(Mj - Ms) + 0.023 * sind(2 * Mj - 3 * Ms + 52)
                    - 0.016 * sind(Mj - 5 * Ms - 69))
        else:
            lon += (0.812 * sind(2 * Mj - 5 * Ms - 67.6) - 0.229 * cosd(2 * Mj - 4 * Ms - 2)
                    + 0.119 * sind(Mj - 2 * Ms - 3) + 0.046 * sind(2 * Mj - 6 * Ms - 69)
                    + 0.014 * sind(Mj - 3 * Ms + 32))
            lat += -0.020 * cosd(2 * Mj - 4 * Ms - 2) + 0.018 * sind(2 * Mj - 6 * Ms - 49)
        x, y, z = r * cosd(lon) * cosd(lat), r * sind(lon) * cosd(lat), r * sind(lat)
    return x, y, z, r


def sun_geo(d):
    """Geocentric ecliptic x, y of the sun, its longitude and mean longitude."""
    x, y, _, r, M, w = orbit('sun', d)
    return x, y, rev(deg(math.atan2(y, x))), rev(M + w)


def alt_az(name, t, lat, lon):
    d = day_number(t)
    xs, ys, lsun, Ls = sun_geo(d)
    if name == 'sun':
        xg, yg, zg = xs, ys, 0.0
    else:
        xh, yh, zh, _ = helio(name, d)
        xg, yg, zg = xh + xs, yh + ys, zh
    ecl = 23.4393 - 3.563e-7 * d
    xe, ye, ze = xg, yg * cosd(ecl) - zg * sind(ecl), yg * sind(ecl) + zg * cosd(ecl)
    ra, dec = rev(deg(math.atan2(ye, xe))), deg(math.atan2(ze, math.hypot(xe, ye)))
    ut = t.hour + t.minute / 60 + t.second / 3600
    ha = rev(Ls + 180 + ut * 15 + lon - ra)
    x, y, z = cosd(ha) * cosd(dec), sind(ha) * cosd(dec), sind(dec)
    xhor = x * sind(lat) - z * cosd(lat)
    zhor = x * cosd(lat) + z * sind(lat)
    az = rev(deg(math.atan2(y, xhor)) + 180)
    alt = deg(math.asin(max(-1, min(1, zhor))))
    return alt, az, math.sqrt(xg * xg + yg * yg + zg * zg)


def moon(t, lat, lon):
    """Topocentric altitude/azimuth of the Moon, illuminated fraction (0-1) and
    whether it is waxing (Schlyter: main perturbations, then parallax)."""
    d = day_number(t)
    N, i, w = 125.1228 - 0.0529538083 * d, 5.1454, 318.0634 + 0.1643573223 * d
    a, e, M = 60.2666, 0.054900, rev(115.3654 + 13.0649929509 * d)
    E = M + deg(e * sind(M) * (1 + e * cosd(M)))
    for _ in range(10):
        E = E - (E - deg(e * sind(E)) - M) / (1 - e * cosd(E))
    xv, yv = a * (cosd(E) - e), a * math.sqrt(1 - e * e) * sind(E)
    v, r = deg(math.atan2(yv, xv)), math.hypot(xv, yv)
    x = r * (cosd(N) * cosd(v + w) - sind(N) * sind(v + w) * cosd(i))
    y = r * (sind(N) * cosd(v + w) + cosd(N) * sind(v + w) * cosd(i))
    z = r * sind(v + w) * sind(i)
    mlon, mlat = rev(deg(math.atan2(y, x))), deg(math.atan2(z, math.hypot(x, y)))
    _, _, slon, Ls = sun_geo(d)
    Ms = rev(356.0470 + 0.9856002585 * d)
    Lm = rev(M + w + N)
    D, F = rev(Lm - Ls), rev(Lm - N)
    mlon += (-1.274 * sind(M - 2 * D) + 0.658 * sind(2 * D) - 0.186 * sind(Ms) - 0.059 * sind(2 * M - 2 * D)
             - 0.057 * sind(M - 2 * D + Ms) + 0.053 * sind(M + 2 * D) + 0.046 * sind(2 * D - Ms)
             + 0.041 * sind(M - Ms) - 0.035 * sind(D) - 0.031 * sind(M + Ms) - 0.015 * sind(2 * F - 2 * D)
             + 0.011 * sind(M - 4 * D))
    mlat += (-0.173 * sind(F - 2 * D) - 0.055 * sind(M - F - 2 * D) - 0.046 * sind(M + F - 2 * D)
             + 0.033 * sind(F + 2 * D) + 0.017 * sind(2 * M + F))
    r += -0.58 * cosd(M - 2 * D) - 0.46 * cosd(2 * D)
    ecl = 23.4393 - 3.563e-7 * d
    xg, yg, zg = cosd(mlon) * cosd(mlat), sind(mlon) * cosd(mlat), sind(mlat)
    xe, ye, ze = xg, yg * cosd(ecl) - zg * sind(ecl), yg * sind(ecl) + zg * cosd(ecl)
    ra, dec = rev(deg(math.atan2(ye, xe))), deg(math.atan2(ze, math.hypot(xe, ye)))
    ut = t.hour + t.minute / 60 + t.second / 3600
    ha = rev(Ls + 180 + ut * 15 + lon - ra)
    hx, hy, hz = cosd(ha) * cosd(dec), sind(ha) * cosd(dec), sind(dec)
    xhor, zhor = hx * sind(lat) - hz * cosd(lat), hx * cosd(lat) + hz * sind(lat)
    az = rev(deg(math.atan2(hy, xhor)) + 180)
    alt = deg(math.asin(max(-1, min(1, zhor))))
    alt -= deg(math.asin(1 / r)) * cosd(alt)          # parallax: up to ~1 deg
    elong = deg(math.acos(max(-1, min(1, cosd(slon - mlon) * cosd(mlat)))))
    return alt, az, (1 - cosd(elong)) / 2, rev(mlon - slon) < 180


def magnitude(name, t):
    """Apparent magnitude (Schlyter's formulas; Saturn without its rings)."""
    d = day_number(t)
    xh, yh, zh, r = helio(name, d)
    xs, ys, _, _ = sun_geo(d)
    R = math.sqrt((xh + xs) ** 2 + (yh + ys) ** 2 + zh ** 2)
    s = math.hypot(xs, ys)
    FV = deg(math.acos(max(-1, min(1, (r * r + R * R - s * s) / (2 * r * R)))))
    base = {'mercury': (-0.36, 0.027, 2.2e-13, 6), 'venus': (-4.34, 0.013, 4.2e-7, 3),
            'mars': (-1.51, 0.016, 0, 1), 'jupiter': (-9.25, 0.014, 0, 1),
            'saturn': (-9.0, 0.044, 0, 1)}[name]
    m = base[0] + 5 * math.log10(r * R) + base[1] * FV + base[2] * FV ** base[3]
    return round(m, 1)


class NoNight(Exception):
    pass


def night(now, lat, lon):
    """Tonight's dusk and dawn (UTC): the next stretch with the sun below DUSK,
    or the current one if it is already dark."""
    t = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    day = timedelta(hours=24)
    if alt_az('sun', t, lat, lon)[0] < DUSK:
        a = t
        while alt_az('sun', a - STEP, lat, lon)[0] < DUSK:
            a -= STEP
            if t - a > day:
                raise NoNight('the sun does not rise today')
    else:
        a = t
        while alt_az('sun', a, lat, lon)[0] >= DUSK:
            a += STEP
            if a - t > day:
                raise NoNight('it does not get dark today')
    b = a
    while alt_az('sun', b, lat, lon)[0] < DUSK:
        b += STEP
        if b - a > day:
            raise NoNight('the sun does not rise today')
    # refine both edges to the minute (the 5-minute grid starts at "now")
    one = timedelta(minutes=1)
    while alt_az('sun', a - one, lat, lon)[0] < DUSK:
        a -= one
    while alt_az('sun', b - one, lat, lon)[0] >= DUSK:
        b -= one
    return a, b


def clock_times(a, b, minutes=20):
    """a, then every `minutes` on the clock (:00, :20, :40) up to b, then b."""
    m = timedelta(minutes=minutes)
    t = a + m
    t = t.replace(minute=(t.minute // minutes) * minutes, second=0, microsecond=0)
    out = [a]
    while t < b:
        out.append(t)
        t += m
    return out + [b]


def above(name, a, b, lat, lon):
    """[(t, alt, az)] while `name` is >= MIN_ALT between dusk a and dawn b, every STEP and at b."""
    times = [a + STEP * k for k in range(int((b - a) / STEP) + 1)]
    if times[-1] < b:
        times.append(b)                          # dawn itself, so "until dawn" matches
    return [(t, alt, az) for t in times for alt, az, _ in [alt_az(name, t, lat, lon)] if alt >= MIN_ALT]


def upcoming(name, b, lat, lon, days=400):
    """The first later night (after the dawn b) on which `name` counts as visible, by the
    same rule as tonight's list, or None within `days`."""
    hour = timedelta(hours=1)
    for k in range(days):
        try:
            a2, b2 = night(b + timedelta(hours=12 + 24 * k), lat, lon)
        except NoNight:
            continue
        up = above(name, a2, b2, lat, lon)
        if up:
            t, _, az = up[0]
            when = 'dawn' if b2 - t <= hour else 'dusk' if t - a2 <= hour else ''
            return {'id': name, 'start': local(t), 'az_start': round(az), 'when': when,
                    'mag': magnitude(name, t)}
    return None


def local(t):
    return t.astimezone(TZ).replace(tzinfo=None).isoformat(timespec='minutes')


def main():
    global TZ
    args = sys.argv[1:]
    cfg = settings.load(args)
    lat, lon, TZ = float(cfg['latitude']), float(cfg['longitude']), ZoneInfo(cfg['timezone'])
    now = datetime.now(timezone.utc)
    if '--now' in args:
        now = datetime.fromisoformat(args[args.index('--now') + 1]).replace(tzinfo=TZ)
    try:
        a, b = night(now, lat, lon)
    except NoNight:
        print(json.dumps({'state': 0, 'updated': local(now), 'night': None, 'moon': None,
                          'planets': [], 'upcoming': []}, separators=(',', ':')))
        return
    out = []
    for p in PLANETS:
        up = above(p, a, b, lat, lon)
        if not up:
            continue
        top = max(up, key=lambda u: u[1])
        # path across tonight's sky for the dome: every 20 min while above the
        # horizon (not just the >= 10 deg part), whole degrees
        path = []
        for t in clock_times(a, b):
            alt, az, _ = alt_az(p, t, lat, lon)
            if alt >= 0:
                path.append([local(t)[11:], round(alt), round(az)])
        out.append({'id': p, 'start': local(up[0][0]), 'end': local(up[-1][0]),
                    't_max': local(top[0]), 'alt_max': round(top[1]), 'az_max': round(top[2]),
                    'az_start': round(up[0][2]), 'mag': magnitude(p, top[0]), 'path': path})
    out.sort(key=lambda o: o['start'])
    # the Moon: path while above the horizon; lit fraction and waxing at the middle of the night
    mid = a + (b - a) / 2
    _, _, lit, waxing = moon(mid, lat, lon)
    mp = [[local(t)[11:], round(al), round(az)] for t in clock_times(a, b)
          for al, az, _, _ in [moon(t, lat, lon)] if al >= 0]
    # planets not up tonight: when each one can be seen again (they are lost near the Sun)
    seen = {o['id'] for o in out}
    later = [q for q in (upcoming(p, b, lat, lon) for p in PLANETS if p not in seen) if q]
    later.sort(key=lambda q: q['start'])
    print(json.dumps({'state': len(out), 'updated': local(now), 'night': {'start': local(a), 'end': local(b)},
                      'moon': {'lit': round(lit * 100), 'waxing': waxing, 'path': mp},
                      'planets': out, 'upcoming': later}, separators=(',', ':')))


if __name__ == '__main__':
    main()
