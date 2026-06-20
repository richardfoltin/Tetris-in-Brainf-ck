"""
Master proof for subsystems B, C, D, E. Executes real BF; asserts expected vs
got with pass/fail and step counts.
"""
from bf import run_bf, Emitter
from layout import (W, H, WELL_CELLS, WELL_BASE, LEFT_SENT, RIGHT_SENT, cell,
                    EMPTY, ACTIVE, ANCHOR, LOCKED)
from shapes import footprint, occupied_cells, PIECE_NAMES
import tetris as T

PASS = []

def check(name, cond, detail=""):
    PASS.append(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")

def piece_cells_in_tape(tape):
    return sorted(i - WELL_BASE for i in range(WELL_BASE, RIGHT_SENT)
                  if tape[i] in (ACTIVE, ANCHOR))

def anchor_in_tape(tape):
    for i in range(WELL_BASE, RIGHT_SENT):
        if tape[i] == ANCHOR:
            return i
    return None

def read_sh(tape, na):
    """read the (unbiased) shadow px,py,rot at anchor abs 'na'."""
    return (tape[na + T.SH_PX] - T.SH_BIAS,
            tape[na + T.SH_PY] - T.SH_BIAS,
            tape[na + T.SH_ROT] - T.SH_BIAS)

def run_move(piece, rot, px, py, nrot, mdx, mdy, locked=None):
    init = T.make_well_with_piece(piece, rot, px, py, locked)
    e = Emitter(); e.goto(LEFT_SENT)
    T.emit_try_move(e, piece, rot, nrot, mdx, mdy)
    tape, ptr, out, steps = run_bf(e.code(), init_tape=init)
    return tape, ptr, steps

def well_has_no_internal_zero_breaking_resync(tape, anchor_abs):
    """resync walks LEFT from anchor; ensure no zero between LEFT_SENT and anchor."""
    for i in range(LEFT_SENT + 1, anchor_abs + 1):
        if tape[i] == 0:
            return False
    return True


def test_C_moves():
    print("\n=== C) CONDITIONAL MOVE (allowed) ===")
    cases = [
        # piece, rot, px, py, nrot, mdx, mdy, label
        (2, 0, 5, 5, 0, 0, 1, "O down"),
        (2, 0, 5, 5, 0, 1, 0, "O right"),
        (2, 0, 5, 5, 0, -1, 0, "O left"),
        (1, 0, 3, 2, 0, 0, 1, "I horiz down"),
        (1, 0, 3, 2, 1, 0, 0, "I rotate to vertical"),
        (3, 0, 8, 4, 0, 0, 1, "T down"),
        (6, 0, 2, 10, 0, 1, 0, "J right"),
        (7, 0, 14, 6, 0, 0, 1, "L down"),
    ]
    total = 0
    for (piece, rot, px, py, nrot, mdx, mdy, label) in cases:
        tape, ptr, steps = run_move(piece, rot, px, py, nrot, mdx, mdy)
        total += steps
        npx, npy = px + mdx, py + mdy
        exp = sorted(T.cell(x, y) - WELL_BASE for (x, y) in occupied_cells(piece, nrot, npx, npy))
        got = piece_cells_in_tape(tape)
        na = cell(npx, npy)
        sh = read_sh(tape, na)
        ok = (got == exp and tape[na] == ANCHOR and sh == (npx, npy, nrot)
              and ptr == LEFT_SENT and len(got) == 4)
        check(f"{PIECE_NAMES[piece]} {label}", ok,
              f"footprint {'ok' if got==exp else f'{got}!={exp}'} shadow={sh} steps={steps}")
    print(f"  C allowed-moves avg steps: {total // len(cases)}")


def test_B_blocked():
    print("\n=== B) COLLISION (blocked moves: walls/floor + locked) ===")
    cases = [
        # O at left edge moving left -> wall blocked
        (2, 0, 0, 5, 0, -1, 0, None, "O left into wall"),
        # O at right edge (px=18 so cells 18,19) moving right -> wall
        (2, 0, 18, 5, 0, 1, 0, None, "O right into wall"),
        # O at bottom (py=38 -> cells 38,39) moving down -> floor
        (2, 0, 5, 38, 0, 0, 1, None, "O down into floor"),
        # O down into a LOCKED cell directly below
        (2, 0, 5, 5, 0, 0, 1, [(5, 7, 3), (6, 7, 3)], "O down into locked"),
        # O right into a locked cell
        (2, 0, 5, 5, 0, 1, 0, [(7, 5, 4), (7, 6, 4)], "O right into locked"),
    ]
    for (piece, rot, px, py, nrot, mdx, mdy, locked, label) in cases:
        tape, ptr, steps = run_move(piece, rot, px, py, nrot, mdx, mdy, locked)
        # blocked => piece UNCHANGED at (px,py)
        exp = sorted(T.cell(x, y) - WELL_BASE for (x, y) in occupied_cells(piece, rot, px, py))
        got = piece_cells_in_tape(tape)
        na = cell(px, py)
        sh = read_sh(tape, na)
        ok = (got == exp and tape[na] == ANCHOR and sh == (px, py, rot)
              and ptr == LEFT_SENT)
        check(f"{PIECE_NAMES[piece]} {label} (stays put)", ok,
              f"{'unchanged' if got==exp else f'{got}!={exp}'} shadow={sh} steps={steps}")


def test_D_lock_spawn():
    print("\n=== D) LOCK & SPAWN ===")
    # Active O at bottom; a down-move collides with floor -> lock+spawn.
    piece, rot, px, py = 2, 0, 5, 38     # O occupies rows 38,39 (floor)
    new_piece, sx, sy = 3, 8, 0          # spawn T at top middle
    init = T.make_well_with_piece(piece, rot, px, py)
    e = Emitter(); e.goto(LEFT_SENT)
    T.emit_lock_and_spawn(e, piece, rot, new_piece, sx, sy)
    tape, ptr, out, steps = run_bf(e.code(), init_tape=init)
    # old piece cells now LOCKED(piece)
    locked_ok = all(tape[cell(x, y)] == LOCKED(piece)
                    for (x, y) in occupied_cells(piece, rot, px, py))
    # new piece markers at spawn
    new_cells = occupied_cells(new_piece, 0, sx, sy)
    spawn_ok = (tape[cell(sx, sy)] == ANCHOR and
                all(tape[cell(x, y)] in (ACTIVE, ANCHOR) for (x, y) in new_cells))
    na = cell(sx, sy)
    sh = read_sh(tape, na)
    nm = sum(1 for i in range(WELL_CELLS) if tape[WELL_BASE + i] in (ACTIVE, ANCHOR))
    check("old piece locked to id", locked_ok)
    check("new piece spawned at top", spawn_ok, f"shadow={sh}")
    check("exactly 4 active markers after spawn", nm == 4, f"got {nm}")
    check("shadow reset to spawn pose", sh == (sx, sy, 0))
    check("ptr resynced to LEFT_SENT", ptr == LEFT_SENT)
    print(f"  D lock+spawn steps: {steps}")


def test_E_cycle():
    print("\n=== E) RESYNC + MULTI-FRAME CYCLE (>= 2 frames) ===")
    # Frame loop: O spawned at (5,3). 3 down moves then a lock+spawn, then move
    # the spawned piece. Run as ONE program (the well IS the tape across frames).
    e = Emitter(); e.goto(LEFT_SENT)
    # frame 1: down
    T.emit_try_move(e, 2, 0, 0, 0, 1)       # (5,3)->(5,4)
    # frame 2: down
    T.emit_try_move(e, 2, 0, 0, 0, 1)       # (5,4)->(5,5)
    # frame 3: right
    T.emit_try_move(e, 2, 0, 0, 1, 0)       # (5,5)->(6,5)
    init = T.make_well_with_piece(2, 0, 5, 3)
    tape, ptr, out, steps = run_bf(e.code(), init_tape=init)
    na = cell(6, 5)
    sh = read_sh(tape, na)
    nm = sum(1 for i in range(WELL_CELLS) if tape[WELL_BASE + i] in (ACTIVE, ANCHOR))
    resync_ok = well_has_no_internal_zero_breaking_resync(tape, na)
    check("3 frames: anchor at (6,5)", tape[na] == ANCHOR, f"shadow={sh}")
    check("3 frames: shadow consistent", sh == (6, 5, 0))
    check("3 frames: exactly 4 markers", nm == 4, f"got {nm}")
    check("3 frames: ptr resynced to LEFT_SENT", ptr == LEFT_SENT)
    check("resync path has no false zero-sentinel", resync_ok)
    print(f"  E 3-frame cycle steps: {steps} (~{steps//3}/frame)")


def main():
    test_C_moves()
    test_B_blocked()
    test_D_lock_spawn()
    test_E_cycle()
    print("\n================ SUMMARY ================")
    print(f"  {sum(PASS)}/{len(PASS)} checks PASS")
    allok = all(PASS)
    print("  RESULT:", "ALL PASS" if allok else "FAILURES PRESENT")
    return allok

if __name__ == '__main__':
    import sys
    sys.exit(0 if main() else 1)
