"""Care board regression suite.

Run from the repo root before every release (works on both versions, family and App Store):
    python3 tests/regression.py            # tests ./index.html, upgrade from the last commit
    python3 tests/regression.py --prev OLD.html
    python3 tests/regression.py --html dist/store/index.html --prev OLD_STORE.html   # test a build

Needs Python Playwright and a Chromium/Chrome. Exits 1 if anything fails.
"""
import sys, os, json, threading, subprocess, tempfile, shutil, http.server, socketserver, functools, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROME = next((p for p in ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/opt/pw-browsers/chromium'] if os.path.exists(p)), None)
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
        if pg.is_visible('#tecan'): pg.click('#tecan'); moved = True
        for m, b in [('#rk', '#rkok'), ('#tour', '#tourskip'), ('#ft', '#ftskip'), ('#ah', '#ahy'), ('#due', '#dueok')]:
            if pg.is_visible(m): pg.click(b); moved = True
        if pg.is_visible('#na'): pg.locator('#na button').last.click(); moved = True
        if not moved: break

def code(pg, digits):
    for d in digits: pg.click(f'#pad [data-pk="{d}"]')

def setup(pg, url, name='Owner', pin='1111'):
    pg.goto(url); pg.wait_for_timeout(250)
    pg.fill('#frn', name); pg.fill('#frp', pin); pg.click('#frok'); clear(pg)
    # App Store version: answer its one-time "Want an alert?" question now so it can't pop up mid-test (ED10 tests it)
    pg.evaluate("if(typeof answerNA==='function'&&!S.notifAsked){S.notifAsked=true;save()}")

def main():
    prev = None
    if '--prev' in sys.argv: prev = open(sys.argv[sys.argv.index('--prev') + 1]).read()
    else:
        try: prev = subprocess.run(['git', '-C', ROOT, 'show', 'HEAD:index.html'], capture_output=True, text=True, check=True).stdout
        except Exception: prev = None
    html = sys.argv[sys.argv.index('--html') + 1] if '--html' in sys.argv else os.path.join(ROOT, 'index.html')
    tmp = tempfile.mkdtemp()
    shutil.copy(html, os.path.join(tmp, 'index.html'))
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
        pg.click('#whob'); pg.click('#wpl [data-wp="Nurse"]'); code(pg, '2222'); code(pg, '2222'); clear(pg)
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
        pg.click('#whob'); pg.click('#wpl [data-wp="Owner"]')
        for _ in range(5): code(pg, '9999')
        check('E1 five wrong codes pause entry', pg.evaluate('pinLocked()') and pg.locator('#pad button:disabled').count() > 0)
        pg.evaluate('S.pinFail.until=Date.now()-1'); pg.wait_for_timeout(1200)
        code(pg, '1111'); clear(pg)
        check('E2 correct code works after the pause', pg.evaluate("S.who==='Owner'&&S.pinFail.n===0"))

        # N. owners/managers go straight into the Menu after signing in
        pg.evaluate("S.who='';S.adminOk=false;render()")
        pg.click('#whob'); pg.click('#wpl [data-wp="Owner"]'); code(pg, '1111'); clear(pg)
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
        pg.click('#tadd'); pg.fill('#te [data-n]', 'Trach ties Q'); pg.select_option('#te [data-f]', 'days'); pg.wait_for_timeout(150)
        qid = pg.evaluate("DRAFT.id")
        check('Q1 new repeating task asks when it is first due, defaults to one interval out', 'When is it first due' in pg.inner_text('#te') and pg.locator(f'[data-ndq="{qid}|3"].on').count() == 1)
        pg.click(f'[data-ndq="{qid}|0"]'); pg.wait_for_timeout(100)
        check('Q2 "Today" makes it due now', pg.evaluate(f"T({qid}).every-T({qid}).last===0&&ivDue(T({qid}))===bizDay()") and 'Due today' in pg.inner_text('#te'))
        pg.click('#teadd'); pg.wait_for_timeout(150)
        pg.evaluate(f"openTE({qid})")
        check('Q4 reopening says "Next due", not the first-time question', 'Next due' in pg.inner_text('#te') and 'first due' not in pg.inner_text('#te'))
        pg.fill(f'[data-nd="{qid}"]', pg.evaluate("addDays(bizDay(),10)")); pg.dispatch_event(f'[data-nd="{qid}"]', 'change'); pg.wait_for_timeout(100)
        check('Q3 a picked date further out than the interval works', pg.evaluate(f"ivDue(T({qid}))===addDays(bizDay(),10)") and pg.evaluate("S.log[0].d.indexOf('next due')>-1"))
        pg.evaluate(f"T({qid}).done={{who:'Owner',time:'9:00 AM',pid:'day'}};drawTE()")
        check('Q5 checked off today shows the next date instead of choices', 'Checked off today' in pg.inner_text('#te') and pg.locator(f'[data-ndq^="{qid}|"]').count() == 0)
        pg.evaluate(f"T({qid}).done=null;$('te').classList.remove('show')")

        # R. one "+ Add task" on the board: owners/managers pick how often, caregivers add one-time tasks
        pr, er = page(viewport={'width': 820, 'height': 1180})
        setup(pr, U + 'index.html', 'Rae', '3333'); pr.evaluate("S.people.forEach(p=>p.toured=true);S.tab='today';render()")
        pr.click('#otadd'); pr.fill('#te [data-n]', 'Bath R')
        check('R1 owner can pick any how often', pr.locator('#te [data-f] option').count() == 8 and pr.input_value('#te [data-f]') == 'period')
        pr.click('#teadd'); pr.wait_for_timeout(150)
        check('R2 a repeating task is added right on the board', not pr.is_visible('#te') and pr.evaluate("S.tasks.some(t=>t.name==='Bath R'&&t.periods.length)") and pr.evaluate("S.tab") == 'today')
        pr.click('#otadd'); pr.fill('#te [data-n]', 'Ties R'); pr.select_option('#te [data-f]', 'days'); pr.wait_for_timeout(150)
        check('R3 Every few days asks when it’s first due', 'first due' in pr.inner_text('#te'))
        pr.click('#tecan'); pr.evaluate("S.people.push({name:'Cal',role:'caregiver',pin:'2222',toured:true});lockAdmin();S.who='Cal';render()")
        pr.click('#otadd')
        check('R4 caregivers only get one-time tasks', pr.locator('#te [data-f] option').count() == 1 and pr.input_value('#te [data-f]') == 'once' and pr.locator('#te [data-od]').count() == 1)
        pr.fill('#te [data-n]', 'Call R'); pr.click('#teadd')
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
        check('S2 one-shift board: early-morning dose not overdue the day before; late dose overdue next morning', 'OVERDUE' not in e1.upper() and 'OVERDUE' in l1.upper(), e1 + ' / ' + l1)
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
        pq_.evaluate("S.notifAsked=true;S.people.forEach(p=>p.toured=true);S.people.push({name:'Kim',role:'caregiver',pin:'7272',toured:true});S.tasks.push({id:931,name:'Feed SH',periods:[],every:0,at:['20:50'],needs:[]});S.tab='today';render();S.who='';render();openPin('Kim')")
        code(pq_, '7272'); pq_.wait_for_timeout(400)
        check('SH1 signing in hours before the next shift doesn’t ask', not pq_.is_visible('#ti'))
        pq_.clock.set_system_time(D(20, 40, 14)); pq_.evaluate("S.who='Pat';render();openPin('Kim')"); code(pq_, '7272'); pq_.wait_for_timeout(400)
        check('SH2 signing in within 30 minutes of the next shift asks if they’re starting it', pq_.is_visible('#ti') and 'Starting your shift' in pq_.inner_text('#ti'))
        pq_.click('#tif [data-shst]'); pq_.wait_for_timeout(150)
        check('SH3 starting early switches the board and moves later timed tasks', pq_.evaluate("nowP().id==='night'&&perAt(mins('20:50')).id==='night'") and 'started by Kim' in pq_.inner_text('.shbar'))
        check('SH4 the early start is logged', pq_.evaluate("S.log[0].d.indexOf('started early')>-1&&S.log[0].who==='Kim'"))
        pq_.click('[data-shun]')
        check('SH5 Undo puts the usual times back', pq_.evaluate("nowP().id==='day'&&curPeriods()[0].end==='21:00'"))
        pq_.evaluate("startShift('night')"); pq_.clock.set_system_time(D(12, 0, 15)); pq_.evaluate("maybeReset();render()")
        check('SH6 the next day goes back to the usual times', pq_.evaluate("curPeriods()[0].end==='21:00'&&nowP().id==='day'"))
        pq_.clock.set_system_time(D(14, 0, 15)); pq_.evaluate("$('ti').classList.remove('show');S.who='Pat';render();openPin('Kim')"); code(pq_, '7272'); pq_.wait_for_timeout(400)
        check('SH8 signing in hours before Night (2 PM) isn’t asked', not pq_.is_visible('#ti'))
        pq_.clock.set_system_time(D(20, 35, 16)); pq_.evaluate("maybeReset();S.who='Pat';render();openPin('Kim')"); code(pq_, '7272'); pq_.wait_for_timeout(400); pq_.click('#tif [data-shno]')
        pq_.evaluate("S.who='Pat';render();openPin('Kim')"); code(pq_, '7272'); pq_.wait_for_timeout(400)
        check('SH9 after saying No, the same person isn’t asked again that day', not pq_.is_visible('#ti'))
        pq_.clock.set_system_time(D(6, 30, 17)); pq_.evaluate("maybeReset();S.who='Pat';render();openPin('Kim')"); code(pq_, '7272'); pq_.wait_for_timeout(400)
        check('SH10 an early-morning arrival gets a hint that Day starts at the new day', pq_.is_visible('#toast') and 'when the new day begins' in pq_.inner_text('#toast'))
        check('SH7 no script errors (shift start)', not eq_, '; '.join(eq_[:3]))

        # TP. times per day starts blank and must be filled in
        pt_, et_ = page(viewport={'width': 820, 'height': 1180})
        setup(pt_, U + 'index.html', 'Tia', '9191'); pt_.evaluate("S.people.forEach(p=>p.toured=true);S.tab='today';render()")
        pt_.click('#otadd'); pt_.fill('#te [data-n]', 'Count TP'); pt_.select_option('#te [data-f]', 'times'); pt_.wait_for_timeout(200)
        check('TP1 times per day starts blank with a prompt', pt_.input_value('#te [data-tm]') == '' and pt_.is_visible('#te .tmerr'))
        pt_.click('#teadd'); pt_.wait_for_timeout(100)
        check('TP2 can’t add it while it’s blank, and it isn’t on the board', pt_.is_visible('#te') and 'how many times' in pt_.inner_text('#tem') and pt_.evaluate("!dayModels(0).some(m=>m.cnts.some(t=>t.name==='Count TP'))"))
        pt_.fill('#te [data-tm]', '5'); pt_.dispatch_event('#te [data-tm]', 'change'); pt_.wait_for_timeout(100); pt_.click('#teadd'); pt_.wait_for_timeout(150)
        check('TP3 a number saves, closes, and puts it on the board', not pt_.is_visible('#te') and pt_.evaluate("dayModels(0).some(m=>m.cnts.some(t=>t.name==='Count TP'&&t.times===5))"))
        check('TP4 no script errors (times per day)', not et_, '; '.join(et_[:3]))

        # DS. 1.16 design pass: who's-here button, tab bar, supply details, grouped editor
        pd_, ed_ = page(viewport={'width': 1080, 'height': 810})
        setup(pd_, U + 'index.html', 'Dee', '2525')
        pd_.evaluate("S.people.forEach(p=>p.toured=true);S.people.push({name:'Kim Larson',role:'caregiver',pin:'3636',toured:true});S.stock.push({id:881,name:'Gauze DS',qty:0,low:2});S.tasks.push({id:882,name:'Med DS',periods:[],every:0,at:['09:00'],needs:[]});S.tab='today';render()")
        check('DS1 who’s here shows initials and name', pd_.inner_text('#whob').startswith('D') and 'Dee' in pd_.inner_text('#whob'))
        pd_.click('#whob')
        check('DS2 tapping it lists people with roles and a sign-out', pd_.is_visible('#wp') and 'KL' in pd_.inner_text('#wpl') and 'Caregiver' in pd_.inner_text('#wpl') and pd_.locator('[data-wso]').count() == 1)
        pd_.click('#wpx')
        check('DS3 the tab bar has six tabs with a low-supply badge', pd_.locator('nav .tabs [data-t]').count() == 6 and pd_.inner_text('nav [data-t="stock"] .nbadge') == '1')
        pd_.click('.lowchip')
        check('DS4 the low-supplies chip opens Supplies', pd_.evaluate("S.tab") == 'stock')
        pd_.click('[data-sdet="881"]')
        check('DS5 tapping a supply opens its details', pd_.is_visible('#ti') and 'Reorder at' in pd_.inner_text('#tib') and pd_.locator('#tif [data-sd="881"]').count() == 1)
        pd_.click('#tif [data-cl="ti"]'); pd_.evaluate("openTE(882)"); pd_.wait_for_timeout(100)
        check('DS6 the editor folds supplies and how-to under More options', pd_.locator('#te [data-tna]').count() == 0 and pd_.is_visible('#te [data-temore]'))
        pd_.click('#te [data-temore]'); pd_.wait_for_timeout(100)
        check('DS7 More options opens them', pd_.locator('#te [data-tna]').count() == 1 and pd_.locator('#te [data-gr]').count() == 1)
        pd_.evaluate("$('te').classList.remove('show')")
        pd_.evaluate("S.tasks.push({id:883,name:'Care DS',periods:['day'],every:0,needs:[{sid:881,use:1}]});S.orders=[{id:'oDS',items:[{sid:881,qty:5}],expected:bizDay(),from:'X',status:'open'}];S.tab='admin';render()")
        pd_.click('[data-bsup="0"]'); pd_.evaluate("S.tab='today';render()")
        check('DS9 hiding supplies removes low warnings, supply icons, and deliveries from the board', pd_.locator('.lowchip').count() == 0 and pd_.locator('.dlv').count() == 0 and pd_.locator('main .infob').count() == 0)
        pd_.evaluate("togK('883|day',false)")
        check('DS10 counts still go down when tasks are checked off', pd_.evaluate("sItem(881).qty") == 0 and pd_.evaluate("S.log.some(r=>r.d.indexOf('task board: hidden')>-1)"))
        pd_.evaluate("S.guides.push({id:'gDS',title:'Guide DS',steps:'a'});S.tasks.push({id:884,name:'How DS',periods:S.periods.map(function(p){return p.id}),every:0,needs:[],guide:'gDS'});S.tab='today';render()")
        h1 = pd_.locator('main .infob[data-ti="884"]').count(); pd_.evaluate("S.tab='admin';render()"); pd_.click('[data-bhow="0"]'); pd_.evaluate("S.tab='today';render()")
        check('DS11 hiding how-tos removes the How-to icon from tasks', h1 == 1 and pd_.locator('main .infob').count() == 0 and pd_.evaluate("S.log.some(r=>r.d.indexOf('How-tos on the task board: hidden')>-1)"))
        check('DS8 no script errors (design pass)', not ed_, '; '.join(ed_[:3]))

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

        # N. 1.18: Today title, shift switcher, sections, round checks, last shift, Typical day
        import datetime as _dt
        pk, ek = page(viewport={'width': 1080, 'height': 810})
        pk.clock.set_fixed_time(_dt.datetime(2026, 11, 17, 11, 40))
        setup(pk, U + 'index.html', 'Kay', '1212')
        pk.evaluate("S.people.forEach(p=>p.toured=true);S.notifAsked=true;S.setup=false;S.periods=[{id:'day',name:'Day',start:'07:00',end:'21:00'},{id:'night',name:'Night',start:'21:00',end:'07:00'}];S.resetAt='07:00';S.stock.push({id:1101,name:'Gauze K',qty:5,low:1});S.tasks.push({id:1001,name:'Feed K',periods:[],every:0,at:['08:00','12:00','16:00'],needs:[]},{id:1002,name:'Care K',periods:['day'],every:0,needs:[{sid:1101,use:1}]},{id:1003,name:'Wipe K',periods:['night'],every:0,needs:[{sid:1101,use:1}]});togCt('1001@08:00',false);hideUndo();S.tab='today';render()")
        t1 = pk.inner_text('#ttl'); pk.evaluate("S.tab='week';render()"); t2 = pk.inner_text('#ttl'); pk.evaluate("S.tab='today';render()")
        check('N1 the title is the screen name (Today, This week)', t1 == 'Today' and t2 == 'This week', t1 + '/' + t2)
        check('N2 system font, no Inter files inside the app', pk.evaluate("getComputedStyle(document.body).fontFamily.indexOf('Inter')<0&&document.documentElement.outerHTML.indexOf('font/woff')<0"))
        secs = pk.evaluate("[...document.querySelectorAll('main .panel .sec')].map(e=>e.firstChild.textContent)")
        check('N3 small shift switcher and Up next / Anytime / Later / Done sections', pk.locator('.shsw button').count() == 3 and secs == ['Up next', 'Anytime today', 'Later today', 'Done'] and 'in 20 min' in pk.inner_text('main .panel .tiles >> nth=0').lower(), str(secs))
        check('N4 round checkmarks', pk.evaluate("getComputedStyle(document.querySelector('main .task .box')).borderRadius") == '50%')
        check('N5 done tasks keep the strikethrough', pk.evaluate("getComputedStyle(document.querySelector('main .task.done .tn')).textDecorationLine").startswith('line-through'))
        pk.clock.set_fixed_time(_dt.datetime(2026, 11, 18, 8, 0)); pk.evaluate("maybeReset();S.tab='today';render()")
        check('N6 the new day keeps last night’s check-offs', pk.evaluate("prevOK()&&S.prevDay.key==='2026-11-17'&&!!S.prevDay.cdone['1001@08:00']&&!S.cdone['1001@08:00']"))
        pk.click('[data-shv="prev"]')
        check('N7 Last night shows what was missed', 'Wipe K' in pk.inner_text('main .panel') and 'Missed' in pk.inner_text('main .panel') and pk.locator('[data-pv="r|1003|night"]').count() == 1)
        q0 = pk.evaluate("sItem(1101).qty"); pk.click('[data-pv="r|1003|night"]')
        check('N8 a missed task can be checked off late (logged, supplies counted)', pk.evaluate("S.prevDay.done['1003|night'].late===true&&S.log[0].d.indexOf('Wipe K')>-1&&S.log[0].d.indexOf('late')>-1") and pk.evaluate("sItem(1101).qty") == q0 - 1)
        pk.evaluate("S.tasks.push({id:1009,name:'Tylenol K',periods:[],every:0,prn:true,gap:4,needs:[],hist:[{ts:new Date(2026,10,17,15,0).getTime(),who:'Kay'},{ts:new Date(2026,10,17,23,40).getTime(),who:'Ann'},{ts:new Date(2026,10,18,4,10).getTime(),who:'Mo'},{ts:new Date(2026,10,18,7,30).getTime(),who:'Kay'}]});render()")
        pt = pk.inner_text('main .panel')
        check('N8b Last night lists As needed tasks given during that shift (who and when)', 'As needed' in pt and 'Tylenol K' in pt and 'Ann at 11:40 PM' in pt and 'Mo at 4:10 AM' in pt and '2 times' in pt and '3:00 PM' not in pt and '7:30 AM' not in pt, pt[-200:])
        pk.evaluate("S.tasks=S.tasks.filter(t=>t.id!==1009);render()")
        pk.click('[data-shv="cur"]')
        check('N9 Back to the current shift', not pk.evaluate("S.viewPrev") and pk.locator('[data-pv]').count() == 0)
        pk.clock.set_fixed_time(_dt.datetime(2026, 11, 18, 22, 0)); pk.evaluate("maybeReset();togK('1002|day',false);hideUndo()")
        check('N10 checking off a Day task during Night is marked late', pk.evaluate("S.done['1002|day'].late===true&&S.log[0].d.indexOf(' · late')>-1"))
        pk.evaluate("S.adminOk=false"); pk.click('[data-st="1"]'); pk.click('[data-typ="1"]'); off = pk.evaluate("typOn()")
        pk.evaluate("S.adminOk=true;fillSt()"); pk.click('[data-typ="1"]'); pk.click('#stx')
        check('N11 Typical day is turned on in Settings, only by someone who can edit schedules', off is False and pk.evaluate("typOn()&&S.log[0].d.indexOf('Typical day turned on')>-1"))
        pk.evaluate("goArea('typ');S.tyd=3;render()")
        pk.click('[data-tyb="new"]'); pk.fill('#tbn', 'Nap K'); pk.evaluate("TB.s='21:30';TB.e='22:30';drawTB()"); pk.click('#tbok')
        pk.click('[data-tyb="new"]'); pk.click('#tbok'); err1 = pk.inner_text('#tbm'); pk.fill('#tbn', 'PT K'); pk.evaluate("TB.s='23:00';TB.e='';drawTB()"); pk.click('#tbok')
        check('N12 blocks are added to a weekday, and a name/time is required', pk.evaluate("typDay(3).map(b=>b.n).join()") == 'Nap K,PT K' and 'name' in err1)
        pk.evaluate("S.tab='today';render()")
        tl = pk.inner_text('.typline') if pk.locator('.typline').count() else ''
        check('N13 Today shows what is happening now and next', 'Now: Nap K' in tl and 'until 10:30 PM' in tl and 'Next: PT K' in tl, tl)
        pk.evaluate("S.tab='typ';render()"); pk.click('[data-tycp="3"]'); pk.click('[data-tcq="wk"]'); pk.click('#tcok')
        check('N14 copy a day to all weekdays', pk.evaluate("[1,2,4,5].every(w=>typDay(w).length===2)&&typDay(6).length===0&&typDay(0).length===0"))
        pk.evaluate("S.tab='today';render()"); pk.click('.typline [data-wv="typ"]')
        check('N15 This week shows the typical day', pk.evaluate("S.tab") == 'week' and pk.locator('.tychips').count() == 1 and 'Nap K' in pk.inner_text('main'))
        check('N16 backups include the typical day and last night', pk.evaluate("snap().state.typ.on===true&&!!snap().state.prevDay&&snap().state.viewPrev===undefined"))
        pk.evaluate("S.typ.days[3].push({id:'zz',n:'Sleep K',s:'23:30',e:'06:30',note:''})"); pk.clock.set_fixed_time(_dt.datetime(2026, 11, 19, 2, 0)); pk.evaluate("maybeReset();S.tab='today';S.viewP=null;render()")
        tl2 = pk.inner_text('.typline') if pk.locator('.typline').count() else ''
        check('N18 an overnight block still shows after midnight', 'Now: Sleep K until 6:30 AM' in tl2, tl2)
        # AT. 1.19: one Add task pop-up everywhere
        pa, ea = page(viewport={'width': 1080, 'height': 810})
        setup(pa, U + 'index.html', 'Ada', '4545'); pa.evaluate("S.people.forEach(p=>p.toured=true);S.notifAsked=true;S.tab='today';render()")
        n0 = pa.evaluate("S.tasks.length"); l0 = pa.evaluate("S.log.length")
        pa.click('#otadd'); pa.wait_for_timeout(150)
        check('AT1 Today’s Add task opens the editor-style pop-up', pa.is_visible('#te') and pa.inner_text('#tet') == 'Add task' and pa.is_visible('#teadd') and pa.is_visible('#tecan') and not pa.is_visible('#tedel') and not pa.is_visible('#tedone'))
        check('AT2 nothing is added until Add task is tapped', pa.evaluate("S.tasks.length") == n0 and pa.evaluate("!snap().state.tasks.some(t=>t.id===DRAFT.id)"))
        pa.click('#teadd'); pa.wait_for_timeout(100)
        check('AT3 a name is required', pa.is_visible('#te') and 'name' in pa.inner_text('#tem'))
        pa.mouse.click(5, 800); pa.wait_for_timeout(100)
        check('AT4 tapping outside an empty new task closes it; nothing added', not pa.is_visible('#te') and pa.evaluate("DRAFT===null") and pa.evaluate("S.tasks.length") == n0)
        pa.click('#otadd'); pa.wait_for_timeout(150); pa.fill('#te [data-n]', 'Half AT'); pa.mouse.click(5, 800); pa.wait_for_timeout(150)
        check('AT4b with a name typed, tapping outside asks before throwing it away', pa.is_visible('#cf') and pa.is_visible('#te') and 'Half AT' in pa.inner_text('#cfm') and pa.inner_text('#cfx') == 'Keep editing')
        pa.click('#cfx'); pa.wait_for_timeout(150)
        check('AT4c Keep editing goes back to the task as typed', not pa.is_visible('#cf') and pa.is_visible('#te') and pa.input_value('#te [data-n]') == 'Half AT')
        pa.mouse.click(5, 800); pa.wait_for_timeout(150); pa.click('#cfok'); pa.wait_for_timeout(150)
        check('AT4d Discard closes it; nothing added or logged', not pa.is_visible('#te') and not pa.is_visible('#cf') and pa.evaluate("S.tasks.length") == n0 and pa.evaluate("S.log.length") == l0)
        pa.evaluate("askConfirm('t','m','OK',function(){})"); ok = pa.inner_text('#cfx') == 'Cancel'; pa.click('#cfx')
        check('AT4e other confirmations still say Cancel', ok)
        pa.evaluate("S.tasks.push({id:4401,name:'Wipe AT4',periods:S.periods.map(p=>p.id),every:0,needs:[]});openTE(4401)"); pa.wait_for_timeout(150); ok = pa.is_visible('#te')
        pa.mouse.click(5, 800); pa.wait_for_timeout(150)
        check('AT4f tapping outside an existing task still closes it', ok and not pa.is_visible('#te'))
        pa.evaluate("S.tasks=S.tasks.filter(t=>t.id!==4401);render()")
        pa.click('#otadd'); pa.wait_for_timeout(150)
        check('AT4g How often says “Once per shift”', 'Once per shift' in pa.inner_text('#te [data-f]'))
        pa.fill('#te [data-n]', 'Draft AT'); pa.dispatch_event('#te [data-n]', 'change'); pa.click('[data-okind$="|med"]') if pa.locator('[data-okind$="|med"]').count() else None; pa.wait_for_timeout(100)
        pa.click('#tecan'); pa.wait_for_timeout(100)
        check('AT5 Cancel adds nothing and logs nothing', not pa.is_visible('#te') and pa.evaluate("S.tasks.length") == n0 and pa.evaluate("S.log.length") == l0 and pa.evaluate("DRAFT===null"))
        pa.click('#otadd'); pa.fill('#te [data-n]', 'Meds AT'); pa.select_option('#te [data-f]', 'clock'); pa.wait_for_timeout(150)
        pa.click('#tpok'); pa.wait_for_timeout(150)
        check('AT6 At set times asks for the first time inside the pop-up', pa.is_visible('#te') and pa.evaluate("DRAFT.at.length") == 1)
        pa.click('#teadd'); pa.wait_for_timeout(200)
        check('AT7 added, logged once, and shown on the board', not pa.is_visible('#te') and pa.evaluate("S.tasks.some(t=>t.name==='Meds AT'&&t.at.length===1)") and pa.evaluate("S.log.filter(r=>r.a==='Added task'&&r.d.indexOf('Meds AT')===0).length") == 1 and pa.evaluate("S.log.filter(r=>r.a==='Changed'&&r.d.indexOf('Meds AT')>-1).length") == 0)
        pa.evaluate("S.tab='edit';render()"); pa.wait_for_timeout(100)
        check('AT8 All tasks has the same + Add task button, not a form', pa.inner_text('#tadd').strip() == '+ Add task' and pa.locator('#newn').count() == 0)
        pa.click('#tadd'); pa.fill('#te [data-n]', 'Wipe AT'); pa.click('#teadd'); pa.wait_for_timeout(150)
        check('AT9 adding from All tasks stays on All tasks', pa.evaluate("S.tab") == 'edit' and pa.locator('[data-te]').filter(has_text='Wipe AT').count() == 1)
        pa.evaluate("openFT()"); pa.wait_for_timeout(100)
        check('AT10 first task during setup is the same pop-up', pa.is_visible('#te') and pa.inner_text('#tet') == 'Add your first task' and pa.is_visible('#tek') and pa.inner_text('#tecan') == 'Skip for now' and pa.locator('#ft').count() == 0)
        pa.fill('#te [data-n]', 'First AT'); pa.click('#teadd'); pa.wait_for_timeout(200)
        check('AT11 first task lands on Today with the hint', pa.evaluate("S.tab") == 'today' and pa.is_visible('#toast') and 'That’s your task' in pa.inner_text('#toast'))
        pa.evaluate("S.people.push({name:'Mo',role:'manager',perms:{sched:true},pin:'7777',toured:true});lockAdmin();S.who='Mo';render()")
        pa.click('#otadd'); pa.wait_for_timeout(100)
        check('AT12 a manager not yet confirmed starts on One time, with all choices shown', pa.input_value('#te [data-f]') == 'once' and pa.locator('#te [data-f] option').count() == 8)
        pa.select_option('#te [data-f]', 'days'); pa.wait_for_timeout(150)
        check('AT13 picking a repeating option asks for their code first', pa.is_visible('#pin') and pa.evaluate("fq(DRAFT)") == 'once')
        for d in '7777': pa.click(f'#pad [data-pk="{d}"]')
        pa.wait_for_timeout(200)
        check('AT14 after the code, the choice is applied to the new task', pa.is_visible('#te') and pa.evaluate("fq(DRAFT)") == 'days')
        pa.click('#tecan'); pa.click('#otadd'); pa.fill('#te [data-n]', 'Keep AT'); pa.select_option('#te [data-f]', 'once'); pa.wait_for_timeout(150)
        check('AT16 changing How often keeps the name you typed', pa.input_value('#te [data-n]') == 'Keep AT')
        pa.click('#tecan')
        check('AT15 no script errors (add task)', not ea, '; '.join(ea[:3]))

        # KB. 1.19.1: iPad landscape keyboard keeps the first-task title in view.
        # Chromium has no on-screen keyboard, so fake what iOS reports: a 400px visible strip slid 200px down.
        pv, ev = page(viewport={'width': 1080, 'height': 810})
        pv.add_init_script("(()=>{var vv=new EventTarget();vv.width=1080;vv.height=810;vv.offsetTop=0;vv.offsetLeft=0;vv.scale=1;Object.defineProperty(window,'visualViewport',{get:function(){return vv},configurable:true});window.__vv=vv})()")
        setup(pv, U + 'index.html'); pv.evaluate("openFT()"); pv.wait_for_timeout(300)
        check('KB1 first-task pop-up puts the cursor in the name box', pv.evaluate("document.activeElement===document.querySelector('#te [data-n]')"))
        pv.evaluate("(()=>{var v=window.__vv;v.height=400;v.offsetTop=200;v.dispatchEvent(new Event('resize'));v.dispatchEvent(new Event('scroll'))})()"); pv.wait_for_timeout(500)
        shown = lambda sel: pv.evaluate("(s=>{var v=window.__vv,r=document.querySelector(s).getBoundingClientRect();return r.top>=v.offsetTop&&r.bottom<=v.offsetTop+v.height})", sel)
        check('KB2 with the keyboard up, the title and "Last step" stay on screen', shown('#tet') and shown('#tek'))
        check('KB3 with the keyboard up, the name box is on screen too', shown('#te [data-n]'))
        pv.evaluate("(()=>{var v=window.__vv;v.height=810;v.offsetTop=0;v.dispatchEvent(new Event('resize'))})()"); pv.wait_for_timeout(200)
        check('KB4 keyboard down, the pop-up uses the full screen again', abs(pv.evaluate("document.querySelector('#te .card').getBoundingClientRect().height") - 767) < 40)
        check('KB5 no script errors (keyboard)', not ev, '; '.join(ev[:3]))

        # TD. 1.19.1: "N times a day" tasks move to Done, and Yesterday works with one Day shift
        pn, en = page(viewport={'width': 1080, 'height': 810}); pn.clock.install(time=datetime.datetime(2026, 11, 12, 9, 30))
        pn.goto(U + 'index.html'); pn.wait_for_timeout(250); pn.fill('#frn', 'Dad'); pn.fill('#frp', '1212'); pn.click('#frok'); pn.wait_for_timeout(200)
        if pn.is_visible('#sh'): pn.click('#sh [data-shn="1"]'); pn.click('#shok')
        clear(pn)
        pn.evaluate("S.periods=S.periods.slice(0,1);S.periods[0].name='Day';['Brush TD','Drops TD'].forEach(function(n){S.tasks.push({id:S.nid++,name:n,periods:[],every:0,n:3,times:2,prn:false,last:0,needs:[]})});S.tab='today';render()")
        bt, dt = pn.evaluate("['Brush TD','Drops TD'].map(n=>S.tasks.filter(t=>t.name===n)[0].id)")
        grp_of = lambda tid: pn.evaluate(f"(()=>{{var e=document.querySelector('main [data-c=\"{tid}\"]'),t=e&&e.closest('.tiles');return t&&t.previousElementSibling?t.previousElementSibling.firstChild.textContent:''}})()")
        pn.click(f'[data-c="{bt}"]'); pn.wait_for_timeout(150)
        check('TD1 one of two check-offs stays in Anytime', grp_of(bt).lower().startswith('anytime'))
        pn.click(f'[data-c="{bt}"]'); pn.click(f'[data-c="{dt}"]'); pn.wait_for_timeout(150)
        check('TD2 both check-offs done moves it to Done', grp_of(bt) == 'Done' and grp_of(dt).lower().startswith('anytime'))
        pn.click('[data-shv="prev"]', force=True); pn.wait_for_timeout(150)
        check('TD3 Yesterday with nothing saved explains why instead of doing nothing', pn.is_visible('#toast') and 'Nothing saved from yesterday' in pn.inner_text('#toast') and not pn.evaluate("S.viewPrev"))
        pn.clock.run_for(24 * 3600 * 1000); pn.wait_for_timeout(300); pn.evaluate("render()"); clear(pn)
        pn.click('[data-shv="prev"]'); pn.wait_for_timeout(150)
        check('TD4 next day, Yesterday opens', pn.evaluate("S.viewPrev") is True)
        check('TD5 Yesterday shows the finished task as done and the half-done one as missed', pn.locator(f'[data-pv="n|{bt}"].done').count() == 1 and pn.locator(f'[data-pv="n|{dt}"].over').count() == 1 and '1 of 2' in pn.inner_text(f'[data-pv="n|{dt}"]'))
        pn.click(f'[data-pv="n|{dt}"]'); pn.wait_for_timeout(150)
        check('TD6 a missed one can be checked off late from Yesterday', pn.locator(f'[data-pv="n|{dt}"].done').count() == 1 and pn.evaluate("S.log[0].a==='Logged'&&/Drops TD.*late/.test(S.log[0].d)"))
        check('TD7 no script errors (times a day / yesterday)', not en, '; '.join(en[:3]))

        # LD. 1.19: filter the log by date
        pl, el_ = page(viewport={'width': 1080, 'height': 810}); pl.clock.install(time=datetime.datetime(2026, 11, 17, 10, 0))
        setup(pl, U + 'index.html', 'Lee', '5151'); pl.evaluate("S.people.forEach(p=>p.toured=true)")
        pl.evaluate("""S.log=[];[[17,9,'Today LD'],[16,15,'Yday LD'],[10,8,'Week LD'],[1,8,'Nov1 LD'],[28,8,'Oct LD']].forEach(function(x){var m=x[0]>=17||x[0]<10&&x[2]!=='Oct LD'?10:10;var d=x[2]==='Oct LD'?new Date(2026,9,x[0],x[1]):new Date(2026,10,x[0],x[1]);S.log.push({ts:d,who:'Lee',a:'Completed',d:x[2]})});S.log.sort(function(a,b){return b.ts-a.ts});S.tab='log';render()""")
        names = lambda: pl.evaluate("logRows(true).map(r=>r.d).join(',')")
        pl.select_option('[data-ld]', 'today'); pl.wait_for_timeout(100)
        check('LD1 Today shows only today', names() == 'Today LD' and 'Today LD' in pl.inner_text('#main') and 'Yday LD' not in pl.inner_text('#main'), names())
        pl.select_option('[data-ld]', 'yday'); pl.wait_for_timeout(100)
        check('LD2 Yesterday', names() == 'Yday LD')
        pl.select_option('[data-ld]', 'd7'); pl.wait_for_timeout(100)
        check('LD3 Last 7 days includes Nov 11 onward', names() == 'Today LD,Yday LD')
        pl.select_option('[data-ld]', 'lmonth'); pl.wait_for_timeout(100)
        check('LD4 Last month is October', names() == 'Oct LD')
        pl.select_option('[data-ld]', 'custom'); pl.wait_for_timeout(100)
        check('LD5 Pick dates shows From and To, starting with the last week', pl.locator('[data-ld1]').count() == 1 and pl.input_value('[data-ld1]') == '2026-11-11' and pl.input_value('[data-ld2]') == '2026-11-17')
        pl.fill('[data-ld1]', '2026-11-01'); pl.dispatch_event('[data-ld1]', 'change'); pl.fill('[data-ld2]', '2026-11-10'); pl.dispatch_event('[data-ld2]', 'change'); pl.wait_for_timeout(100)
        check('LD6 a custom range includes both end days', names() == 'Week LD,Nov1 LD' and 'Nov 1 – Nov 10' in pl.inner_text('#main'), names())
        pl.fill('[data-ld1]', '2026-11-16'); pl.dispatch_event('[data-ld1]', 'change'); pl.wait_for_timeout(100)
        check('LD7 From after To still works (dates are swapped)', names() == 'Yday LD,Week LD', names())
        pl.select_option('[data-lf]', 'Lee'); pl.wait_for_timeout(100); pl.click('[data-lclr]'); pl.wait_for_timeout(100)
        check('LD8 Clear filters clears the dates too', pl.evaluate("!S.logd&&!S.logd1&&!S.logd2") and pl.input_value('[data-ld]') == '')
        check('LD9 date filters aren’t saved', pl.evaluate("(S.logd='today',!('logd' in snap().state))"))
        check('LD10 no script errors (log dates)', not el_, '; '.join(el_[:3]))

        pl.evaluate("S.tab='menu';render()"); pl.wait_for_timeout(100)
        bx = pl.evaluate("(function(){var a=document.querySelector('#emedit .mgic').getBoundingClientRect(),b=document.querySelector('.mgrow .mgic').getBoundingClientRect(),s=document.querySelector('#emedit .mgic svg').getBoundingClientRect();return [a.width,a.height,b.width,b.height,Math.abs((s.left+s.width/2)-(a.left+a.width/2)),Math.abs((s.top+s.height/2)-(a.top+a.height/2))]})()")
        check('MI1 Emergency info icon is the same size as the others and centered', bx[0] == bx[2] and bx[1] == bx[3] and bx[4] < 1.5 and bx[5] < 1.5, bx)

        check('N17 no script errors (1.18)', not ek, '; '.join(ek[:3]))

        # ED. one codebase, two versions: the edition block decides the storage key and the App Store-only pieces
        pe, ee = page(viewport={'width': 1080, 'height': 810})
        pe.goto(U + 'index.html'); pe.wait_for_timeout(250)
        store = pe.evaluate('ED.store')
        check('ED1 storage key and backup id match the edition', pe.evaluate("KEY===ED.key&&snap().app===ED.app") and pe.evaluate('KEY') == ('ezaide.v1' if store else 'zeke-care-board.v1') and pe.evaluate("snap().app") == ('ezaide' if store else 'zeke-care-board'))
        check('ED2 App Store pieces only in the App Store version', pe.evaluate("['dc','na','trl','abt'].every(function(i){return !!document.getElementById(i)===ED.store})&&(KEEP.indexOf('dc')>-1)===ED.store&&tourCards('x').some(function(c){return c.t==='A quick note'})===ED.store"))
        check('ED3 both versions accept a family backup; only the App Store one accepts its own', pe.evaluate("okSnap({app:'zeke-care-board',state:{tasks:[],periods:[1],people:[1]}})") and pe.evaluate("okSnap({app:'ezaide',state:{tasks:[],periods:[1],people:[1]}})") == store)
        pe.locator('#frp').press_sequentially('ab12'); v1 = pe.input_value('#frp')
        pe.fill('#frp', ''); pe.locator('#frp').press_sequentially('１２x３４'); v2 = pe.input_value('#frp')
        pe.evaluate("(()=>{var i=document.getElementById('rcn');i.value='9a8b7c6d5';i.dispatchEvent(new Event('input',{bubbles:true}))})()"); v3 = pe.input_value('#rcn')
        check('PN1 sign-in code boxes only take digits (letters dropped as you type)', v1 == '12' and v2 == '1234' and v3 == '9876', f'{v1!r} {v2!r} {v3!r}')
        pe.fill('#frp', '')
        pe.fill('#frn', 'Eve'); pe.fill('#frp', '1212'); pe.click('#frok'); pe.wait_for_timeout(200)
        if pe.is_visible('#sh'):
            if pe.locator('#sh [data-shn="2"]').count(): pe.click('#sh [data-shn="2"]')
            pe.click('#shok'); pe.wait_for_timeout(200)
        if store:
            check('ED4 App Store first run: disclaimer, then recovery key, then first task (no tour)', pe.is_visible('#dc') and not pe.is_visible('#rk'))
            pe.check('#dcck'); pe.click('#dcok'); pe.wait_for_timeout(150); ok = pe.is_visible('#rk')
            pe.click('#rkok'); pe.wait_for_timeout(200); ok = ok and not pe.is_visible('#tour') and pe.is_visible('#te')
            check('ED5 ...recovery key, then straight to the first task', ok)
        else:
            check('ED4 family first run: recovery key, then the welcome tour', pe.is_visible('#rk') and pe.locator('#dc').count() == 0)
            pe.click('#rkok'); pe.wait_for_timeout(200); ok = pe.is_visible('#tour')
            pe.click('#tourskip'); pe.wait_for_timeout(400)
            check('ED5 ...then the first task', ok and pe.is_visible('#te'))
        check('ED6 first task step doesn’t ask about the hours again (the shifts step already did)', 'hours are right' not in pe.inner_text('#te').lower() and pe.evaluate('S.setupHours===true'))
        pe.click('#tecan'); pe.wait_for_timeout(200)
        pe.evaluate("openNT('today')"); pe.wait_for_timeout(150); t = pe.inner_text('#te').lower()
        check('ED7 the task box calls Day/Night “shifts”', 'once per shift' in t and 'which shifts' in t and 'time of day' not in t)
        pe.click('#tecan'); pe.wait_for_timeout(150)
        pe.evaluate("S.tab='periods';render()"); pe.wait_for_timeout(150); t = pe.inner_text('#main').lower() + pe.inner_text('#ttl').lower()
        check('ED8 the Shifts screen is called Shifts', 'shifts' in t and 'add a shift' in t and 'time of day' not in t)
        pe.evaluate("S.tab='menu';render()"); pe.wait_for_timeout(150)
        m = pe.inner_text('#main').lower()
        check('ED9 setup checklist is grouped: Essentials, then When you have a minute', 'essentials' in m and 'when you have a minute' in m and m.index('essentials') < m.index('when you have a minute'))
        pe.evaluate('openWho()'); pe.wait_for_timeout(150)
        lay = pe.evaluate("(()=>{var r=document.querySelector('#wpl .wprow'),a=r.querySelector('.av').getBoundingClientRect(),n=r.querySelector('.wpn').getBoundingClientRect();return [getComputedStyle(r).display,a.right<=n.left,Math.abs((a.top+a.bottom)/2-(n.top+n.bottom)/2)<12]})()")
        check('WP1 Who’s here: initial sits beside the name, not above it', lay == ['flex', True, True], str(lay))
        pe.click('#wpx'); pe.wait_for_timeout(100)
        pe.evaluate("S.tasks.push({id:9901,name:'Med ED',periods:[],every:0,at:['08:00'],needs:[]});S.tab='today';render()"); pe.wait_for_timeout(1200)
        check('ED10 App Store version asks once about alerts when a task has a set time (family never does)', pe.is_visible('#na') == store)
        if store: pe.click('#nano'); pe.wait_for_timeout(150)
        check('ED11 no script errors (editions)', not ee, '; '.join(ee[:3]))

        # J. phone layout
        pg3, e3 = page(**p.devices['iPhone 13'])
        setup(pg3, U + 'index.html', 'Pat', '4444')
        bad = pg3.evaluate("['today','week','library','stock','log','menu','edit','periods','people','admin','typ'].filter(function(t){S.adminOk=true;S.tab=t;render();return document.documentElement.scrollWidth>innerWidth})")
        check('J1 nothing wider than a phone screen', not bad, str(bad))
        check('J2 no script errors (phone)', not e3, '; '.join(e3[:3]))
        b.close()
    srv.shutdown()
    fails = [r for r in results if not r[1]]
    print(f'\n{len(results) - len(fails)}/{len(results)} passed')
    sys.exit(1 if fails else 0)

if __name__ == '__main__':
    main()
