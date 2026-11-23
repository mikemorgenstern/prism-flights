# Claude · 2026-11-23 · Session 8e680ddd-6b26-44d7-8b07-e667fe163a25 · flights portal "Ask" helper (runs on the server, stdlib only)
"""Answers one question about the flights already on a trip page, or turns a home-page trip description into a
proposed search. Answers that pick out flights come back as row ids the page can apply as a removable filter; answers
that need new flights come back as a proposed search the page can start as a job.

  python3 ask_helper.py < request.json > result.json
  request: {"page": "<slug>" | "home", "question": "...", "filters": {...} | null, "visible": ["<row id>", ...] | null}
  result:  {"answer": "...", "ids": [...] | null, "label": "..." | null, "needs_search": null | {"description", "origins",
            "dests", "dates"}, "model", "account", "seconds"}
  exit 0 with a result; exit 2 with one plain line on stderr when it could not answer.

Calls the claude CLI in print mode (claude -p) with the subscription login, tools off, no MCP servers, no CLAUDE.md
or settings (--safe-mode), never an SDK or an API key. Which login and model: an optional account router command
(config ask_router + ask_router_args) that prints JSON {status: ROUTED, provider: claude, seat_dir, model, effort,
account}; without one, the default claude login and config ask_model (sonnet).
Env: FLIGHTS_SITE (site dir holding <slug>/trip-data.json), FLIGHTS_ROUTER (router path), FLIGHTS_ASK_SEAT_DIR and
FLIGHTS_ASK_MODEL (both set = skip the router; for tests), FLIGHTS_ASK_TIMEOUT (seconds, default 120), FLIGHTS_CLAUDE.
"""
import datetime as dt, json, os, re, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portal_config

SITE = os.path.expanduser(os.environ.get('FLIGHTS_SITE') or os.path.join(portal_config.ROOT, 'site'))
ROUTER = os.path.expanduser(os.environ.get('FLIGHTS_ROUTER') or portal_config.get('ask_router', ''))
ROUTER_ARGS = [str(a) for a in portal_config.get('ask_router_args', ['--json'])]
CLAUDE = os.environ.get('FLIGHTS_CLAUDE') or portal_config.user_path('ask_claude', 'claude')
TIMEOUT = int(os.environ.get('FLIGHTS_ASK_TIMEOUT', '120'))
PAGE_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
IATA = re.compile(r'^[A-Z]{3}$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
PT = dt.timezone(dt.timedelta(hours=-8))
MAX_IDS = 80

class Fail(Exception):
    pass

def tm(m):
    nd = m >= 1440; m %= 1440; h, mi = divmod(m, 60); ap = 'p' if h >= 12 else 'a'; h = h % 12 or 12
    return f'{h}:{mi:02d}{ap}' + ('+1' if nd else '')

def du(m): return f'{m // 60}h{m % 60:02d}'

def kf(n): return '' if n is None else (f'{n / 1000:.1f}'.rstrip('0').rstrip('.') + 'k')

def plain(s, n):
    s = re.sub('\\s*[\u2014\u2013]\\s*', ', ', str(s or '')).strip()  # no em or en dashes on the pages
    return s[:n]

def trip_table(td, visible):
    """One short line per flight. Row numbers stand in for the long ids to keep the prompt small."""
    vis = set(visible or [])
    mark = bool(vis)
    days = {k: v.split()[0][:2] for k, v in td['days'].items()}
    lines, idmap = [], {}
    for n, r in enumerate(td['rows'], 1):
        idmap[n] = r[0]
        via = ' '.join(r[7]) + ('(' + ','.join(du(x) for x in r[8]) + ')' if r[8] else '')
        stops = 'nonstop' if r[6] == 0 else f'{r[6]}stop {via}'.strip()
        flags = []
        if r[21]: flags.append('near-duplicate')
        if r[22]: flags.append('UA saver sold out')
        if r[20]: flags.append(plain(r[20], 60))
        cells = [('*' if mark and r[0] in vis else '') + str(n), days.get(str(r[1]), str(r[1])), f'{r[24]}>{r[2]}', f'{tm(r[3])}-{tm(r[4])}', du(r[5]),
                 stops, r[9], (r[10] or '').replace(' + ', '+'), '' if r[11] is None else f'${r[11]}', kf(r[13]), kf(r[14]), kf(r[15]), kf(r[16]), kf(r[17]),
                 '' if r[18] is None else f'${r[18]}', '; '.join(flags)]
        lines.append('|'.join(cells).rstrip('|'))
    head = '#|day|from>to|depart-arrive|time|stops via(layovers)|airline|flights|cash|DL miles|WN pts basic|WN pts choice|AA miles|UA miles|WN cash|notes'
    return head + '\n' + '\n'.join(lines), idmap

def trip_prompt(td, req):
    table, idmap = trip_table(td, req.get('visible'))
    held = td.get('held')
    ctx = [f"Trip: {td['title']} ({td.get('scope', '')}). Searched {td.get('searchedLabel') or td.get('searched')}.",
           'Days: ' + ', '.join(f'{v}' for v in td['days'].values()) + '.',
           'Airports: from ' + ', '.join(f'{k} {v}' for k, v in (td.get('origins') or {}).items()) + '; to ' + ', '.join(f'{k} {v}' for k, v in td['destNames'].items()) + '.',
           f"Departure times are {td.get('tzOrigin', 'PT')} (origin), arrival times {td.get('tzDest', 'ET')} (destination); +1 means the next day.",
           'Travel credits (cut the cash price on that airline only): ' + (', '.join(f"{k} ${v['sure']:.0f}" for k, v in (td.get('credits') or {}).items() if v.get('sure')) or 'none') + '.',
           'Miles and points balances: ' + ', '.join(f'{k.upper()} {v:,}' for k, v in (td.get('balances') or {}).items()) + '.']
    if held: ctx.append(f"Ticket the traveler already holds: {held['flight']}, {td['days'].get(str(held['d']), '')}, departs {tm(held['dep'])}, ${held['price']:.2f}.")
    if req.get('visible'): ctx.append(f"Rows starting with * are the {len(req['visible'])} flights on screen now with the current filters; the rest are filtered out.")
    if req.get('filters'): ctx.append('Filters now: ' + json.dumps(req['filters'], separators=(',', ':'))[:1500])
    system = ("You answer the traveler's question about the flights on one saved flight-search page. Use only the table and facts given. "
              "Never invent a flight, price, time or seat. If the data cannot answer, say so plainly in one sentence. "
              "Reply with JSON only, no prose around it, matching: "
              '{"answer": string, "ids": [row numbers] or null, "label": string or null, "needs_search": null or {"description": string, "origins": [IATA], "dests": [IATA], "dates": ["YYYY-MM-DD"]}}. '
              "answer: one to four short sentences in plain words, no dashes as punctuation. Name flights by airline, day, departure time and price. "
              f"ids: when the question picks out flights from this table (which ones, the best, a filter), list their row numbers, best first, at most {MAX_IDS}; otherwise null. "
              "label: two to five words naming that set for a removable filter chip, like \"Nonstops under $400\"; null when ids is null. "
              "needs_search: only when answering needs flights this table does not have (other dates, airports, airlines or a return trip); propose that search and say in answer that a new search is needed; otherwise null. "
              "Columns: cash is the lowest economy cash fare; DL, WN, AA and UA are economy award prices in that program; WN cash is Southwest's own price. "
              "near-duplicate rows are hidden by default on the page.")
    user = '\n'.join(ctx) + '\n\nFlights:\n' + table + '\n\nQuestion: ' + req['question']
    return system, user, idmap

def home_prompt(req):
    trips = []
    for p in sorted(os.listdir(SITE)) if os.path.isdir(SITE) else []:
        f = os.path.join(SITE, p, 'trip-data.json')
        if PAGE_RE.match(p) and os.path.isfile(f):
            try:
                td = json.load(open(f))
                trips.append(f"{p}: {td.get('short') or td['title']}, {', '.join(td['dates'])}, from {', '.join(td.get('origins') or [])} to {', '.join(td['destNames'])}")
            except (OSError, ValueError, KeyError):
                pass
    today = dt.datetime.now(PT).strftime('%A %B %-d, %Y')
    system = ("You turn the traveler's description of a trip into a proposed flight search that a separate Claude session will run later with their browser. "
              "Reply with JSON only, no prose around it, matching: "
              '{"answer": string, "ids": null, "label": null, "needs_search": null or {"description": string, "origins": [IATA], "dests": [IATA], "dates": ["YYYY-MM-DD"]}}. '
              "needs_search: origins and dests as 3-letter airport codes including nearby airports (New York means JFK, LGA, EWR unless one is named); "
              "dates: every date named, each day of a range, at most 10, never in the past; description: one sentence restating the trip with passengers, cabin, one way or round trip and any limits given. "
              "answer: one or two short sentences saying what would be searched and any assumption you made, plain words, no dashes as punctuation. "
              "If a destination or dates are missing, ask for exactly what is missing in answer and set needs_search to null. "
              "If the question is about a trip that already has a page, say which page and set needs_search to null unless new flights are wanted. Nothing is booked or bought.")
    user = f'Today is {today} (Pacific time). Saved trips:\n' + ('\n'.join(trips) or 'none') + '\n\nDescription: ' + req['question']
    return system, user, {}

SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['answer', 'ids', 'label', 'needs_search'], 'properties': {
    'answer': {'type': 'string'}, 'ids': {'type': ['array', 'null'], 'items': {'type': 'integer'}}, 'label': {'type': ['string', 'null']},
    'needs_search': {'type': ['object', 'null'], 'additionalProperties': False, 'required': ['description', 'origins', 'dests', 'dates'], 'properties': {
        'description': {'type': 'string'}, 'origins': {'type': 'array', 'items': {'type': 'string'}}, 'dests': {'type': 'array', 'items': {'type': 'string'}},
        'dates': {'type': 'array', 'items': {'type': 'string'}}}}}}

def route():
    seat, model = os.environ.get('FLIGHTS_ASK_SEAT_DIR'), os.environ.get('FLIGHTS_ASK_MODEL')
    if seat and model: return {'seat_dir': seat, 'model': model, 'effort': os.environ.get('FLIGHTS_ASK_EFFORT', 'low'), 'account': 'override'}
    if not ROUTER:   # no account router: the default claude login
        return {'seat_dir': None, 'model': portal_config.get('ask_model', 'sonnet'), 'effort': os.environ.get('FLIGHTS_ASK_EFFORT', 'low'), 'account': 'default'}
    # run through sh, so a router file without its exec bit still runs
    p = subprocess.run(['sh', ROUTER] + ROUTER_ARGS, capture_output=True, text=True, timeout=60)
    try: d = json.loads(p.stdout)
    except ValueError: raise Fail('The account router gave no answer (' + (p.stderr.strip().splitlines() or ['no output'])[-1][:160] + ')')
    if d.get('status') != 'ROUTED' or d.get('provider') != 'claude' or not d.get('seat_dir'):
        raise Fail('No Claude account has room right now (router: ' + '; '.join(d.get('why') or [str(d.get('status'))])[:200] + ')')
    return {'seat_dir': d['seat_dir'], 'model': d['model'], 'effort': d.get('effort') or 'low', 'account': d.get('account')}

def call_claude(rt, system, user):
    env = dict(os.environ, CLAUDE_CONFIG_DIR=rt['seat_dir']) if rt.get('seat_dir') else dict(os.environ)
    for k in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN'): env.pop(k, None)  # subscription login only
    cmd = [CLAUDE, '-p', '--model', rt['model'], '--effort', rt['effort'], '--output-format', 'json', '--tools', '', '--strict-mcp-config',
           '--safe-mode', '--no-session-persistence', '--disable-slash-commands', '--permission-prompts', 'none',
           '--system-prompt', system, '--json-schema', json.dumps(SCHEMA, separators=(',', ':'))]
    try:
        p = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=TIMEOUT, env=env, cwd=os.path.dirname(os.path.abspath(__file__)))
    except subprocess.TimeoutExpired:
        raise Fail(f'Claude took longer than {TIMEOUT} seconds')
    try: out = json.loads(p.stdout)
    except ValueError: raise Fail('Claude gave no readable reply (' + ((p.stderr or p.stdout).strip().splitlines() or ['empty'])[-1][:200] + ')')
    if out.get('is_error'): raise Fail('Claude could not answer: ' + str(out.get('result') or out.get('subtype'))[:200])
    if isinstance(out.get('structured_output'), dict): return out['structured_output']
    txt = str(out.get('result') or '')
    m = re.search(r'\{.*\}', txt, re.S)
    if not m: raise Fail('Claude replied without the expected JSON')
    try: return json.loads(m.group(0))
    except ValueError: raise Fail('Claude replied with JSON that could not be read')

def clean(raw, idmap, page):
    ans = plain(raw.get('answer'), 1200) or 'No answer came back.'
    ids = None
    if page != 'home' and isinstance(raw.get('ids'), list):
        seen = []
        for n in raw['ids']:
            try: rid = idmap.get(int(n))
            except (TypeError, ValueError): rid = None
            if rid and rid not in seen: seen.append(rid)
        ids = seen[:MAX_IDS] or None
    label = plain(raw.get('label'), 40) if ids else None
    if ids and not label: label = f'{len(ids)} flights'
    ns = raw.get('needs_search')
    if isinstance(ns, dict):
        codes = lambda xs: [x for x in (str(v).strip().upper() for v in (xs or [])) if IATA.match(x)][:8]
        today = dt.datetime.now(PT).date().isoformat()
        dates = [x for x in (str(v).strip() for v in (ns.get('dates') or [])) if DATE.match(x) and x >= today][:10]
        ns = {'description': plain(ns.get('description'), 400), 'origins': codes(ns.get('origins')), 'dests': codes(ns.get('dests')), 'dates': dates}
        if not ns['description'] or not ns['dests']: ns = None
    else:
        ns = None
    return {'answer': ans, 'ids': ids, 'label': label, 'needs_search': ns}

def answer(req):
    page, q = str(req.get('page') or ''), str(req.get('question') or '').strip()
    if not PAGE_RE.match(page) or not q: raise Fail('Need a page and a question')
    if page == 'home':
        system, user, idmap = home_prompt(req)
    else:
        f = os.path.join(SITE, page, 'trip-data.json')
        if not os.path.isfile(f): raise Fail(f'No flight data for {page} on the server yet (trip-data.json missing; publish the pages again)')
        system, user, idmap = trip_prompt(json.load(open(f)), req)
    t0 = time.time()
    rt = route()
    res = clean(call_claude(rt, system, user), idmap, page)
    res.update(model=rt['model'], account=rt.get('account'), seconds=round(time.time() - t0, 1), prompt_chars=len(system) + len(user))
    return res

if __name__ == '__main__':
    try:
        req = json.load(sys.stdin)
        if '--prompt-only' in sys.argv:  # show what would be sent, no model call
            p = req.get('page')
            s, u, _ = home_prompt(req) if p == 'home' else trip_prompt(json.load(open(os.path.join(SITE, p, 'trip-data.json'))), req)
            print(s + '\n\n' + u); sys.exit(0)
        print(json.dumps(answer(req)))
    except Fail as e:
        print(str(e), file=sys.stderr); sys.exit(2)
    except Exception as e:  # loud, one line, for the page
        print(f'Helper error: {type(e).__name__}: {e}'[:300], file=sys.stderr); sys.exit(2)
