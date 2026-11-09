"""
Where am I? Settings shared by the three sensor scripts.

Nothing to fill in: the location, elevation and time zone are the ones you gave
Home Assistant (Settings → System → General), read from its own
`.storage/core.config`. The optional N2YO key is read from `secrets.yaml`
(`n2yo_api_key: "…"`).

To run the scripts outside Home Assistant, or to override a value, put a
`config.json` beside this file:
  {"latitude": 9.9331, "longitude": -84.0770, "elevation_m": 1160,
   "timezone": "America/Costa_Rica", "n2yo_api_key": ""}
(or pass `--config path/to/config.json`).
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent


def ha_config_dir():
    """The Home Assistant config folder: the nearest parent that has .storage/core.config."""
    for d in HERE.parents:
        if (d / '.storage' / 'core.config').exists():
            return d
    return None


def load(args=None):
    """{latitude, longitude, elevation_m, timezone, n2yo_api_key, cache_dir}"""
    args = sys.argv[1:] if args is None else args
    cfg = {'elevation_m': 0, 'n2yo_api_key': '', 'cache_dir': HERE}
    ha = ha_config_dir()
    if ha:
        core = json.loads((ha / '.storage' / 'core.config').read_text())['data']
        cfg.update(latitude=core['latitude'], longitude=core['longitude'],
                   elevation_m=core.get('elevation') or 0, timezone=core['time_zone'])
        try:
            m = re.search(r'^n2yo_api_key:\s*["\']?([A-Za-z0-9-]+)', (ha / 'secrets.yaml').read_text(), re.M)
            if m:
                cfg['n2yo_api_key'] = m.group(1)
        except OSError:
            pass
    override = pathlib.Path(args[args.index('--config') + 1]) if '--config' in args else HERE / 'config.json'
    if override.exists():
        cfg.update(json.loads(override.read_text()))
        if '--config' in args:
            cfg['cache_dir'] = override.parent
    missing = [k for k in ('latitude', 'longitude', 'timezone') if k not in cfg]
    if missing:
        raise SystemExit(f'no {", ".join(missing)}: run inside Home Assistant\'s config folder, or add a config.json '
                         f'(see {HERE / "settings.py"})')
    cfg['cache_dir'] = pathlib.Path(cfg['cache_dir'])
    return cfg
