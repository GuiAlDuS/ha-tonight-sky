# How it works

This page explains every calculation behind the Tonight card: where each number
on the card comes from, how it was checked, and what it cannot do. You do not
need any of it to install the card (see the [README](../README.md)).

Four sensors feed the card. Everything is computed on your Home Assistant;
the internet is only used to fetch satellite orbits and the cloud forecast.

| Sensor | Script | What it does | Network |
|---|---|---|---|
| `sensor.tonight_sky` | `sensors/tonight.py` | Dusk, dawn, planets, Moon | none |
| `sensor.tonight_satellites` | `sensors/satellites.py` | Visible passes of four satellites | CelesTrak, a few kB every 8 h |
| `sensor.tonight_clouds` | `sensors/clouds.py` | Cloud cover per hour | Open-Meteo, hourly |
| `sensor.tonight_trains` (optional) | `sensors/trains.py` | Starlink trains | CelesTrak, 5 MB every 8 h |

The card itself (`build_card.py`) runs in your browser: it draws the stars,
places everything on the dome and writes the sentences.

## The night

"Tonight" runs from the end of civil twilight in the evening to its start at
dawn, when the Sun is 6° below the horizon. Before that, only the Moon, Venus
and Jupiter stand out; after it, stars of magnitude 3 to 4 appear, which is
about what a garden sky shows.

The script steps through the day every 5 minutes until the Sun crosses −6°,
then refines both edges to the minute. Near the poles, where the Sun does not
go that low or does not rise, the sensor says so and the card shows a single
sentence.

The sky sensor runs once an hour. An automation (in
`configuration.example.yaml`) recalculates it the minute the night ends, so
the card never shows the night that just finished.

## Planets and the Moon

Positions come from Paul Schlyter's
[low-precision orbital elements](https://stjarnhimlen.se/comp/ppcomp.html):
each planet's orbit as an ellipse that changes slowly with time, solved with
Kepler's equation, with his corrections for the pull between Jupiter and
Saturn and the main perturbations of the Moon. The result is converted to
altitude and azimuth for your location using the local sidereal time.

Checked against JPL's DE421 ephemeris (through skyfield) at 10° N over a year
of samples, the planets were within 0.03° and the Moon within about 0.1°.
The card shows whole degrees and eight compass directions, so this is far more
than it needs.

- **A planet counts as visible** while it is at least 10° above the horizon
  during the night. Lower than that, trees, buildings and haze usually hide it.
- **Its path** is sampled at dusk, every 20 minutes on the clock, and at dawn.
- **Its brightness** uses Schlyter's magnitude formulas: distance from the Sun,
  distance from the Earth and phase angle. Saturn's rings are left out, so
  Saturn can be up to about a magnitude brighter than the card says when the
  rings are wide open.
- **Uranus and Neptune** are left out: they are not visible to the naked eye.
- **The Moon's illuminated fraction** comes from the angle between the Sun and
  the Moon seen from the Earth.
- **Planets not visible tonight** get the first later night when they are 10°
  up in the dark, and whether that happens near dusk or near dawn.

## Stars and constellations

The 390 stars on the dome are every star of magnitude 3.6 or brighter, plus
the fainter ones that a constellation line needs, from the
[HYG database](https://codeberg.org/astronexus/hyg) v4 (Hipparcos positions).
The lines of 15 well-known constellations come from
[Stellarium](https://github.com/Stellarium/stellarium-skycultures)'s modern
sky culture.

Positions are J2000 and are not corrected for precession. That moves them by
about 0.36° in 2026, which cannot be seen at the dome's size. The browser
converts them to altitude and azimuth for Home Assistant's location every time
the card draws.

A constellation's name is drawn only when at least 7 in 10 of its stars are up,
at the centre of its visible stars, and only where it does not cover a planet,
the Moon or a satellite.

## The dome

The dome is the sky as seen lying on your back with your head to the north:
the centre is the point straight overhead, the rim is the horizon, and the
distance from the centre is 90° minus the altitude. Because it is read like a
map (north up, east right), it is mirrored compared with looking up. That
mirroring also applies to the Moon's lit side and to the constellations.

It shows **one moment**: now, when it is dark; before dark, tonight's best
moment (below). A body that is up then has its mark and the path it will
follow from that moment on. A body that rises later sits on the rim where it
will appear, and the timeline under the dome says when.

Mark sizes follow brightness: 9 to 16 px, from `11 − 2 × magnitude`, for
planets and satellites alike.

### The Moon's phase

The Moon is drawn as a dim disc with its sunlit part over it, turned the way
it really is:

1. The direction of the bright side is found by taking one degree along the
   great circle from the Moon towards the Sun, at the moment the dome shows.
   The Sun is computed in the browser with a low-precision formula, good to
   about 0.01°.
2. In a frame where the Sun is to the right, the lit part is the half of the
   rim on that side, closed by the terminator. The terminator is half an
   ellipse with half-width `1 − 2k`, where k is the lit fraction (0 new,
   1 full).
3. Both shapes are turned to the bright side's direction and drawn in dome
   units, so they stay round at any card size.

## Tonight's best

The headline picks one thing to look for. The same rule runs in the dome
(JavaScript) and in the text card (Jinja).

The candidates are:

- tonight's satellite passes that reach 30°: the ISS always, another satellite
  only at magnitude 0 or brighter;
- every 20-minute point at 25° or more (or the planet's highest, if it stays
  lower) of the planets that are up before 23:00.

Each candidate gets a score, and the lowest wins:

`score = past × 10000 + cloud class × 1000 + rank × 100 + (90 − altitude)`

- The cloud class is 0 under 20 % cover, 1 under 50 %, 2 under 80 %, 3 above.
- The rank is the planet's place by brightness. Satellites use `(mag + 5) × 10`
  in its place, which always ranks them above any planet.

In words: a clearer hour beats a cloudier one, a bright satellite beats a
planet, a brighter planet beats a fainter one, and higher beats lower.

## Satellites

### Orbits

The four satellites (ISS, Tiangong, Hubble and a BlueBird) are fetched one by
one from [CelesTrak](https://celestrak.org)'s GP data in the OMM JSON format,
when the local copy is more than 8 hours old. Their positions are computed
with SGP4, the standard model for these elements, using Brandon Rhodes's
[`sgp4`](https://pypi.org/project/sgp4/) library. Its pure-Python part is
included in `sensors/sgp4/`, because Home Assistant's Python cannot install
packages. Elements older than 7 days are not used: a low orbit drifts by
minutes within a week, more after a reboost.

Three simplifications, each far below what the card shows:

- **The Sun** is a low-precision direction (about 0.01°).
- **The Earth's shadow** is a cylinder with no penumbra. A real satellite
  fades over a few seconds rather than going out at once.
- **The frame.** SGP4's TEME frame is treated as the true-of-date frame, and
  the observer is turned with the mean sidereal time. Seen from the ground,
  both differ by well under a tenth of a degree.

### When a satellite can be seen

At a given moment, a satellite can be seen when all three are true:

1. it is at least 10° above the horizon;
2. the Sun lights it (it is outside the Earth's shadow);
3. your sky is dark enough: Sun below −6°, or below −4° for satellites of
   standard magnitude 0 or brighter (ISS, Tiangong), which show up in a
   still-blue sky.

The search walks the next 10 days:

- 5-minute steps while the sky is too bright;
- 20-second steps when the Sun is within 1.5° of the darkness limit, so a pass
  in the first minutes after dusk is not stepped over;
- 40-second steps through the night;
- once a moment of visibility is found, back and forward in 5-second steps to
  the exact start and end of the pass.

The deep night (Sun below −45°) is skipped: at that hour a low satellite is
always in the Earth's shadow.

For each pass the sensor gives the rise (over the horizon, lit or not), the
first moment it can be seen, the highest point while it can be seen, and where
it ends. It ends either in the Earth's shadow ("fades at 31° as it enters
Earth's shadow") or at the horizon or in the dawn. Passes seen for less than a
minute are dropped.

What the card lists:

- every ISS pass;
- for the other three, passes of magnitude 5.5 or brighter that reach 15° (a
  pass fainter than 5.5 is lost in the twilight);
- at most five passes a night, the ISS first, then the brightest.

The card says how bright each pass is in words and as a magnitude, so faint
passes are listed but marked as faint.

**Check.** Before this version, the passes came from N2YO's API. For four
days, both were computed side by side for the same place: 13 passes found by
both, highest point within 4 seconds and 0.2° of height, direction within 1–4°.
The two passes that only N2YO listed were limits, not orbit errors: N2YO
accepts a brighter sky and counts a pass from lower down.

### Brightness

A satellite's brightness depends on three things: how reflective it is, how
far away it is, and how much of its sunlit side faces you. That last part is
the phase angle, the angle at the satellite between the Sun and you:

- near 0°, the Sun is behind you and you see the satellite fully lit;
- near 180°, you look towards the Sun and see mostly its dark side.

The estimate is

```
mag = std + 5 log10(d / 1000 km) + K × (−2.5 log10(sin p + (π − p) cos p))
```

- `std`, the standard magnitude: how bright the satellite is at 1000 km, half
  lit (phase angle 90°);
- `d`, the distance in km;
- `p`, the phase angle;
- the last term, the phase law of a dull, evenly lit sphere: zero at 90°,
  −1.2 magnitudes (brighter) at full face, more than +2 (fainter) beyond 135°;
- `K`, a share of that law (below).

The card gives the brightest moment of the visible part of the pass.

| Satellite | `std` |
|---|---|
| ISS | −1.8 |
| Tiangong | 0.0 |
| Hubble | 2.2 |
| BlueBird | 4.5 |

**Check against Heavens-Above.** [Heavens-Above](https://www.heavens-above.com)
is the pass-prediction site many satellite observers use, and it estimates
brightness with the phase angle. Its pass tables were compared with the
formula for six cities: Madrid, Tokyo, Buenos Aires, Mexico City, Sydney and
Miami. Nairobi and Singapore had no passes. The comparison covered 198 passes
between 19 and 28 November 2026, with phase angles from 31° to 135°. For each
pass the formula was evaluated at the same place, at Heavens-Above's times,
from the same CelesTrak orbits.

Heavens-Above minus the formula, in magnitudes (0 = the same; positive = the
formula is too bright):

| Satellite | Passes | Distance only (K = 0) | Full sphere law (K = 1) | K = 0.32 |
|---|---|---|---|---|
| ISS | 38 | +0.12 ± 0.36 (worst +0.75) | −0.20 ± 0.63 (worst −1.32) | +0.00 ± 0.07 (worst −0.13) |
| Tiangong | 62 | +0.14 ± 0.32 (worst +0.75) | −0.05 ± 0.58 (worst −1.34) | +0.04 ± 0.08 (worst +0.25) |
| Hubble | 61 | −0.02 ± 0.29 (worst +0.69) | +0.14 ± 0.49 (worst −1.35) | +0.00 ± 0.08 (worst +0.20) |
| BlueBird, `std` 3.8 | 37 | +0.75 ± 0.29 | +0.79 ± 0.49 | +0.72 ± 0.09 |
| BlueBird, `std` 4.5 | 37 | | | +0.02 ± 0.09 (worst −0.16) |

The same comparison by phase angle shows why: without the phase term, the
error grows steadily with the angle, and the full sphere law overshoots the
other way.

| Phase angle | Passes | Distance only | Full sphere law | K = 0.32 |
|---|---|---|---|---|
| 30–60° | 58 | −0.27 | +0.51 | −0.05 |
| 60–90° | 77 | +0.04 | +0.21 | +0.04 |
| 90–120° | 32 | +0.26 | −0.37 | +0.05 |
| 120–135° | 31 | +0.59 | −1.07 | +0.06 |

What came out of it:

- **Heavens-Above uses about a third of the sphere law.** Any K from 0.30 to
  0.40 fits about equally well (spread 0.07 to 0.09 magnitudes over all 198
  passes); the card uses 0.32.
- **The standard magnitudes of the ISS, Tiangong and Hubble needed no change**
  (mean differences under 0.05).
- **BlueBird was 0.7 too bright**, with the same phase behaviour, so its
  standard magnitude was set to Heavens-Above's 4.5.
- **The card shows the brightest moment of the pass**, as Heavens-Above does.

**Limits.**

- Heavens-Above is a model too. This shows the card agrees with the reference
  most observers use, not with measurements.
- Real satellites are not spheres. Solar panels and flat antennas can flare
  for a few seconds, and BlueBird's large antenna does this most.
- There is no atmospheric extinction: a pass 10° up looks about half a
  magnitude dimmer than the figure.

### Brightness words

| Magnitude | Words |
|---|---|
| −1 or less | very bright |
| up to 1 | bright |
| up to 2.5 | medium brightness |
| up to 4 | faint |
| more than 4 | very faint, best with binoculars |

Magnitudes run backwards: lower is brighter, and the brightest objects are
negative (Venus about −4.5). The naked eye reaches about 6 in a dark sky, and
3 to 4 in a town.

## Starlink trains (optional)

For a few days after a launch, a batch of Starlink satellites travels in a
row, low and close together. It is seen as a line of lights crossing the sky
shortly after dusk or before dawn. The satellites then raise their orbits and
spread round the Earth, and within days there is no train left.

New satellites have no catalogue numbers yet, so they cannot be fetched one by
one. The script downloads CelesTrak's supplemental Starlink file instead:
SpaceX's own orbit data, about 5 MB, every 8 hours. Then:

1. The satellites are grouped by launch: the first eight characters of the
   international designator, for example `2026-256`.
2. Only the eight newest launches are looked at, and of those only the ones
   still within 90° of orbit are kept. The kept groups are a few kB, so
   offline runs work.
3. For each group, the satellite nearest its middle stands for the train. Its
   passes are found with the same search as the other satellites.
4. A pass is listed when it reaches 20°, the whole group is still within 25°
   of orbit at that moment, and the orbit data is less than 3.5 days old at the
   time of the pass. Satellites raising their orbit make older data a few
   minutes off.

There is no brightness for trains: new satellites change attitude and height
in their first days.

## Clouds

The cloud cover per hour comes from [Open-Meteo](https://open-meteo.com):
total, low, mid and high cloud and the chance of rain, for your location. Many
weather integrations give a condition ("partly cloudy") but no cover per hour.
The strip under the timeline shows the total cover in each hour cell, as a
number and as the cell's opacity. The headline's "Will it be visible?" uses the
classes from *Tonight's best*: clear under 20 %, partly cloudy under 50 %,
cloudy under 80 %, very cloudy above.

## Updates and offline use

| What | How often |
|---|---|
| Sky sensor | hourly, and at the end of each night (automation) |
| Satellite passes | every 2 hours, from the stored orbits (fetched every 8 h) |
| Trains | every 2 hours (file fetched every 8 h) |
| Clouds | hourly |
| The card | redraws every 10 minutes |

Each script keeps its last good data beside it. Without internet the passes
are still recomputed from the stored orbits (for up to 7 days), and the
clouds keep their last forecast.

## Accuracy at a glance

| Quantity | Accuracy | Checked against |
|---|---|---|
| Planet positions | 0.03° | JPL DE421 |
| Moon position | about 0.1° | JPL DE421 |
| Satellite pass times | a few seconds | N2YO, 13 passes |
| Satellite heights | 0.2° | N2YO, 13 passes |
| Satellite brightness | ±0.1 magnitude (worst 0.25) | Heavens-Above, 198 passes |
| Star positions | 0.4° (no precession) | |
| Train pass times | a minute or two, two or three days ahead | |
