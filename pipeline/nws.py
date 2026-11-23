# Claude · 2026-11-22 · Session 8e680ddd · National Weather Service forecasts and alerts for connection and end airports (flight-search skill)
import json, os, sys, urllib.request, concurrent.futures as cf
# Usage: python3 -I nws.py YYYY-MM-DD[,YYYY-MM-DD...] [CODE,CODE,...]   (dates to show; airports default to all in AP below;
# add any missing airport with its latitude and longitude). Writes weather/nws.json and prints a summary.
DATES = sys.argv[1].split(',') if len(sys.argv) > 1 else []
if not DATES: sys.exit('give the travel dates, for example: python3 -I nws.py 2026-12-01,2026-12-02 ORD,DEN')
AP = {'ORD':(41.9786,-87.9048),'MDW':(41.7868,-87.7522),'DEN':(39.8561,-104.6737),'LAS':(36.0840,-115.1537),'LAX':(33.9416,-118.4085),
 'DFW':(32.8998,-97.0403),'DAL':(32.8471,-96.8518),'PHX':(33.4342,-112.0116),'ATL':(33.6407,-84.4277),'SAN':(32.7338,-117.1933),
 'SLC':(40.7899,-111.9791),'IAH':(29.9902,-95.3368),'HOU':(29.6454,-95.2789),'IAD':(38.9531,-77.4565),'BNA':(36.1263,-86.6774),
 'EWR':(40.6895,-74.1745),'SEA':(47.4502,-122.3088),'AUS':(30.1975,-97.6664),'MSP':(44.8848,-93.2223),'SFO':(37.6213,-122.3790),
 'CLT':(35.2144,-80.9473),'SJC':(37.3639,-121.9289),'FLL':(26.0742,-80.1506),'MIA':(25.7959,-80.2870),'PBI':(26.6857,-80.0928)}
H = {'User-Agent':'flight-weather-check (personal use)','Accept':'application/geo+json'}
def get(u):
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30))
def one(code):
    lat, lon = AP[code]
    try:
        pt = get(f'https://api.weather.gov/points/{lat},{lon}')['properties']
        fc = get(pt['forecast'])['properties']
        per = [dict(name=p['name'], start=p['startTime'], temp=p['temperature'], wind=p['windSpeed'], pop=(p.get('probabilityOfPrecipitation') or {}).get('value'), short=p['shortForecast'], detail=p['detailedForecast'])
               for p in fc['periods'] if p['startTime'][:10] in DATES]
        al = get(f'https://api.weather.gov/alerts/active?point={lat},{lon}')['features']
        alerts = [dict(event=a['properties']['event'], headline=a['properties']['headline'], onset=a['properties'].get('onset'), ends=a['properties'].get('ends')) for a in al]
        return code, dict(updated=fc.get('updateTime') or fc.get('generatedAt'), office=pt.get('gridId'), periods=per, alerts=alerts)
    except Exception as e:
        return code, dict(error=repr(e))
CODES = sys.argv[2].split(',') if len(sys.argv) > 2 else list(AP)
missing = [c for c in CODES if c not in AP]
if missing: sys.exit(f'add coordinates to AP for: {missing}')
with cf.ThreadPoolExecutor(8) as ex:
    out = dict(ex.map(one, CODES))
os.makedirs('weather', exist_ok=True)
json.dump(out, open('weather/nws.json', 'w'), indent=1)
for c, d in out.items():
    if 'error' in d: print(c, 'ERROR', d['error']); continue
    tw = d['periods']
    print(f"{c} (updated {d['updated'][:16]}) alerts={[a['event'] for a in d['alerts']]}")
    for p in tw: print(f"   {p['name'][:16]:16} {p['temp']:>3}F pop={p['pop']} wind={p['wind']:<14} {p['short']}")
