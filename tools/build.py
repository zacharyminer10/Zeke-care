#!/usr/bin/env python3
"""Build both versions of EZAide from this one codebase.

    python3 tools/build.py                 # -> dist/family/ and dist/store/
    python3 tools/build.py --src DIR --out DIR [--no-browser]

index.html + sw.js in the repo ARE the family version (main, Zach's iPad). The App Store version is made by
swapping the EDITION block at the top of the script for store/edition.js and renaming the service worker cache.

The build refuses to finish (exit 1, nothing usable left in --out) if:
  - the family version doesn't use KEY 'zeke-care-board.v1', backup app 'zeke-care-board', CACHE 'zeke-care-'
  - the App Store version doesn't use 'ezaide.v1', 'ezaide' (still accepting 'zeke-care-board' backups), 'ezaide-'
  - the App Store version contains "Zeke", "He’s" or "Care Board"
  - VER in index.html and VERSION in sw.js differ
It checks the files as text, then opens each build in a real browser and reads the values the app actually uses.
"""
import os, re, sys, shutil, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCK = re.compile(r'/\* ==== EDITION ====.*?/\* ==== END EDITION ==== \*/\n', re.S)
SHARED = ['manifest.webmanifest', 'icon-180.png', 'icon-192.png', 'icon-512.png']
FAMILY = dict(id='family', key='zeke-care-board.v1', app='zeke-care-board', apps=['zeke-care-board'],
              backup='zeke-care-backup', cache='zeke-care-')
STORE = dict(id='store', key='ezaide.v1', app='ezaide', apps=['ezaide', 'zeke-care-board'],
             backup='ezaide-backup', cache='ezaide-')
BANNED_IN_STORE = ['Zeke', 'He’s', "He's", 'Care Board', 'zeke-care-board.v1', 'zeke-care-backup', "'zeke-care-'"]
SW_HEAD_FAMILY = '// EZAide (family board) service worker.'
SW_HEAD_STORE = '// EZAide service worker.'


class BuildError(Exception):
    pass


def need(ok, msg):
    if not ok:
        raise BuildError(msg)


def once(text, s, where):
    n = text.count(s)
    need(n == 1, f'{where}: expected exactly one "{s}", found {n}')


def edition_values(html, where):
    m = BLOCK.findall(html)
    need(len(m) == 1, f'{where}: expected exactly one EDITION block, found {len(m)}')
    b = m[0]
    val = lambda k: (re.search(r"\b%s:'([^']*)'" % k, b) or [None, None])[1]
    apps = re.search(r"\bapps:\[([^\]]*)\]", b)
    return dict(id=val('id'), key=val('key'), app=val('app'), backup=val('backup'),
                apps=re.findall(r"'([^']*)'", apps[1]) if apps else None,
                store=re.search(r'\bstore:(true|false)', b)[1] if re.search(r'\bstore:(true|false)', b) else None)


def check_identity(html, sw, want, where):
    """Text checks: the edition block has the right values and the app really reads them."""
    ed = edition_values(html, where)
    for k in ['id', 'key', 'app', 'backup', 'apps']:
        need(ed[k] == want[k], f'{where}: ED.{k} is {ed[k]!r}, must be {want[k]!r}')
    need(ed['store'] == ('true' if want['id'] == 'store' else 'false'), f'{where}: ED.store is {ed["store"]}')
    for s in ["var KEY=ED.key,", "return{app:ED.app,v:1,", "ED.apps.indexOf(d.app)>-1", "name=ED.backup+'-'+"]:
        once(html, s, where)
    need("var KEY='" not in html, f'{where}: KEY is hard-coded instead of coming from ED.key')
    once(sw, f"const CACHE = '{want['cache']}' + VERSION;", where + ' sw.js')
    once(sw, f"k.startsWith('{want['cache']}')", where + ' sw.js')
    other = STORE if want is FAMILY else FAMILY
    need(f"'{other['cache']}'" not in sw, f"{where} sw.js: contains the other version's cache name {other['cache']!r}")
    need(other['key'] not in html, f"{where}: contains the other version's storage key {other['key']!r}")


def versions(html, sw, where):
    v1 = re.findall(r"var VER='([^']+)'", html)
    v2 = re.findall(r"const VERSION = '([^']+)'", sw)
    need(len(v1) == 1 and len(v2) == 1, f'{where}: VER/VERSION not found exactly once')
    need(v1[0] == v2[0], f'{where}: index.html VER {v1[0]} != sw.js VERSION {v2[0]}')
    return v1[0]


def make_store(html, sw, edition):
    need(len(BLOCK.findall(edition)) == 1, 'store/edition.js: expected exactly one EDITION block')
    out = BLOCK.sub(lambda m: BLOCK.findall(edition)[0], html, count=1)
    once(sw, SW_HEAD_FAMILY, 'sw.js')
    need(sw.count("'zeke-care-'") == 2, "sw.js: expected 'zeke-care-' exactly twice (CACHE and the clean-up)")
    sws = sw.replace(SW_HEAD_FAMILY, SW_HEAD_STORE).replace("'zeke-care-'", "'ezaide-'")
    return out, sws


def browser_check(folder, want):
    """Open the build in Chromium and read what the app actually uses."""
    sys.path.insert(0, os.path.join(ROOT, 'tests'))
    import regression as R
    from playwright.sync_api import sync_playwright
    srv, U = R.serve(folder)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=R.CHROME, args=['--no-sandbox']) if R.CHROME else p.chromium.launch()
            pg = b.new_page(); errs = []
            pg.on('pageerror', lambda e: errs.append(str(e)))
            pg.goto(U + 'index.html'); pg.wait_for_timeout(300)
            got = pg.evaluate("""({id:ED.id,key:KEY,app:snap().app,apps:ED.apps,
              acceptsFamily:okSnap({app:'zeke-care-board',state:{tasks:[],periods:[1],people:[1]}}),
              acceptsStore:okSnap({app:'ezaide',state:{tasks:[],periods:[1],people:[1]}}),
              dc:!!document.getElementById('dc'),na:!!document.getElementById('na'),trl:!!document.getElementById('trl'),
              abt:!!document.getElementById('abt'),keep:KEEP.indexOf('dc')>-1,stored:Object.keys(localStorage)})""")
            b.close()
    finally:
        srv.shutdown()
    w = want['id']
    need(not errs, f'{w}: script errors in the browser: {errs[:3]}')
    need(got['key'] == want['key'] and got['app'] == want['app'] and got['id'] == w,
         f'{w}: in the browser KEY={got["key"]!r} app={got["app"]!r} ED.id={got["id"]!r}')
    need(got['stored'] == [want['key']], f'{w}: saved under {got["stored"]}, must be only {want["key"]!r}')
    need(got['acceptsFamily'], f'{w}: does not accept family (zeke-care-board) backups')
    store_bits = [got[k] for k in ['dc', 'na', 'trl', 'abt', 'keep']]
    if w == 'store':
        need(got['acceptsStore'], 'store: does not accept its own backups')
        need(all(store_bits), f'store: App Store pieces missing {got}')
    else:
        need(not got['acceptsStore'], 'family: accepts App Store (ezaide) backups')
        need(not any(store_bits), f'family: App Store pieces present {got}')
    return got


def build(src=ROOT, out=os.path.join(ROOT, 'dist'), browser=True, log=print):
    rd = lambda f: open(os.path.join(src, f), encoding='utf-8').read()
    html, sw = rd('index.html'), rd('sw.js')
    edition = open(os.path.join(src, 'store', 'edition.js'), encoding='utf-8').read()
    ver = versions(html, sw, 'family')
    check_identity(html, sw, FAMILY, 'family')
    need(SW_HEAD_FAMILY in sw, 'family sw.js: header comment changed')

    shtml, ssw = make_store(html, sw, edition)
    versions(shtml, ssw, 'store')
    check_identity(shtml, ssw, STORE, 'store')
    for f, text in [('index.html', shtml), ('sw.js', ssw), ('manifest.webmanifest', rd('manifest.webmanifest'))]:
        for bad in BANNED_IN_STORE:
            need(bad not in text, f'store {f}: contains {bad!r}')

    if os.path.exists(out):
        shutil.rmtree(out)
    fam, sto = os.path.join(out, 'family'), os.path.join(out, 'store')
    for d in (fam, sto):
        os.makedirs(d)
        for f in SHARED:
            shutil.copy(os.path.join(src, f), d)
    open(os.path.join(fam, 'index.html'), 'w', encoding='utf-8').write(html)
    open(os.path.join(fam, 'sw.js'), 'w', encoding='utf-8').write(sw)
    open(os.path.join(sto, 'index.html'), 'w', encoding='utf-8').write(shtml)
    open(os.path.join(sto, 'sw.js'), 'w', encoding='utf-8').write(ssw)
    shutil.copy(os.path.join(src, 'store', 'privacy.html'), sto)
    try:
        if browser:
            browser_check(fam, FAMILY)
            browser_check(sto, STORE)
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)
        raise
    log(f'Built {ver}: family -> {fam} (zeke-care-board.v1)   App Store -> {sto} (ezaide.v1)'
        + ('' if browser else '   [browser check skipped]'))
    return ver, fam, sto


if __name__ == '__main__':
    a = sys.argv[1:]
    arg = lambda k, d: a[a.index(k) + 1] if k in a else d
    try:
        build(os.path.abspath(arg('--src', ROOT)), os.path.abspath(arg('--out', os.path.join(ROOT, 'dist'))),
              browser='--no-browser' not in a)
    except BuildError as e:
        shutil.rmtree(os.path.abspath(arg('--out', os.path.join(ROOT, 'dist'))), ignore_errors=True)
        print('BUILD REFUSED: ' + str(e))
        sys.exit(1)
