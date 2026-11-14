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
        if pg.is_visible('#sh'):
            if pg.locator('#sh [data-shn="2"]').count(): pg.click('#sh [data-shn="2"]')
            pg.click('#shok'); moved = True
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

        # O. onboarding asks about overnight tasks and sets shifts
        po, eo = page(viewport={'width': 820, 'height': 1180})
        po.goto(U + 'index.html'); po.wait_for_timeout(250); po.fill('#frn', 'Solo'); po.fill('#frp', '5555'); po.click('#frok')
        check('O1 shifts question comes right after the welcome screen', po.is_visible('#sh') and 'overnight' in po.inner_text('#sh'))
        po.click('#sh [data-shn="1"]'); po.click('#shok')
        check('O2 "No" makes a single Day shift and sets the daily reset to its start', po.evaluate("S.periods.length===1&&S.periods[0].name==='Day'&&S.resetAt===S.periods[0].start"))
        po2, eo2 = page(viewport={'width': 820, 'height': 1180})
        po2.goto(U + 'index.html'); po2.wait_for_timeout(250); po2.fill('#frn', 'Duo'); po2.fill('#frp', '6666'); po2.click('#frok')
        po2.click('#sh [data-shn="2"]'); po2.click('#shok')
        check('O3 "Yes" makes Day and Night that cover the whole day', po2.evaluate("S.periods.length===2&&S.periods[0].end===S.periods[1].start&&S.periods[1].end===S.periods[0].start"))
        check('O4 no script errors (onboarding)', not (eo or eo2), '; '.join((eo + eo2)[:3]))

        # P. iPhone/iPad: warn when opened in a Safari tab instead of the Home Screen app
        ps, es = page(**p.devices['iPhone 13']); ps.goto(U + 'index.html'); ps.wait_for_timeout(250)
        check('P1 Safari tab on iPhone shows the install-first note', ps.locator('#frsf .sfn').count() == 1)
        pa_ctx = b.new_context(**p.devices['iPhone 13']); pa_ctx.add_init_script("Object.defineProperty(navigator,'standalone',{get:()=>true})")
        pa = pa_ctx.new_page(); pa.goto(U + 'index.html'); pa.wait_for_timeout(250)
        check('P2 Home Screen app shows no note', pa.locator('.sfn').count() == 0)

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
        x = pg.evaluate("(function(){var d=new Date(Date.now()-60000),x=String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');S.moves=[];S.tasks=S.tasks.filter(t=>!(t.at&&t.at.length));S.tasks.push({id:503,name:'Feed',periods:[],every:0,at:[x],needs:[]});S.alerted={};checkDue();return x})()")
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

        # Q. repeating tasks ask when they're first due
        pg.evaluate("S.adminOk=true;S.last=Date.now();S.tab='edit';render()")
        pg.fill('#newn', 'Trach ties Q'); pg.select_option('#newk', 'days'); pg.click('#add'); pg.wait_for_timeout(150)
        qid = pg.evaluate("S.tasks.filter(t=>t.name==='Trach ties Q')[0].id")
        check('Q1 new repeating task asks when it is first due, defaults to one interval out', 'When is it first due' in pg.inner_text('#te') and pg.locator(f'[data-ndq="{qid}|3"].on').count() == 1)
        pg.click(f'[data-ndq="{qid}|0"]'); pg.wait_for_timeout(100)
        check('Q2 "Today" makes it due now', pg.evaluate(f"T({qid}).every-T({qid}).last===0&&ivDue(T({qid}))===bizDay()") and 'Due today' in pg.inner_text('#te'))
        pg.fill(f'[data-nd="{qid}"]', pg.evaluate("addDays(bizDay(),10)")); pg.dispatch_event(f'[data-nd="{qid}"]', 'change'); pg.wait_for_timeout(100)
        check('Q3 a picked date further out than the interval works', pg.evaluate(f"ivDue(T({qid}))===addDays(bizDay(),10)") and pg.evaluate("S.log[0].d.indexOf('next due')>-1"))
        pg.click('[data-cl="te"]') if pg.locator('[data-cl="te"]').count() else pg.evaluate("$('te').classList.remove('show')")
        pg.evaluate(f"openTE({qid})")
        check('Q4 reopening says "Next due", not the first-time question', 'Next due' in pg.inner_text('#te') and 'first due' not in pg.inner_text('#te'))
        pg.evaluate(f"T({qid}).done={{who:'Owner',time:'9:00 AM',pid:'day'}};drawTE()")
        check('Q5 checked off today shows the next date instead of choices', 'Checked off today' in pg.inner_text('#te') and pg.locator(f'[data-ndq^="{qid}|"]').count() == 0)
        pg.evaluate(f"T({qid}).done=null;$('te').classList.remove('show')")

        # R. one "+ Add task" on the board: owners/managers pick how often, caregivers add one-time tasks
        pr, er = page(viewport={'width': 820, 'height': 1180})
        setup(pr, U + 'index.html', 'Rae', '3333'); pr.evaluate("S.people.forEach(p=>p.toured=true);S.tab='today';render()")
        pr.click('#otadd'); pr.fill('#otn', 'Bath R'); pr.click('[data-otk="period"]')
        check('R1 owner can pick how often, and the button says what’s next', pr.is_visible('#otk') and pr.inner_text('#otok') == 'Next: set it up' and not pr.is_visible('#otd'))
        pr.click('#otok'); pr.wait_for_timeout(150)
        check('R2 a repeating task opens the editor right on the board', pr.is_visible('#te') and pr.evaluate("T(S.teId).name") == 'Bath R' and pr.evaluate("S.tab") == 'today')
        pr.evaluate("$('te').classList.remove('show')"); pr.click('#otadd'); pr.fill('#otn', 'Ties R'); pr.click('[data-otk="days"]'); pr.click('#otok'); pr.wait_for_timeout(150)
        check('R3 Every few days asks when it’s first due', 'first due' in pr.inner_text('#te'))
        pr.evaluate("$('te').classList.remove('show');S.people.push({name:'Cal',role:'caregiver',pin:'2222',toured:true});lockAdmin();S.who='Cal';render()")
        pr.click('#otadd')
        check('R4 caregivers only get one-time tasks', not pr.is_visible('#otk') and pr.is_visible('#otd'))
        pr.fill('#otn', 'Call R'); pr.click('#otok')
        check('R5 caregiver one-time task is added', pr.evaluate("S.tasks.some(t=>t.name==='Call R'&&t.once)"))
        check('R6 no script errors (add task)', not er, '; '.join(er[:3]))

        # S. 1.14 bug sweep: day boundaries, shift edits, backups, names, log completeness
        import datetime
        D = lambda h, m=0, day=12: datetime.datetime(2026, 11, day, h, m)
        ps_, es_ = page(viewport={'width': 820, 'height': 1180}); ps_.clock.install(time=D(10))
        setup(ps_, U + 'index.html', 'Sam', '8642')
        ps_.evaluate("S.tasks.push({id:901,name:'Pickup S',periods:[],every:0,once:true,date:addDays(bizDay(),2),time:'',needs:[]},{id:902,name:'Ties S',periods:[],every:3,n:3,unit:'days',last:3,needs:[]},{id:903,name:'G-tube S',periods:['day'],every:0,needs:[]});render()")
        ps_.clock.set_system_time(D(2, 0, 13)); ps_.evaluate("S.tab='week';render()")
        check('S1 This week follows the board day after midnight', ps_.inner_text('[data-wday="0"] .wkh small') == 'Nov 12' and 'Pickup S' in ps_.inner_text('[data-wday="2"]'))
        ps_.clock.set_system_time(D(10, 0, 12)); ps_.evaluate("S.periods=[{id:'day',name:'Day',start:'07:00',end:'21:00'}];S.resetAt='07:00';S.tasks.push({id:904,name:'Early S',periods:[],every:0,at:['06:00'],needs:[]},{id:905,name:'Late S',periods:[],every:0,at:['23:00'],needs:[]});S.tab='today';render()")
        e1 = ps_.inner_text('[data-ct="904@06:00"]'); ps_.clock.set_system_time(D(6, 30, 13)); ps_.evaluate("render()"); l1 = ps_.inner_text('[data-ct="905@23:00"]')
        check('S2 one-shift board: early-morning dose not overdue the day before; late dose overdue next morning', 'Overdue' not in e1 and 'Overdue' in l1, e1 + ' / ' + l1)
        ps_.clock.set_system_time(D(10, 0, 13)); ps_.evaluate("maybeReset();S.periods=[{id:'day',name:'Day',start:'07:00',end:'21:00'},{id:'night',name:'Night',start:'21:00',end:'07:00'}];S.resetAt='07:00';S.adminOk=true;togK('903|day',false);S.tab='periods';render()")
        ps_.click('[data-pst="day|start"]'); ps_.evaluate("(()=>{var o=TP.o;tpClose();o.ok('06:00')})()")
        check('S3 moving Day start moves Night end and the reset time', ps_.evaluate("S.periods[1].end==='06:00'&&S.resetAt==='06:00'"))
        ps_.clock.set_system_time(D(6, 30, 14)); ps_.evaluate("maybeReset();S.tab='today';render()")
        check('S4 at the new start, yesterday’s check-offs are cleared', ps_.evaluate("nowP().id==='day'&&!S.done['903|day']"))
        ps_.evaluate("togK('903|day',false)"); ps_.clock.set_system_time(D(6, 30, 13)); ps_.evaluate("maybeReset()")
        check('S5 clock going backwards never resets the day', ps_.evaluate("!!S.done['903|day']&&S.dayKey==='2026-11-14'"))
        ps_.clock.set_system_time(D(9, 0, 14))
        ps_.evaluate("S.people.push({name:'Cara',role:'caregiver',pin:'1357'});lockAdmin();S.who='Cara';render()"); ps_.click('[data-st="1"]')
        check('S6 caregivers can’t save or restore backups', not ps_.is_visible('#bkp') and not ps_.is_visible('#rst') and ps_.is_visible('#stbo'))
        ps_.evaluate("$('st').classList.remove('show');S.who='Sam';S.adminOk=true"); ps_.click('[data-st="1"]')
        bk = ps_.evaluate("(()=>{var b=snap(true);b.state.tasks=[];return JSON.stringify(b)})()")
        ps_.set_input_files('#rsf', files=[{'name': 'b.json', 'mimeType': 'application/json', 'buffer': bk.encode()}]); ps_.wait_for_timeout(300)
        check('S7 restoring asks the owner first', ps_.is_visible('#cf') and 'Replace' in ps_.inner_text('#cf') and ps_.evaluate("S.tasks.length>0"))
        ps_.click('#cfx'); ps_.evaluate("$('st').classList.remove('show');S.tab='people';render()")
        ci = ps_.evaluate("S.people.findIndex(p=>p.name==='Cara')"); ps_.fill(f'[data-ppn="{ci}"]', 'sam'); ps_.dispatch_event(f'[data-ppn="{ci}"]', 'change')
        check('S8 can’t rename someone to a name already on the board', ps_.evaluate("S.people.filter(p=>p.name.toLowerCase()==='sam').length===1"))
        ps_.evaluate("S.tab='today';S.reason='He’s sleeping';openPush(903,'day')"); ps_.click('[data-mv="903|day|tomorrow"]')
        check('S9 pushes are logged with the reason', ps_.evaluate("S.log[0].a==='Pushed'&&S.log[0].d.indexOf('sleeping')>-1"))
        ps_.evaluate("T(902).last=3;T(902).done=null;T(902).missedFor=null"); m0 = ps_.evaluate("S.log.filter(r=>r.a==='Missed'&&r.d.indexOf('Ties S')>-1).length")
        ps_.clock.set_system_time(D(9, 0, 15)); ps_.evaluate("maybeReset()")
        m1 = ps_.evaluate("S.log.filter(r=>r.a==='Missed'&&r.d.indexOf('Ties S')>-1).length"); ps_.clock.set_system_time(D(9, 0, 16)); ps_.evaluate("maybeReset()")
        check('S10 a repeating task that comes due and isn’t done is logged missed once', m1 == m0 + 1 and ps_.evaluate("S.log.filter(r=>r.a==='Missed'&&r.d.indexOf('Ties S')>-1).length") == m1)
        ps_.evaluate("S.periods.push({id:'lunch',name:'Lunch',start:'12:00',end:'13:00'})"); ps_.clock.set_system_time(D(12, 30, 16))
        check('S11 a shorter time of day inside a longer one becomes Now', ps_.evaluate("nowP().id")=='lunch')
        check('S12 no script errors (bug sweep)', not es_, '; '.join(es_[:3]))

        # W. 1.14: days of the week, and This week matches the board
        pw_, ew_ = page(viewport={'width': 1180, 'height': 820}); pw_.clock.install(time=D(9, 30, 14))  # Saturday
        setup(pw_, U + 'index.html', 'Wes', '9753')
        pw_.evaluate("S.tasks.push({id:951,name:'Feed W',periods:[],every:0,at:['08:00','23:00','02:00'],needs:[],order:{kind:'feed',amt:'120 mL',route:'G-tube'}},{id:952,name:'Med MWF',periods:[],every:0,at:['08:00'],days:[1,3,5],needs:[]},{id:953,name:'Bath TTh',periods:['day'],every:0,days:[2,4],needs:[]},{id:954,name:'Stoma W',periods:['day','night'],every:0,needs:[]},{id:955,name:'Ties W',periods:[],every:3,n:3,unit:'days',last:3,needs:[]},{id:956,name:'Mon 2am med',periods:[],every:0,at:['02:00'],days:[1],needs:[]});togCt('951@08:00',false);S.tab='today';render()")
        left = pw_.evaluate("S.periods.map(q=>stats(periodModel(q,nowP())).open)")
        on_board = pw_.evaluate("!!document.querySelector('[data-ct^=\"952@\"]')||!!document.querySelector('[data-k^=\"953|\"]')")
        pw_.evaluate("S.tab='week';render()")
        wk = pw_.evaluate("dayModels(0).map(m=>mCount(m)-stats(m).open)")
        tot = pw_.evaluate("dayModels(0).map(mCount)")
        check('W1 This week today matches the board’s left counts', [t - d for t, d in zip(tot, wk)] == left, f'{tot} {wk} {left}')
        check('W2 tasks set to other days stay off today’s board', not on_board)
        check('W3 week shows them on their days', 'Med MWF' in pw_.evaluate("(()=>{var m=dayModels(2);return m.map(x=>x.sls.map(s=>s.t.name).join(',')).join(',')})()") and 'Bath TTh' in pw_.evaluate("dayModels(3).map(m=>m.list.map(t=>t.name).join(',')).join(',')"))
        check('W4 a Monday 2 AM dose is on Sunday’s board day', 'Mon 2am med' in pw_.evaluate("dayModels(1).map(m=>m.sls.map(s=>s.t.name).join(',')).join(',')") and 'Mon 2am med' not in pw_.evaluate("dayModels(2).map(m=>m.sls.map(s=>s.t.name).join(',')).join(',')"))
        pw_.click('[data-wday="0"]')
        check('W5 tapping a day lists everything on it', pw_.is_visible('#ti') and pw_.locator('#tib .wdi').count() == sum(tot) and 'Open the board' in pw_.inner_text('#tif'))
        pw_.click('#wdgo')
        check('W6 Open the board goes to Today', pw_.evaluate("S.tab")=='today' and not pw_.is_visible('#ti'))
        pw_.evaluate("S.adminOk=true;S.tab='edit';render();openTE(952)")
        pw_.click('[data-dw="952|1"]'); pw_.click('[data-dw="952|3"]'); pw_.click('[data-dw="952|5"]')
        check('W7 can’t turn off the last day', pw_.evaluate("JSON.stringify(T(952).days)")=='[5]')
        pw_.click('[data-dwp="952|wk"]')
        check('W8 Weekdays sets Mon–Fri and is logged', pw_.evaluate("JSON.stringify(T(952).days)")=='[1,2,3,4,5]' and 'Weekdays' in pw_.evaluate("S.log[0].d"))
        pw_.click('[data-dwp="952|all"]')
        check('W9 Every day clears the day limit', pw_.evaluate("T(952).days===undefined"))
        pw_.evaluate("$('te').classList.remove('show')")
        miss0 = pw_.evaluate("S.log.filter(r=>r.a==='Missed'&&/Bath TTh|Mon 2am/.test(r.d)).length"); pw_.clock.set_system_time(D(9, 30, 15)); pw_.evaluate("maybeReset()")
        check('W10 tasks not scheduled that day aren’t logged as missed', pw_.evaluate("S.log.filter(r=>r.a==='Missed'&&/Bath TTh|Mon 2am/.test(r.d)).length") == miss0 and pw_.evaluate("S.log.some(r=>r.a==='Missed'&&/Stoma W/.test(r.d))"))
        check('W11 no script errors (week)', not ew_, '; '.join(ew_[:3]))

        # X. a reminder never hides the sign-in screens or Emergency
        TOPJS = "(sel)=>{var el=document.querySelector(sel);if(!el)return false;var r=el.getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return el.contains(hit)||hit===el}"
        px_, ex_ = page(viewport={'width': 820, 'height': 1180}); px_.clock.install(time=D(9, 30, 14))
        setup(px_, U + 'index.html', 'Xan', '2468')
        px_.evaluate("S.people.push({name:'Nina',role:'caregiver',pin:'1357',toured:true});S.tasks.push({id:971,name:'Feed X',periods:[],every:0,at:['09:25'],needs:[]});S.who='';S.adminOk=false;S.alerted={};render();checkDue()")
        px_.click('#duel [data-dued]')
        check('X1 Mark done with nobody signed in puts Who’s here on top', px_.evaluate(TOPJS, '#wpl button'))
        px_.click('#wpl [data-wp="Nina"]')
        check('X2 the code pad is on top too', px_.evaluate(TOPJS, '#pad [data-pk="1"]'))
        code(px_, '1357'); px_.wait_for_timeout(200)
        check('X3 after signing in, the reminder’s task is checked off by that person', px_.evaluate("(S.cdone['971@09:25']||{}).who")=='Nina')
        px_.evaluate("S.tasks.push({id:972,name:'Med X',periods:[],every:0,at:['09:20'],needs:[]});checkDue();fillEm();$('modal').classList.add('show')"); px_.wait_for_timeout(100)
        check('X4 Emergency opens on top of a reminder', px_.is_visible('#due') and px_.evaluate(TOPJS, '#modal .card'))
        check('X5 no script errors (reminder stacking)', not ex_, '; '.join(ex_[:3]))

        # Y. holding a task: clear title, sections, and an Edit button for people who can edit
        def holdt(pgx, sel):
            pgx.locator(sel).first.scroll_into_view_if_needed(); bx = pgx.locator(sel).first.bounding_box()
            pgx.mouse.move(bx['x'] + 40, bx['y'] + bx['height'] / 2); pgx.mouse.down(); pgx.wait_for_timeout(650); pgx.mouse.up(); pgx.wait_for_timeout(150)
        py_, ey_ = page(viewport={'width': 820, 'height': 1180}); py_.clock.install(time=D(9, 30, 14))
        setup(py_, U + 'index.html', 'Yan', '1470')
        py_.evaluate("S.people.push({name:'Cy',role:'caregiver',pin:'2580',toured:true},{name:'Mo',role:'manager',perms:{sched:false},pin:'3690',toured:true});S.tasks.push({id:981,name:'Stoma Y',periods:['day'],every:0,needs:[]},{id:982,name:'Feed Y',periods:[],every:0,at:['11:00'],needs:[]},{id:983,name:'Night Y',periods:['night'],every:0,needs:[]});S.moves.push({tid:983,from:'night',to:'day',at:Date.now(),who:'Yan',reason:'',time:'9 AM'});S.people.forEach(p=>p.hintEdit=true);S.tab='today';render()")
        holdt(py_, '[data-k="981|day"]')
        check('Y1 hold shows “Move this task” with the shift and sections', 'MOVE THIS TASK' in py_.inner_text('#pmk').upper() and 'Day shift' in py_.inner_text('#pmsub') and 'LATER TODAY' in py_.inner_text('#pmb').upper())
        py_.click('[data-pe="981"]')
        check('Y2 Edit this task opens the task editor', py_.is_visible('#te') and py_.evaluate("S.teId") == 981)
        py_.evaluate("$('te').classList.remove('show')")
        holdt(py_, '[data-ct="982@11:00"]')
        check('Y3 holding a timed task gives options with Edit', py_.is_visible('#pm') and py_.locator('#pm [data-pe="982"]').count() == 1); py_.click('#pmx')
        holdt(py_, '[data-lpm="983|day"]')
        check('Y4 holding a pushed-here task asks first, with Put back', py_.is_visible('[data-undod="983|night"]') and py_.evaluate("S.moves.length") == 1); py_.click('#pmx')
        py_.evaluate("lockAdmin();S.who='Cy';render()"); holdt(py_, '[data-k="981|day"]')
        c1 = py_.locator('#pm [data-pe]').count(); py_.click('#pmx')
        py_.evaluate("S.who='Mo';render()"); holdt(py_, '[data-k="981|day"]')
        check('Y5 caregivers and managers without edit permission get no Edit button', c1 == 0 and py_.locator('#pm [data-pe]').count() == 0); py_.click('#pmx')
        py_.evaluate("S.who='Yan';S.adminOk=false;render()"); holdt(py_, '[data-k="981|day"]'); py_.click('[data-pe="981"]')
        code(py_, '1470'); py_.wait_for_timeout(200)
        check('Y6 a locked owner confirms the code, then lands in the editor on the board', py_.is_visible('#te') and py_.evaluate("S.tab") == 'today')
        check('Y7 no script errors (hold sheet)', not ey_, '; '.join(ey_[:3]))

        # Z. slimmer tiles: who/when sits beside the name, not under it
        pz_, ez_ = page(viewport={'width': 820, 'height': 1180}); pz_.clock.install(time=D(11, 40, 14))
        setup(pz_, U + 'index.html', 'Zoe', '1593')
        pz_.evaluate("S.tasks.push({id:991,name:'Stoma Z',periods:['day'],every:0,needs:[]},{id:992,name:'Feed Z',periods:[],every:0,at:['11:00'],needs:[],order:{kind:'feed',amt:'130 mL',route:'G-tube',note:'Run over 30 min'}});S.people.forEach(p=>p.hintEdit=true);S.tab='today';render();togK('991|day',false);togCt('992@11:00',false);hideUndo()")
        tz = pz_.inner_text('[data-k="991|day"] .tag'); hz = pz_.evaluate("Math.max(...['[data-k=\"991|day\"]','[data-ct=\"992@11:00\"]'].map(q=>document.querySelector(q).getBoundingClientRect().height))")
        check('Z1 done tiles show who and when in the tag and stay one row tall', 'Zoe' in tz and '11:40' in tz and hz <= 62, f'{tz} {hz}')
        check('Z2 no script errors (tiles)', not ez_, '; '.join(ez_[:3]))

        # F2. future tasks are clearly separated and never include what's due today
        pf_, ef_ = page(viewport={'width': 820, 'height': 1180}); pf_.clock.install(time=D(9, 30, 14))
        setup(pf_, U + 'index.html', 'Fay', '4444')
        pf_.evaluate("S.people.forEach(p=>p.toured=true);S.tasks.push({id:961,name:'Due F',periods:[],every:3,n:3,unit:'days',last:3,needs:[]},{id:962,name:'Soon F',periods:[],every:7,n:1,unit:'weeks',last:5,needs:[]},{id:963,name:'Once F',periods:[],every:0,once:true,date:addDays(bizDay(),3),time:'',needs:[]},{id:964,name:'Early F',periods:[],every:7,n:1,unit:'weeks',last:2,needs:[]});S.tab='today';render()")
        ft_ = pf_.inner_text('.futc')
        check('F21 Future tasks sits under a “Not due today” divider', pf_.is_visible('.futsep') and 'NOT DUE TODAY' in pf_.inner_text('.futsep').upper() and 'Future tasks' in ft_)
        check('F22 what’s due today is only on the board, not in Future tasks', 'Due F' not in ft_ and 'Soon F' in ft_ and 'Once F' in ft_)
        pf_.click('.futc [data-i="964"]'); pf_.wait_for_timeout(100)
        check('F23 tapping a future task marks it done early and it stays listed', pf_.evaluate("!!T(964).done") and 'Done early' in pf_.inner_text('.futc'))
        check('F24 no script errors (future)', not ef_, '; '.join(ef_[:3]))

        # O2. supply orders: owners/managers log them, anyone checks them in, counting up asks first
        po_, eo_ = page(viewport={'width': 820, 'height': 1180}); po_.clock.install(time=D(9, 30, 14))
        setup(po_, U + 'index.html', 'Ola', '5151')
        po_.evaluate("S.people.forEach(p=>p.toured=true);S.people.push({name:'Nia',role:'caregiver',pin:'6262',toured:true});S.stock.push({id:771,name:'Ties O',qty:3,low:2},{id:772,name:'Ext O',qty:0,low:1});S.tab='stock';render()")
        po_.click('#ordnew'); po_.fill('#ordfrom', 'Apria'); po_.fill('[data-oq="771"]', '20'); po_.fill('[data-oq="772"]', '2'); po_.click('#ordok')
        check('O21 an owner logs an order and it shows as on order', po_.evaluate("onOrder(771)===20&&onOrder(772)===2") and '20 on order' in po_.inner_text('main'))
        check('O22 a low supply that’s on order gets the calmer flag', po_.locator('.srow.low.ordd').count() == 1)
        po_.evaluate("lockAdmin();S.who='Nia';render()")
        check('O23 caregivers can check in but not log orders', po_.locator('#ordnew').count() == 0 and po_.locator('[data-arr]').count() >= 1)
        po_.click('[data-sq="771|1"]')
        check('O24 counting up a supply on order asks if it arrived', po_.is_visible('#ti') and 'Did the order arrive' in po_.inner_text('#ti') and po_.evaluate("sItem(771).qty") == 3)
        po_.click('[data-arry]'); po_.fill('[data-aq="772"]', '1'); po_.click('#arrok'); po_.wait_for_timeout(100)
        check('O25 checking in adds what came and keeps the rest on order', po_.evaluate("sItem(771).qty===23&&sItem(772).qty===1&&onOrder(772)===1&&onOrder(771)===0") and po_.evaluate("S.log.some(r=>r.a==='Arrived'&&r.who==='Nia')"))
        po_.click('[data-sq="772|1"]'); po_.click('[data-arrn]')
        check('O26 “just counting” updates the count without checking in', po_.evaluate("sItem(772).qty===2&&onOrder(772)===1"))
        po_.evaluate("openOrders()[0].expected=bizDay();S.tab='today';render()")
        check('O27 a delivery shows on Today on its day', po_.locator('.dlv').count() == 1 and 'Arriving today' in po_.inner_text('.dlv'))
        po_.clock.set_system_time(D(9, 30, 16)); po_.evaluate("maybeReset();render()")
        check('O28 a delivery that doesn’t come shows as late', 'Late' in po_.inner_text('.dlv'))
        check('O29 no script errors (orders)', not eo_, '; '.join(eo_[:3]))

        # SH. a new person signing in near the next shift can start it early
        pq_, eq_ = page(viewport={'width': 820, 'height': 1180}); pq_.clock.install(time=D(12, 0, 14))
        setup(pq_, U + 'index.html', 'Pat', '8181')
        pq_.evaluate("S.people.forEach(p=>p.toured=true);S.people.push({name:'Kim',role:'caregiver',pin:'7272',toured:true});S.tasks.push({id:931,name:'Feed SH',periods:[],every:0,at:['19:00'],needs:[]});S.tab='today';render();S.who='';render();openPin('Kim')")
        code(pq_, '7272'); pq_.wait_for_timeout(400)
        check('SH1 signing in hours before the next shift doesn’t ask', not pq_.is_visible('#ti'))
        pq_.clock.set_system_time(D(17, 0, 14)); pq_.evaluate("S.who='Pat';render();openPin('Kim')"); code(pq_, '7272'); pq_.wait_for_timeout(400)
        check('SH2 signing in near the next shift asks if they’re starting it', pq_.is_visible('#ti') and 'Starting your shift' in pq_.inner_text('#ti'))
        pq_.click('#tif [data-shst]'); pq_.wait_for_timeout(150)
        check('SH3 starting early switches the board and moves later timed tasks', pq_.evaluate("nowP().id==='night'&&perAt(mins('19:00')).id==='night'") and 'started by Kim' in pq_.inner_text('.shifts'))
        check('SH4 the early start is logged', pq_.evaluate("S.log[0].d.indexOf('started early')>-1&&S.log[0].who==='Kim'"))
        pq_.click('[data-shun]')
        check('SH5 Undo puts the usual times back', pq_.evaluate("nowP().id==='day'&&curPeriods()[0].end==='21:00'"))
        pq_.evaluate("startShift('night')"); pq_.clock.set_system_time(D(12, 0, 15)); pq_.evaluate("maybeReset();render()")
        check('SH6 the next day goes back to the usual times', pq_.evaluate("curPeriods()[0].end==='21:00'&&nowP().id==='day'"))
        pq_.clock.set_system_time(D(20, 52, 15)); pq_.evaluate("$('ti').classList.remove('show');S.who='Pat';render();openPin('Kim')"); code(pq_, '7272'); pq_.wait_for_timeout(400)
        check('SH8 a nurse arriving on time (within 15 min) isn’t asked', not pq_.is_visible('#ti'))
        pq_.clock.set_system_time(D(16, 0, 16)); pq_.evaluate("maybeReset();S.who='Pat';render();openPin('Kim')"); code(pq_, '7272'); pq_.wait_for_timeout(400); pq_.click('#tif [data-shno]')
        pq_.evaluate("S.who='Pat';render();openPin('Kim')"); code(pq_, '7272'); pq_.wait_for_timeout(400)
        check('SH9 after saying No, the same person isn’t asked again that day', not pq_.is_visible('#ti'))
        pq_.clock.set_system_time(D(6, 30, 17)); pq_.evaluate("maybeReset();S.who='Pat';render();openPin('Kim')"); code(pq_, '7272'); pq_.wait_for_timeout(400)
        check('SH10 an early-morning arrival gets a hint that Day starts at the new day', pq_.is_visible('#toast') and 'when the new day begins' in pq_.inner_text('#toast'))
        check('SH7 no script errors (shift start)', not eq_, '; '.join(eq_[:3]))

        # H. inventory + log database persistence
        pg.wait_for_timeout(800); clear(pg)
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
