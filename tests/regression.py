"""Care board regression suite.

Run from the repo root before every release (works on main and app-store):
    python3 tests/regression.py            # tests ./index.html, upgrade from the last commit
    python3 tests/regression.py --prev OLD.html

Needs Python Playwright and a Chromium/Chrome. Exits 1 if anything fails.
"""
import sys, os, json, threading, subprocess, tempfile, shutil, http.server, socketserver, functools, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = next((p for p in ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'] if os.path.exists(p)), None)
results = []

def check(name, ok, detail=''):
    results.append((name, bool(ok), detail))
    print(('PASS ' if ok else 'FAIL ') + name + (f'  [{detail}]' if detail and not ok else ''))

def serve(folder):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    h = functools.partial(Quiet, directory=folder)
    srv = socketserver.TCPServer(('127.0.0.1', 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://127.0.0.1:{srv.server_address[1]}/'

def clear(pg):
    """Click through first-run pop-ups (works with or without the App Store screens)."""
    for _ in range(6):
        moved = False
        if pg.is_visible('#dc'): pg.check('#dcck'); pg.click('#dcok'); moved = True
        for m, b in [('#rk', '#rkok'), ('#tour', '#tourskip'), ('#ft', '#ftskip'), ('#ah', '#ahy'), ('#due', '#dueok')]:
            if pg.is_visible(m): pg.click(b); moved = True
        if pg.is_visible('#na'): pg.locator('#na button').last.click(); moved = True
        if not moved: break

def code(pg, digits):
    for d in digits: pg.click(f'#pad [data-pk="{d}"]')

def setup(pg, url, name='Owner', pin='1111'):
    pg.goto(url); pg.wait_for_timeout(250)
    pg.fill('#frn', name); pg.fill('#frp', pin); pg.click('#frok'); clear(pg)

def main():
    prev = None
    if '--prev' in sys.argv: prev = open(sys.argv[sys.argv.index('--prev') + 1]).read()
    else:
        try: prev = subprocess.run(['git', '-C', ROOT, 'show', 'HEAD:index.html'], capture_output=True, text=True, check=True).stdout
        except Exception: prev = None
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(ROOT, 'index.html'), os.path.join(tmp, 'index.html'))
    if prev: open(os.path.join(tmp, 'prev.html'), 'w').write(prev)
    srv, U = serve(tmp)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=['--no-sandbox']) if CHROME else p.chromium.launch()
        def page(**kw):
            ctx = b.new_context(accept_downloads=True, **kw); pg = ctx.new_page(); errs = []
            pg.on('pageerror', lambda e: errs.append(str(e))); return pg, errs

        # A. fresh install
        pg, errs = page(viewport={'width': 820, 'height': 1180})
        pg.goto(U + 'index.html'); pg.wait_for_timeout(250)
        check('A1 new device starts empty with welcome screen', pg.is_visible('#fr') and pg.evaluate('S.tasks.length+S.stock.length+S.people.length') == 0)
        pg.fill('#frn', 'Owner'); pg.fill('#frp', '1111'); pg.click('#frok'); clear(pg)
        check('A2 first person is owner with recovery key', pg.evaluate("me().role==='owner'&&!!S.rkey"))

        # B. roles and private codes
        pg.evaluate("S.adminOk=true;S.last=Date.now();S.tab='people';render()")
        pg.fill('#newpn', 'Nurse'); pg.select_option('#newpr', 'caregiver'); pg.click('#addpp')
        pg.fill('#newpn', 'Mgr'); pg.select_option('#newpr', 'manager'); pg.click('#addpp')
        check('B1 codes never shown on People screen', '1111' not in pg.inner_html('main'))
        pg.select_option('#whosel', 'Nurse'); code(pg, '2222'); code(pg, '2222'); clear(pg)
        pg.click('#nav [data-t="menu"]')
        check('B2 caregiver cannot open Menu', not pg.is_visible('#pin') and pg.evaluate("S.tab")!='menu')

        # C. check-offs: tapping a done task does not undo it
        pg.evaluate("S.tasks.push({id:501,name:'Routine A',periods:S.periods.map(p=>p.id),every:0,needs:[]});render()")
        k = pg.evaluate("'501|'+nowP().id")
        pg.click(f'[data-k="{k}"]')
        check('C1 tap checks off', pg.evaluate(f"!!S.done['{k}']"))
        pg.click(f'[data-k="{k}"]')
        check('C2 second tap keeps it done and shows details', pg.evaluate(f"!!S.done['{k}']") and pg.is_visible('#ti'))
        pg.click('[data-undoco]')
        check('C3 deliberate undo works and is logged', pg.evaluate(f"!S.done['{k}']&&S.log[0].a==='Undid'"))

        # D. pushes made before the daily reset carry over, not marked missed
        r = pg.evaluate("""(function(){var y=addDays(bizDay(),-1);S.dayKey=y;
          S.tasks.push({id:502,name:'Night care',periods:[S.periods[S.periods.length-1].id],every:0,needs:[]});
          var pid=S.periods[S.periods.length-1].id,ts=dayStartOf(bizDay())+30*60000;
          S.moves=[{tid:502,from:pid,to:'at',ts:ts,at:Date.now()-3600000,who:'Nurse',reason:'',time:'6:30 AM'}];
          maybeReset();var mv=S.moves.filter(m=>m.tid===502)[0];
          var missed=S.log.some(r=>r.a==='Missed'&&r.d.indexOf('Night care')>-1&&r.d.indexOf('moved')<0&&new Date(r.ts)>Date.now()-60000);
          return {carried:!!(mv&&mv.carry),missed:missed}})()""")
        check('D1 push across reset is carried over', r['carried'], str(r))
        check('D2 carried push not logged as missed', not r['missed'], str(r))

        # E. wrong-code limits
        pg.evaluate("S.pinFail={n:0,until:0,last:0};S.who='';render()")
        pg.select_option('#whosel', 'Owner')
        for _ in range(5): code(pg, '9999')
        check('E1 five wrong codes pause entry', pg.evaluate('pinLocked()') and pg.locator('#pad button:disabled').count() > 0)
        pg.evaluate('S.pinFail.until=Date.now()-1'); pg.wait_for_timeout(1200)
        code(pg, '1111'); clear(pg)
        check('E2 correct code works after the pause', pg.evaluate("S.who==='Owner'&&S.pinFail.n===0"))

        # N. owners/managers go straight into the Menu after signing in
        pg.evaluate("S.who='';S.adminOk=false;render()")
        pg.select_option('#whosel', 'Owner'); code(pg, '1111'); clear(pg)
        pg.click('#nav [data-t="menu"]')
        check('N1 owner opens Menu without retyping a code', not pg.is_visible('#pin') and pg.evaluate("S.tab")=='menu')
        pg.click('[data-lock]'); pg.click('#nav [data-t="menu"]')
        check('N2 after tapping Lock, the Menu asks for the code', pg.is_visible('#pin'))
        code(pg, '1111')

        # F. idle asks, never signs out
        pg.evaluate('S.idle=60;S.last=Date.now()-61*60000;idleCheck()')
        check('F1 idle shows Still here? and keeps person', pg.is_visible('#ah') and pg.evaluate("S.who==='Owner'"))
        pg.click('#ahy')

        # G. due alerts
        x = pg.evaluate("(function(){var d=new Date(Date.now()-60000),x=String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');S.tasks.push({id:503,name:'Feed',periods:[],every:0,at:[x],needs:[]});S.alerted={};checkDue();return x})()")
        check('G1 due banner appears', pg.is_visible('#due') and 'Feed' in pg.inner_text('#duel'))
        pg.click('#duel [data-dued]')
        check('G2 Mark done from banner checks it off', pg.evaluate(f"!!S.cdone['503@{x}']"))
        pg.evaluate('checkDue()')
        check('G3 no repeat alert after handling', not pg.is_visible('#due'))

        # K. backup reminder: owners only, monthly, quiet
        pg.evaluate("S.who='Owner';S.bkOff=false;S.bkSnooze=0;S.lastBackup=Date.now()-20*864e5;S.tab='today';render()")
        check('K1 no backup reminder within 30 days', pg.locator('.bkline').count() == 0)
        pg.evaluate("S.lastBackup=Date.now()-34*864e5;render()")
        check('K2 owner sees a small reminder after 30 days', pg.locator('.bkline').count() == 1)
        pg.evaluate("S.who='Nurse';render()")
        check('K3 caregivers never see it', pg.locator('.bkline').count() == 0)
        pg.evaluate("S.who='Owner';render()"); pg.click('#bklater')
        check('K4 Not now snoozes about a month', pg.evaluate("Math.round((S.bkSnooze-Date.now())/864e5)") == 30)

        # L. doctor's orders on tasks
        pg.evaluate("S.who='Owner';S.adminOk=true;S.last=Date.now();var d=new Date(Date.now()+3600000),x=String(d.getHours()).padStart(2,'0')+':00';S.tasks.push({id:801,name:'Feed B',periods:[],every:0,at:[x],needs:[]});setOrder(801,'kind','feed');setOrder(801,'amt','120 mL');setOrder(801,'route','G-tube');S.tab='today';render()")
        check('L1 order shows on the tile', '120 mL' in pg.locator('[data-ct^="801@"]').first.inner_text())
        pg.locator('[data-ct^="801@"]').first.click()
        check('L2 check-off logs the order as given', pg.evaluate("S.log[0].a==='Completed'&&S.log[0].d.indexOf('120 mL')>-1"))
        pg.evaluate("setOrder(801,'amt','140 mL')")
        check('L3 order change is logged, old entry keeps old amount', pg.evaluate("S.log[0].d.indexOf('120 mL → 140 mL')>-1&&S.log.some(r=>r.a==='Completed'&&r.d.indexOf('120 mL')>-1)"))
        pg.evaluate("S.adminOk=false;setOrder(801,'amt','999 mL')")
        check('L4 only people who can edit tasks can change an order', pg.evaluate("T(801).order.amt==='140 mL'"))

        # M. "also have ready" items are listed but never counted
        pg.evaluate("S.adminOk=true;S.last=Date.now();var n=S.stock.length;addExtra(801,'Wet washcloth');addExtra(801,'wet washcloth');window._n=n")
        check('M1 also-have-ready adds once and creates no inventory', pg.evaluate("T(801).extras.length===1&&S.stock.length===window._n"))
        pg.evaluate("S.tab='today';render()"); pg.click('[data-ti="801"]')
        check('M2 shows on the task card as not counted', 'Wet washcloth' in pg.inner_text('#tib') and 'Not counted' in pg.inner_text('#tib'))
        pg.click('[data-cl="ti"]')

        # H. inventory + log database persistence
        pg.evaluate("S.stock.push({id:601,name:'Gauze',qty:10,low:2});S.tab='stock';render()")
        pg.click('[data-sq="601|-1"]'); pg.wait_for_timeout(300)
        pg.reload(); pg.wait_for_timeout(700); clear(pg)
        check('H1 count change saved and logged across reload', pg.evaluate("S.stock.find(i=>i.id===601).qty===9&&S.log.some(r=>r.a==='Inventory'&&r.d.indexOf('Gauze')>-1)"))
        check('H2 log kept in device database', pg.evaluate('LDBOK') and pg.evaluate("!JSON.parse(localStorage.getItem(KEY)).state.log"))
        check('H3 no script errors (desktop)', not errs, '; '.join(errs[:3]))

        # I. upgrade from previous committed version keeps data
        if prev:
            pg2, e2 = page(viewport={'width': 820, 'height': 1180})
            setup(pg2, U + 'prev.html', 'Lee', '1111')
            pg2.evaluate("S.tasks.push({id:701,name:'Keep me',periods:[S.periods[0].id],every:0});S.stock.push({id:702,name:'Tape',qty:4,low:1});lg('Completed','before upgrade');save()")
            before = pg2.evaluate("JSON.stringify([S.tasks.map(t=>t.name),S.stock.map(i=>i.qty),S.people.map(p=>p.name)])")
            pg2.goto(U + 'index.html'); pg2.wait_for_timeout(800); clear(pg2)
            after = pg2.evaluate("JSON.stringify([S.tasks.map(t=>t.name),S.stock.map(i=>i.qty),S.people.map(p=>p.name)])")
            check('I1 upgrade keeps tasks, counts, people', before == after, before + ' -> ' + after)
            check('I2 upgrade keeps log', pg2.evaluate("S.log.some(r=>r.d==='before upgrade')"))
            check('I3 no welcome screen after upgrade', not pg2.is_visible('#fr'))
            check('I4 no script errors (upgrade)', not e2, '; '.join(e2[:3]))
        else:
            print('SKIP upgrade test (no previous version found)')

        # J. phone layout
        pg3, e3 = page(**p.devices['iPhone 13'])
        setup(pg3, U + 'index.html', 'Pat', '4444')
        bad = pg3.evaluate("['today','week','library','stock','log','menu','edit','periods','people','admin'].filter(function(t){S.adminOk=true;S.tab=t;render();return document.documentElement.scrollWidth>innerWidth})")
        check('J1 nothing wider than a phone screen', not bad, str(bad))
        check('J2 no script errors (phone)', not e3, '; '.join(e3[:3]))
        b.close()
    srv.shutdown()
    fails = [r for r in results if not r[1]]
    print(f'\n{len(results) - len(fails)}/{len(results)} passed')
    sys.exit(1 if fails else 0)

if __name__ == '__main__':
    main()
