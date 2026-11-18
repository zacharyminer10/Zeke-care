"""Tiny CSS parser/serializer for index.html's single <style> block.
Nodes: {'t':'c','v':text} comment | {'t':'r','sel':..,'d':[(prop,val,imp)]} rule
       {'t':'a','pre':'@media ...','kids':[...]} grouping at-rule | {'t':'raw','v':text} opaque (@keyframes, @font-face)
"""
import re

def _skip_str(s, i):
    q = s[i]; i += 1
    while i < len(s) and s[i] != q:
        i += 2 if s[i] == '\\' else 1
    return i + 1

def _block_end(s, i):  # s[i] == '{' -> index after matching '}'
    d = 0
    while i < len(s):
        c = s[i]
        if c in '"\'': i = _skip_str(s, i); continue
        if s.startswith('/*', i): i = s.index('*/', i) + 2; continue
        if c == '{': d += 1
        elif c == '}':
            d -= 1
            if d == 0: return i + 1
        i += 1
    raise ValueError('unbalanced')

def decls(body):
    out, cur, i = [], '', 0
    parts = []
    while i < len(body):
        c = body[i]
        if c in '"\'':
            j = _skip_str(body, i); cur += body[i:j]; i = j; continue
        if c == '(':
            d = 0; j = i
            while j < len(body):
                if body[j] == '(': d += 1
                elif body[j] == ')':
                    d -= 1
                    if d == 0: break
                j += 1
            cur += body[i:j + 1]; i = j + 1; continue
        if c == ';': parts.append(cur); cur = ''; i += 1; continue
        cur += c; i += 1
    parts.append(cur)
    for p in parts:
        p = p.strip()
        if not p: continue
        k, v = p.split(':', 1)
        v = v.strip(); imp = False
        if re.search(r'!\s*important$', v): imp = True; v = re.sub(r'\s*!\s*important$', '', v)
        out.append([k.strip(), v, imp])
    return out

def parse(s):
    nodes, i = [], 0
    while i < len(s):
        if s[i].isspace(): i += 1; continue
        if s.startswith('/*', i):
            j = s.index('*/', i) + 2; nodes.append({'t': 'c', 'v': s[i:j]}); i = j; continue
        j = s.index('{', i)
        pre = s[i:j].strip(); e = _block_end(s, j)
        if pre.startswith('@media') or pre.startswith('@supports'):
            nodes.append({'t': 'a', 'pre': pre, 'kids': parse(s[j + 1:e - 1])})
        elif pre.startswith('@'):
            nodes.append({'t': 'raw', 'v': s[i:e]})
        else:
            nodes.append({'t': 'r', 'sel': pre, 'd': decls(s[j + 1:e - 1])})
        i = e
    return nodes

def ser_decls(d):
    return ';'.join(k + ':' + v + ('!important' if imp else '') for k, v, imp in d)

def ser(nodes, ind=''):
    out = []
    for n in nodes:
        if n['t'] == 'c': out.append(ind + n['v'])
        elif n['t'] == 'raw': out.append(ind + n['v'])
        elif n['t'] == 'r':
            if n['d']: out.append(ind + n['sel'] + '{' + ser_decls(n['d']) + '}')
        else:
            inner = ser(n['kids'], ind + '  ')
            if inner.strip(): out.append(ind + n['pre'] + '{\n' + inner + '\n' + ind + '}')
    return '\n'.join(out)

def walk(nodes, ctx=()):
    """yield (ctx, node) for every rule, ctx = tuple of enclosing @media preludes"""
    for n in nodes:
        if n['t'] == 'r': yield ctx, n
        elif n['t'] == 'a': yield from walk(n['kids'], ctx + (n['pre'],))

def norm_sel(sel):
    return ','.join(re.sub(r'\s+', ' ', x.strip()) for x in sel.split(','))
