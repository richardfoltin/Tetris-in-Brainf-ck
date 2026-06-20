"""
Drive: emit BF for can_move and 4x4 collision peeks at many anchors over a
crafted well (with EMPTY cells), run on real interpreter, assert vs reference.
"""
from bfinterp import run_bf
from emitter import Emitter, HOME, WELL_BASE, WELL_W, WELL_H, WELL_N
import macros


def make_tape_from_well(well_logical):
    tape = [0] * 4096
    for i, v in enumerate(well_logical):
        tape[WELL_BASE + i] = (v + 1) & 0xFF   # +1 bias
    return tape


def expected_collision_4x4(well, ax, ay):
    res = 0
    for dy in range(4):
        for dx in range(4):
            tx, ty = ax + dx, ay + dy
            if tx < 0 or tx >= WELL_W or ty < 0 or ty >= WELL_H:
                res = 1
            elif well[ty * WELL_W + tx] != 0:
                res = 1
    return res


def expected_can_move_blocked(well, ax, ay, dx, dy):
    tx, ty = ax + dx, ay + dy
    if tx < 0 or tx >= WELL_W or ty < 0 or ty >= WELL_H:
        return 1
    return 1 if well[ty * WELL_W + tx] != 0 else 0


def craft_well():
    """200 logical cells. Mix of empty(0) and ids(1..7), incl. big empty zones
    (classic failure mode) and a full bottom edge / scattered blocks."""
    w = [0] * WELL_N
    # bottom two rows partly filled
    for x in range(WELL_W):
        w[19 * WELL_W + x] = (x % 7) + 1            # row 19 full of ids 1..7
    for x in range(0, WELL_W, 2):
        w[18 * WELL_W + x] = 4                       # row 18 every other cell
    # a scattered block near top-left to test interior collisions
    w[2 * WELL_W + 2] = 3
    w[2 * WELL_W + 5] = 7
    w[5 * WELL_W + 0] = 1
    w[5 * WELL_W + 9] = 2
    # everything else empty (0) -> biased to 1
    return w


def goto_anchor_code(e, ax, ay):
    e.goto(WELL_BASE + ay * WELL_W + ax)


def test_collision():
    well = craft_well()
    init = make_tape_from_well(well)
    # anchors: interior, near right wall, bottom area, top-left corner,
    # and spots whose 4x4 spills out of bounds.
    anchors = [(0, 0), (1, 1), (2, 2), (6, 4), (7, 17), (9, 9),
               (8, 18), (0, 16), (5, 5), (6, 18), (7, 7)]
    total_steps = 0
    worst = 0
    n = 0
    for (ax, ay) in anchors:
        e = Emitter()
        goto_anchor_code(e, ax, ay)
        macros.peek_collision_4x4(e, ax, ay, result_abs=HOME)
        # read result: print HOME cell
        e.goto(HOME)
        e.emit('.')
        code = e.code_str()
        tape, ptr, out, steps = run_bf(code, init_tape=init)
        got = out[0]
        exp = expected_collision_4x4(well, ax, ay)
        ok = (got == exp)
        # pointer must be HOME==0 at end (we did goto HOME then '.')
        ptr_ok = (ptr == HOME)
        # well must be UNCHANGED (non-destructive peek)
        well_after = [tape[WELL_BASE + i] for i in range(WELL_N)]
        well_orig = [init[WELL_BASE + i] for i in range(WELL_N)]
        well_ok = (well_after == well_orig)
        print(f"[4x4] anchor=({ax:>2},{ay:>2}) exp={exp} got={got} "
              f"{'PASS' if ok else 'FAIL'} ptr_ok={ptr_ok} well_unchanged={well_ok} "
              f"steps={steps}")
        assert ok, f"collision mismatch at {(ax,ay)}: exp {exp} got {got}"
        assert ptr_ok, f"pointer not home at {(ax,ay)}: {ptr}"
        assert well_ok, f"well mutated at {(ax,ay)}"
        total_steps += steps
        worst = max(worst, steps)
        n += 1
    print(f"[4x4] ALL PASS  ({n} anchors)  worst_steps={worst} avg={total_steps//n}")
    return worst


def test_can_move():
    well = craft_well()
    init = make_tape_from_well(well)
    cases = [
        # (ax, ay, dx, dy)
        (5, 5, 1, 0),   # right into empty
        (8, 5, 1, 0),   # right at x=8 -> x=9 occupied(id2) ? well[5*10+9]=2 occupied
        (9, 5, 1, 0),   # right OOB
        (0, 5, -1, 0),  # left OOB
        (1, 5, -1, 0),  # left into well[5*10+0]=1 occupied
        (3, 18, 0, 1),  # down into row19 occupied
        (3, 19, 0, 1),  # down OOB (bottom)
        (4, 4, 0, 1),   # down into empty
        (2, 1, 0, 1),   # down into well[2*10+2]=3 occupied
    ]
    worst = 0
    n = 0
    tot = 0
    for (ax, ay, dx, dy) in cases:
        e = Emitter()
        goto_anchor_code(e, ax, ay)
        macros.can_move(e, ax, ay, dx, dy, result_abs=HOME)
        e.goto(HOME); e.emit('.')
        code = e.code_str()
        tape, ptr, out, steps = run_bf(code, init_tape=init)
        got = out[0]
        exp = expected_can_move_blocked(well, ax, ay, dx, dy)
        ok = got == exp
        ptr_ok = ptr == HOME
        well_after = [tape[WELL_BASE + i] for i in range(WELL_N)]
        well_ok = well_after == [init[WELL_BASE + i] for i in range(WELL_N)]
        print(f"[move] a=({ax:>2},{ay:>2}) d=({dx:>2},{dy:>2}) blocked exp={exp} "
              f"got={got} {'PASS' if ok else 'FAIL'} ptr_ok={ptr_ok} "
              f"well_unchanged={well_ok} steps={steps}")
        assert ok and ptr_ok and well_ok
        worst = max(worst, steps); tot += steps; n += 1
    print(f"[move] ALL PASS ({n} cases) worst_steps={worst} avg={tot//n}")
    return worst


if __name__ == "__main__":
    print("=== can_move (relative collision peek) ===")
    w1 = test_can_move()
    print()
    print("=== 4x4 neighborhood collision scan ===")
    w2 = test_collision()
    print()
    print(f"WORST STEPS: can_move={w1}  4x4={w2}")
