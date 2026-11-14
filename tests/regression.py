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

        # R. hint pointing admins to Menu → Edit tasks, until they've been there once
        pr, er = page(viewport={'width': 820, 'height': 1180})
        setup(pr, U + 'index.html', 'Hint', '3333'); pr.evaluate("S.tab='today';render()")
        check('R1 owner sees the hint pointing at Menu', pr.is_visible('#mhint') and 'repeating' in pr.inner_text('#mhint'))
        pr.click('nav [data-t="menu"]')
        check('R2 Menu marks Edit tasks as the place to start', pr.locator('main .task.mhl[data-t="edit"] .mhtag').count() == 1)
        pr.click('main [data-t="edit"]'); pr.click('nav [data-t="today"]')
        check('R3 hint goes away once they have opened Edit tasks', not pr.is_visible('#mhint') and pr.evaluate("me().hintEdit===true"))
        pr.evaluate("S.people.push({name:'Nurse R',role:'caregiver',pin:'2468'});S.who='Nurse R';render()")
        check('R4 caregivers never see it', not pr.is_visible('#mhint'))
        pr.evaluate("S.people.push({name:'Mgr R',role:'manager',perms:{sched:true},pin:'1357'});S.who='Mgr R';render()")
        pr.click('#mhx')
        check('R5 the × dismisses it for that person', not pr.is_visible('#mhint') and pr.evaluate("me().hintEdit===true"))
        check('R6 no script errors (hint)', not er, '; '.join(er[:3]))

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
