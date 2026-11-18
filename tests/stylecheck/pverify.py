"""Run verify.verify for each screen size in its own process."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from multiprocessing import Pool
import verify
from snap import VIEWS

def _one(a):
    html, cands, view, detail = a
    return verify.verify(html, cands, [view], detail)

def pverify(html, cands, detail=False):
    with Pool(len(VIEWS)) as p:
        outs = p.map(_one, [(html, cands, v, detail) for v in VIEWS])
    res = {k: [] for k in cands}; info = {}
    for r, i in outs:
        for k in r: res[k] += r[k]
        for k in i: info.setdefault(k, i[k])
    return res, info
