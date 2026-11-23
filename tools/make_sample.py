# Claude · 2026-11-23 · Session 8e680ddd-6b26-44d7-8b07-e667fe163a25 · writes the made-up sample data in examples/
"""Writes examples/: a made-up wallet (balances and travel credits), credit tracking, and one invented trip,
Seattle to Boston in March 2027, with about 40 flights. Nothing here is real: names, prices, balances, credits and
flight numbers are invented (flight numbers are drawn at random), so the portal can be tried without any account.

  python3 tools/make_sample.py            writes examples/ next to tools/
  FLIGHTS_DATA=examples FLIGHTS_SITE=sample-site python3 src/build_portal.py    then builds the sample pages
"""
import json, os, random, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'examples')
R = random.Random(20270312)
SLUG = '27-03-12-boston'
TZ = 180  # Boston clocks are 3 hours ahead of Seattle
CODE = {'Delta': 'DL', 'Southwest': 'WN', 'American': 'AA', 'United': 'UA', 'Alaska': 'AS'}
HUBS = {'Delta': ['MSP', 'DTW', 'ATL', 'SLC'], 'Southwest': ['DEN', 'MDW', 'BWI'], 'American': ['DFW', 'ORD', 'CLT', 'PHL'],
        'United': ['DEN', 'ORD'], 'Alaska': []}

def hm(m):
    m %= 1440; h, mi = divmod(m, 60)
    return f"{h % 12 or 12}:{mi:02d} {'pm' if h >= 12 else 'am'}"

def fnum():
    return str(R.randrange(7000, 8000))   # an invented range, so no real flight is named

def flight(day, origin, dest, airline, dep, nonstop=False):
    code = CODE[airline]
    if nonstop or not HUBS[airline]:
        via, lays, legs_t = [], [], [R.randrange(318, 345)]
    else:
        via = [R.choice(HUBS[airline])]; lays = [R.choice([45, 55, 70, 85, 105, 140])]
        legs_t = [R.randrange(150, 230), R.randrange(130, 200)]
    dur = sum(legs_t) + sum(lays)
    arr = dep + dur + TZ
    stops = len(via)
    pts = [origin] + via + [dest]
    legs, t = [], dep
    for i, lt in enumerate(legs_t):
        legs.append([pts[i], pts[i + 1], code, fnum(), hm(t), hm(t + lt + (TZ if i == len(legs_t) - 1 else 0))])
        t += lt + (lays[i] if i < len(lays) else 0)
    cash = R.randrange(170, 470) + (60 if nonstop else 0)
    miles = lambda lo, hi: R.randrange(lo, hi) // 500 * 500
    dl = miles(14000, 36000) if airline == 'Delta' else None
    sw = miles(11000, 29000) if airline == 'Southwest' else None
    swc = int(sw * 1.25) // 100 * 100 if sw else None
    aa = miles(12500, 30000) if airline == 'American' else None
    ua = miles(15000, 34000) if airline == 'United' else None
    swcb, swcc = (cash, cash + 70) if airline == 'Southwest' else (None, None)
    fares = []
    if airline == 'Delta': fares = [['DL', 'Main Basic', 0, cash, dl, 'dl', 5.6, [], ''], ['DL', 'Main Classic', 1, cash + 65, dl + 6000, 'dl', 5.6, [], '']]
    if airline == 'Southwest': fares = [['WN', 'Basic', 0, swcb, sw, 'sw', 5.6, [], ''], ['WN', 'Choice', 1, swcc, swc, 'sw', 5.6, [], '']]
    if airline == 'United': fares = [['UA', 'Economy', 1, cash + 40, ua, 'ua', 5.6, [[ua // 2, round(cash * 0.45)]], '']]
    if airline == 'Alaska': fares = [['AS', 'Saver', 0, cash, None, 'as', None, [], ''], ['AS', 'Main', 1, cash + 50, None, 'as', None, [], '']]
    rid = f'{day}-{dest.lower()}-{dep}-{arr}-{airline.lower()}'
    notes = 'lands after midnight' if arr >= 1440 else ''
    fl = ' + '.join(l[2] + l[3] for l in legs)
    return [rid, day, dest, dep, arr, dur, stops, via, lays, airline, fl, cash, f'{airline} site' if fares else 'Google Flights',
            dl, sw, swc, aa, ua, swcb, swcc, notes, 0, 0, legs, fares]

def rows_for(origin, n_per):
    rows = []
    for day in (12, 13):
        for dest in ('BOS', 'PVD'):
            if dest == 'BOS': rows.append(flight(day, origin, dest, 'Alaska', R.choice([420, 480, 540]), nonstop=True))
            if dest == 'BOS' and origin == 'SEA': rows.append(flight(day, origin, dest, 'Delta', R.choice([465, 600, 735]), nonstop=True))
            for _ in range(n_per):
                al = R.choice(['Delta', 'Southwest', 'American', 'United'])
                rows.append(flight(day, origin, dest, al, R.randrange(330, 1080, 5)))
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: (r[1], r[2], r[3])):
        if r[0] in seen: continue
        seen.add(r[0]); out.append(r)
    for r in out[3::9]: r[21] = 1   # a few near-duplicates, folded by default on the page
    return out

def write(rel, obj, jsonl=False):
    p = os.path.join(OUT, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w') as f:
        if jsonl: f.write(''.join(json.dumps(o) + '\n' for o in obj))
        else: json.dump(obj, f, indent=1 if not rel.endswith('page-rows.json') else None, separators=None if not rel.endswith('page-rows.json') else (',', ':'))

def main():
    if os.path.isdir(OUT): shutil.rmtree(OUT)
    checked = '2027-02-20T19:30:00-08:00'
    programs = [
        dict(airline='Delta', program='SkyMiles', unit='miles', balance=84210, balanceAsOf='Feb 20, 7:30pm PT', expiry='', creditsStatus='checked', creditsNote='Sample: no certificates.', creditsSource='live'),
        dict(airline='Southwest', program='Rapid Rewards', unit='points', balance=51300, balanceAsOf='Feb 20, 7:25pm PT', expiry='', creditsStatus='checked', creditsNote='Sample.', creditsSource='live'),
        dict(airline='American', program='AAdvantage', unit='miles', balance=72640, balanceAsOf='Feb 20, 7:20pm PT', expiry='', creditsStatus='checked', creditsNote='Sample.', creditsSource='live'),
        dict(airline='United', program='MileagePlus', unit='miles', balance=40125, balanceAsOf='Feb 20, 7:15pm PT', expiry='Miles never expire', creditsStatus='checked', creditsNote='Sample.', creditsSource='live'),
        dict(airline='Alaska', program='Atmos Rewards', unit='points', balance=28900, balanceAsOf='Feb 20, 7:10pm PT', expiry='', creditsStatus='unchecked', creditsNote='Sample: credits not checked yet.', creditsSource='live'),
    ]
    credits = [
        dict(airline='Southwest', what='Flight credit', amount=142.3, useBy='2027-08-15', useByLabel='Expires', **{'from': 'Sample: canceled trip'}, note='Not transferable'),
        dict(airline='United', what='TravelBank', amount=75.0, useBy='2027-12-31', useByLabel='Expires', **{'from': 'Sample: card benefit'}, note='Applies at checkout'),
        dict(airline='Delta', what='eCredit', amount=210.55, useBy='2027-05-01', useByLabel='Use by', **{'from': 'Sample: schedule change'}, note=''),
        dict(airline='American', what='Trip credit', amount=None, original=188.2, useBy='2027-09-30', useByLabel='Start travel by', **{'from': 'Sample: canceled trip'}, note='Usable amount shown at checkout'),
    ]
    write('credits/wallet.json', dict(asof='Sat Feb 20, 2027, 7:30pm PT (sample data)', programs=programs, credits=credits, loose=[]))
    write('credits/tracking.json', dict(tracker_version=1, changes=[dict(version=1, date='2027-02-20', what='Sample: started tracking five airlines')],
        airlines={p['airline']: dict(tracked_since='2027-02-20', email_backfill=dict(done='2027-02-20', scope='sample'), last_live_check=checked) for p in programs},
        last_record=checked))
    write('credits/flags.json', dict(computed_at=checked, since={}, flags={}))
    trip = dict(title='Boston flights, Mar 12 and 13 (sample)', h1='Seattle to Boston, Fri Mar 12 or Sat Mar 13 (made-up sample)', slug=SLUG,
        short='Seattle to Boston', card_name='Boston, Mar 12 or 13', route='Seattle or Everett → Boston, Providence',
        scope='Economy, one way, 1 passenger. Made-up sample data.', searched='2027-02-20T18:00:00-08:00', searched_label='Sat Feb 20, 6:00pm PT (sample)',
        origin='SEA', origin_name='Seattle or Everett', origins={'SEA': {'name': 'Seattle', 'dir': '.'}, 'PAE': {'name': 'Everett', 'dir': 'pae'}},
        primary_origin='SEA', dest_names={'BOS': 'Boston', 'PVD': 'Providence'}, dest_default=['BOS', 'PVD'], dest_region='New England',
        dates=['2027-03-12', '2027-03-13'], tz_diff=TZ, tz_origin='PT', tz_dest='ET',
        held=dict(airline='Alaska', flight='Alaska AS 7468', fromName='Seattle', to='BOS', d=12, dep=480, arr=1120, cabin='Main', price=287.6),
        notes=['Everything on this page is made up, to show how the portal works.', 'Prices are one way, economy, one passenger.'],
        why='Sample trip.')
    write(f'searches/{SLUG}/trip.json', trip)
    write(f'searches/{SLUG}/page-rows.json', rows_for('SEA', 8))
    write(f'searches/{SLUG}/pae/trip.json', dict(tz_diff=TZ))
    write(f'searches/{SLUG}/pae/page-rows.json', rows_for('PAE', 1))
    write(f'searches/{SLUG}/weather/nws.json', {'ORD': dict(updated='2027-02-20T17:00:00-06:00', office='LOT', alerts=[], periods=[
        dict(name='Friday', start='2027-03-12T06:00:00-06:00', temp=41, wind='15 mph', pop=70, short='Rain Showers', detail='Sample forecast.')])})
    n = sum(len(json.load(open(os.path.join(OUT, f'searches/{SLUG}', d, 'page-rows.json')))) for d in ('.', 'pae'))
    print(f'wrote {OUT}: 5 programs, {len(credits)} credits, trip {SLUG} with {n} flights')

if __name__ == '__main__':
    main()
