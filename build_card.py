#!/usr/bin/env python3
"""
Builds the "Tonight" dashboard section for Home Assistant: a sky dome with a
timeline and a cloud strip (one plotly-graph card) and the same information as
plain sentences (one markdown card).

You only need this to change the card (wording, colours, satellites, a new
language): the ready-made sections are in cards/, one file per language.

  python3 build_card.py          # rewrites cards/tonight_section.<language>.yaml

Each output is one dashboard section (two cards) to paste into a sections-view
dashboard. Needs PyYAML (`pip install pyyaml`). The card takes the location
from Home Assistant in the browser (hass.config), so the files hold no
coordinates and are the same for everybody.

How the card is put together
  * One hidden helper trace computes everything once in the browser (BUILD)
    and leaves it in `vars`; the visible traces only read it.
  * The dome shows ONE moment: now, when it is dark; before dark, the best
    moment of the coming night. A body that is up at that moment has its mark
    and the path it will follow from then on; a body that rises later sits on
    the horizon rim where it will appear. When each one can be seen is the
    timeline under the dome, on the same hour axis as the cloud strip.
  * Each planet has one colour and one symbol (BODY). Satellites share the
    diamond and a dashed path and have a colour each (SAT_C). The colours were
    checked for colour-blind separation on the dome's night blue.
  * "Tonight's best" is chosen by the same rule in the dome (JavaScript, BUILD)
    and in the text (Jinja, PRELUDE): keep the two in step when changing it.
    Candidates are tonight's satellite passes that reach 30 degrees (the ISS
    always; another satellite only at magnitude 0 or brighter) and every 20-min
    point at 25 degrees or more of the planets that are up before 23:00.
    Score = past * 10000 + cloud class * 1000 + rank * 100 + (90 - altitude),
    lowest wins: a clearer hour beats a cloudy one, a satellite beats a planet,
    a brighter planet a fainter one, higher beats lower.
  * Both cards are one fixed "night panel" in light and dark themes.

All wording lives in LANG (English and Spanish). To add a language, copy one
block and translate it.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent

SKY = '#101a33'                     # the dome's night blue, both themes
INK = 'rgba(232, 236, 244, {a})'    # light ink on the dome
NIGHT_BG = '#0b1226'                # the cards, a step darker so the horizon shows
NIGHT_CARD = ('ha-card { background: %s !important; color: #dadfe8;'
              ' --card-background-color: %s; --ha-card-background: %s;'
              ' --primary-text-color: #dadfe8; --secondary-text-color: #a3a9b7;'
              ' --divider-color: rgba(232, 236, 244, 0.14); }\n' % (NIGHT_BG, NIGHT_BG, NIGHT_BG))
MOON = '#f4f1e8'
# one colour and one symbol per planet (colour + shape, so identity is never colour alone)
BODY = {
    'mercury': ('#6fd6ff', 'triangle-up'),
    'venus': ('#fff3a6', 'star'),
    'mars': ('#ff6f4f', 'circle'),
    'jupiter': ('#ffb54d', 'square'),
    'saturn': ('#b49cff', 'cross'),
}
GLYPH = {'triangle-up': '▲', 'star': '★', 'circle': '●', 'square': '■', 'cross': '✚'}
# satellites: one shape (diamond), a colour each, by NORAD id (see sensors/satellites.py)
SAT_C = {25544: '#ffffff', 48274: '#e867c3', 20580: '#44b782', 61047: '#faa9c1'}
N_SLOTS = 5
X0 = 0.2            # left edge of the timeline / strip; row labels to its left
DOME_COLS = 12      # of the section's 24 columns; the text card takes the rest

# ---------------------------------------------------------------------------------------
# Wording. `js` holds JavaScript (template literals) for the dome; `jinja` holds the macros
# of the text card. Satellites: [inside a sentence, start of a list line, timeline label].
# ---------------------------------------------------------------------------------------
LANG = {
    'en': {
        'heading': 'Tonight', 'dome_title': 'The sky tonight', 'clouds_row': 'Clouds (%)',
        'compass': ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'],
        'dirs': ['north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest'],
        'bodies': {'mercury': 'Mercury', 'venus': 'Venus', 'mars': 'Mars', 'jupiter': 'Jupiter', 'saturn': 'Saturn'},
        'moon': 'Moon',
        'sats': {25544: ['the Space Station', 'Space Station (ISS)', 'ISS'],
                 48274: ['the Chinese station Tiangong', 'Chinese station Tiangong', 'Tiangong'],
                 20580: ['the Hubble telescope', 'Hubble telescope', 'Hubble'],
                 61047: ['the BlueBird satellite', 'BlueBird satellite', 'BlueBird']},
        'constellations': {'Ori': 'Orion', 'CMa': 'Canis Major', 'Tau': 'Taurus', 'Gem': 'Gemini', 'Leo': 'Leo',
                           'UMa': 'Ursa Major', 'Cas': 'Cassiopeia', 'Cyg': 'Cygnus', 'Lyr': 'Lyra', 'Aql': 'Aquila',
                           'Sco': 'Scorpius', 'Sgr': 'Sagittarius', 'Cru': 'Southern Cross', 'Cen': 'Centaurus',
                           'Boo': 'Boötes'},
        'stars': {32349: 'Sirius', 30438: 'Canopus', 69673: 'Arcturus', 91262: 'Vega', 24608: 'Capella',
                  24436: 'Rigel', 37279: 'Procyon', 27989: 'Betelgeuse', 97649: 'Altair', 21421: 'Aldebaran',
                  65474: 'Spica', 80763: 'Antares', 37826: 'Pollux', 113368: 'Fomalhaut', 102098: 'Deneb',
                  49669: 'Regulus', 11767: 'Polaris'},
        'js': r"""{
    where: (who, t, alt, dir) => `${who}, ${t}<br>${alt}° up, to the ${dir}`,
    star: (name, alt, dir) => `${name} (star)<br>${alt}° up, to the ${dir}`,
    rim: (who, t, dir) => `${who}: visible from ${t},<br>in the ${dir}`,
    satMark: (name, t, el, d1, d2) => `${name}, ${t}<br>up to ${el}°, from the ${d1} to the ${d2}`,
    passTip: (name, t, min, el, d1, d2) => `${name}, ${t}<br>about ${min} min, up to ${el}°,<br>from the ${d1} to the ${d2}`,
    cloudTip: (t, c, lo, mi, hi, pp) => `${t}: ${c} % cloud<br><span style="font-size:11px">low ${lo} %, mid ${mi} %, high ${hi} %; rain ${pp} %</span>`,
    best: (who, t) => `Best: ${who}, ${t}`,
    mapNow: t => `Map time: now, ${t}`,
    mapBest: (who, t) => `Map time: the best, ${who}, ${t}`,
    mapAt: t => `Map time: ${t}`,
    fromNow: 'from now on', fromAt: t => `from ${t} on`,
    notePath: f => [`Each line is the path that body will follow across the sky ${f}.`,
                    `Each line is the path that body<br>will follow across the sky ${f}.`],
    noteRim: ['Bodies on the rim of the dome rise later tonight.', 'Bodies on the rim of the dome<br>rise later tonight.'],
    span: (a, b, dusk, dawn) => `visible from ${dusk ? 'dusk' : a} until ${dawn ? 'dawn' : b}`,
    moonRow: (lit, span) => `Moon (${lit} % lit): ${span}`,
    subNow: t => `Now, at ${t}`, subBest: t => `The sky at its best, at ${t}`, subAt: t => `The sky at ${t}`,
    clouds: c => ` · ${c} % cloud`,
    noNight: 'It does not get dark tonight at this latitude',
  }""",
        'jinja': """\
{%- set dirs = ['north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest'] -%}
{%- set days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] -%}
{%- set months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'] -%}
{%- set title = 'In the sky' -%}
{%- macro level(m) %}{{ 'very bright' if m <= -1 else 'bright' if m <= 1 else 'medium brightness' if m <= 2.5 else 'faint' }}{% endmacro -%}
{%- macro height(a) %}{{ 'almost overhead' if a >= 70 else 'high' if a >= 40 else 'low' }}{% endmacro -%}
{%- macro day(t) -%}
{%- set d = as_datetime(t) -%}{%- set k = (d.date() - now().date()).days -%}
{{ 'today' if k == 0 else 'tomorrow' if k == 1 else 'on ' ~ days[d.weekday()] ~ ' ' ~ d.day ~ ' ' ~ months[d.month - 1] }}
{%- endmacro -%}
{%- macro cloud(t) -%}
{%- set c = cover(t) -%}
{%- if c != '' %}{%- set c = c | int -%}{{ c }} % cloud: {{ 'clear' if c < 20 else 'partly cloudy' if c < 50 else 'cloudy' if c < 80 else 'very cloudy, hard to see' }}{% endif -%}
{%- endmacro -%}
{%- macro pass_words(q) -%}
about {{ ((q.duration / 60) | round) | int }} min, from the {{ dirn(q.az_start) }} to the {{ dirn(q.az_end) }}, up to {{ q.el_max }}°
{%- if q.el_end >= 10 %}; fades at {{ q.el_end }}° as it enters Earth's shadow{% endif %}
{%- endmacro -%}
{%- macro hl_sat(p) -%}
Tonight's best: {{ sat_name(p.id, 0) }} at {{ hm(p.visible) }}, {{ height(p.el_max) }}.
{%- endmacro -%}
{%- macro hl_planet(b) -%}
Tonight's best: {{ names[b.id] }}, {{ height(b.alt_max) }}
{%- if b.t_max == n.end %} in the {{ dirn(b.az_max) }} before dawn.
{%- elif b.t_max == n.start %} in the {{ dirn(b.az_max) }} at dusk.
{%- else %} at {{ hm(b.t_max) }}, in the {{ dirn(b.az_max) }}.{% endif %}
{%- endmacro -%}
{%- macro hl_none() %}No planets or satellites in view tonight.{% endmacro -%}
{%- macro no_night() %}It does not get dark tonight at this latitude.{% endmacro -%}
{%- macro can_see(t) %}Will it be visible? At {{ hm(t) }}, {{ cloud(t) }}.{% endmacro -%}
{%- macro sat_line(p) -%}
{{ diamond(p.id) }}{{ sat_name(p.id, 1) }} · {{ level(p.mag) }}: {{ day(p.visible) }} at {{ hm(p.visible) }}, {{ pass_words(p) }}.
{%- endmacro -%}
{%- macro planet_line(p) -%}
{{ mark(p.id) }}{{ names[p.id] }} · {{ level(p.mag) }}:
{%- if p.t_max == n.end and p.start != n.start %} rises in the {{ dirn(p.az_start) }}; visible from {{ hm(p.start) }} until dawn, when it is {{ p.alt_max }}° up.
{%- else %} {{ 'from dusk' if p.start == n.start else 'from ' ~ hm(p.start) ~ ' (in the ' ~ dirn(p.az_start) ~ ')' }}
{{- ' until dawn' if p.end == n.end else ' until ' ~ hm(p.end) }};
{%- if p.t_max == n.start %} highest at dusk, {{ p.alt_max }}° up in the {{ dirn(p.az_max) }}.
{%- elif p.t_max == n.end %} highest at dawn, {{ p.alt_max }}° up in the {{ dirn(p.az_max) }}.
{%- else %} highest at {{ hm(p.t_max) }}, in the {{ dirn(p.az_max) }} ({{ p.alt_max }}°).{% endif %}{% endif %}
{%- endmacro -%}
{%- macro iss_absent(nx) -%}
{{ diamond(25544) }}{{ sat_name(25544, 1) }} · no pass tonight.
{%- if nx %}{% set q = nx[0] %} Next visible {{ day(q.visible) }} at {{ hm(q.visible) }}, {{ pass_words(q) }} ({{ level(q.mag) }}).
{%- else %} No visible pass in the next 10 days.{% endif %}
{%- endmacro -%}
{%- macro upcoming_line(q) -%}
{{ mark(q.id) }}{{ names[q.id] }} · not visible these days, it is close to the Sun. Visible again {{ day(q.start) }},
{{- ' shortly before dawn' if q.when == 'dawn' else ' shortly after dusk' if q.when == 'dusk' else ' at ' ~ hm(q.start) }}, low in the {{ dirn(q.az_start) }}.
{%- endmacro -%}
""",
    },
    'es': {
        'heading': 'Esta noche', 'dome_title': 'El cielo esta noche', 'clouds_row': 'Nubes (%)',
        'compass': ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO'],
        'dirs': ['norte', 'noreste', 'este', 'sureste', 'sur', 'suroeste', 'oeste', 'noroeste'],
        'bodies': {'mercury': 'Mercurio', 'venus': 'Venus', 'mars': 'Marte', 'jupiter': 'Júpiter', 'saturn': 'Saturno'},
        'moon': 'Luna',
        'sats': {25544: ['la Estación Espacial', 'Estación Espacial (ISS)', 'ISS'],
                 48274: ['la estación china Tiangong', 'Estación china Tiangong', 'Tiangong'],
                 20580: ['el telescopio Hubble', 'Telescopio Hubble', 'Hubble'],
                 61047: ['el satélite BlueBird', 'Satélite BlueBird', 'BlueBird']},
        'constellations': {'Ori': 'Orión', 'CMa': 'Can Mayor', 'Tau': 'Tauro', 'Gem': 'Géminis', 'Leo': 'Leo',
                           'UMa': 'Osa Mayor', 'Cas': 'Casiopea', 'Cyg': 'Cisne', 'Lyr': 'Lira', 'Aql': 'Águila',
                           'Sco': 'Escorpión', 'Sgr': 'Sagitario', 'Cru': 'Cruz del Sur', 'Cen': 'Centauro',
                           'Boo': 'Boyero'},
        'stars': {32349: 'Sirio', 30438: 'Canopus', 69673: 'Arturo', 91262: 'Vega', 24608: 'Capella',
                  24436: 'Rigel', 37279: 'Proción', 27989: 'Betelgeuse', 97649: 'Altair', 21421: 'Aldebarán',
                  65474: 'Espiga', 80763: 'Antares', 37826: 'Pólux', 113368: 'Fomalhaut', 102098: 'Deneb',
                  49669: 'Régulo', 11767: 'Polar'},
        'js': r"""{
    where: (who, t, alt, dir) => `${who}, ${t}<br>${alt}° de altura, al ${dir}`,
    star: (name, alt, dir) => `${name} (estrella)<br>${alt}° de altura, al ${dir}`,
    rim: (who, t, dir) => `${who}: se ve desde las ${t},<br>por el ${dir}`,
    satMark: (name, t, el, d1, d2) => `${name}, ${t}<br>hasta ${el}° de altura, del ${d1} al ${d2}`,
    passTip: (name, t, min, el, d1, d2) => `${name}, ${t}<br>unos ${min} min, hasta ${el}° de altura,<br>del ${d1} al ${d2}`,
    cloudTip: (t, c, lo, mi, hi, pp) => `${t}: ${c} % de nubes<br><span style="font-size:11px">bajas ${lo} %, medias ${mi} %, altas ${hi} %; lluvia ${pp} %</span>`,
    best: (who, t) => `Lo mejor: ${who}, ${t}`,
    mapNow: t => `Hora del mapa: ahora, ${t}`,
    mapBest: (who, t) => `Hora del mapa: lo mejor, ${who}, ${t}`,
    mapAt: t => `Hora del mapa: ${t}`,
    fromNow: 'desde ahora', fromAt: t => `desde las ${t}`,
    notePath: f => [`La línea de cada astro es el camino que seguirá en el cielo ${f}.`,
                    `La línea de cada astro es el camino<br>que seguirá en el cielo ${f}.`],
    noteRim: ['Los astros en el borde del domo salen más tarde esta noche.', 'Los astros en el borde del domo<br>salen más tarde esta noche.'],
    span: (a, b, dusk, dawn) => `se ve desde ${dusk ? 'que oscurece' : 'las ' + a} hasta ${dawn ? 'el amanecer' : 'las ' + b}`,
    moonRow: (lit, span) => `Luna (${lit} %): ${span}`,
    subNow: t => `Ahora, a las ${t}`, subBest: t => `Así se verá lo mejor, a las ${t}`, subAt: t => `Así se verá a las ${t}`,
    clouds: c => ` · ${c} % de nubes`,
    noNight: 'Esta noche no oscurece en esta latitud',
  }""",
        'jinja': """\
{%- set dirs = ['norte', 'noreste', 'este', 'sureste', 'sur', 'suroeste', 'oeste', 'noroeste'] -%}
{%- set days = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom'] -%}
{%- set months = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'] -%}
{%- set title = 'Astros' -%}
{%- macro level(m) %}{{ 'muy brillante' if m <= -1 else 'brillante' if m <= 1 else 'brillo medio' if m <= 2.5 else 'tenue' }}{% endmacro -%}
{%- macro height(a) %}{{ 'casi sobre la cabeza' if a >= 70 else 'alto' if a >= 40 else 'bajo' }}{% endmacro -%}
{%- macro day(t) -%}
{%- set d = as_datetime(t) -%}{%- set k = (d.date() - now().date()).days -%}
{{ 'hoy' if k == 0 else 'mañana' if k == 1 else 'el ' ~ days[d.weekday()] ~ ' ' ~ d.day ~ ' ' ~ months[d.month - 1] }}
{%- endmacro -%}
{%- macro cloud(t) -%}
{%- set c = cover(t) -%}
{%- if c != '' %}{%- set c = c | int -%}{{ c }} % de nubes: {{ 'despejado' if c < 20 else 'algo nublado' if c < 50 else 'nublado' if c < 80 else 'muy nublado, difícil de ver' }}{% endif -%}
{%- endmacro -%}
{%- macro pass_words(q) -%}
unos {{ ((q.duration / 60) | round) | int }} min, del {{ dirn(q.az_start) }} al {{ dirn(q.az_end) }}, hasta {{ q.el_max }}°
{%- if q.el_end >= 10 %}; se apaga a {{ q.el_end }}° al entrar en la sombra de la Tierra{% endif %}
{%- endmacro -%}
{%- macro hl_sat(p) -%}
Lo mejor de esta noche: {{ sat_name(p.id, 0) }} a las {{ hm(p.visible) }}, {{ height(p.el_max) }}.
{%- endmacro -%}
{%- macro hl_planet(b) -%}
Lo mejor de esta noche: {{ names[b.id] }}, {{ height(b.alt_max) }}
{%- if b.t_max == n.end %} al {{ dirn(b.az_max) }} antes del amanecer.
{%- elif b.t_max == n.start %} al {{ dirn(b.az_max) }} al oscurecer.
{%- else %} a las {{ hm(b.t_max) }}, al {{ dirn(b.az_max) }}.{% endif %}
{%- endmacro -%}
{%- macro hl_none() %}Esta noche no hay planetas ni satélites a la vista.{% endmacro -%}
{%- macro no_night() %}Esta noche no oscurece en esta latitud.{% endmacro -%}
{%- macro can_see(t) %}¿Se podrá ver? A las {{ hm(t) }}, {{ cloud(t) }}.{% endmacro -%}
{%- macro sat_line(p) -%}
{{ diamond(p.id) }}{{ sat_name(p.id, 1) }} · {{ level(p.mag) }}: {{ day(p.visible) }} a las {{ hm(p.visible) }}, {{ pass_words(p) }}.
{%- endmacro -%}
{%- macro planet_line(p) -%}
{{ mark(p.id) }}{{ names[p.id] }} · {{ level(p.mag) }}:
{%- if p.t_max == n.end and p.start != n.start %} sale por el {{ dirn(p.az_start) }}; visible desde las {{ hm(p.start) }} hasta el amanecer, cuando está a {{ p.alt_max }}°.
{%- else %} {{ 'desde que oscurece' if p.start == n.start else 'desde las ' ~ hm(p.start) ~ ' (por el ' ~ dirn(p.az_start) ~ ')' }}
{{- ' hasta el amanecer' if p.end == n.end else ' hasta las ' ~ hm(p.end) }};
{%- if p.t_max == n.start %} lo más alto al oscurecer, a {{ p.alt_max }}° al {{ dirn(p.az_max) }}.
{%- elif p.t_max == n.end %} lo más alto al amanecer, a {{ p.alt_max }}° al {{ dirn(p.az_max) }}.
{%- else %} lo más alto a las {{ hm(p.t_max) }}, al {{ dirn(p.az_max) }} ({{ p.alt_max }}°).{% endif %}{% endif %}
{%- endmacro -%}
{%- macro iss_absent(nx) -%}
{{ diamond(25544) }}{{ sat_name(25544, 1) }} · no pasa esta noche.
{%- if nx %}{% set q = nx[0] %} Vuelve a verse {{ day(q.visible) }} a las {{ hm(q.visible) }}, {{ pass_words(q) }} ({{ level(q.mag) }}).
{%- else %} Ningún paso visible en los próximos 10 días.{% endif %}
{%- endmacro -%}
{%- macro upcoming_line(q) -%}
{{ mark(q.id) }}{{ names[q.id] }} · no se ve estos días, está cerca del Sol. Vuelve a verse {{ day(q.start) }},
{{- ' poco antes del amanecer' if q.when == 'dawn' else ' poco después de oscurecer' if q.when == 'dusk' else ' a las ' ~ hm(q.start) }}, bajo por el {{ dirn(q.az_start) }}.
{%- endmacro -%}
""",
    },
}

# ---------------------------------------------------------------------------------------
# The dome's helper: computes everything once into `vars` (plotly-graph `filters: fn`).
# __TOKENS__ are replaced in build(); the JavaScript itself is not a format string.
# ---------------------------------------------------------------------------------------
BUILD = r"""({xs, ys, vars, hass}) => {
  const S = __S__;
  const BODY = __BODY__, GLYPH = __GLYPH__, SATC = __SATC__, NAME = __NAME__, SATN = __SATN__;
  const DIRS = __DIRS__, CONS = __CONS__, STARN = __STARN__, MOONNAME = __MOONNAME__;
  const LAT = hass.config.latitude, LON = hass.config.longitude, R = Math.PI / 180;
  const attrs = id => (hass.states[id] || {attributes: {}}).attributes;
  const A = attrs('__E_SKY__'), I = attrs('__E_SAT__'), C = attrs('__E_CLD__');
  const ps = A.planets || [], n = A.night || null, L = A.moon || {};
  const empty = () => { for (const k of ['sR','sT','sS','sO','cR','cT','cD','nR','nT','nD','qR','qT','qX','iR','iT','iD',
      'kX','kC','kTxt','kTC','kD','kTV','kTT','TX','tV','tT','bY','bC','bD','bB','bX','lX','lY','lT','eX','eY','eD','eC']) vars[k] = [];
    vars.slots = []; vars.moon = null; vars.iM = null; vars.iC = '#ffffff'; vars.key = null; vars.TN = ''; vars.nota = ['', ''];
    vars.tN = 0; vars.kRange = [new Date(), new Date(Date.now() + 432e5)]; };
  if (!n) { empty(); vars.sub = A.night === null ? S.noNight : ''; return {xs, ys}; }
  const now = Date.now(), nd = new Date(n.start).getTime(), nh = new Date(n.end).getTime();
  const dark = now >= nd && now <= nh;
  const day0 = n.start.slice(0, 10), d0 = new Date(day0 + 'T00:00').getTime();
  const hm = ms => new Date(ms).toTimeString().slice(0, 5);
  const DIR = az => DIRS[Math.floor((az + 22.5) / 45) % 8];
  const satName = (id, k) => (SATN[id] || [`satellite ${id}`, `Satellite ${id}`, String(id)])[k];
  const where = (who, t, al, az) => S.where(who, hm(t), Math.round(al), DIR(az));
  // "tonight's best": the SAME rule as the text card's PRELUDE (Jinja); keep them in step
  const CL = (C.hours || []).map(x => [new Date(x[0]).getTime(), x[1]]);
  const cls = t => { const c = CL.find(x => x[0] <= t && t < x[0] + 36e5); return !c ? 0 : c[1] < 20 ? 0 : c[1] < 50 ? 1 : c[1] < 80 ? 2 : 3; };
  const d1 = new Date(new Date(day0 + 'T12:00').getTime() + 864e5).toISOString().slice(0, 10);
  const iso = h => (h >= '12:00' ? day0 : d1) + 'T' + h;
  const nowS = new Date(now - new Date(now).getTimezoneOffset() * 6e4).toISOString().slice(0, 16);
  let key = null, kS = 1e9;
  (I.passes || []).filter(x => x.visible < n.end && x.end > nowS && x.el_max >= 30 && (x.id == 25544 || x.mag <= 0)).forEach(x => {
    const sc = cls(new Date(x.visible).getTime()) * 1000 + Math.round((x.mag + 5) * 10);
    if (sc < kS) { kS = sc; key = [new Date(x.visible).getTime(), satName(x.id, 2)]; } });
  const early = ps.filter(p => p.start < day0 + 'T23:00'), pool = (early.length ? early : ps).slice().sort((a, b) => a.mag - b.mag);
  pool.forEach((p, i) => { const lim = Math.min(25, p.alt_max);
    (p.path || []).forEach(([h, al]) => { const t = iso(h);
      if (al < lim || t < p.start || t > p.end) return;
      const sc = (t < nowS ? 10000 : 0) + cls(new Date(t).getTime()) * 1000 + (i + 1) * 100 + (90 - al);
      if (sc < kS) { kS = sc; key = [new Date(t).getTime(), NAME[p.id] || p.id]; } }); });
  // the dome's moment: now when dark; before dark the best moment, else 20:00 (or an hour after dusk)
  const best_T = key && key[0] >= nd && key[0] <= nh;
  const T = dark ? now : best_T ? key[0] : Math.max(new Date(day0 + 'T20:00').getTime(), nd + 36e5);
  const path = r => (r || []).map(([h, al, az]) => { let t = d0 + (+h.slice(0, 2) * 60 + +h.slice(3, 5)) * 6e4;
    if (t < nd - 18e5) t += 864e5; return [t, al, az]; });
  const at = (r, t) => { if (!r.length || t < r[0][0] || t > r[r.length - 1][0]) return null;
    const i = r.findIndex(x => x[0] >= t); if (i <= 0) return r[0];
    const [ta, aa, za] = r[i - 1], [tb, ab, zb] = r[i], f = (t - ta) / (tb - ta);
    const dz = ((zb - za + 540) % 360) - 180; return [t, aa + (ab - aa) * f, (za + dz * f + 360) % 360]; };
  const rr = alt => 90 - alt;

  // stars and constellations at T (J2000 positions, local sidereal time)
  const D = T / 864e5 + 2440587.5 - 2451545;
  const lst = ((280.46061837 + 360.98564736629 * D + LON) % 360 + 360) % 360;
  const sl = Math.sin(LAT * R), cl = Math.cos(LAT * R);
  const altaz = (ra, dec) => { const H = (lst - ra) * R, sd = Math.sin(dec * R), cd = Math.cos(dec * R);
    const alt = Math.asin(sd * sl + cd * cl * Math.cos(H)) / R;
    const az = (Math.atan2(-cd * Math.sin(H), sd * cl - cd * sl * Math.cos(H)) / R + 360) % 360; return [alt, az]; };
  const SK = __STARS__, pos = {};
  vars.sR = []; vars.sT = []; vars.sS = []; vars.sO = [];
  for (const [h, ra, dec, m] of SK.s) { const [al, az] = altaz(ra, dec); pos[h] = [al, az, m];
    if (al > 0) { vars.sR.push(rr(al)); vars.sT.push(az); vars.sS.push(Math.max(1.6, 6.5 - 1.3 * (m + 1.5)));
      vars.sO.push(Math.max(0.35, Math.min(1, 1.05 - 0.17 * m))); } }
  vars.cR = []; vars.cT = []; vars.cD = [];
  for (const [abbr, polys] of Object.entries(SK.l)) for (const poly of polys) {
    for (const h of poly) { const p = pos[h];
      if (p && p[0] > 0) { vars.cR.push(rr(p[0])); vars.cT.push(p[1]); vars.cD.push(CONS[abbr] || abbr); }
      else { vars.cR.push(null); vars.cT.push(null); vars.cD.push(''); } }
    vars.cR.push(null); vars.cT.push(null); vars.cD.push(''); }
  // constellation names: the only text on the dome, at the centroid of the visible stars of
  // constellations that are mostly (7 in 10 stars) up; placed after the bodies, below
  const KN = [];
  for (const [abbr, polys] of Object.entries(SK.l)) {
    const all = [...new Set(polys.flat())], vis = all.map(h => pos[h]).filter(p => p && p[0] > 0);
    if (!vis.length || vis.length < 0.7 * all.length) continue;
    const x = vis.reduce((s, p) => s + Math.sin(p[1] * R) * rr(p[0]), 0) / vis.length;
    const y = vis.reduce((s, p) => s + Math.cos(p[1] * R) * rr(p[0]), 0) / vis.length;
    const r = Math.hypot(x, y); if (r < 80) KN.push([r, (Math.atan2(x, y) / R + 360) % 360, CONS[abbr] || abbr]); }
  vars.nR = []; vars.nT = []; vars.nD = [];
  for (const h of SK.named) { const p = pos[h];
    if (p && p[0] > 0 && STARN[h]) { vars.nR.push(rr(p[0])); vars.nT.push(p[1]); vars.nD.push(S.star(STARN[h], Math.round(p[0]), DIR(p[1]))); } }

  // bodies. Up at T: the mark where it is then and its path from T on. Not up yet: a mark on
  // the horizon rim where it will appear; when lives in the timeline.
  const body = (who, r, start) => { const q = at(r, T);
    if (q && q[1] >= 0) { const f = [q, ...r.filter(x => x[0] > T)];
      return {r: rr(q[1]), t: q[2], rim: false, d: where(who, q[0], q[1], q[2]),
        pr: f.map(x => rr(x[1])), pt: f.map(x => x[2]), pd: f.map(x => where(who, ...x))}; }
    const s = start && start > T ? at(r, start) : null;
    if (s) return {r: 90, t: s[2], rim: true, d: S.rim(who, hm(start), DIR(s[2])), pr: [], pt: [], pd: []};
    return {r: null, t: null, rim: false, d: '', pr: [], pt: [], pd: []}; };
  vars.slots = ps.map(p => { const r = path(p.path).filter(x => x[1] >= 0), [c, sym] = BODY[p.id] || ['#ffffff', 'circle'];
    const b = body(NAME[p.id] || p.id, r, new Date(p.start).getTime());
    // a cross has less ink than a filled disc: larger, to weigh the same; smaller on the rim
    return {c, size: Math.max(9, Math.min(16, 11 - 2 * p.mag)) * (sym == 'cross' ? 1.4 : 1) * (b.rim ? 0.8 : 1), ...b, sym}; });
  // the Moon (counted as visible from 5 deg up)
  const lp = path(L.path), lv = lp.filter(x => x[1] >= 0), l5 = lp.filter(x => x[1] >= 5);
  vars.moon = body(MOONNAME, lv, l5[0] ? l5[0][0] : null);
  // rim marks at least 8 deg apart: push later ones along the rim
  const rim = [...vars.slots, vars.moon].filter(b => b.rim).sort((a, b) => a.t - b.t);
  rim.forEach((b, k) => { if (k && b.t - rim[k - 1].t < 8) b.t = rim[k - 1].t + 8; });
  // a satellite on the dome only while its pass is under way at T (the brightest, if two)
  const s = (I.passes || []).filter(x => new Date(x.rise).getTime() <= T && new Date(x.end).getTime() >= T)
    .sort((a, b) => a.mag - b.mag)[0];
  vars.iR = []; vars.iT = []; vars.iD = []; vars.iM = null; vars.iC = s ? SATC[s.id] || '#ffffff' : '#ffffff';
  if (s) { const seg = (a, b, f) => (a + (((b - a + 540) % 360) - 180) * f + 360) % 360;
    const ti = new Date(s.rise).getTime(), tm = new Date(s.max).getTime(), tf = new Date(s.end).getTime();
    for (let k = 0; k <= 20; k++) { const f = k / 20;
      const az = f < 0.5 ? seg(s.az_start, s.az_max, f * 2) : seg(s.az_max, s.az_end, f * 2 - 1);
      const el = f < 0.5 ? s.el_max * Math.sin(f * Math.PI) : s.el_end + (s.el_max - s.el_end) * Math.cos((f * 2 - 1) * Math.PI / 2);
      const t = f < 0.5 ? ti + (tm - ti) * f * 2 : tm + (tf - tm) * (f * 2 - 1);
      vars.iR.push(rr(el)); vars.iT.push(az); vars.iD.push(where(satName(s.id, 1), t, el, az)); }
    vars.iM = {r: rr(s.el_max), t: s.az_max,
      d: S.satMark(satName(s.id, 1), s.visible.slice(11, 16), s.el_max, DIR(s.az_start), DIR(s.az_end))}; }

  // constellation names clear of every body mark (dome units, 90 = rim)
  const xy = (r, t) => [r * Math.sin(t * R), r * Math.cos(t * R)];
  const marks = [...vars.slots.filter(b => b.r != null && !b.rim).map(b => xy(b.r, b.t)),
    ...(vars.moon.r != null && !vars.moon.rim ? [xy(vars.moon.r, vars.moon.t)] : []),
    ...(vars.iM ? [xy(vars.iM.r, vars.iM.t)] : [])];
  vars.qR = []; vars.qT = []; vars.qX = [];
  KN.forEach(([r, t, name]) => { const [x, y] = xy(r, t);
    if (r < 76 && marks.every(([u, w]) => Math.hypot(x - u, y - w) >= 16)) { vars.qR.push(r); vars.qT.push(t); vars.qX.push(name); marks.push([x, y]); } });

  // clouds per hour, dusk -> dawn or from now; the value written in every cell
  const H = (C.hours || []).map(([t, c, lo, mi, hi, pp]) => [new Date(t).getTime(), c, lo, mi, hi, pp]);
  const from = Math.floor((dark ? now : nd) / 36e5) * 36e5, to = nh;
  const N = H.filter(x => x[0] + 36e5 > from && x[0] < to);
  const alpha = c => 0.06 + 0.86 * c / 100;
  vars.kX = N.map(x => new Date(x[0] + 18e5)); vars.kC = N.map(x => `rgba(214, 220, 232, ${alpha(x[1]).toFixed(2)})`);
  vars.kTxt = N.map(x => String(x[1])); vars.kTC = N.map(x => alpha(x[1]) > 0.55 ? '#101a33' : 'rgba(232, 236, 244, 0.9)');
  vars.kD = N.map(x => S.cloudTip(hm(x[0]), x[1], x[2], x[3], x[4], x[5]));
  vars.kRange = N.length ? [new Date(N[0][0]), new Date(N[N.length - 1][0] + 36e5)] : [new Date(from), new Date(to)];
  vars.kTV = N.filter(x => new Date(x[0]).getHours() % 3 == 0).map(x => new Date(x[0]));
  vars.kTT = vars.kTV.map(t => hm(t.getTime()));
  // the best moment under the strip (a triangle) only when the dome shows another moment
  vars.key = key && !(best_T && !dark) && key[0] >= vars.kRange[0].getTime() && key[0] <= vars.kRange[1].getTime()
    ? [new Date(key[0]), S.best(key[1], hm(key[0]))] : null;
  // the dome's moment as a line through the timeline and the strip
  vars.TX = T >= vars.kRange[0].getTime() && T <= vars.kRange[1].getTime() ? [new Date(T), new Date(T)] : [];
  vars.TN = dark ? S.mapNow(hm(T)) : best_T ? S.mapBest(key[1], hm(T)) : S.mapAt(hm(T));
  // the dome's marks explained in words under the legend; shorter lines on a phone
  const fromW = dark ? S.fromNow : S.fromAt(hm(T));
  const hasPath = vars.slots.some(b => b.pr.length > 1) || vars.moon.pr.length > 1;
  const hasRim = vars.slots.some(b => b.rim) || vars.moon.rim;
  vars.nota = [0, 1].map(k => [hasPath ? S.notePath(fromW)[k] : '', hasRim ? S.noteRim[k] : ''].filter(x => x).join('<br>'));
  // timeline: one row per body, a bar while it can be seen; rows in order of appearance
  const span = (a, b) => S.span(hm(a), hm(b), a <= nd + 6e4, b >= nh - 6e4);
  const rows = ps.map(p => { const [c, sym] = BODY[p.id] || ['#ffffff', 'circle'], who = NAME[p.id] || p.id;
    const a = new Date(p.start).getTime(), b = new Date(p.end).getTime();
    return {n: who, c, g: GLYPH[sym] || '●', a, b, d: `${who}: ${span(a, b)}`}; });
  if (l5.length) { const a = l5[0][0], b = l5[l5.length - 1][0];
    rows.push({n: MOONNAME, c: '__MOON__', g: '●', a, b, d: S.moonRow(L.lit ?? '', span(a, b))}); }
  const ip = (I.passes || []).filter(x => new Date(x.visible).getTime() < nh && new Date(x.end).getTime() > nd);
  // a row per satellite passing tonight
  [...new Set(ip.map(x => x.id))].forEach(id => { const q = ip.filter(x => x.id == id);
    rows.push({n: satName(id, 2), c: SATC[id] || '#ffffff', g: '◆', a: new Date(q[0].visible).getTime(), b: null, ip: q}); });
  rows.sort((p, q) => p.a - q.a);
  const x0 = vars.kRange[0].getTime(), x1 = vars.kRange[1].getTime();
  vars.tN = rows.length;
  vars.tV = rows.map((_, k) => k);
  vars.tT = rows.map(w => `<span style="color:${w.c}">${w.g}</span> ${w.n}`);
  const bars = rows.map((w, k) => [w, k]).filter(([w]) => w.b != null && w.b > x0 && w.a < x1);
  vars.bY = bars.map(([, k]) => k); vars.bC = bars.map(([w]) => w.c); vars.bD = bars.map(([w]) => w.d);
  vars.bB = bars.map(([w]) => new Date(Math.max(w.a, x0))); vars.bX = bars.map(([w]) => Math.min(w.b, x1) - Math.max(w.a, x0));
  // the time a bar starts, left of it, when it starts after dusk
  const late = bars.filter(([w]) => w.a > Math.max(nd, x0) + 9e5);
  vars.lX = late.map(([w]) => new Date(w.a)); vars.lY = late.map(([, k]) => k); vars.lT = late.map(([w]) => hm(w.a));
  // satellite passes: a diamond at each (a few minutes is too short for a bar)
  vars.eX = []; vars.eY = []; vars.eD = []; vars.eC = [];
  rows.forEach((w, k) => (w.ip || []).forEach(x => { const t = new Date(x.visible).getTime();
    if (t >= x0 && t <= x1) { vars.eX.push(new Date(t)); vars.eY.push(k); vars.eC.push(w.c);
      vars.eD.push(S.passTip(satName(x.id, 1), hm(t), Math.round(x.duration / 60), x.el_max, DIR(x.az_start), DIR(x.az_end))); } }));
  const cNow = H.find(x => x[0] <= T && T < x[0] + 36e5);
  vars.sub = (dark ? S.subNow(hm(T)) : best_T ? S.subBest(hm(T)) : S.subAt(hm(T))) + (cNow ? S.clouds(cNow[1]) : '');
  return {xs, ys};
}"""

# card geometry (px), from the window width: phone = full width; desktop = DOME_COLS of the
# section's 24 columns, beside Home Assistant's sidebar. s = dome side; leg = legend band;
# th = timeline (20 px a row); ph = plot height. Adjust here if your layout differs.
GEOM = ("const vw = window.innerWidth, phone = vw < 870;"
        f" const W = phone ? vw - 32 : (vw - 320 - 16) * {DOME_COLS} / 24;"
        " const s = Math.min(W - 80, 640), leg = phone ? 126 : 96;"
        " const th = 20 * Math.max(1, vars.tN || 0), ph = s + leg + 112 + th;")
POP = '%{customdata}<extra></extra>'


def g(expr):
    return '$fn ({vars}) => { ' + GEOM + f' return {expr}; }}'


def v(expr):
    return '$fn ({vars}) => ' + expr


def polar(label, **kw):
    return {'entity': '', 'name': label, 'type': 'scatterpolar', 'showlegend': False, **kw}


def js(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))


def build_fn(L, ent):
    stars = json.loads((HERE / 'stars.json').read_text())
    stars.pop('_about', None)
    tokens = {
        '__S__': L['js'], '__BODY__': js(BODY), '__GLYPH__': js(GLYPH), '__SATC__': js(SAT_C),
        '__NAME__': js(L['bodies']), '__SATN__': js(L['sats']), '__DIRS__': js(L['dirs']),
        '__CONS__': js(L['constellations']), '__STARN__': js(L['stars']), '__MOONNAME__': js(L['moon']),
        '__E_SKY__': ent['sky'], '__E_SAT__': ent['satellites'], '__E_CLD__': ent['clouds'],
        '__MOON__': MOON, '__STARS__': js(stars),
    }
    out = BUILD
    for k, val in tokens.items():
        out = out.replace(k, val)
    return out


def dome_card(L, ent):
    glow = [{'entity': '', 'name': f'horizon {k}', 'type': 'barpolar', 'r': [w], 'base': [90 - w], 'theta': [180],
             'width': [360], 'marker': {'color': f'rgba(90, 120, 190, {a})', 'line': {'width': 0}},
             'hoverinfo': 'skip', 'showlegend': False}
            for k, (w, a) in enumerate([(14, 0.07), (8, 0.08), (3, 0.10)])]

    def S(i, k, d='[]'):
        return v(f'(vars.slots || [])[{i}] ? vars.slots[{i}].{k} : {d}')
    planets = []
    for i in range(N_SLOTS):
        planets += [
            polar(f'path {i + 1}', mode='lines', r=S(i, 'pr'), theta=S(i, 'pt'),
                  line={'color': S(i, 'c', "'rgba(0,0,0,0)'"), 'width': 1.5, 'shape': 'spline'}, opacity=0.5,
                  customdata=S(i, 'pd'), hovertemplate=POP),
            polar(f'planet {i + 1}', mode='markers', cliponaxis=False,
                  r=v(f'(vars.slots || [])[{i}] ? [vars.slots[{i}].r] : []'),
                  theta=v(f'(vars.slots || [])[{i}] ? [vars.slots[{i}].t] : []'),
                  marker={'color': S(i, 'c', "'#fff'"), 'symbol': S(i, 'sym', "'circle'"),
                          'size': S(i, 'size', '10'), 'line': {'color': SKY, 'width': 1.5}},
                  customdata=v(f'(vars.slots || [])[{i}] ? [vars.slots[{i}].d] : []'), hovertemplate=POP),
        ]
    ink = INK.format
    return {
        'type': 'custom:plotly-graph',
        'hours_to_show': 1,
        'refresh_interval': 600,
        'raw_plotly_config': True,
        'entities': [
            {'entity': ent['sky'], 'name': 'helper', 'internal': True, 'filters': [{'fn': build_fn(L, ent)}]},
            *glow,
            polar('constellations', mode='lines', r=v('vars.cR || []'), theta=v('vars.cT || []'),
                  line={'color': ink(a=0.22), 'width': 1}, connectgaps=False,
                  customdata=v('vars.cD || []'), hovertemplate=POP),
            polar('stars', mode='markers', r=v('vars.sR || []'), theta=v('vars.sT || []'),
                  marker={'color': '#ffffff', 'size': v('vars.sS || []'), 'opacity': v('vars.sO || []'),
                          'line': {'width': 0}}, hoverinfo='skip'),
            polar('constellation names', mode='text', r=v('vars.qR || []'), theta=v('vars.qT || []'),
                  text=v('vars.qX || []'), textfont={'size': 11, 'color': ink(a=0.45)}, hoverinfo='skip'),
            polar('named stars', mode='markers', r=v('vars.nR || []'), theta=v('vars.nT || []'),
                  marker={'size': 14, 'color': 'rgba(0,0,0,0)'}, customdata=v('vars.nD || []'), hovertemplate=POP),
            polar('moon path', mode='lines', r=v('vars.moon ? vars.moon.pr : []'), theta=v('vars.moon ? vars.moon.pt : []'),
                  line={'color': MOON, 'width': 1.5, 'shape': 'spline', 'dash': 'dot'}, opacity=0.45,
                  customdata=v('vars.moon ? vars.moon.pd : []'), hovertemplate=POP),
            *planets,
            polar('moon', mode='markers', cliponaxis=False,
                  r=v('vars.moon && vars.moon.r != null ? [vars.moon.r] : []'),
                  theta=v('vars.moon && vars.moon.r != null ? [vars.moon.t] : []'),
                  marker={'size': v('vars.moon && vars.moon.rim ? 13 : 20'), 'color': MOON, 'line': {'color': SKY, 'width': 2}},
                  customdata=v('vars.moon && vars.moon.r != null ? [vars.moon.d] : []'), hovertemplate=POP),
            polar('satellite', mode='lines+markers',
                  r=v('vars.iR || []'), theta=v('vars.iT || []'),
                  line={'color': v("vars.iC || '#ffffff'"), 'width': 2, 'dash': 'dash'},
                  marker={'symbol': 'diamond', 'color': v("vars.iC || '#ffffff'"),
                          'size': v('(vars.iR || []).map((_, k) => k == 10 ? 11 : 0)')},
                  customdata=v('vars.iD || []'), hovertemplate=POP),
            {   # cloud strip: one cell per hour, light grey with opacity = cloud cover, the % written in it
                'entity': '', 'name': 'clouds', 'type': 'bar', 'xaxis': 'x', 'yaxis': 'y', 'showlegend': False,
                'x': v('vars.kX || []'), 'y': v('(vars.kX || []).map(() => 1)'), 'base': 0, 'width': 36e5 - 2 * 60e3,
                'marker': {'color': v('vars.kC || []'), 'line': {'width': 0}},
                'text': v('vars.kTxt || []'), 'textposition': 'inside', 'insidetextanchor': 'middle',
                'textfont': {'size': g('phone ? 10 : 12'), 'color': v('vars.kTC || []')}, 'textangle': 0,
                'constraintext': 'none', 'customdata': v('vars.kD || []'), 'hovertemplate': POP,
            },
            {   # the dome's moment across the strip
                'entity': '', 'name': 'map time (clouds)', 'type': 'scatter', 'mode': 'lines', 'xaxis': 'x', 'yaxis': 'y',
                'showlegend': False, 'x': v('vars.TX || []'), 'y': v('(vars.TX || []).length ? [-0.06, 1.06] : []'),
                'line': {'color': ink(a=0.85), 'width': 1.5}, 'hoverinfo': 'skip',
            },
            {   # timeline: a bar per body while it can be seen (base = start, x = duration in ms)
                'entity': '', 'name': 'visible', 'type': 'bar', 'orientation': 'h', 'xaxis': 'x', 'yaxis': 'y2',
                'showlegend': False, 'y': v('vars.bY || []'), 'x': v('vars.bX || []'), 'base': v('vars.bB || []'),
                'width': 0.42, 'marker': {'color': v('vars.bC || []'), 'line': {'width': 0}, 'opacity': 0.9},
                'customdata': v('vars.bD || []'), 'hovertemplate': POP,
            },
            {   # start times left of the bars that start after dusk
                'entity': '', 'name': 'from', 'type': 'scatter', 'mode': 'text', 'xaxis': 'x', 'yaxis': 'y2',
                'showlegend': False, 'x': v('vars.lX || []'), 'y': v('vars.lY || []'), 'text': v('vars.lT || []'),
                'textposition': 'middle left', 'textfont': {'size': 11, 'color': ink(a=0.7)}, 'hoverinfo': 'skip',
                'cliponaxis': False,
            },
            {   # satellite passes
                'entity': '', 'name': 'satellite passes', 'type': 'scatter', 'mode': 'markers', 'xaxis': 'x', 'yaxis': 'y2',
                'showlegend': False, 'x': v('vars.eX || []'), 'y': v('vars.eY || []'),
                'marker': {'symbol': 'diamond', 'size': 11, 'color': v('vars.eC || []'), 'line': {'color': SKY, 'width': 1.5}},
                'customdata': v('vars.eD || []'), 'hovertemplate': POP, 'cliponaxis': False,
            },
            {   # the dome's moment through the timeline
                'entity': '', 'name': 'map time', 'type': 'scatter', 'mode': 'lines', 'xaxis': 'x', 'yaxis': 'y2',
                'showlegend': False, 'x': v('vars.TX || []'),
                'y': v('(vars.TX || []).length ? [-0.5, (vars.tN || 1) - 0.5] : []'),
                'line': {'color': ink(a=0.85), 'width': 1.5}, 'hoverinfo': 'skip',
            },
            {   # its legend entry: a vertical tick, as the line runs on the chart
                'entity': '', 'name': v("vars.TN || ''"), 'type': 'scatter', 'mode': 'markers', 'xaxis': 'x', 'yaxis': 'y2',
                'showlegend': v('(vars.TX || []).length > 0'), 'x': [None], 'y': [None],
                'marker': {'symbol': 'line-ns-open', 'size': 14, 'color': ink(a=0.85), 'line': {'color': ink(a=0.85), 'width': 2}},
                'hoverinfo': 'skip',
            },
            {   # the best moment, a mark under the strip
                'entity': '', 'name': v("vars.key ? vars.key[1] : ''"), 'type': 'scatter', 'mode': 'markers',
                'xaxis': 'x', 'yaxis': 'y', 'showlegend': v('!!vars.key'),
                'x': v('vars.key ? [vars.key[0]] : []'), 'y': v('vars.key ? [-0.22] : []'),
                'marker': {'symbol': 'triangle-up', 'size': 9, 'color': ink(a=0.95)},
                'customdata': v('vars.key ? [vars.key[1]] : []'), 'hovertemplate': POP,
            },
        ],
        'layout': {
            'title': {'text': L['dome_title'], 'font': {'size': 16, 'color': ink(a=0.80)},
                      'yref': 'container', 'y': 1, 'yanchor': 'top', 'pad': {'t': 10}},
            'annotations': [{   # the strip's row label, in the timeline's label column
                'xref': 'paper', 'x': X0, 'xanchor': 'right', 'xshift': -6, 'yref': 'paper', 'y': g('(leg + 30 + 29) / ph'),
                'yanchor': 'middle', 'showarrow': False, 'text': L['clouds_row'],
                'font': {'size': 12, 'color': ink(a=0.75)},
            }, {
                'xref': 'paper', 'x': 0.5, 'xanchor': 'center', 'yref': 'paper', 'y': 1, 'yanchor': 'bottom',
                'yshift': 14, 'showarrow': False, 'font': {'size': 13, 'color': ink(a=0.92)},
                'text': v("vars.sub || ''"),
            }, {   # the note at the foot, under the legend
                'xref': 'paper', 'x': 0.5, 'xanchor': 'center', 'yref': 'paper', 'y': 0, 'yanchor': 'bottom',
                'showarrow': False, 'align': 'center', 'font': {'size': 12, 'color': ink(a=0.75)},
                'text': g("vars.nota ? vars.nota[phone ? 1 : 0] : ''"),
            }],
            'showlegend': True,
            'legend': {'orientation': 'h', 'x': 0.5, 'xanchor': 'center', 'y': g('(leg - 4) / ph'), 'yanchor': 'top',
                       'font': {'size': 12, 'color': ink(a=0.92)},
                       'itemsizing': 'constant', 'itemclick': False, 'itemdoubleclick': False,
                       'bgcolor': 'rgba(0,0,0,0)', 'tracegroupgap': 4},
            'polar': {
                'domain': {'x': [0, 1], 'y': g('[(leg + 112 + th) / ph, 1]')},
                'bgcolor': SKY,
                'barmode': 'overlay',
                'radialaxis': {'range': [0, 90], 'tickvals': [30, 60], 'ticktext': ['60°', '30°'],
                               'angle': 90, 'tickangle': 90, 'showline': False, 'ticks': '',
                               'tickfont': {'size': 10, 'color': ink(a=0.45)}, 'gridcolor': ink(a=0.10)},
                'angularaxis': {'rotation': 90, 'direction': 'clockwise', 'tickmode': 'array',
                                'tickvals': [0, 45, 90, 135, 180, 225, 270, 315], 'ticktext': L['compass'],
                                'tickfont': {'size': 12, 'color': ink(a=0.62)},
                                'gridcolor': ink(a=0.06), 'linecolor': ink(a=0.35), 'ticks': ''},
            },
            # the cloud strip and the timeline above it share this hour axis (labels left of X0)
            'xaxis': {'type': 'date', 'domain': [X0, 0.97], 'anchor': 'y', 'range': v('vars.kRange'),
                      'tickmode': 'array', 'tickvals': v('vars.kTV || []'), 'ticktext': v('vars.kTT || []'),
                      'tickfont': {'size': 12, 'color': ink(a=0.7)},
                      'showgrid': True, 'gridcolor': ink(a=0.09), 'gridwidth': 1,
                      'zeroline': False, 'fixedrange': True, 'ticks': '', 'showline': False},
            'yaxis': {'domain': g('[(leg + 30) / ph, (leg + 76) / ph]'), 'range': [-0.45, 1.08],
                      'visible': False, 'fixedrange': True},
            'yaxis2': {'domain': g('[(leg + 84) / ph, (leg + 84 + th) / ph]'), 'anchor': 'x',
                       'range': v('[(vars.tN || 1) - 0.5, -0.5]'), 'tickmode': 'array',
                       'tickvals': v('vars.tV || []'), 'ticktext': v('vars.tT || []'),
                       'tickfont': {'size': 12, 'color': ink(a=0.88)}, 'ticks': '', 'ticklabelstandoff': 4,
                       'showgrid': False, 'zeroline': False, 'showline': False, 'fixedrange': True},
            'plot_bgcolor': SKY,
            'bargap': 0,
            'hovermode': 'closest',
            'hoverdistance': 30,
            'paper_bgcolor': 'rgba(0,0,0,0)',
            'height': g('Math.round(ph + 76)'),
            'margin': {'t': 70, 'b': 6, 'l': 16, 'r': 16},
            'hoverlabel': {'bgcolor': NIGHT_BG, 'bordercolor': ink(a=0.14),
                           'font': {'color': ink(a=0.92), 'size': 13}},
            'dragmode': False,
        },
        'config': {'displayModeBar': False, 'scrollZoom': False},
        'grid_options': {'columns': DOME_COLS},
        'card_mod': {'style': NIGHT_CARD},
        'extended_touch_support': {'pinch_to_zoom': False, 'double_tap_drag_to_zoom': False},
    }


# ---------------------------------------------------------------------------------------
# The text card (Jinja). PRELUDE = data, helpers and the "best" rule (the same as BUILD's);
# then the language's macros; then BODY_MD, which only calls them.
# ---------------------------------------------------------------------------------------
PRELUDE = """\
{%- set n = state_attr('__E_SKY__', 'night') -%}
{%- set ps = state_attr('__E_SKY__', 'planets') or [] -%}
{%- set later = state_attr('__E_SKY__', 'upcoming') or [] -%}
{%- set sats = state_attr('__E_SAT__', 'passes') or [] -%}
{%- set hours = state_attr('__E_CLD__', 'hours') or [] -%}
{%- set names = __NAMES__ -%}
{%- set satn = __SATN__ -%}
{%- set marks = __MARKS__ -%}
{%- set satc = __SATC__ -%}
{%- macro hm(t) %}{{ as_datetime(t).strftime('%H:%M') }}{% endmacro -%}
{%- macro dirn(az) %}{{ dirs[((az + 22.5) // 45) | int % 8] }}{% endmacro -%}
{%- macro sat_name(id, k) %}{{ satn[id][k] if id in satn else ('satellite ' ~ id) }}{% endmacro -%}
{%- macro mark(id) %}{% if id in marks %}<font color="{{ marks[id][0] }}">{{ marks[id][1] }}</font> {% endif %}{% endmacro -%}
{%- macro diamond(id) %}<font color="{{ satc[id] if id in satc else '#ffffff' }}">◆</font> {% endmacro -%}
{#- cloud cover (%) of the hour of t, '' without data -#}
{%- macro cover(t) -%}
{%- set l = hours | selectattr(0, 'eq', as_datetime(t).strftime('%Y-%m-%dT%H:00')) | list -%}
{%- if l %}{{ l[0][1] }}{% endif -%}
{%- endmacro -%}
{%- macro cls(t) -%}
{%- set c = cover(t) -%}
{{ 0 if c == '' else 0 if c | int < 20 else 1 if c | int < 50 else 2 if c | int < 80 else 3 }}
{%- endmacro -%}
{%- set nows = now().strftime('%Y-%m-%dT%H:%M') -%}
{%- set ns = namespace(sat=none, best=none, sc=1000000000) -%}
{%- for p in sats if n and p.visible < n.end and p.end > nows and p.el_max >= 30 and (p.id == 25544 or p.mag <= 0) -%}
{%- set sc = (cls(p.visible) | int) * 1000 + (((p.mag + 5) * 10) | round | int) -%}
{%- if sc < ns.sc %}{% set ns.sc = sc %}{% set ns.sat = p %}{% endif -%}
{%- endfor -%}
{%- if n -%}
{%- set d1 = (as_datetime(n.start[:10] ~ 'T12:00') + timedelta(days=1)).strftime('%Y-%m-%d') -%}
{%- set early = ps | selectattr('start', 'lt', n.start[:11] ~ '23:00') | list -%}
{%- for p in (early or ps) | sort(attribute='mag') -%}
{%- set lim = [25, p.alt_max] | min -%}{%- set i = loop.index -%}
{%- for x in p.path -%}
{%- set t = (n.start[:10] if x[0] >= '12:00' else d1) ~ 'T' ~ x[0] -%}
{%- if x[1] >= lim and t >= p.start and t <= p.end -%}
{%- set sc = (10000 if t < nows else 0) + (cls(t) | int) * 1000 + i * 100 + (90 - x[1]) -%}
{%- if sc < ns.sc %}{% set ns.sc = sc %}{% set ns.sat = none %}{% set ns.best = {'id': p.id, 't_max': t,
    'alt_max': x[1], 'az_max': x[2], 'mag': p.mag} %}{% endif -%}
{%- endif -%}
{%- endfor -%}
{%- endfor -%}
{%- endif -%}
{%- set key = ns.sat.visible if ns.sat else (ns.best.t_max if ns.best else none) -%}
"""

BODY_MD = """\
{%- if not n -%}
<font size="4">{{ no_night() }}</font>
{%- else -%}
<font size="4">{% if ns.sat %}{{ hl_sat(ns.sat) }}{% elif ns.best %}{{ hl_planet(ns.best) }}{% else %}{{ hl_none() }}{% endif %}</font>
{%- if key and cover(key) != '' %}

---

{{ can_see(key) }}
{%- endif %}

---

{#- one list: tonight's planets and satellite passes in order of appearance (as the timeline),
    each with its mark; the ISS, when it does not pass tonight, says when it is next seen; then
    the planets that are lost near the Sun -#}
{%- set it = namespace(items=[]) -%}
{%- for p in ps %}{% set it.items = it.items + [{'t': p.start, 'k': 'p', 'o': p}] %}{% endfor -%}
{%- set tonight = sats | selectattr('visible', 'lt', n.end) | selectattr('end', 'gt', nows) | list -%}
{%- for q in tonight %}{% set it.items = it.items + [{'t': q.visible, 'k': 's', 'o': q}] %}{% endfor %}

<font size="3">{{ title }}</font>

{% for x in it.items | sort(attribute='t') -%}
{%- if x.k == 's' %}{{ sat_line(x.o) }}{% else %}{{ planet_line(x.o) }}{% endif %}

{% endfor -%}
{%- if sats and not (tonight | selectattr('id', 'eq', 25544) | list) -%}
{{ iss_absent(sats | selectattr('id', 'eq', 25544) | selectattr('end', 'gt', nows) | list) }}

{% endif -%}
{%- for q in later -%}
{{ upcoming_line(q) }}

{% endfor -%}
{%- endif -%}
"""


def text_template(L, ent):
    def jdict(d):
        # a Jinja dict literal (integer keys stay integers)
        return '{' + ', '.join(f'{k!r}: {json.dumps(val, ensure_ascii=False)}' for k, val in d.items()) + '}'
    pre = PRELUDE
    for k, val in {'__E_SKY__': ent['sky'], '__E_SAT__': ent['satellites'], '__E_CLD__': ent['clouds'],
                   '__NAMES__': jdict(L['bodies']), '__SATN__': jdict(L['sats']),
                   '__MARKS__': jdict({k: [c, GLYPH[sym]] for k, (c, sym) in BODY.items()}),
                   '__SATC__': jdict(SAT_C)}.items():
        pre = pre.replace(k, val)
    return pre + L['jinja'] + BODY_MD


def text_card(L, ent):
    # natural height. No markdown headings or bold: <font size> for the headline and the list
    # title over the body text, all at normal weight; `---` rules between the blocks.
    return {'type': 'markdown', 'content': text_template(L, ent), 'grid_options': {'columns': 24 - DOME_COLS},
            'card_mod': {'style': NIGHT_CARD}}


ENTITIES = {'sky': 'sensor.tonight_sky', 'satellites': 'sensor.tonight_satellites', 'clouds': 'sensor.tonight_clouds'}


def section(lang, entities=None):
    L = LANG[lang]
    ent = {**ENTITIES, **(entities or {})}
    return {'type': 'grid', 'column_span': 2, 'cards': [
        {'type': 'heading', 'heading': L['heading'], 'heading_style': 'title', 'icon': 'mdi:telescope'},
        dome_card(L, ent),
        text_card(L, ent),
    ]}


def main():
    import yaml
    (HERE / 'cards').mkdir(exist_ok=True)
    for lang in LANG:
        out = HERE / 'cards' / f'tonight_section.{lang}.yaml'
        text = yaml.safe_dump(section(lang), allow_unicode=True, sort_keys=False, width=10 ** 6)
        out.write_text(text)
        print(f'{out.relative_to(HERE)}: {len(text) // 1000} kB')


if __name__ == '__main__':
    main()
