"""
Register arithmetic helpers (absolute cells, emitter cursor known).
Standard verified BF idioms. Proven in test_regops.py.

8-bit wrapping cells. Scratch cells named 'tmp*' must be 0 before each call
and are left 0 after.
"""

def r_set(e, a, v):
    e.set_at(a, v); return e

def r_zero(e, a):
    e.set_at(a, 0); return e

def r_add_const(e, a, v):
    e.add_at(a, v); return e

def r_sub_const(e, a, v):
    e.goto(a); e.sub(v); return e

def r_move(e, src, dst):
    """dst += src; src -> 0."""
    e.goto(src)
    e.emit('[-')
    e.goto(dst); e.emit('+')
    e.goto(src); e.emit(']')
    e.cursor = src
    return e

def r_copy(e, src, dst, tmp):
    """dst = src (src preserved). dst cleared first. tmp 0 before/after."""
    e.set_at(dst, 0)
    e.set_at(tmp, 0)
    e.goto(src)
    e.emit('[-')
    e.goto(dst); e.emit('+')
    e.goto(tmp); e.emit('+')
    e.goto(src); e.emit(']')
    e.cursor = src
    e.goto(tmp)
    e.emit('[-')
    e.goto(src); e.emit('+')
    e.goto(tmp); e.emit(']')
    e.cursor = tmp
    return e

def r_if_setflag(e, cond, flag, tmp1, tmp2):
    """
    if cond != 0: flag = 1   (flag unchanged if cond == 0)
    cond preserved. tmp1, tmp2 are scratch (0 before/after), distinct from all.
    Method: tmp1 = copy(cond) using tmp2 as scratch; then consume tmp1 in an
    'if': while tmp1: tmp1=0, flag+=... no -- we drain tmp1 fully then set flag.
    Clean if: [ [-] >... ] would loop; instead use the move-into-if pattern:
        copy cond->tmp1 ; then:  tmp1[ flag (clear+set 1) ; tmp1=0 ]
    We zero tmp1 inside the body BEFORE re-test so body runs once.
    """
    r_copy(e, cond, tmp1, tmp2)
    e.goto(tmp1)
    e.emit('[')          # if tmp1 != 0
    e.set_at(flag, 1)    #   flag = 1
    e.set_at(tmp1, 0)    #   tmp1 = 0  -> loop exits after one pass
    e.goto(tmp1)
    e.emit(']')
    e.cursor = tmp1
    return e

def r_eq_const_flag(e, cond, k, flag, tmp1, tmp2):
    """
    if cond == k: flag = 1 (else flag unchanged). cond preserved.
    Implement: t = copy(cond); t -= k; if t==0 -> equal. We need 'if zero'.
    'if zero' = set helper h=1; if t!=0: h=0. then if h: flag=1.
    """
    r_copy(e, cond, tmp1, tmp2)   # tmp1 = cond
    e.goto(tmp1); e.sub(k)        # tmp1 = cond - k  (0 iff equal)
    # tmp2 = 1; if tmp1 != 0 -> tmp2 = 0
    e.set_at(tmp2, 1)
    e.goto(tmp1)
    e.emit('[')
    e.set_at(tmp2, 0)
    e.set_at(tmp1, 0)
    e.goto(tmp1)
    e.emit(']')
    e.cursor = tmp1
    # now tmp2 == 1 iff equal. if tmp2: flag = 1
    e.goto(tmp2)
    e.emit('[')
    e.set_at(flag, 1)
    e.set_at(tmp2, 0)
    e.goto(tmp2)
    e.emit(']')
    e.cursor = tmp2
    return e
