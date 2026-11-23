# Claude · 2026-11-23 · Session 8e680ddd-6b26-44d7-8b07-e667fe163a25 · flights portal: start one search job on the Mac (runs on the server)
"""Run by service.py when a queued job's turn comes. Reads the job (with its progress URL and token) on stdin, writes it
into the project's job folder on the Mac (config mac_job_dir) and asks src/jobs_mac.py there to start it in a
detached tmux session. One ssh call; no browser is touched from here.

  exit 0  started (stdout: one line)
  exit 3  needs the owner (Mac asleep or offline, Chrome closed, Claude login expired); stderr says what to do
  exit 1  anything else failed; stderr says what
Settings: FLIGHTS_MAC or config mac (ssh target), FLIGHTS_MAC_PROJECT or config mac_project (project folder there),
config mac_job_dir (job folder inside the project, default jobs).
"""
import json, os, re, shlex, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import portal_config

MAC = os.environ.get('FLIGHTS_MAC') or portal_config.get('mac')
PROJECT = os.environ.get('FLIGHTS_MAC_PROJECT') or portal_config.get('mac_project')
JOBDIR = portal_config.get('mac_job_dir', 'jobs')

def main():
    if not MAC or not PROJECT:
        print('Search jobs are off: set mac and mac_project in config.local.json on the server', file=sys.stderr); return 1
    job = json.load(sys.stdin)
    name = re.sub(r'[^0-9A-Za-z-]', '', job['id'])
    rel = f'{JOBDIR}/{name}.json'
    q = shlex.quote
    remote = (f'cd {q(PROJECT)} && mkdir -p {q(JOBDIR)} && umask 077 && cat > {q(rel + ".tmp")} && mv {q(rel + ".tmp")} {q(rel)} '
              f'&& python3 src/jobs_mac.py start {q(rel)}')
    try:
        p = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=12', '-o', 'ServerAliveInterval=10', MAC, remote],
                           input=json.dumps(job), capture_output=True, text=True, timeout=100)
    except subprocess.TimeoutExpired:
        print('The MacBook did not answer within 100 seconds (asleep or offline?). Wake it, open Chrome, then press Try again.', file=sys.stderr); return 3
    out, err = p.stdout.strip(), p.stderr.strip()
    if p.returncode == 255:
        print('Could not reach the MacBook (asleep or offline). Wake it, open Chrome, then press Try again.', file=sys.stderr); return 3
    if p.returncode != 0:
        print((err.splitlines() or out.splitlines() or [f'The MacBook refused the job (exit {p.returncode})'])[-1][:300], file=sys.stderr)
        return 3 if p.returncode == 3 else 1
    print((out.splitlines() or ['Started on the MacBook'])[-1][:300])
    return 0

if __name__ == '__main__':
    sys.exit(main())
