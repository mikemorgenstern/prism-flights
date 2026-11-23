# Claude · 2026-11-23 · Session 8e680ddd-6b26-44d7-8b07-e667fe163a25 · flights portal: report a search job's progress (runs on the Mac)
"""The only command a portal search job's Claude session may use to talk to the portal.

  python3 src/jobs_report.py <job file> <status> "<short note>" [--slug <trip slug>]
  status: starting | running | done | failed | needs_you

The job file (<mac_job_dir>/<id>.json, written by the server) holds the progress URL and the job's token, so the
session cannot point a report anywhere else. Prints the portal's answer; exit 1 if the portal refused or was unreachable.
"""
import json, sys, urllib.error, urllib.request

def report(jobfile, status, note, slug=None):
    job = json.load(open(jobfile))
    body = {'status': status, 'note': note[:500]}
    if slug: body['slug'] = slug
    req = urllib.request.Request(job['progress_url'], data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json', 'X-Flights': '1', 'X-Job-Token': job['token']})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b'{}')
        except ValueError: return e.code, {}
    except OSError as e:
        return 0, {'error': f'portal unreachable: {e}'}

if __name__ == '__main__':
    a = sys.argv[1:]
    slug = None
    if '--slug' in a:
        i = a.index('--slug'); slug = a[i + 1] if i + 1 < len(a) else None; del a[i:i + 2]
    if len(a) < 2 or a[1] not in ('starting', 'running', 'done', 'failed', 'needs_you'):
        print(__doc__, file=sys.stderr); sys.exit(2)
    code, resp = report(a[0], a[1], a[2] if len(a) > 2 else a[1], slug)
    print(f"{code} {resp.get('status') or resp.get('error') or ''}".strip())
    sys.exit(0 if code == 200 else 1)
