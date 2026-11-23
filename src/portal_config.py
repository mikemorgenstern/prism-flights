# Claude · 2026-11-23 · Session 8e680ddd-6b26-44d7-8b07-e667fe163a25 · flights portal: local settings loader
"""Reads the portal's local settings: config.local.json next to src/ (or the file named by FLIGHTS_CONFIG).

Every setting is optional. A missing file means "no servers, no email check, no search jobs": the portal still builds
and serves pages. config.example.json lists every key with a placeholder and what it does.
"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def path():
    return os.environ.get('FLIGHTS_CONFIG') or os.path.join(ROOT, 'config.local.json')

def load():
    p = path()
    try:
        with open(p) as f: cfg = json.load(f)
    except FileNotFoundError:
        return {}
    except ValueError as e:
        raise SystemExit(f'{p} is not valid JSON ({e}); fix it or remove it')
    return {k: v for k, v in cfg.items() if not k.startswith('_')} if isinstance(cfg, dict) else {}

CFG = load()

def get(key, default=None):
    v = CFG.get(key)
    return default if v in (None, '') else v

def user_path(key, default=None):
    """A setting that is a file or folder path; ~ is expanded."""
    v = get(key, default)
    return os.path.expanduser(v) if isinstance(v, str) else v
