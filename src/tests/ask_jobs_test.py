# Claude · 2026-11-23 · Session 8e680ddd-6b26-44d7-8b07-e667fe163a25 · flights portal: local test of the Ask and search-job API
"""Runs src/service.py on a spare port with a scratch state and site folder and stub commands in place of the Claude
helper and the MacBook job starter (FLIGHTS_ASK_CMD, FLIGHTS_JOB_CMD), then checks ask, jobs, guardrails, and the
409 and X-Flights header rules. Nothing touches the live service, the box, the MacBook or any browser.

  python3 src/tests/ask_jobs_test.py          prints one line per check; exit 1 if any check fails
  python3 src/tests/ask_jobs_test.py --write-stubs DIR   only writes the two stub commands (for ask_ui_test.js)
"""
import json, os, shlex, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STUB_ASK = r'''
import json, sys, time
req = json.load(sys.stdin); q = req['question']
if q == 'fail': print('stub failure: helper could not answer', file=sys.stderr); sys.exit(2)
if q.startswith('slow'): time.sleep(3)
if q == 'search':
    print(json.dumps({'answer': 'Needs a new search.', 'ids': None, 'label': None, 'needs_search': {'description': 'PAE to BOS Mar 12', 'origins': ['PAE'], 'dests': ['BOS'], 'dates': ['2027-03-12']}, 'model': 'stub', 'seconds': 0.1}))
else:
    vis = req.get('visible') or []
    print(json.dumps({'answer': 'Two flights fit.', 'ids': vis[:2], 'label': 'Stub pick', 'needs_search': None, 'model': 'stub', 'seconds': 0.1}))
'''
STUB_JOB = r'''
import json, os, sys
job = json.load(sys.stdin)
open(os.environ['STUB_JOB_LOG'], 'a').write(json.dumps(job) + '\n')
if 'unreachable' in job['description']: print('Could not reach the MacBook (stub)', file=sys.stderr); sys.exit(3)
if 'boom' in job['description']: print('stub starter crashed', file=sys.stderr); sys.exit(1)
print('Started on the MacBook (stub)')
'''
fails = []

def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))
    if not ok: fails.append(name)

def main():
    os.makedirs(os.path.join(ROOT, 'build'), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='ask-test-', dir=os.path.join(ROOT, 'build'))
    site, state = os.path.join(tmp, 'site'), os.path.join(tmp, 'state')
    os.makedirs(os.path.join(site, 'test-trip'))
    open(os.path.join(site, 'index.html'), 'w').write('<h1>home</h1>')
    open(os.path.join(site, 'test-trip', 'index.html'), 'w').write('<h1>trip</h1>')
    open(os.path.join(tmp, 'stub_ask.py'), 'w').write(STUB_ASK); open(os.path.join(tmp, 'stub_job.py'), 'w').write(STUB_JOB)
    s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
    joblog = os.path.join(tmp, 'jobs.log')
    env = dict(os.environ, FLIGHTS_PORT=str(port), FLIGHTS_SITE=site, FLIGHTS_STATE=state, STUB_JOB_LOG=joblog,
               FLIGHTS_ASK_CMD=shlex.join([sys.executable, tmp + '/stub_ask.py']), FLIGHTS_JOB_CMD=shlex.join([sys.executable, tmp + '/stub_job.py']),
               FLIGHTS_JOB_START_QUIET='3', FLIGHTS_PUBLIC_BASE=f'http://127.0.0.1:{port}')
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, 'src', 'service.py')], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f'http://127.0.0.1:{port}'
    def req(method, path, body=None, headers=None):
        h = {'Content-Type': 'application/json'}; h.update(headers if headers is not None else {'X-Flights': '1'})
        r = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(), method=method, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp: return resp.status, json.loads(resp.read() or b'null') if 'json' in resp.headers.get('Content-Type', '') else resp.read().decode()
        except urllib.error.HTTPError as e:
            raw = e.read(); return e.code, (json.loads(raw) if raw[:1] in (b'{', b'[') else raw.decode())
    def wait_ask(rid, limit=15):
        t = time.time()
        while time.time() - t < limit:
            c, d = req('GET', '/flights/api/ask/' + urllib.parse.quote(rid, safe=''))
            if d.get('status') != 'working': return d
            time.sleep(0.3)
        return d
    def jobs(): return req('GET', '/flights/api/jobs')[1]
    def job(jid): return next(j for j in jobs()['jobs'] if j['id'] == jid)
    def token(jid):
        return [json.loads(l) for l in open(joblog)][-1]['token'] if jid is None else next(json.loads(l)['token'] for l in reversed(open(joblog).readlines()) if json.loads(l)['id'] == jid)
    def prog(jid, body, tok):
        return req('POST', '/flights/api/jobs/' + urllib.parse.quote(jid, safe='') + '/progress', body, {'X-Flights': '1', 'X-Job-Token': tok})
    try:
        for _ in range(50):
            try:
                if req('GET', '/flights/healthz')[0] == 200: break
            except OSError: time.sleep(0.1)
        check('healthz answers', req('GET', '/flights/healthz') == (200, 'ok'))
        check('pages still served', req('GET', '/flights/test-trip/')[0] == 200 and req('GET', '/flights/')[0] == 200)
        # headers rule
        check('ask without X-Flights is 403', req('POST', '/flights/api/ask', {'page': 'test-trip', 'question': 'hi'}, {})[0] == 403)
        check('jobs without X-Flights is 403', req('POST', '/flights/api/jobs', {'page': 'test-trip', 'description': 'x', 'dests': ['BOS']}, {})[0] == 403)
        check('progress without X-Flights is 403', req('POST', '/flights/api/jobs/x/progress', {'status': 'running'}, {'X-Job-Token': 'x'})[0] == 403)
        # 409 rule on likes and hides still holds
        c1, d1 = req('POST', '/flights/api/state/test-trip', {'value': {'like': {'a': True}, 'hide': {}}, 'revision': 0})
        c2, d2 = req('POST', '/flights/api/state/test-trip', {'value': {'like': {}, 'hide': {}}, 'revision': 0})
        check('state save then stale revision gives 409 with current copy', c1 == 200 and c2 == 409 and d2.get('revision') == 1 and d2['value']['like'] == {'a': True}, f'{c1} {c2} {d2}')
        # ask validation
        check('ask with bad page is 400', req('POST', '/flights/api/ask', {'page': 'Bad Page', 'question': 'hi'})[0] == 400)
        check('ask with empty question is 400', req('POST', '/flights/api/ask', {'page': 'test-trip', 'question': '   '})[0] == 400)
        check('ask over 500 characters is 400', req('POST', '/flights/api/ask', {'page': 'test-trip', 'question': 'x' * 501})[0] == 400)
        check('ask with visible not a list is 400', req('POST', '/flights/api/ask', {'page': 'test-trip', 'question': 'hi', 'visible': 'a'})[0] == 400)
        check('ask with huge visible list is 400', req('POST', '/flights/api/ask', {'page': 'test-trip', 'question': 'hi', 'visible': ['a'] * 2001})[0] == 400)
        check('non-object body is 400', req('POST', '/flights/api/ask', ['x'])[0] == 400)
        # ask happy path
        c, d = req('POST', '/flights/api/ask', {'page': 'test-trip', 'question': 'which are cheapest', 'visible': ['r1', 'r2', 'r3'], 'filters': {'stops': 'any'}})
        check('ask returns an id and working', c == 200 and d.get('status') == 'working' and d.get('id'), f'{c} {d}')
        done = wait_ask(d['id'])
        check('ask answer comes back with ids and label', done.get('status') == 'done' and done.get('ids') == ['r1', 'r2'] and done.get('label') == 'Stub pick', str(done))
        check('ask id with : and + works url-encoded', '+' in d['id'] and ':' in d['id'])
        c, d = req('POST', '/flights/api/ask', {'page': 'test-trip', 'question': 'search'})
        done = wait_ask(d['id'])
        check('ask can propose a search', (done.get('needs_search') or {}).get('dests') == ['BOS'], str(done))
        c, d = req('POST', '/flights/api/ask', {'page': 'test-trip', 'question': 'fail'})
        done = wait_ask(d['id'])
        check('helper failure is a readable error', done.get('status') == 'error' and 'stub failure' in done.get('error', ''), str(done))
        check('unknown ask id is 404', req('GET', '/flights/api/ask/' + urllib.parse.quote('2026-11-23T10:00:00+00:00-abcdef', safe=''))[0] == 404)
        check('malformed ask id is 400', req('GET', '/flights/api/ask/nonsense')[0] == 400)
        h = req('GET', '/flights/api/ask?page=test-trip')[1]
        check('recent questions list for the page', len(h['asks']) == 3 and h['asks'][0]['question'] == 'fail', str([a['question'] for a in h['asks']]))
        check('recent list needs a page', req('GET', '/flights/api/ask')[0] == 400)
        # ask rate limit: at most 2 working
        a1 = req('POST', '/flights/api/ask', {'page': 'test-trip', 'question': 'slow one'})
        a2 = req('POST', '/flights/api/ask', {'page': 'test-trip', 'question': 'slow two'})
        a3 = req('POST', '/flights/api/ask', {'page': 'test-trip', 'question': 'third'})
        check('third ask while two are working is 429', a1[0] == 200 and a2[0] == 200 and a3[0] == 429 and 'already answering' in a3[1]['error'], f'{a1[0]} {a2[0]} {a3}')
        wait_ask(a1[1]['id']); wait_ask(a2[1]['id'])
        check('asks work again once they finish', req('POST', '/flights/api/ask', {'page': 'test-trip', 'question': 'again'})[0] == 200)
        # jobs validation
        check('job without destination is 400', req('POST', '/flights/api/jobs', {'page': 'test-trip', 'description': 'x', 'dests': []})[0] == 400)
        check('job without description is 400', req('POST', '/flights/api/jobs', {'page': 'test-trip', 'description': '', 'dests': ['BOS']})[0] == 400)
        check('job with bad page is 400', req('POST', '/flights/api/jobs', {'page': '../etc', 'description': 'x', 'dests': ['BOS']})[0] == 400)
        # jobs queue: one at a time
        c, j1 = req('POST', '/flights/api/jobs', {'page': 'test-trip', 'description': 'SEA to BOS', 'origins': ['sea', 'bad1'], 'dests': ['BOS'], 'dates': ['2027-03-12', 'nope'], 'from_ask': 'x'})
        check('first job starts at once', c == 200 and j1['status'] == 'starting' and j1['origins'] == ['SEA'] and j1['dates'] == ['2027-03-12'], str(j1))
        check('job token is never returned', 'token' not in j1 and all('token' not in j for j in jobs()['jobs']))
        c, j2 = req('POST', '/flights/api/jobs', {'page': 'test-trip', 'description': 'PDX to PVD', 'dests': ['PVD']})
        check('second job waits queued', c == 200 and j2['status'] == 'queued', str(j2))
        c, d = req('POST', '/flights/api/jobs', {'page': 'test-trip', 'description': 'PDX to PVD', 'dests': ['PVD']})
        check('duplicate active job is 409', c == 409 and d['id'] == j2['id'], f'{c} {d}')
        time.sleep(0.8)
        check('starter result recorded on the job', job(j1['id'])['note'] == 'Started on the MacBook (stub)', job(j1['id'])['note'])
        lg = [json.loads(l) for l in open(joblog)]
        check('starter got progress URL and token', lg[0]['progress_url'].startswith(base + '/flights/api/jobs/') and len(lg[0]['token']) == 32)
        t1 = token(j1['id'])
        check('progress with wrong token is 403', prog(j1['id'], {'status': 'running'}, 'nope')[0] == 403)
        check('progress with bad status is 400', prog(j1['id'], {'status': 'queued'}, t1)[0] == 400)
        c, d = prog(j1['id'], {'status': 'running', 'note': 'Searching Google Flights'}, t1)
        check('progress running accepted', c == 200 and d['status'] == 'running' and d['note'] == 'Searching Google Flights', str(d))
        # the reporter script itself, against this test service
        jf = os.path.join(tmp, 'job1.json'); json.dump({'progress_url': lg[0]['progress_url'], 'token': t1}, open(jf, 'w'))
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'src', 'jobs_report.py'), jf, 'running', 'Reporter works'], capture_output=True, text=True)
        check('jobs_report.py posts progress', r.returncode == 0 and r.stdout.strip() == '200 running' and job(j1['id'])['note'] == 'Reporter works', r.stdout + r.stderr)
        c, d = prog(j1['id'], {'status': 'done', 'note': 'Added 40 flights', 'slug': 'test-trip'}, t1)
        check('progress done with slug', c == 200 and d['status'] == 'done' and d['slug'] == 'test-trip')
        check('next queued job starts when one ends', job(j2['id'])['status'] == 'starting')
        check('progress after the end is 409', prog(j1['id'], {'status': 'running'}, t1)[0] == 409)
        # quiet job is failed so the queue moves (start-quiet set to 3 s for this test)
        c, j3 = req('POST', '/flights/api/jobs', {'page': 'test-trip', 'description': 'third trip', 'dests': ['BDL']})
        time.sleep(3.5)
        check('a quiet starting job is marked failed and the next one starts', job(j2['id'])['status'] == 'failed' and 'never reported back' in job(j2['id'])['note'] and job(j3['id'])['status'] == 'starting', f"{job(j2['id'])} {job(j3['id'])['status']}")
        time.sleep(0.8)  # let the starter thread for j3 run
        check('needs_you from the Mac accepted', prog(j3['id'], {'status': 'needs_you', 'note': 'United signed out'}, token(j3['id']))[1].get('status') == 'needs_you')
        # needs_you from the starter, retry and cancel
        c, j4 = req('POST', '/flights/api/jobs', {'page': 'home', 'description': 'unreachable mac', 'dests': ['SEA']})
        time.sleep(0.8)
        check('starter exit 3 becomes needs_you with its message', job(j4['id'])['status'] == 'needs_you' and 'Could not reach' in job(j4['id'])['note'], str(job(j4['id'])))
        c, d = req('POST', '/flights/api/jobs/' + urllib.parse.quote(j4['id'], safe='') + '/retry', {})
        check('retry puts it back in line', c == 200 and d['status'] in ('queued', 'starting') and d['retries'] == 1, str(d))
        time.sleep(0.8)
        c, j5 = req('POST', '/flights/api/jobs', {'page': 'home', 'description': 'boom', 'dests': ['SEA']})
        time.sleep(0.8)
        check('starter crash becomes failed', job(j5['id'])['status'] == 'failed' and 'crashed' in job(j5['id'])['note'], str(job(j5['id'])))
        c, d = req('POST', '/flights/api/jobs/' + urllib.parse.quote(j1['id'], safe='') + '/retry', {})
        check('retry of a done job is 409', c == 409)
        c, d = req('POST', '/flights/api/jobs/' + urllib.parse.quote(j1['id'], safe='') + '/cancel', {})
        check('cancel of a non-queued job is 409', c == 409)
        # daily cap: 6 real searches a day; dry runs not counted
        lim = jobs()['limits']
        check('limits reported', lim['per_day'] == 6 and lim['used_today'] == 5, str(lim))
        c, j6 = req('POST', '/flights/api/jobs', {'page': 'home', 'description': 'sixth', 'dests': ['LAX']})
        c7, d7 = req('POST', '/flights/api/jobs', {'page': 'home', 'description': 'seventh', 'dests': ['LAX']})
        check('seventh search of the day is 429', c == 200 and c7 == 429 and '6 searches today' in d7['error'], f'{c} {c7} {d7}')
        c, dr = req('POST', '/flights/api/jobs', {'page': 'home', 'description': 'dry run', 'dests': ['LAX'], 'dry_run': True})
        check('dry run allowed past the cap and marked', c == 200 and dr['dry_run'] is True, str(dr))
        c, d = req('POST', '/flights/api/jobs/' + urllib.parse.quote(dr['id'], safe='') + '/cancel', {})
        check('cancel of a queued job works', c == 200 and d['status'] == 'cancelled', f'{c} {d}')
        check('unknown job is 404', req('GET', '/flights/api/jobs/nope')[0] == 404 and req('POST', '/flights/api/jobs/nope/retry', {})[0] == 404)
        check('one job at a time held throughout', sum(1 for j in jobs()['jobs'] if j['status'] in ('starting', 'running')) <= 1)
    finally:
        srv.terminate(); srv.wait(5)
        shutil.rmtree(tmp, ignore_errors=True)
    print(f'{len(fails)} failed' if fails else 'all passed')
    return 1 if fails else 0

if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--write-stubs':
        os.makedirs(sys.argv[2], exist_ok=True)
        open(os.path.join(sys.argv[2], 'stub_ask.py'), 'w').write(STUB_ASK); open(os.path.join(sys.argv[2], 'stub_job.py'), 'w').write(STUB_JOB)
        print('wrote', os.path.join(sys.argv[2], 'stub_ask.py'), 'and stub_job.py; the job stub appends to $STUB_JOB_LOG'); sys.exit(0)
    sys.exit(main())
