#!/usr/bin/env python3
"""Structured-CFG dominator tree over a spirv-dis listing.

handoff/88. Exists because `patch_earglow.clone_chain` has exactly one
strategy -- clone the def chain with fresh ids -- and it dies on any op
outside its whitelist. Two of the twelve rgs_reference_main permutations
build the G-buffer fetch coordinate through OpConvertFToU over an LCG
sample (a jittered/upscaled fetch), which the whitelist refuses, so those
two shipped UNPATCHED. A launch on 2026-09-01 09:16 then dispatched one of
them and the capture read as base -- see 88 sec 1.

Cloning is only ever needed when the value does not already dominate the
splice. This computes that directly (Cooper-Harvey-Kennedy iterative
dominators over the block graph), so a value that is already in scope is
used as-is and the clone is the fallback, not the only path.

spirv-val is the backstop: it enforces SSA dominance, so a wrong answer
here fails the build rather than reaching the screen.
"""
import re

TERMS = ('OpBranch', 'OpBranchConditional', 'OpSwitch', 'OpReturn',
         'OpReturnValue', 'OpKill', 'OpUnreachable', 'OpTerminateRayKHR',
         'OpIgnoreIntersectionKHR')


def blocks(mod, fs, fe):
    """[(label_id, start_line, end_line)] for the function body [fs, fe)."""
    out = []
    cur = None
    for i in range(fs, fe):
        m = re.match(r'\s*(%\w+)\s*=\s*OpLabel\s*$', mod.lines[i])
        if m:
            if cur is not None:
                out.append((cur[0], cur[1], i))
            cur = (m.group(1), i)
    if cur is not None:
        out.append((cur[0], cur[1], fe))
    return out


def succs(mod, s, e):
    """Successor labels of the block spanning [s, e)."""
    for i in range(e - 1, s - 1, -1):
        ln = mod.lines[i].strip()
        if not ln or ln.startswith('%'):
            continue
        op = ln.split()[0]
        if op not in TERMS:
            continue
        ids = re.findall(r'%\w+', ln)
        if op == 'OpBranch':
            return ids[:1]
        if op == 'OpBranchConditional':
            return ids[1:3]
        if op == 'OpSwitch':
            return ids[1:]
        return []
    return []


def dom_tree(mod, fs, fe):
    """(idom, order, block_of_line). idom maps label -> immediate dominator."""
    bl = blocks(mod, fs, fe)
    if not bl:
        return {}, [], (lambda ln: None)
    lab = [b[0] for b in bl]
    span = {b[0]: (b[1], b[2]) for b in bl}
    idx = {l: n for n, l in enumerate(lab)}
    succ = {l: [s for s in succs(mod, *span[l]) if s in idx] for l in lab}
    pred = {l: [] for l in lab}
    for l in lab:
        for s in succ[l]:
            pred[s].append(l)

    # reverse postorder over the reachable graph from the entry block
    order, seen, stack = [], set(), [(lab[0], iter(succ[lab[0]]))]
    seen.add(lab[0])
    while stack:
        node, it = stack[-1]
        nxt = next(it, None)
        if nxt is None:
            order.append(node)
            stack.pop()
        elif nxt not in seen:
            seen.add(nxt)
            stack.append((nxt, iter(succ[nxt])))
    order.reverse()
    rpo = {l: n for n, l in enumerate(order)}

    idom = {lab[0]: lab[0]}

    def isect(a, b):
        while a != b:
            while rpo[a] > rpo[b]:
                a = idom[a]
            while rpo[b] > rpo[a]:
                b = idom[b]
        return a

    changed = True
    while changed:
        changed = False
        for l in order[1:]:
            new = None
            for p in pred[l]:
                if p not in idom or p not in rpo:
                    continue
                new = p if new is None else isect(new, p)
            if new is not None and idom.get(l) != new:
                idom[l] = new
                changed = True

    starts = sorted((span[l][0], l) for l in lab)

    def block_of_line(ln):
        lo, hi, found = 0, len(starts) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            if starts[mid][0] <= ln:
                found = starts[mid][1]
                lo = mid + 1
            else:
                hi = mid - 1
        return found

    return idom, order, block_of_line


def dominates(mod, fs, fe, def_line, use_line, cache={}):
    """True if the instruction at def_line dominates the one at use_line.

    Same block: dominance is textual order. Different blocks: walk the
    idom chain up from the use block. An unreachable use block (absent
    from the dominator forest) answers False -- fail closed, clone instead.
    """
    key = (id(mod), fs, fe)
    if key not in cache:
        cache[key] = dom_tree(mod, fs, fe)
    idom, order, block_of_line = cache[key]
    db, ub = block_of_line(def_line), block_of_line(use_line)
    if db is None or ub is None:
        return False
    if db == ub:
        return def_line < use_line
    seen = 0
    while ub in idom and idom[ub] != ub and seen < 1 << 20:
        ub = idom[ub]
        seen += 1
        if ub == db:
            return True
    return ub == db
