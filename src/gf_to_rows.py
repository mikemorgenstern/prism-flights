# Claude · 2026-11-22 · Session 8e680ddd-6b26-44d7-8b07-e667fe163a25 · Google Flights results -> raw rows for merge.py
"""Turns saved Google Flights results (gf/gf-<ORIGIN>-<DD>.json, written by the flight-search skill's Google Flights reader)
into pipe rows merge.py reads (gf-<DEST>-<DD>.txt), one folder per origin:

  D|dest|dep|arr|airlines|stops|via|layovers|duration|price|legs JSON

Usage: python3 gf_to_rows.py <search folder> ORIGIN=<raw folder for that origin> [ORIGIN=<folder> ...]
   e.g. python3 gf_to_rows.py data/searches/27-03-12-boston SEA=raw PAE=pae/raw
"""
import glob, json, os, re, sys

CARRIER = {'WN': 'Southwest', 'DL': 'Delta', 'AA': 'American', 'UA': 'United', 'AS': 'Alaska', 'F9': 'Frontier', 'NK': 'Spirit', 'B6': 'JetBlue',
           'HA': 'Hawaiian', 'SY': 'Sun Country', 'G4': 'Allegiant', 'MX': 'Breeze', 'XP': 'Avelo', 'AM': 'Aeromexico', 'Y4': 'Volaris'}

def hm(s):
    h = re.search(r'(\d+) hr', s or ''); m = re.search(r'(\d+) min', s or '')
    return (f"{h[1]}h " if h else '') + (f"{m[1]}m" if m else '').strip() or ''

def low(t): return t.replace(' ', ' ').replace('AM', 'am').replace('PM', 'pm')

def convert(folder, origin, outdir):
    n = 0; per = {}
    for f in sorted(glob.glob(os.path.join(folder, 'gf', f'gf-{origin}-*.json'))):
        d = re.search(r'-(\d{2})\.json$', f)[1]
        data = json.load(open(f)); data = json.loads(data) if isinstance(data, str) else data
        for x in data:
            L = x['legs']
            if not L or L[0]['from'] != origin: continue
            dest = L[-1]['to']
            plus = sum(int(l['arrPlus'][1:] or 0) for l in L if l.get('arrPlus')) + sum(int(l['depPlus'][1:] or 0) for l in L if l.get('depPlus'))
            names = []
            for l in L:
                nm = CARRIER.get(l['al'], l['al'])
                if nm not in names: names.append(nm)
            legs = [[l['from'], l['to'], l['al'], l['num'], low(l['dep']), low(l['arr']) + (l.get('arrPlus') or '')] for l in L]
            row = [d, dest, low(L[0]['dep']), low(L[-1]['arr']) + ('+1' if plus else ''), ','.join(names), 'Nonstop' if x['stops'] == 0 else f"{x['stops']} stop" + ('s' if x['stops'] > 1 else ''),
                   ','.join(l['to'] for l in L[:-1]), '+'.join(hm(s) for s in x.get('lays', [])), hm(x['dur']), str(x['price']), json.dumps(legs, separators=(',', ':'))]
            per.setdefault((dest, d), []).append('|'.join(row)); n += 1
    os.makedirs(outdir, exist_ok=True)
    for (dest, d), rows in per.items():
        open(os.path.join(outdir, f'gf-{dest}-{d}.txt'), 'w').write('\n'.join(rows) + '\n')
    return n

if __name__ == '__main__':
    folder = sys.argv[1]
    for a in sys.argv[2:]:
        o, sub = a.split('=', 1)
        print(o, convert(folder, o, os.path.join(folder, sub)), 'rows ->', os.path.join(folder, sub))
