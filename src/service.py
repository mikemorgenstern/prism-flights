# Claude · 2026-11-22 · Session 8e680ddd-6b26-44d7-8b07-e667fe163a25 · flights portal web service (stdlib only)
"""Serves the portal under /flights from prebuilt pages, plus a small JSON API. Meant to sit behind a reverse proxy
on a private network: there is no login, so anyone who can reach it can read the pages and use the API.

  GET  /flights/                     home page (site/index.html)
  GET  /flights/<slug>/              one saved search (site/<slug>/index.html)
  GET  /flights/assets/<file>         banner images (site/assets/)
  GET  /flights/credit-codes.json     credit codes for the home page's Show code (site/credit-codes.json, if built)
  GET  /flights/api/state/<page>     likes and hides for a page: {"value": {...}, "revision": n}
  POST /flights/api/state/<page>     body {"value": {...}, "revision": n}; 409 with the current copy if revision is stale
  GET  /flights/api/checks           check requests (newest last)
  POST /flights/api/checks           body {"items": [...], "note": "..."}: a submitted round asking for a live credits check
  POST /flights/api/checks/done      body {"id": "...", "result": "..."}: marks a request done after doing it
  POST /flights/api/ask              body {"page", "question", "filters", "visible"}: starts the Ask helper; returns {"id", "status"}
  GET  /flights/api/ask/<id>         {"status": "working"|"done"|"error", "answer", "ids", "label", "needs_search", ...}
  GET  /flights/api/ask?page=<page>  the last few questions asked on that page
  POST /flights/api/jobs             body {"page", "description", "origins", "dests", "dates", "from_ask"}: a search job,
                                     created only by an explicit click on the page; runs on the Mac, one at a time
  GET  /flights/api/jobs             recent jobs plus limits;   GET /flights/api/jobs/<id>   one job
  POST /flights/api/jobs/<id>/progress  body {"status", "note", "slug"} + header X-Job-Token: the Mac session reports
  POST /flights/api/jobs/<id>/retry  a failed or needs_you job goes back in the queue;   .../cancel  drops a queued job
  GET  /flights/healthz              "ok"

POST needs the header X-Flights: 1 (blocks cross-site form posts). Binds 127.0.0.1 only; the reverse proxy adds the
network. Check requests are only recorded; they are read at the next credits check (src/credits.py requests).
Ask: a question box answered by src/ask_helper.py on this server. Jobs: new searches run by src/jobs_start.py on a Mac.
Guardrails: question length cap, at most 2 asks working and 30 an hour, one job running at a time (others queued),
at most 6 searches a day (dry runs not counted), and a job that goes quiet is marked failed so the queue moves.
Env: FLIGHTS_PORT (8873), FLIGHTS_SITE (site/ next to src/), FLIGHTS_STATE (~/.local/share/flights-portal),
FLIGHTS_BIND (127.0.0.1; tests only), FLIGHTS_ASK_CMD and FLIGHTS_JOB_CMD (stub commands for tests),
FLIGHTS_PUBLIC_BASE (where the Mac reports progress; default public_base in config.local.json, else this server).
"""
import collections, datetime as dt, json, os, re, secrets, shlex, subprocess, sys, threading, time, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get('FLIGHTS_PORT', '8873'))
BIND = os.environ.get('FLIGHTS_BIND', '127.0.0.1')
SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
import portal_config
SITE = os.path.expanduser(os.environ.get('FLIGHTS_SITE') or os.path.join(os.path.dirname(SRC), 'site'))
STATE = os.path.expanduser(os.environ.get('FLIGHTS_STATE', '~/.local/share/flights-portal'))
PUBLIC = (os.environ.get('FLIGHTS_PUBLIC_BASE') or portal_config.get('public_base') or f'http://127.0.0.1:{PORT}').rstrip('/')
ASK_CMD = shlex.split(os.environ['FLIGHTS_ASK_CMD']) if os.environ.get('FLIGHTS_ASK_CMD') else [sys.executable, os.path.join(SRC, 'ask_helper.py')]
JOB_CMD = shlex.split(os.environ['FLIGHTS_JOB_CMD']) if os.environ.get('FLIGHTS_JOB_CMD') else [sys.executable, os.path.join(SRC, 'jobs_start.py')]
LOCK = threading.Lock()
PAGE_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
ID_RE = re.compile(r'^[0-9T:+.-]{19,32}-[0-9a-f]{6}$')
IATA = re.compile(r'^[A-Z]{3}$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
MAX_BODY = 256 * 1024
PT = dt.timezone(dt.timedelta(hours=-8))
Q_MAX, ASK_TIMEOUT, ASK_WORKING_MAX, ASK_PER_HOUR = 500, 150, 2, 30
JOBS_PER_DAY, JOB_RETRIES = 6, 3
JOB_START_QUIET = int(os.environ.get('FLIGHTS_JOB_START_QUIET', 15 * 60))  # seconds; env only for tests
JOB_RUN_QUIET = int(os.environ.get('FLIGHTS_JOB_RUN_QUIET', 90 * 60))
JOB_STATUS = ('queued', 'starting', 'running', 'done', 'failed', 'needs_you', 'cancelled')
ACTIVE, ENDED = ('starting', 'running'), ('done', 'failed', 'needs_you', 'cancelled')
ASKS_WORKING, ASK_TIMES = set(), collections.deque()
for d in ('state', 'asks', 'jobs'): os.makedirs(os.path.join(STATE, d), exist_ok=True)

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')

def age(iso):
    try: return time.time() - dt.datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError): return 1e9

def read_json(p, default):
    try:
        with open(p) as f: return json.load(f)
    except (OSError, ValueError): return default

def write_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w') as f: json.dump(obj, f)
    os.replace(tmp, p)

def fname(rid): return re.sub(r'[^0-9A-Za-z-]', '', rid)
def last_line(s, default): return ((s or '').strip().splitlines() or [default])[-1][:300]
def codes(xs): return [x for x in (str(v).strip().upper() for v in (xs if isinstance(xs, list) else [])) if IATA.match(x)][:8]

# ---- Ask: one question, answered by ask_helper.py in a background thread -------------------------------------------
def ask_path(rid): return os.path.join(STATE, 'asks', fname(rid) + '.json')

def run_ask(rec, req):
    try:
        p = subprocess.run(ASK_CMD, input=json.dumps(req), capture_output=True, text=True, timeout=ASK_TIMEOUT, env=dict(os.environ, FLIGHTS_SITE=SITE))
        if p.returncode == 0:
            res = json.loads(p.stdout)
            rec.update(status='done', **{k: res.get(k) for k in ('answer', 'ids', 'label', 'needs_search', 'model', 'seconds')})
        else:
            rec.update(status='error', error=last_line(p.stderr, 'The helper stopped without saying why'))
    except subprocess.TimeoutExpired:
        rec.update(status='error', error=f'No answer within {ASK_TIMEOUT} seconds; try again or ask in chat')
    except Exception as e:
        rec.update(status='error', error=f'{type(e).__name__}: {e}'[:300])
    rec['finished_at'] = now()
    with LOCK:
        write_json(ask_path(rec['id']), rec); ASKS_WORKING.discard(rec['id'])

def ask_get(rid):
    rec = read_json(ask_path(rid), None)
    if rec and rec['status'] == 'working' and rid not in ASKS_WORKING and age(rec['asked_at']) > ASK_TIMEOUT + 30:
        rec.update(status='error', error='Interrupted (the portal restarted); ask again', finished_at=now())  # loud, not silent
        write_json(ask_path(rid), rec)
    return rec

def ask_recent(page, n=8):
    files = sorted(os.listdir(os.path.join(STATE, 'asks')), reverse=True)[:300]
    recs = [r for r in (read_json(os.path.join(STATE, 'asks', f), None) for f in files) if r and r.get('page') == page]
    return sorted(recs, key=lambda r: r.get('seq', 0), reverse=True)[:n]  # seq: same-second asks keep their order

def prune(folder, keep):
    files = sorted(os.listdir(folder))
    for f in files[:-keep] if len(files) > keep else []:
        try: os.remove(os.path.join(folder, f))
        except OSError: pass

# ---- Jobs: search jobs that run on the MacBook, one at a time --------------------------------------------------------
JOBS = os.path.join(STATE, 'jobs.json')

def jobs_load(): return read_json(JOBS, {'jobs': []})

def jobs_tick():
    """Called with LOCK held: load, sweep and pump, and write only when something changed (pages poll this)."""
    cur = jobs_load(); before = json.dumps(cur)
    pump(cur)
    if json.dumps(cur) != before: write_json(JOBS, cur)
    return cur
def public(j): return {k: v for k, v in j.items() if k != 'token'}
def pt_day(iso): return dt.datetime.fromisoformat(iso).astimezone(PT).date()

def used_today(cur):
    today = dt.datetime.now(PT).date()
    return sum(1 for j in cur['jobs'] if not j.get('dry_run') and pt_day(j['created_at']) == today)

def note(j, status, text):
    j.update(status=status, note=str(text)[:500], updated_at=now())
    j.setdefault('log', []).append({'at': j['updated_at'], 'status': status, 'note': j['note']})
    j['log'] = j['log'][-40:]
    if status in ENDED: j['finished_at'] = j['updated_at']

def sweep(cur):
    """A job that goes quiet is marked failed (loudly) so the queue never sits behind it."""
    for j in cur['jobs']:
        if j['status'] == 'starting' and age(j['updated_at']) > JOB_START_QUIET:
            note(j, 'failed', 'The MacBook never reported back (asleep, Chrome closed, or Claude could not start there). Press Try again when it is awake.')
        elif j['status'] == 'running' and age(j['updated_at']) > JOB_RUN_QUIET:
            note(j, 'failed', f'No word from the MacBook for {JOB_RUN_QUIET // 60} minutes; the search may have stopped. Press Try again, or ask in chat.')

def pump(cur):
    """Called with LOCK held. Starts the oldest queued job when nothing is starting or running."""
    sweep(cur)
    if any(j['status'] in ACTIVE for j in cur['jobs']): return
    q = [j for j in cur['jobs'] if j['status'] == 'queued']
    if not q: return
    j = q[0]
    note(j, 'starting', 'Starting on the MacBook')
    payload = dict(public(j), token=j['token'], progress_url=f"{PUBLIC}/flights/api/jobs/{urllib.parse.quote(j['id'], safe='')}/progress")
    threading.Thread(target=start_job, args=(payload,), daemon=True).start()

def start_job(payload):
    try:
        p = subprocess.run(JOB_CMD, input=json.dumps(payload), capture_output=True, text=True, timeout=120)
        rc, msg = p.returncode, last_line(p.stderr if p.returncode else p.stdout, '')
    except subprocess.TimeoutExpired:
        rc, msg = 3, 'Starting on the MacBook took over 2 minutes (asleep or offline?). Wake it, open Chrome, then press Try again.'
    except Exception as e:
        rc, msg = 1, f'Could not run the job starter: {type(e).__name__}: {e}'
    with LOCK:
        cur = jobs_load()
        j = next((x for x in cur['jobs'] if x['id'] == payload['id']), None)
        if not j or j['status'] != 'starting' or j.get('token') != payload['token']: return  # the Mac already reported, or it was retried
        if rc == 0: note(j, 'starting', msg or 'Started on the MacBook; waiting for Claude to report')
        else: note(j, 'needs_you' if rc == 3 else 'failed', msg or f'The job starter failed (exit {rc})')
        pump(cur); write_json(JOBS, cur)

class H(BaseHTTPRequestHandler):
    server_version = 'flights-portal/1'

    def log_message(self, fmt, *args):
        print('%s %s' % (self.address_string(), fmt % args), flush=True)

    def send(self, code, body, ctype='application/json; charset=utf-8', extra=None):
        data = body if isinstance(body, bytes) else (json.dumps(body) if not isinstance(body, str) else body).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD': self.wfile.write(data)

    def page_file(self, rel):
        p = os.path.realpath(os.path.join(SITE, rel, 'index.html'))
        return p if p.startswith(os.path.realpath(SITE) + os.sep) and os.path.isfile(p) else None

    def do_HEAD(self): self.do_GET()

    def do_GET(self):
        path, _, qs = self.path.partition('?')
        if path == '/flights/healthz': return self.send(200, 'ok', 'text/plain')
        if path == '/flights': return self.send(301, '', 'text/plain', {'Location': '/flights/'})
        m = re.match(r'^/flights/assets/([A-Za-z0-9_-]+\.(jpg|png|webp|svg))$', path)   # banner images and logo
        if m:
            f = os.path.join(SITE, 'assets', m[1])
            if not os.path.isfile(f): return self.send(404, 'not found', 'text/plain')
            return self.send(200, open(f, 'rb').read(), {'jpg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp', 'svg': 'image/svg+xml'}[m[2]])
        if path == '/flights/credit-codes.json':   # credit codes, fetched only when the owner taps Show code (private network only)
            f = os.path.join(SITE, 'credit-codes.json')
            return self.send(200, open(f, 'rb').read()) if os.path.isfile(f) else self.send(404, {'error': 'no codes'})
        m = re.match(r'^/flights/api/state/([^/]+)$', path)
        if m:
            if not PAGE_RE.match(m[1]): return self.send(400, {'error': 'bad page name'})
            return self.send(200, read_json(os.path.join(STATE, 'state', m[1] + '.json'), {'value': None, 'revision': 0}))
        if path == '/flights/api/checks':
            return self.send(200, read_json(os.path.join(STATE, 'checks.json'), {'checks': []}))
        if path == '/flights/api/ask':
            page = urllib.parse.parse_qs(qs).get('page', [''])[0]
            if not PAGE_RE.match(page): return self.send(400, {'error': 'need ?page=<page>'})
            with LOCK: return self.send(200, {'asks': ask_recent(page)})
        m = re.match(r'^/flights/api/ask/([^/]+)$', path)
        if m:
            rid = urllib.parse.unquote(m[1])
            if not ID_RE.match(rid): return self.send(400, {'error': 'bad id'})
            with LOCK: rec = ask_get(rid)
            return self.send(200, rec) if rec else self.send(404, {'error': 'no such question'})
        if path == '/flights/api/jobs':
            with LOCK:
                cur = jobs_tick()
                running = next((j['id'] for j in cur['jobs'] if j['status'] in ACTIVE), None)
                return self.send(200, {'jobs': [public(j) for j in cur['jobs'][-20:]], 'limits': {'per_day': JOBS_PER_DAY, 'used_today': used_today(cur), 'running': running}})
        m = re.match(r'^/flights/api/jobs/([^/]+)$', path)
        if m:
            rid = urllib.parse.unquote(m[1])
            with LOCK:
                cur = jobs_tick()
                j = next((x for x in cur['jobs'] if x['id'] == rid), None)
            return self.send(200, public(j)) if j else self.send(404, {'error': 'no such job'})
        if path == '/flights/':
            f = self.page_file('')
        else:
            m = re.match(r'^/flights/([a-z0-9][a-z0-9-]{0,63})(/?)$', path)
            if not m: return self.send(404, 'Not found', 'text/plain')
            if not m[2]: return self.send(301, '', 'text/plain', {'Location': f'/flights/{m[1]}/'})
            f = self.page_file(m[1])
        if not f: return self.send(404, 'Not found', 'text/plain')
        with open(f, 'rb') as fh: return self.send(200, fh.read(), 'text/html; charset=utf-8')

    def body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_BODY: raise ValueError('body too large')
        b = json.loads(self.rfile.read(n) or b'{}')
        if not isinstance(b, dict): raise ValueError('body must be a JSON object')
        return b

    def do_POST(self):
        path = self.path.split('?', 1)[0]
        if self.headers.get('X-Flights') != '1': return self.send(403, {'error': 'missing X-Flights header'})
        try: b = self.body()
        except ValueError as e: return self.send(400, {'error': str(e)})
        m = re.match(r'^/flights/api/state/([^/]+)$', path)
        if m:
            if not PAGE_RE.match(m[1]) or not isinstance(b.get('value'), dict): return self.send(400, {'error': 'need {"value": {...}, "revision": n}'})
            p = os.path.join(STATE, 'state', m[1] + '.json')
            with LOCK:
                cur = read_json(p, {'value': None, 'revision': 0})
                if b.get('revision', 0) != cur['revision']: return self.send(409, cur)
                new = {'value': b['value'], 'revision': cur['revision'] + 1, 'saved_at': now()}
                write_json(p, new)
            return self.send(200, new)
        if path == '/flights/api/checks/done':
            p = os.path.join(STATE, 'checks.json')
            with LOCK:
                cur = read_json(p, {'checks': []})
                hit = [c for c in cur['checks'] if c['id'] == b.get('id')]
                if not hit: return self.send(404, {'error': 'no such request'})
                hit[0].update(status='done', done_at=now(), result=str(b.get('result', ''))[:500])
                write_json(p, cur)
            return self.send(200, hit[0])
        if path == '/flights/api/checks':
            items = b.get('items')
            if not isinstance(items, list) or not items or len(items) > 50: return self.send(400, {'error': 'need 1 to 50 items'})
            rec = {'id': now() + '-' + secrets.token_hex(3), 'requested_at': now(), 'items': [str(i)[:120] for i in items], 'note': str(b.get('note', ''))[:500], 'status': 'requested'}
            p = os.path.join(STATE, 'checks.json')
            with LOCK:
                cur = read_json(p, {'checks': []})
                cur['checks'].append(rec)
                write_json(p, cur)
            return self.send(200, rec)
        if path == '/flights/api/ask': return self.post_ask(b)
        if path == '/flights/api/jobs': return self.post_job(b)
        m = re.match(r'^/flights/api/jobs/([^/]+)/(progress|retry|cancel)$', path)
        if m: return self.job_action(urllib.parse.unquote(m[1]), m[2], b)
        return self.send(404, {'error': 'not found'})

    def post_ask(self, b):
        page, q = str(b.get('page') or ''), str(b.get('question') or '').strip()
        vis, filt = b.get('visible'), b.get('filters')
        if not PAGE_RE.match(page): return self.send(400, {'error': 'bad page name'})
        if not q: return self.send(400, {'error': 'type a question first'})
        if len(q) > Q_MAX: return self.send(400, {'error': f'question is too long (at most {Q_MAX} characters)'})
        if vis is not None and (not isinstance(vis, list) or len(vis) > 2000): return self.send(400, {'error': 'visible must be a list of at most 2000 ids'})
        if filt is not None and (not isinstance(filt, dict) or len(json.dumps(filt)) > 8000): return self.send(400, {'error': 'filters must be a small object'})
        with LOCK:
            t = time.time()
            while ASK_TIMES and t - ASK_TIMES[0] > 3600: ASK_TIMES.popleft()
            if len(ASKS_WORKING) >= ASK_WORKING_MAX: return self.send(429, {'error': f'Claude is already answering {len(ASKS_WORKING)} questions; try again when one finishes'})
            if len(ASK_TIMES) >= ASK_PER_HOUR: return self.send(429, {'error': f'{ASK_PER_HOUR} questions in the last hour is the limit; ask in chat for more'})
            rec = {'id': now() + '-' + secrets.token_hex(3), 'page': page, 'question': q, 'status': 'working', 'asked_at': now(), 'seq': time.time_ns()}
            ASK_TIMES.append(t); ASKS_WORKING.add(rec['id'])
            write_json(ask_path(rec['id']), rec); prune(os.path.join(STATE, 'asks'), 500)
        req = {'page': page, 'question': q, 'filters': filt, 'visible': [str(v)[:80] for v in vis] if vis else None}
        threading.Thread(target=run_ask, args=(dict(rec), req), daemon=True).start()
        return self.send(200, rec)

    def post_job(self, b):
        page, desc = str(b.get('page') or ''), str(b.get('description') or '').strip()
        dates = [x for x in (str(v).strip() for v in (b.get('dates') if isinstance(b.get('dates'), list) else [])) if DATE.match(x)][:10]
        origins, dests = codes(b.get('origins')), codes(b.get('dests'))
        if not PAGE_RE.match(page): return self.send(400, {'error': 'bad page name'})
        if not desc or len(desc) > 600: return self.send(400, {'error': 'need a description of 1 to 600 characters'})
        if not dests: return self.send(400, {'error': 'need at least one destination airport code'})
        dry = b.get('dry_run') if b.get('dry_run') in (True, 'no-claude') else False
        with LOCK:
            cur = jobs_load(); sweep(cur)
            same = next((j for j in cur['jobs'] if j['status'] in ('queued',) + ACTIVE and j['page'] == page and j['description'] == desc), None)
            if same: return self.send(409, dict(public(same), error='That search is already queued or running'))
            if not dry and used_today(cur) >= JOBS_PER_DAY: return self.send(429, {'error': f'{JOBS_PER_DAY} searches today is the limit; ask in chat for more'})
            j = {'id': now() + '-' + secrets.token_hex(3), 'page': page, 'description': desc, 'origins': origins, 'dests': dests, 'dates': dates,
                 'from_ask': str(b.get('from_ask') or '')[:40] or None, 'dry_run': dry, 'created_at': now(), 'retries': 0, 'token': secrets.token_hex(16)}
            note(j, 'queued', 'Waiting for the search before it to finish')
            cur['jobs'].append(j); cur['jobs'] = cur['jobs'][-200:]
            pump(cur); write_json(JOBS, cur)
            return self.send(200, public(j))

    def job_action(self, rid, action, b):
        with LOCK:
            cur = jobs_load()
            j = next((x for x in cur['jobs'] if x['id'] == rid), None)
            if not j: return self.send(404, {'error': 'no such job'})
            if action == 'progress':
                if not secrets.compare_digest(str(self.headers.get('X-Job-Token') or ''), j['token']): return self.send(403, {'error': 'bad job token'})
                st = b.get('status')
                if st not in JOB_STATUS or st in ('queued', 'cancelled'): return self.send(400, {'error': 'status must be one of starting, running, done, failed, needs_you'})
                if j['status'] in ENDED: return self.send(409, dict(public(j), error='this job has already ended'))
                note(j, st, b.get('note') or st)
                if PAGE_RE.match(str(b.get('slug') or '')): j['slug'] = b['slug']
            elif action == 'retry':
                if j['status'] not in ('failed', 'needs_you'): return self.send(409, dict(public(j), error='only a failed or stopped search can be tried again'))
                if j.get('retries', 0) >= JOB_RETRIES: return self.send(429, dict(public(j), error=f'tried {JOB_RETRIES} times already; ask in chat'))
                j['retries'] = j.get('retries', 0) + 1; j['token'] = secrets.token_hex(16)
                note(j, 'queued', 'Queued again')
            else:
                if j['status'] != 'queued': return self.send(409, dict(public(j), error='only a waiting search can be cancelled here'))
                note(j, 'cancelled', 'Cancelled from the page')
            pump(cur); write_json(JOBS, cur)
            return self.send(200, public(j))

if __name__ == '__main__':
    print(f'flights portal on {BIND}:{PORT}, site {SITE}, state {STATE}', flush=True)
    ThreadingHTTPServer((BIND, PORT), H).serve_forever()
