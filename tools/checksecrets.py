#!/usr/bin/env python3
"""Refuse to commit, build or release anything containing keys, passwords or personal details.

    python3 tools/checksecrets.py               # every tracked file in this repo
    python3 tools/checksecrets.py --staged      # only what is about to be committed (the pre-commit hook)
    python3 tools/checksecrets.py --history     # every version of every file ever committed
    python3 tools/checksecrets.py --dir PATH    # every file in a folder (used on build output / the tester site)
    add --repo PATH to check another git checkout (e.g. ../ezaide) instead of this one

Exit 1 and a list of findings if anything is found. Findings show only the first few characters of a match,
so running this never prints a whole key.

What it looks for (see RULES): API keys and tokens (Anthropic/Claude, OpenAI, GitHub, Google, AWS, Slack,
Stripe, Cloudflare), private keys, login/session cookies, passwords or secrets written into code, credential
files (.env, *.pem, id_rsa, credentials.json), and personal email addresses or real-looking phone numbers.
Allowed on purpose: the public support address ezaide.app@gmail.com, GitHub/Anthropic no-reply addresses,
911, and 555-01xx numbers (reserved for fiction).
"""
import os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RULES = [
    ('Anthropic / Claude key or session', r'sk-ant-[A-Za-z0-9_-]{8,}'),
    ('Claude session cookie', r'sessionKey\s*[=:]\s*["\']?[A-Za-z0-9_-]{12,}'),
    ('OpenAI-style key', r'\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}'),
    ('GitHub token', r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})'),
    ('Google API key', r'\bAIza[0-9A-Za-z_-]{30,}'),
    ('Google OAuth secret', r'\bGOCSPX-[A-Za-z0-9_-]{10,}'),
    ('AWS access key', r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b'),
    ('Slack token', r'\bxox[abprs]-[A-Za-z0-9-]{10,}'),
    ('Stripe key', r'\b(?:sk|rk|pk)_live_[A-Za-z0-9]{10,}'),
    ('Cloudflare token', r'(?i)cloudflare[^\n]{0,40}(?:token|key)\s*[=:]\s*["\'][A-Za-z0-9_-]{20,}'),
    ('Private key', r'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----'),
    ('Login token (JWT)', r'\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'),
    ('Bearer token', r'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{24,}'),
    ('Password / secret in code', r'(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)\s*[=:]\s*["\'][^"\'\s]{8,}["\']'),
    ('URL with a password in it', r'[a-z]+://[^/\s:@"\']+:[^/\s@"\']{6,}@'),
]
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}')
EMAIL_OK = re.compile(r'^(?:ezaide\.app@gmail\.com|noreply@anthropic\.com|noreply@github\.com|[^@]+@users\.noreply\.github\.com|[^@]+@example\.(?:com|org))$', re.I)
PHONE = re.compile(r'(?<![\d.])(?:\+?1[ .-]?)?\(?([2-9]\d{2})\)?[ .-]([2-9]\d{2})[ .-](\d{4})(?![\d])')
BAD_FILES = re.compile(r'(?:^|/)(?:\.env(?:\..*)?|.*\.pem|.*\.p12|.*\.pfx|.*\.key|id_rsa|id_ed25519|credentials\.json|\.netrc|\.npmrc|\.pypirc|settings\.local\.json)$')
SKIP = re.compile(r'\.(?:png|jpe?g|gif|ico|webp|pdf|woff2?|pyc)$', re.I)


def scan_text(name, text):
    found = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for label, pat in RULES:
            for m in re.finditer(pat, line):
                found.append((name, line_no, label, m.group(0)))
        for m in EMAIL.finditer(line):
            if not EMAIL_OK.match(m.group(0)):
                found.append((name, line_no, 'Email address (personal details)', m.group(0)))
        for m in PHONE.finditer(line):
            if not (m.group(2) == '555' and m.group(3).startswith('01')):
                found.append((name, line_no, 'Phone number (personal details)', m.group(0)))
    return found


def scan_file(name, data):
    if BAD_FILES.search(name):
        return [(name, 0, 'Credential file must never be committed', name)]
    if SKIP.search(name) or (isinstance(data, bytes) and b'\0' in data[:8000]):
        return []
    return scan_text(name, data.decode('utf-8', 'replace') if isinstance(data, bytes) else data)


def git(*a, cwd=ROOT):
    return subprocess.run(['git', *a], cwd=cwd, capture_output=True, check=True).stdout


def scan_tracked(cwd=ROOT):
    out = []
    for f in git('ls-files', '-z', cwd=cwd).decode().split('\0'):
        if f and os.path.isfile(os.path.join(cwd, f)):
            out += scan_file(f, open(os.path.join(cwd, f), 'rb').read())
    return out


def scan_staged(cwd=ROOT):
    out = []
    for f in git('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z', cwd=cwd).decode().split('\0'):
        if f:
            out += scan_file(f, git('show', ':' + f, cwd=cwd))
    return out


def scan_history(cwd=ROOT):
    out, seen = [], set()
    for line in git('rev-list', '--all', '--objects', cwd=cwd).decode().splitlines():
        parts = line.split(' ', 1)
        if len(parts) < 2 or parts[0] in seen:
            continue
        seen.add(parts[0])
        if git('cat-file', '-t', parts[0], cwd=cwd).strip() == b'blob':
            out += [(f'{parts[1]} (old version {parts[0][:7]})',) + x[1:] for x in scan_file(parts[1], git('cat-file', 'blob', parts[0], cwd=cwd))]
    return out


def scan_dir(path):
    out = []
    for base, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d != '.git']
        for f in files:
            p = os.path.join(base, f)
            out += scan_file(os.path.relpath(p, path), open(p, 'rb').read())
    return out


def report(found, what):
    if not found:
        print(f'Secrets check: nothing found in {what}.')
        return True
    print(f'SECRETS CHECK FAILED: {len(found)} problem(s) in {what}. Remove them before committing or releasing.')
    for name, line_no, label, match in found[:50]:
        shown = match if label.startswith('Credential file') else (match[:6] + '…' if len(match) > 6 else match)
        print(f'  {name}:{line_no}  {label}: {shown}')
    return False


if __name__ == '__main__':
    a = sys.argv[1:]
    repo = os.path.abspath(a[a.index('--repo') + 1]) if '--repo' in a else ROOT
    if '--staged' in a:
        ok = report(scan_staged(repo), 'the files being committed')
    elif '--history' in a:
        ok = report(scan_history(repo), 'every version ever committed')
    elif '--dir' in a:
        d = a[a.index('--dir') + 1]
        ok = report(scan_dir(d), d)
    else:
        ok = report(scan_tracked(repo), 'the tracked files')
    sys.exit(0 if ok else 1)
