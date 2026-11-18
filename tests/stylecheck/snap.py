"""Style snapshot: records the computed style + box of every element on every screen.
usage: python3 snap.py page.html out.json            -> write snapshot
       python3 snap.py page.html out.json base.json  -> also diff against base
"""
import sys, os, json, datetime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import regression as R
from playwright.sync_api import sync_playwright


SEED = r"""(()=>{
var P=S.periods,p0=P[0].id,p1=(P[1]||P[0]).id,id=function(){return S.nid++};
var mk=function(o){var t=Object.assign({id:id(),name:'',periods:[],every:0,n:3,times:0,prn:false,last:0,needs:[]},o);S.tasks.push(t);return t};
mk({name:'Morning meds',periods:[p0]});mk({name:'Night meds & check',periods:[p1]});
var a=mk({name:'Wipe tube site',periods:[p0,p1]});S.done[a.id+'|'+p0]={who:'Owner',time:'8:05 AM'};
mk({name:'Feed 120 mL',at:['08:00','12:00','20:00']});
var c=mk({name:'Brush teeth',times:2});S.cnt[c.id]={n:1,last:'9:00 AM',who:'Owner'};
mk({name:'Change sheets',every:3,last:3});mk({name:'Bath',every:2,last:0});
mk({name:'Tylenol',prn:true,gap:4,hist:[{ts:Date.now()-3600e3,who:'Owner'}]});
mk({name:'Call pharmacy',once:true,date:bizDay()});
S.stock.push({id:id(),name:'Syringes',qty:2,low:5},{id:id(),name:'Gauze',qty:40,low:10},{id:id(),name:'Formula',qty:0,low:3});
S.guides.push({id:id(),title:'Changing the dressing',steps:'Wash hands\nRemove old gauze\nClean with saline'});
S.people.push({name:'Mo',role:'manager',perms:{sched:true},pin:'7777',toured:true},{name:'Ann',role:'caregiver',perms:{},pin:'8888',toured:true});
for(var i=0;i<12;i++)S.log.unshift({ts:new Date(Date.now()-i*3600e3),who:i%2?'Mo':'Owner',a:i%3?'Completed':'Changed',d:'Task '+i});
S.emer=S.emer||{};S.emer.alert='Allergic to penicillin';S.emer.contacts=[{n:'Dr. Lee',p:'555-0100'}];
S.people.forEach(function(p){p.toured=true});save();render()})()"""

STATES = [
    ('today', "S.tab='today';render()"),
    ('today-next', "S.tab='today';render();var b=document.querySelector('[data-shv=\"next\"]');b&&b.click()"),
    ('week', "S.tab='week';render()"),
    ('day', "S.tab='today';render();openDay(1)"),
    ('library', "S.tab='library';render()"),
    ('stock', "S.tab='stock';render()"),
    ('log', "S.tab='log';render()"),
    ('menu', "S.tab='menu';render()"),
    ('edit', "S.tab='edit';render()"),
    ('periods', "S.tab='periods';render()"),
    ('typ', "S.tab='typ';render()"),
    ('admin', "S.tab='admin';render()"),
    ('settings', "S.tab='today';render();fillSt();$('st').classList.add('show')"),
    ('task-edit', "S.tab='today';render();openTE(S.tasks[0].id)"),
    ('task-edit-clock', "S.tab='today';render();openTE(S.tasks[3].id)"),
    ('add-task', "S.tab='today';render();openNT('today')"),
    ('first-task', "S.tab='menu';render();openFT()"),
    ('info', "S.tab='today';render();openInfo(S.tasks[0].id)"),
    ('emergency', "S.tab='today';render();fillEm();$('modal').classList.add('show')"),
    ('confirm', "S.tab='today';render();askConfirm('Remove this?','It will be gone.','Remove',function(){})"),
    ('toast', "S.tab='today';render();showUndo('Logged: Brush teeth (2)',function(){});clearTimeout(UNDO.t)"),
    ('emergency-edit', "S.tab='today';render();openEmEd()"),
    ('guide', "S.tab='library';render();openGuide(S.guides[0].id)"),
]

COLLECT = r"""(()=>{
function h(s){var x=0;for(var i=0;i<s.length;i++){x=(x*31+s.charCodeAt(i))|0}return x}
function sty(el,ps){var cs=getComputedStyle(el,ps),a=[];for(var i=0;i<cs.length;i++){var k=cs[i];if(k.indexOf('--')===0||k==='transition'||k.indexOf('transition')===0||k.indexOf('animation')===0)continue;a.push(k+':'+cs.getPropertyValue(k))}return a.join(';')}
var out={},all=document.querySelectorAll('*');
for(var i=0;i<all.length;i++){var el=all[i],r=el.getBoundingClientRect();
  var key=i+':'+el.tagName+(el.id?'#'+el.id:'')+(el.className&&typeof el.className==='string'?'.'+el.className.trim().split(/\s+/).join('.'):'');
  var full=sty(el)+'|B:'+sty(el,'::before')+'|A:'+sty(el,'::after')+'|R:'+[r.x,r.y,r.width,r.height].map(Math.round).join(',');
  out[key]=window.__detail?full:h(full)}
return out})()"""

VIEWS = [('land', 1080, 810), ('port', 810, 1080), ('phone', 390, 844)]
if __name__ == '__main__':
    html, out = sys.argv[1], sys.argv[2]
    base = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else None
    snap, errors = {}, []
    srv, U = R.serve(os.path.dirname(os.path.abspath(html)))
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=R.CHROME, args=['--no-sandbox']) if R.CHROME else p.chromium.launch()
        for vn, w, hgt in VIEWS:
            ctx = b.new_context(viewport={'width': w, 'height': hgt}, reduced_motion='reduce')
            pg = ctx.new_page(); pg.on('pageerror', lambda e: errors.append(str(e)))
            pg.clock.set_fixed_time(datetime.datetime(2026, 11, 12, 10, 0))
            R.setup(pg, U + os.path.basename(html)); pg.evaluate(SEED); pg.wait_for_timeout(200); R.clear(pg)
            for theme in ['dark', 'light']:
                for name, js in STATES:
                    pg.evaluate("document.querySelectorAll('.modal.show').forEach(m=>m.classList.remove('show'));DRAFT=null;NTX=null;hideUndo();window.scrollTo(0,0)")
                    pg.evaluate(f"document.documentElement.dataset.theme='{theme}'")
                    try: pg.evaluate(js)
                    except Exception as e: errors.append(f'{name}: {e}'); continue
                    pg.wait_for_timeout(450)
                    k = f'{vn}/{theme}/{name}'
                    snap[k] = pg.evaluate(COLLECT)
                    if base and k in base and base[k] != snap[k]:
                        diff = [e for e in snap[k] if base[k].get(e) != snap[k][e]]
                        print(f'DIFF {k}: {len(diff)} elements, e.g. {diff[:4]}')
            ctx.close()
    json.dump(snap, open(out, 'w'))
    n = sum(len(v) for v in snap.values())
    print(f'{len(snap)} states, {n} element snapshots, errors: {errors[:5]}')
    if base:
        bad = [k for k in snap if base.get(k) != snap[k]] + [k for k in base if k not in snap]
        print('IDENTICAL' if not bad else f'CHANGED in {len(bad)} states')
