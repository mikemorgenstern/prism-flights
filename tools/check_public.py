# Claude · 2026-11-23 · Session 8e680ddd-6b26-44d7-8b07-e667fe163a25 · pre-publish privacy check for this repo
"""Fails (exit 1) when anything about to be published could carry private information.

  python3 tools/check_public.py [--tree]      run from anywhere inside the repo

Checks, in the working tree and (unless --tree) the whole git history:
  1. every tracked file, and every file on disk outside .git, is listed in tools/public-files.txt
  2. no binary file, except images under src/assets/ that carry no comments, XMP, GPS or large EXIF blocks
  3. no value from the maintainer's private banned list in file contents, the full history (git log -p --all),
     commit messages, author and committer names and emails, branch names or tags

The banned list is a JSON file kept outside the repo ({"literal": [...], "regex": [...], "allow": [...]}); its path
comes from `git config prism.bannedList` or PRISM_BANNED. Without it the check refuses to pass. Literals match as
whole words, ignoring case; regexes match as written; "allow" strings are removed before matching. Matches are shown
masked, so this output never repeats a private value in full.
"""
import json, os, re, struct, subprocess, sys

def git(*a, cwd=None):
    return subprocess.run(['git'] + list(a), capture_output=True, text=True, cwd=cwd, errors='replace')

def fail(msg): print('FAIL ' + msg); FAILS.append(msg)
FAILS = []

def mask(s):
    return f'a {len(s.strip())}-character value'   # never show any part of a private value

def load_rules(top):
    p = os.environ.get('PRISM_BANNED') or git('config', '--get', 'prism.bannedList', cwd=top).stdout.strip()
    if not p or not os.path.isfile(os.path.expanduser(p)):
        print('FAIL no banned list: set `git config prism.bannedList <path>` (or PRISM_BANNED) to the private list'); sys.exit(1)
    d = json.load(open(os.path.expanduser(p)))
    lits = [x for x in d.get('literal', []) if x.strip()]
    rules = [(f'literal #{i}', re.compile(r'(?<![A-Za-z0-9_])' + re.escape(x) + r'(?![A-Za-z0-9_])', re.I)) for i, x in enumerate(lits)]
    rules += [(f'regex #{i}', re.compile(x)) for i, x in enumerate(d.get('regex', []))]
    allow = sorted(d.get('allow', []), key=len, reverse=True)
    if len(rules) < 20: print(f'FAIL banned list has only {len(rules)} rules; it looks wrong'); sys.exit(1)
    print(f'banned list: {len(lits)} literals, {len(d.get("regex", []))} patterns, {len(allow)} allowed strings')
    return rules, allow

def scan(text, where, rules, allow, limit=20):
    for a in allow: text = text.replace(a, ' ')
    hits = 0
    for name, rx in rules:
        for m in rx.finditer(text):
            line = text.count('\n', 0, m.start()) + 1
            fail(f'{where}:{line}: {name} matched {mask(m.group(0))}')
            hits += 1
            if hits >= limit: fail(f'{where}: stopping after {limit} matches'); return

def image_ok(path, data):
    """JPEG or PNG with no comment, XMP, GPS or big EXIF segment. Returns (problem or None, metadata bytes to scan)."""
    if data[:2] == b'\xff\xd8':
        i = 2
        while i < len(data) - 4 and data[i] == 0xFF:
            m = data[i + 1]
            if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7: i += 2; continue
            L = struct.unpack('>H', data[i + 2:i + 4])[0]; seg = data[i + 4:i + 2 + L]
            if m == 0xFE: return 'has a JPEG comment', data[:i + 2 + L]
            if m == 0xE1 and (b'http://ns.adobe.com/xap' in seg or len(seg) > 400): return 'has XMP or a large EXIF block', data[:i + 2 + L]
            if m == 0xE1 and b'GPS' in seg: return 'has GPS data', data[:i + 2 + L]
            if m == 0xDA: return None, data[:i]
            i += 2 + L
        return 'has no image data marker', data
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        meta, i = b'', 8
        while i + 8 <= len(data):
            L, t = struct.unpack('>I4s', data[i:i + 8])
            if t != b'IDAT': meta += t + data[i + 8:i + 8 + L]
            i += 12 + L
        return ('has a text or EXIF chunk' if any(t in meta for t in (b'tEXt', b'iTXt', b'zTXt', b'eXIf')) else None), meta
    return 'is not a JPEG or PNG', data

def main():
    tree_only = '--tree' in sys.argv
    top = git('rev-parse', '--show-toplevel').stdout.strip()
    if not top: print('FAIL not inside a git repository'); sys.exit(1)
    os.chdir(top)
    rules, allow = load_rules(top)
    listed = {l.strip() for l in open('tools/public-files.txt') if l.strip() and not l.startswith('#')}
    tracked = set(git('ls-files', '-z').stdout.split('\0')) - {''}
    ondisk = set()
    for d, dirs, files in os.walk('.'):
        dirs[:] = [x for x in dirs if x != '.git']
        for f in files: ondisk.add(os.path.relpath(os.path.join(d, f)))
    for f in sorted(tracked - listed): fail(f'{f}: tracked but not in tools/public-files.txt')
    for f in sorted(ondisk - listed): fail(f'{f}: on disk but not in tools/public-files.txt (remove it or list it)')
    for f in sorted(ondisk & listed):
        data = open(f, 'rb').read()
        if b'\0' in data[:8000] or f.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf', '.zip')):
            if not re.match(r'^src/assets/[A-Za-z0-9_-]+\.(jpg|png)$', f): fail(f'{f}: binary file outside src/assets/'); continue
            why, meta = image_ok(f, data)
            if why: fail(f'{f}: image {why}')
            scan(meta.decode('latin-1'), f + ' (image metadata)', rules, allow, limit=5)
        else:
            scan(data.decode('utf-8', 'replace'), f, rules, allow)
        scan(f, 'file name ' + f, rules, allow)
    print(f'files: {len(ondisk)} on disk, {len(tracked)} tracked, {len(listed)} listed')
    if not tree_only and git('rev-parse', '--verify', 'HEAD').returncode == 0:
        scan(git('log', '-p', '--all', '--format=%H%n%an <%ae>%n%cn <%ce>%n%B').stdout, 'history', rules, allow)  # images: checked in the tree
        scan(git('for-each-ref', '--format=%(refname) %(contents)').stdout, 'refs and tags', rules, allow)
        n = git('rev-list', '--all', '--count').stdout.strip()
        print(f'history: {n} commits scanned (diffs, messages, authors, committers, refs, tags)')
    print('PASS: nothing private found' if not FAILS else f'{len(FAILS)} problems; nothing may be published until they are fixed')
    sys.exit(1 if FAILS else 0)

if __name__ == '__main__':
    main()
