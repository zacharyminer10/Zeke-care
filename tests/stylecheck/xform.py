"""CSS clean-up transforms on cssx trees."""
import copy, re, cssx

FALLBACK = ('color-mix(', 'dvh', 'svh', 'lvh', 'env(', 'clamp(', 'min(', 'max(', '-webkit-', ':has(')

def rules_in_order(tree):
    return list(cssx.walk(tree))

def drop_dead(tree):
    """Remove declarations always overridden later by the same selector+property.
    Safe because a later declaration with identical selector (same specificity) and
    equal-or-stronger importance wins for every element, in the same or a wider
    media context. Keeps progressive-enhancement fallbacks."""
    t = copy.deepcopy(tree); rs = rules_in_order(t); n = 0
    for i, (ctx, r) in enumerate(rs):
        S = cssx.norm_sel(r['sel']); keep = []
        for di, (p, v, imp) in enumerate(r['d']):
            dead = False
            later_same = [(p2, v2, i2) for (p2, v2, i2) in r['d'][di + 1:] if p2 == p]
            later = later_same[:]
            for ctx2, r2 in rs[i + 1:]:
                if cssx.norm_sel(r2['sel']) == S and (ctx2 == ctx or ctx2 == ()):
                    later += [(p2, v2, i2) for (p2, v2, i2) in r2['d'] if p2 == p]
            for p2, v2, i2 in later:
                if (i2 or not imp) and (v2 == v or not any(f in v2 for f in FALLBACK)) and not p.startswith('-webkit-'):
                    dead = True; break
            if dead: n += 1
            else: keep.append([p, v, imp])
        r['d'] = keep
    return t, n

def merge_groups(tree):
    """list of (ctx, normsel) keys that occur in more than one rule"""
    seen = {}
    for ctx, r in rules_in_order(tree):
        seen.setdefault((ctx, cssx.norm_sel(r['sel'])), []).append(r)
    return [k for k, v in seen.items() if len([x for x in v if x['d']]) > 1]

def merge(tree, keys, into='first'):
    """Fold all rules with the same (ctx, selector) into the first (or last) one.
    Later declarations override earlier ones property by property."""
    t = copy.deepcopy(tree); keys = set(keys); groups = {}
    for ctx, r in rules_in_order(t):
        k = (ctx, cssx.norm_sel(r['sel']))
        if k in keys and r['d']: groups.setdefault(k, []).append(r)
    for k, rs in groups.items():
        final = []  # ordered: property keeps first-seen position, takes last value
        for r in rs:
            for p, v, imp in r['d']:
                hit = [d for d in final if d[0] == p]
                if hit and any(f in v for f in FALLBACK) and hit[-1][1] != v:
                    final.append([p, v, imp]); continue  # keep fallback pair, later one after
                if hit:
                    old = hit[-1]
                    if old[2] and not imp: continue
                    old[1], old[2] = v, imp
                else: final.append([p, v, imp])
        tgt = rs[0] if into == 'first' else rs[-1]
        for r in rs: r['d'] = []
        tgt['d'] = final
    return t

def important_list(tree):
    return [(i, di) for i, (ctx, r) in enumerate(rules_in_order(tree)) for di, d in enumerate(r['d']) if d[2]]

def unimportant(tree, which):
    t = copy.deepcopy(tree); rs = rules_in_order(t)
    for i, di in which: rs[i][1]['d'][di][2] = False
    return t
