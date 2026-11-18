"""Swap-in CSS checker. On the same live DOM, compare every element's computed style + box
between the page's own CSS and each candidate CSS. Returns {cand_name: [differing state keys]}."""
import sys, os, re, json, datetime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regression as R
from snap import SEED, STATES, COLLECT, VIEWS  # reuse the same screens and collector
from playwright.sync_api import sync_playwright

NOFX = "(()=>{var s=document.getElementById('nofx');if(!s){s=document.createElement('style');s.id='nofx';s.textContent='*,*::before,*::after{transition:none!important;animation:none!important}';document.head.appendChild(s)}})()"
SWAP = "(css)=>{var st=document.querySelector('style:not(#nofx)');if(!window.__orig)window.__orig=st.textContent;st.textContent=css===null?window.__orig:css}"

def verify(html, cands, views=VIEWS, detail=False):
    res = {k: [] for k in cands}; info = {}
    srv, U = R.serve(os.path.dirname(os.path.abspath(html)))
    with sync_playwright() as p:
        b = p.chromium.launch()
        for vn, w, h in views:
            ctx = b.new_context(viewport={'width': w, 'height': h}, reduced_motion='reduce')
            pg = ctx.new_page(); errs = []; pg.on('pageerror', lambda e: errs.append(str(e)))
            pg.clock.set_fixed_time(datetime.datetime(2026, 11, 12, 10, 0))
            R.setup(pg, U + os.path.basename(html)); pg.evaluate(SEED); pg.wait_for_timeout(200); R.clear(pg)
            pg.evaluate(NOFX)
            for theme in ['dark', 'light']:
                for name, js in STATES:
                    pg.evaluate("document.querySelectorAll('.modal.show').forEach(m=>m.classList.remove('show'));DRAFT=null;NTX=null;hideUndo();window.scrollTo(0,0)")
                    pg.evaluate(f"document.documentElement.dataset.theme='{theme}'")
                    pg.evaluate(SWAP, None); pg.evaluate(js); pg.wait_for_timeout(450)
                    if detail: pg.evaluate("window.__detail=true")
                    base = pg.evaluate(COLLECT); key = f'{vn}/{theme}/{name}'
                    for cn, css in cands.items():
                        pg.evaluate(SWAP, css); got = pg.evaluate(COLLECT)
                        if got != base:
                            bad = [e for e in base if base[e] != got.get(e)]
                            res[cn].append(key)
                            if detail and cn not in info:
                                e = bad[0]; A = dict(x.split(':', 1) for x in base[e].split('|R:')[0].split('|B:')[0].split(';') if ':' in x)
                                B = dict(x.split(':', 1) for x in got[e].split('|R:')[0].split('|B:')[0].split(';') if ':' in x)
                                info[cn] = (key, e, {k: (A.get(k), B.get(k)) for k in set(A) | set(B) if A.get(k) != B.get(k)}, base[e][base[e].find('|R:'):], got[e][got[e].find('|R:'):])
                    pg.evaluate(SWAP, None)
            if errs: print('page errors', vn, errs[:2])
            ctx.close()
    return res, info
