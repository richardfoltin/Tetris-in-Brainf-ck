"""Prove register ops: move, copy, if-setflag, eq-const-flag."""
from bf import run_bf, Emitter
import regops as R

def harness(emit_fn, init):
    e = Emitter()
    emit_fn(e)
    tape, ptr, out, steps = run_bf(e.code(), init_tape=init)
    return tape, steps

def main():
    ok = True
    print("=== REGOPS PROOFS ===")

    # r_move: dst += src, src->0
    def f(e): R.r_move(e, 0, 1)
    t, s = harness(f, {0: 7, 1: 3})
    c = (t[0] == 0 and t[1] == 10)
    ok &= c; print(f"r_move 7->(+3): dst={t[1]} src={t[0]} {'PASS' if c else 'FAIL'}")

    # r_copy: dst=src, src preserved, tmp 0
    def f(e): R.r_copy(e, 0, 1, 2)
    t, s = harness(f, {0: 42, 1: 99, 2: 0})
    c = (t[0] == 42 and t[1] == 42 and t[2] == 0)
    ok &= c; print(f"r_copy 42: src={t[0]} dst={t[1]} tmp={t[2]} {'PASS' if c else 'FAIL'}")

    # r_if_setflag: cond nonzero -> flag=1
    def f(e):
        R.r_set(e, 3, 0)            # flag preset 0
        R.r_if_setflag(e, 0, 3, 1, 2)
    t, s = harness(f, {0: 5})
    c = (t[3] == 1 and t[0] == 5 and t[1] == 0 and t[2] == 0)
    ok &= c; print(f"if_setflag(cond=5): flag={t[3]} cond={t[0]} {'PASS' if c else 'FAIL'}")

    # r_if_setflag: cond zero -> flag unchanged
    def f(e):
        R.r_set(e, 3, 0)
        R.r_if_setflag(e, 0, 3, 1, 2)
    t, s = harness(f, {0: 0})
    c = (t[3] == 0)
    ok &= c; print(f"if_setflag(cond=0): flag={t[3]} {'PASS' if c else 'FAIL'}")

    # r_eq_const_flag: equal
    def f(e):
        R.r_set(e, 3, 0)
        R.r_eq_const_flag(e, 0, 19, 3, 1, 2)
    t, s = harness(f, {0: 19})
    c = (t[3] == 1 and t[0] == 19 and t[1] == 0 and t[2] == 0)
    ok &= c; print(f"eq_const(19==19): flag={t[3]} cond={t[0]} {'PASS' if c else 'FAIL'}")

    # r_eq_const_flag: not equal
    def f(e):
        R.r_set(e, 3, 0)
        R.r_eq_const_flag(e, 0, 19, 3, 1, 2)
    t, s = harness(f, {0: 18})
    c = (t[3] == 0 and t[0] == 18)
    ok &= c; print(f"eq_const(18==19): flag={t[3]} cond={t[0]} {'PASS' if c else 'FAIL'}")

    # eq at 0 boundary
    def f(e):
        R.r_set(e, 3, 0)
        R.r_eq_const_flag(e, 0, 0, 3, 1, 2)
    t, s = harness(f, {0: 0})
    c = (t[3] == 1)
    ok &= c; print(f"eq_const(0==0): flag={t[3]} {'PASS' if c else 'FAIL'}")

    print("REGOPS:", "ALL PASS" if ok else "FAIL")
    return ok

if __name__ == '__main__':
    import sys
    sys.exit(0 if main() else 1)
