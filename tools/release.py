#!/usr/bin/env python3
"""The whole release checklist in one command. Only run it when Zach says "release".

    python3 tools/release.py 1.20                 # family version, then App Store version + tester site
    python3 tools/release.py 1.20 --family-only   # main / Zach's iPad only
    python3 tools/release.py 1.20 --store-only    # App Store version + tester site, built from what is on main
    add --dry-run to do every step except commit/push (prepared commits are shown, nothing leaves this machine)
    add --notes "text" to put a short change list in the release commit
    add --ezaide PATH if the zacharyminer10/ezaide checkout is not next to this one (default ../ezaide)

Family part:  bump VER / VERSION, build both versions, regression tests on both (with upgrade checks from what is
              live on main and app-store now), commit as Zach, push main, wait for the GitHub Pages deploy.
Store part:   build from origin/main, test the App Store build, replace the app-store branch's files with the build
              (one commit on top; the branch is output only), copy it to app/ in the ezaide repo with the noindex
              line, push, wait for that Pages deploy.
"""
import os, re, sys, json, shutil, subprocess, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import build as B

ZACH = ['-c', 'user.name=Zach', '-c', 'user.email=zacharyminer10@users.noreply.github.com']
MAIN_REPO, EZ_REPO = 'zacharyminer10/zeke-care', 'zacharyminer10/ezaide'
NOINDEX = '<meta name="robots" content="noindex">'
STORE_FILES = ['index.html', 'sw.js', 'manifest.webmanifest', 'icon-180.png', 'icon-192.png', 'icon-512.png']
GENERATED_NOTE = """# app-store branch: generated, do not edit

This branch only holds the built App Store version of EZAide (index.html, sw.js, manifest, icons, privacy.html).
It is rebuilt from `main` by `tools/release.py` (which runs `tools/build.py`) on every release.
Never edit, merge or cherry-pick here: make changes on `main` (App Store-only values live in `store/edition.js`).
"""


def say(msg):
    print('\n== ' + msg, flush=True)


def fail(msg):
    print('\nRELEASE STOPPED: ' + msg)
    sys.exit(1)


def git(*a, cwd=ROOT, check=True, retry=False):
    for i in range(5 if retry else 1):
        r = subprocess.run(['git', *a], cwd=cwd, capture_output=True, text=True)
        if r.returncode == 0 or not retry:
            break
        time.sleep(2 ** (i + 1))
    if check and r.returncode:
        fail(f'git {" ".join(a)} failed:\n{r.stdout}{r.stderr}')
    return r.stdout.strip()


def bump(folder, ver):
    for f, pat, new in [('index.html', r"var VER='[^']+'", f"var VER='{ver}'"),
                        ('sw.js', r"const VERSION = '[^']+'", f"const VERSION = '{ver}'")]:
        p = os.path.join(folder, f); s = open(p, encoding='utf-8').read()
        if len(re.findall(pat, s)) != 1:
            fail(f'{f}: version line not found exactly once')
        open(p, 'w', encoding='utf-8').write(re.sub(pat, new, s))


def regression(html, prev_html, label, src=ROOT):
    """Run the regression suite that belongs to the same source as the build (src), not this checkout's."""
    say(f'Regression tests: {label}')
    with tempfile.NamedTemporaryFile('w', suffix='.html', delete=False, encoding='utf-8') as f:
        f.write(prev_html)
    r = subprocess.run([sys.executable, os.path.join(src, 'tests', 'regression.py'), '--html', html, '--prev', f.name],
                       capture_output=True, text=True)
    os.unlink(f.name)
    out = r.stdout + r.stderr
    fails = [l for l in out.splitlines() if l.startswith('FAIL')]
    total = len([l for l in out.splitlines() if l.startswith(('PASS', 'FAIL'))])
    print(f'{total - len(fails)}/{total} passed')
    if r.returncode or fails or not total:
        fail(f'{label}: tests failed\n' + '\n'.join(fails or out.splitlines()[-15:]))


def wait_pages(repo, sha, label, timeout=900):
    say(f'Waiting for the GitHub Pages deploy of {label} ({sha[:7]})')
    if not shutil.which('gh'):
        print(f'gh is not installed: check https://github.com/{repo}/actions by hand.')
        return
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = subprocess.run(['gh', 'api', f'repos/{repo}/actions/runs?head_sha={sha}'], capture_output=True, text=True)
        runs = json.loads(r.stdout).get('workflow_runs', []) if r.returncode == 0 else []
        if runs and all(x['status'] == 'completed' for x in runs):
            bad = [x['name'] for x in runs if x['conclusion'] != 'success']
            if bad:
                fail(f'{label}: deploy failed ({", ".join(bad)}). See https://github.com/{repo}/actions')
            print('Deployed.')
            return
        time.sleep(15)
    fail(f'{label}: deploy did not finish in {timeout // 60} minutes. See https://github.com/{repo}/actions')


def family(ver, dry, notes):
    say('Family version (main)')
    if git('status', '--porcelain'):
        fail('there are uncommitted changes; commit or discard them first')
    git('fetch', 'origin', '+refs/heads/main:refs/remotes/origin/main',
        '+refs/heads/app-store:refs/remotes/origin/app-store', retry=True)
    if subprocess.run(['git', 'merge-base', '--is-ancestor', 'origin/main', 'HEAD'], cwd=ROOT).returncode:
        fail('main has commits this branch does not have; merge origin/main into this branch first')
    prev_main = git('show', 'origin/main:index.html')
    prev_store = git('show', 'origin/app-store:index.html')
    src = ROOT
    if dry:
        src = tempfile.mkdtemp()
        for f in git('ls-files').splitlines():
            os.makedirs(os.path.dirname(os.path.join(src, f)), exist_ok=True)
            shutil.copy(os.path.join(ROOT, f), os.path.join(src, f))
    bump(src, ver)
    out = tempfile.mkdtemp()
    try:
        _, fam, sto = B.build(src, out)
    except B.BuildError as e:
        fail('build refused: ' + str(e))
    regression(os.path.join(fam, 'index.html'), prev_main, 'family build (upgrade from live main)', src)
    regression(os.path.join(sto, 'index.html'), prev_store, 'App Store build (upgrade from live app-store)', src)
    if dry:
        print(f'[dry run] would commit "Release {ver}" as Zach and push it to main')
        return src
    git('add', 'index.html', 'sw.js')
    if git('status', '--porcelain'):
        git(*ZACH, 'commit', '-q', '-m', f'Release {ver}' + (f'\n\n{notes}' if notes else ''))
    sha = git('rev-parse', 'HEAD')
    say('Pushing main')
    git('push', 'origin', 'HEAD:main', retry=True)
    branch = git('rev-parse', '--abbrev-ref', 'HEAD')
    if branch not in ('HEAD', 'main'):
        git('push', '-u', 'origin', branch, retry=True)
    wait_pages(MAIN_REPO, sha, 'the family version')
    return None


def store(ver, dry, ez_path, dry_src=None):
    say('App Store version (app-store branch + tester site)')
    git('fetch', 'origin', '+refs/heads/main:refs/remotes/origin/main',
        '+refs/heads/app-store:refs/remotes/origin/app-store', retry=True)
    if dry_src:  # dry run of a full release: build from the (not pushed) bumped copy
        src = dry_src
    else:
        src = tempfile.mkdtemp()
        subprocess.run(f'git archive origin/main | tar -x -C "{src}"', shell=True, cwd=ROOT, check=True)
        if dry:
            bump(src, ver)
    try:
        built, _, sto = B.build(src, tempfile.mkdtemp())
    except B.BuildError as e:
        fail('build refused: ' + str(e))
    if built != ver:
        fail(f'main is at version {built}, not {ver}. Release the family version first (or check the version number).')
    regression(os.path.join(sto, 'index.html'), git('show', 'origin/app-store:index.html'),
               'App Store build (upgrade from live app-store)', src)
    main_sha = git('rev-parse', 'origin/main')

    say('Updating the app-store branch (generated output only)')
    wt = tempfile.mkdtemp(); os.rmdir(wt)
    git('worktree', 'add', '-q', '--detach', wt, 'origin/app-store')
    try:
        git('rm', '-rq', '--ignore-unmatch', '.', cwd=wt)
        for f in STORE_FILES + ['privacy.html']:
            shutil.copy(os.path.join(sto, f), wt)
        open(os.path.join(wt, 'README.md'), 'w').write(GENERATED_NOTE)
        open(os.path.join(wt, 'CLAUDE.md'), 'w').write(GENERATED_NOTE)
        git('add', '-A', cwd=wt)
        print(git('diff', '--cached', '--stat', 'HEAD', cwd=wt) or '(no changes)')
        if git('status', '--porcelain', cwd=wt):
            git(*ZACH, 'commit', '-q', '-m', f'Build EZAide {ver} from main {main_sha[:7]}\n\n'
                'Generated by tools/release.py. Do not edit this branch.', cwd=wt)
        if dry:
            print('[dry run] would push this to app-store')
        else:
            git('push', 'origin', 'HEAD:app-store', cwd=wt, retry=True)
    finally:
        git('worktree', 'remove', '--force', wt, check=False)

    say('Updating the tester site (ezaide repo, app/)')
    if not os.path.isdir(os.path.join(ez_path, '.git')):
        fail(f'ezaide checkout not found at {ez_path}. Start the session with both repos, or pass --ezaide PATH')
    git('fetch', 'origin', '+refs/heads/main:refs/remotes/origin/main', cwd=ez_path, retry=True)
    wt = tempfile.mkdtemp(); os.rmdir(wt)
    git('worktree', 'add', '-q', '--detach', wt, 'origin/main', cwd=ez_path)
    try:
        app = os.path.join(wt, 'app')
        for f in STORE_FILES:
            shutil.copy(os.path.join(sto, f), app)
        p = os.path.join(app, 'index.html'); s = open(p, encoding='utf-8').read()
        if s.count('<head>\n') != 1:
            fail('tester copy: <head> line not found exactly once')
        open(p, 'w', encoding='utf-8').write(s.replace('<head>\n', '<head>\n' + NOINDEX + '\n', 1))
        git('add', '-A', 'app', cwd=wt)
        print(git('diff', '--cached', '--stat', 'HEAD', cwd=wt) or '(no changes)')
        if git('status', '--porcelain', cwd=wt):
            git(*ZACH, 'commit', '-q', '-m', f'Tester copy: EZAide {ver}', cwd=wt)
        sha = git('rev-parse', 'HEAD', cwd=wt)
        if dry:
            print('[dry run] would push this to the ezaide repo (main)')
        else:
            git('push', 'origin', 'HEAD:main', cwd=wt, retry=True)
    finally:
        git('worktree', 'remove', '--force', wt, cwd=ez_path, check=False)
    if not dry:
        wait_pages(EZ_REPO, sha, 'the tester site')


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a or not re.fullmatch(r'\d+\.\d+(\.\d+)?', a[0]):
        print(__doc__); sys.exit(2)
    ver, dry = a[0], '--dry-run' in a
    val = lambda k, d=None: a[a.index(k) + 1] if k in a else d
    ez = os.path.abspath(val('--ezaide', os.path.join(os.path.dirname(ROOT), 'ezaide')))
    dry_src = None
    if '--store-only' not in a:
        dry_src = family(ver, dry, val('--notes', ''))
    if '--family-only' not in a:
        store(ver, dry, ez, dry_src)
    say('Done' + (' (dry run: nothing was pushed)' if dry else ''))
    if not dry:
        print('On the iPad: ⚙ → Check for updates → Update now.')
