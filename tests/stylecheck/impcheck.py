"""For each candidate (a full CSS text + the selector whose rule changed), compare the full computed
style of only the elements that selector matches (and their ::before/::after), on every screen."""
import os, sys, re, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import regression as R
from snap import SEED, STATES, VIEWS
from verify import NOFX, SWAP
from multiprocessing import Pool
from playwright.sync_api import sync_playwright
PICK = r"""(sel)=>{function sty(el,ps){var cs=getComputedStyle(el,ps),a=[];for(var i=0;i<cs.length;i++){var k=cs[i];if(k.indexOf('--')===0)continue;a.push(k+':'+cs.getPropertyValue(k))}return a.join(';')}
var s=sel.replace(/::?(before|after)\b/g,'').replace(/:(hover|active|focus|focus-visible|focus-within|disabled|checked|first-child|last-child|not\([^)]*\))/g,'');var o=[];
try{document.querySelectorAll(s).forEach(function(el,i){var r=el.getBoundingClientRect();o.push(sty(el)+'|'+sty(el,'::before')+'|'+sty(el,'::after')+'|'+[r.x,r.y,r.width,r.height].map(Math.round))})}catch(e){return 'BADSEL '+s}
return o.join('\n')}"""
def one(a):
    html, cands, (vn, w, h) = a; bad = {k: [] for k in cands}
    srv, U = R.serve(os.path.dirname(os.path.abspath(html)))
    with sync_playwright() as p:
        b = p.chromium.launch(); ctx = b.new_context(viewport={'width': w, 'height': h}, reduced_motion='reduce'); pg = ctx.new_page()
        pg.clock.set_fixed_time(datetime.datetime(2026, 11, 12, 10, 0))
        R.setup(pg, U + os.path.basename(html)); pg.evaluate(SEED); pg.wait_for_timeout(200); R.clear(pg); pg.evaluate(NOFX)
        for theme in ['dark', 'light']:
            for name, js in STATES:
                pg.evaluate("document.querySelectorAll('.modal.show').forEach(m=>m.classList.remove('show'));DRAFT=null;NTX=null;hideUndo();window.scrollTo(0,0)")
                pg.evaluate(f"document.documentElement.dataset.theme='{theme}'"); pg.evaluate(SWAP, None); pg.evaluate(js); pg.wait_for_timeout(450)
                for k, (css, sel) in cands.items():
                    base = pg.evaluate(PICK, sel); pg.evaluate(SWAP, css); got = pg.evaluate(PICK, sel); pg.evaluate(SWAP, None)
                    if got != base or base.startswith('BADSEL'): bad[k].append(f'{vn}/{theme}/{name}' + (' BADSEL' if base.startswith('BADSEL') else ''))
    return bad
def check(html, cands):
    with Pool(3) as p: outs = p.map(one, [(html, cands, v) for v in VIEWS])
    return {k: sum((o[k] for o in outs), []) for k in cands}
