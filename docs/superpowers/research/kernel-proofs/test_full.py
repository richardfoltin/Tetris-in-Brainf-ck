"""
Exhaustive proof:
  * 4x4 collision scan at EVERY anchor (all 200 well positions) over THREE wells:
      W_EMPTY  : all logical 0 (biased all 1) -- classic empty-cell failure mode
      W_FULL   : all logical 1..7
      W_MIX    : crafted mix incl. large empty zones
  * can_move (L/R/Down) at every anchor over the same wells.
  * assert: collision/blocked result correct, pointer returns HOME, well
    UNCHANGED, and the compiler cursor resynced to a KNOWN absolute cell.
"""
from bfinterp import run_bf
from emitter import Emitter, HOME, WELL_BASE, WELL_W, WELL_H, WELL_N
import macros


def biased_tape(well):
    t = [0] * 4096
    for i, v in enumerate(well):
        t[WELL_BASE + i] = (v + 1) & 0xFF
    return t


def exp_collision(well, ax, ay):
    for dy in range(4):
        for dx in range(4):
            tx, ty = ax + dx, ay + dy
            if not (0 <= tx < WELL_W and 0 <= ty < WELL_H):
                return 1
            if well[ty * WELL_W + tx] != 0:
                return 1
    return 0


def exp_blocked(well, ax, ay, dx, dy):
    tx, ty = ax + dx, ay + dy
    if not (0 <= tx < WELL_W and 0 <= ty < WELL_H):
        return 1
    return 1 if well[ty * WELL_W + tx] != 0 else 0


def wells():
    w_empty = [0] * WELL_N
    w_full = [(i % 7) + 1 for i in range(WELL_N)]
    w_mix = [0] * WELL_N
    for x in range(WELL_W):
        w_mix[19 * WELL_W + x] = (x % 7) + 1
    for x in range(0, WELL_W, 2):
        w_mix[18 * WELL_W + x] = 4
    w_mix[2 * WELL_W + 2] = 3
    w_mix[5 * WELL_W + 9] = 2
    # big empty zone rows 6..14 entirely empty (classic failure region)
    return {"EMPTY": w_empty, "FULL": w_full, "MIX": w_mix}


def emit_and_run_collision(well_tape, ax, ay):
    e = Emitter()
    e.goto(WELL_BASE + ay * WELL_W + ax)   # cursor starts at HOME(0); move to anchor
    macros.peek_collision_4x4(e, ax, ay, result_abs=HOME)
    # CURSOR RESYNC CHECK: after the op the compiler cursor MUST be a known
    # absolute cell. peek leaves cursor at result_abs (HOME).
    assert e.cursor == HOME, f"cursor not resynced: {e.cursor}"
    e.emit('.')  # print HOME (result)
    tape, ptr, out, steps = run_bf(e.code_str(), init_tape=well_tape)
    return out[0], ptr, tape, steps


def emit_and_run_move(well_tape, ax, ay, dx, dy):
    e = Emitter()
    e.goto(WELL_BASE + ay * WELL_W + ax)
    macros.can_move(e, ax, ay, dx, dy, result_abs=HOME)
    assert e.cursor == HOME, f"cursor not resynced: {e.cursor}"
    e.emit('.')
    tape, ptr, out, steps = run_bf(e.code_str(), init_tape=well_tape)
    return out[0], ptr, tape, steps


def main():
    ws = wells()
    grand_worst_scan = 0
    grand_worst_move = 0
    n_scan = 0
    n_move = 0
    fails = 0

    for name, well in ws.items():
        base = biased_tape(well)
        orig_well = [base[WELL_BASE + i] for i in range(WELL_N)]
        # ---- collision scan at EVERY anchor ----
        for ay in range(WELL_H):
            for ax in range(WELL_W):
                got, ptr, tape, steps = emit_and_run_collision(list(base), ax, ay)
                exp = exp_collision(well, ax, ay)
                wok = [tape[WELL_BASE + i] for i in range(WELL_N)] == orig_well
                ok = (got == exp) and (ptr == HOME) and wok
                if not ok:
                    fails += 1
                    print(f"FAIL scan well={name} a=({ax},{ay}) "
                          f"exp={exp} got={got} ptr={ptr} well_ok={wok}")
                grand_worst_scan = max(grand_worst_scan, steps)
                n_scan += 1
        # ---- can_move L/R/Down at EVERY anchor ----
        for ay in range(WELL_H):
            for ax in range(WELL_W):
                for (dx, dy) in [(-1, 0), (1, 0), (0, 1)]:
                    got, ptr, tape, steps = emit_and_run_move(list(base), ax, ay, dx, dy)
                    exp = exp_blocked(well, ax, ay, dx, dy)
                    wok = [tape[WELL_BASE + i] for i in range(WELL_N)] == orig_well
                    ok = (got == exp) and (ptr == HOME) and wok
                    if not ok:
                        fails += 1
                        print(f"FAIL move well={name} a=({ax},{ay}) d=({dx},{dy}) "
                              f"exp={exp} got={got} ptr={ptr} well_ok={wok}")
                    grand_worst_move = max(grand_worst_move, steps)
                    n_move += 1
        print(f"well={name:5s}: scan {WELL_N} anchors OK, move {WELL_N*3} cases OK")

    print()
    print(f"TOTAL scan runs: {n_scan}   move runs: {n_move}   FAILS: {fails}")
    print(f"WORST STEPS  4x4-scan={grand_worst_scan}   can_move={grand_worst_move}")
    if fails == 0:
        print("ALL EXHAUSTIVE ASSERTIONS PASSED "
              "(every anchor, empty+full+mixed wells, ptr home, well intact, cursor resynced).")
    else:
        print("THERE WERE FAILURES")
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() == 0 else 1)
