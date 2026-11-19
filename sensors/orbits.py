"""
Satellite geometry shared by satellites.py and trains.py: where a satellite is
in your sky, whether the Sun lights it, whether the sky is dark enough to see
it, the visible passes, and an estimate of its brightness.

Orbits are propagated with the SGP4 model (the `sgp4` library by Brandon
Rhodes, MIT licence, its pure-Python part copied to sgp4/ beside this file,
because Home Assistant's Python cannot install packages). Everything else is
done here, with a few simplifications that are far below what the eye can
tell (see docs/how-it-works.md):

  * the Sun: a low-precision formula (about 0.01 degree), as a direction only;
  * the Earth's shadow: a cylinder, no penumbra (a satellite fades over a few
    seconds, not instantly);
  * the frame: SGP4's TEME frame is treated as the true-of-date frame and the
    observer is rotated by the mean sidereal time (both differ by well under
    a tenth of a degree as seen from the ground).

Call setup(cfg) once with the settings from settings.py.
"""
import math
from datetime import timedelta
from zoneinfo import ZoneInfo

from sgp4 import omm
from sgp4.api import Satrec, jday

RE, F = 6378.137, 1 / 298.257223563     # WGS84
EL_HOR = 10        # a pass is counted from 10 degrees up: lower, trees, haze and hills hide it
SUN_DARK = -6      # sun at least this far under the horizon: dark enough (civil dusk)
STEP = timedelta(seconds=5)
K_PHASE = 0.32     # share of the diffuse-sphere phase term (fitted to Heavens-Above, see docs)
KEYS = ('OBJECT_ID', 'EPOCH', 'MEAN_MOTION', 'ECCENTRICITY', 'INCLINATION', 'RA_OF_ASC_NODE',
        'ARG_OF_PERICENTER', 'MEAN_ANOMALY', 'EPHEMERIS_TYPE', 'CLASSIFICATION_TYPE', 'ELEMENT_SET_NO',
        'REV_AT_EPOCH', 'BSTAR', 'MEAN_MOTION_DOT', 'MEAN_MOTION_DDOT')

LAT = LON = ALT = None
TZ = None


def setup(cfg):
    """Observer from settings.py: latitude, longitude (deg), elevation (m), time zone."""
    global LAT, LON, ALT, TZ
    LAT, LON = math.radians(cfg['latitude']), math.radians(cfg['longitude'])
    ALT = (cfg.get('elevation_m') or 0) / 1000
    TZ = ZoneInfo(cfg['timezone'])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def angle(a, b):
    """Angle between two vectors, degrees."""
    return math.degrees(math.acos(max(-1, min(1, dot(a, b) / math.sqrt(dot(a, a) * dot(b, b))))))


def spread(P):
    """Largest angle (degrees, from the Earth's centre) between two of the positions."""
    return max((angle(p, q) for i, p in enumerate(P) for q in P[i + 1:]), default=0)


def sky(t):
    """For a UTC time: Julian date pair, Sun unit vector, sidereal time, observer position, zenith."""
    jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second)
    n = jd - 2451545.0 + fr
    lst = math.radians((280.46061837 + 360.98564736629 * n) % 360) + LON
    L = math.radians((280.460 + 0.9856474 * n) % 360)
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = L + math.radians(1.915) * math.sin(g) + math.radians(0.020) * math.sin(2 * g)
    eps = math.radians(23.439)
    sv = (math.cos(lam), math.cos(eps) * math.sin(lam), math.sin(eps) * math.sin(lam))
    up = (math.cos(LAT) * math.cos(lst), math.cos(LAT) * math.sin(lst), math.sin(LAT))
    e2 = F * (2 - F)                                   # the observer on the ellipsoid
    N = RE / math.sqrt(1 - e2 * math.sin(LAT) ** 2)
    o = ((N + ALT) * up[0], (N + ALT) * up[1], (N * (1 - e2) + ALT) * math.sin(LAT))
    return jd, fr, sv, lst, o, up


def look(r, o, lst, up):
    """Elevation and azimuth (degrees) and distance (km) of a satellite at r from the observer at o."""
    d = (r[0] - o[0], r[1] - o[1], r[2] - o[2])
    rng = math.sqrt(dot(d, d))
    e = -math.sin(lst) * d[0] + math.cos(lst) * d[1]
    n = -math.sin(LAT) * math.cos(lst) * d[0] - math.sin(LAT) * math.sin(lst) * d[1] + math.cos(LAT) * d[2]
    return math.degrees(math.asin(dot(d, up) / rng)), math.degrees(math.atan2(e, n)) % 360, rng


def lit(r, sv):
    """True when the Sun lights the satellite: on the Sun's side, or outside the shadow cylinder."""
    d = dot(r, sv)
    return d > 0 or dot(r, r) - d * d > RE * RE


def satrec(x, k=0):
    """An SGP4 satellite from CelesTrak's JSON (OMM) elements. k replaces the catalogue number
    (new launches have temporary numbers too big for sgp4; the number plays no part in the orbit)."""
    d = {key: str(x[key]) for key in KEYS}
    d['NORAD_CAT_ID'] = str(k + 1)
    s = Satrec()
    omm.initialize(s, d)
    return s


def positions(sats, t):
    jd, fr = sky(t)[:2]
    return [r for e, r, _ in (s.sgp4(jd, fr) for s in sats) if e == 0]


def local(t):
    return t.astimezone(TZ).replace(tzinfo=None).isoformat(timespec='minutes')


def where(sat, t):
    """Elevation, azimuth, km, sunlit, Sun elevation at t, whatever the light (None: no position)."""
    jd, fr, sv, lst, o, up = sky(t)
    e, r, _ = sat.sgp4(jd, fr)
    if e:
        return None
    return (*look(r, o, lst, up), lit(r, sv), math.degrees(math.asin(dot(sv, up))))


def seen(sat, t, sun_dark=SUN_DARK):
    """(t, elevation, azimuth, km) when the satellite can be seen at t: dark here, sunlit, EL_HOR up."""
    jd, fr, sv, lst, o, up = sky(t)
    if math.degrees(math.asin(dot(sv, up))) > sun_dark:
        return None
    e, r, _ = sat.sgp4(jd, fr)
    if e:
        return None
    el, az, rng = look(r, o, lst, up)
    return (t, el, az, rng) if el >= EL_HOR and lit(r, sv) else None


def visible_passes(sat, now, days, sun_dark=SUN_DARK):
    """Each visible pass from `now` on, as its list of `seen` points every 5 s."""
    t, end = now, now + timedelta(days=days)
    while t < end:
        sv, up = sky(t)[2], sky(t)[5]
        sun = math.degrees(math.asin(dot(sv, up)))
        if sun > sun_dark or sun < -45:      # daylight, or deep night (a low satellite is in the shadow)
            # the Sun moves at most 1.25 degrees in 5 min: step finely near the limits, or the
            # first minutes after dusk get skipped
            near = sun_dark < sun < sun_dark + 1.5 or -46.5 < sun < -45
            t += timedelta(seconds=20) if near else timedelta(minutes=5)
            continue
        if not seen(sat, t, sun_dark):
            t += timedelta(seconds=40)
            continue
        a = t                                # inside a pass: walk back to its start, then forward
        while a > now and seen(sat, a - STEP, sun_dark):
            a -= STEP
        pts = []
        while True:
            p = seen(sat, a, sun_dark)
            if not p:
                break
            pts.append(p)
            a += STEP
        t = a + timedelta(seconds=40)
        yield pts


def horizon(sat, t, step):
    """Walk from t (above the horizon) by `step` until the satellite is under it: time, azimuth of the last point up."""
    az = where(sat, t)[1]
    for _ in range(400):
        w = where(sat, t + step)
        if not w or w[0] <= 0:
            break
        t, az = t + step, w[1]
    return t, az


def magnitude(sat, t, std):
    """Estimated visual magnitude at t (lower = brighter).

    std = the satellite's standard magnitude: at 1000 km, half lit (phase angle 90 degrees).
      mag = std + 5 log10(d / 1000) + K_PHASE * (-2.5 log10(sin p + (pi - p) cos p))
    d = distance (km), p = phase angle (Sun - satellite - observer). The last term is the
    diffuse-sphere phase law (0 at 90 degrees); K_PHASE scales it to match Heavens-Above.
    No atmospheric extinction (it dims a pass 10 degrees up by about half a magnitude)."""
    jd, fr, sv, lst, o, up = sky(t)
    e, r, _ = sat.sgp4(jd, fr)
    if e:
        return None
    rng = look(r, o, lst, up)[2]
    p = math.radians(angle(sv, (o[0] - r[0], o[1] - r[1], o[2] - r[2])))
    f = max(math.sin(p) + (math.pi - p) * math.cos(p), 1e-6)
    return std + 5 * math.log10(rng / 1000) - K_PHASE * 2.5 * math.log10(f)
