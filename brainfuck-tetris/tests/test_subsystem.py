"""Ports of the verified reference proofs (runtime-subsystem/test_a_scan.py +
test_bcde.py) onto the PROJECT's ported subsystem (src/subsystem.py), driven
through src.oracle.run_bf and asserting the SAME invariants.

Subsystem A : scan-locate lands non-destructively on the unique anchor + resync
Subsystem B : collision correct for walls/floor + locked (blocked => unchanged)
Subsystem C : conditional move updates well markers + shadow + resyncs
Subsystem D : lock + spawn (old -> locked id, new piece at top, shadow reset)
Subsystem E : resync + a >=2-frame cycle (3 frames as one program)

Ground truth is the host-side reference model (occupied_cells / footprint),
matching the reference tests. 23 BCDE checks are reproduced (8 C + 5 B + 5 D +
5 E) plus 6 scan-A cases.
"""

import pytest

from src.dsl import Compiler
from src.oracle import run_bf
from src.game import (
    alloc_memory, cell, W, H, WELL_CELLS, EMPTY, ACTIVE, ANCHOR, LOCKED,
)
import src.subsystem as S


# ----------------------------------------------------------------- helpers
def _fresh():
    c = Compiler()
    alloc_memory(c)
    return c


def _well_base(c):
    return c.addr("well")


def _left_sent(c):
    return c.addr("LEFT_SENT")


def piece_cells_in_tape(c, tape):
    base = _well_base(c)
    return sorted(i - base for i in range(base, base + WELL_CELLS)
                  if tape[i] in (ACTIVE, ANCHOR))


def read_sh(c, tape, na):
    return (tape[na + S.SH_PX] - S.SH_BIAS,
            tape[na + S.SH_PY] - S.SH_BIAS,
            tape[na + S.SH_ROT] - S.SH_BIAS)


def well_no_internal_zero(c, tape, anchor_abs):
    """resync walks LEFT from anchor; no zero may sit between LEFT_SENT+1 and
    the anchor or '[<]' would stop early (false sentinel)."""
    for i in range(_left_sent(c) + 1, anchor_abs + 1):
        if tape[i] == 0:
            return False
    return True


def build_well_with_anchor(c, ax, ay, body_cells):
    t = {}
    base = _well_base(c)
    for i in range(WELL_CELLS):
        t[base + i] = EMPTY
    t[_left_sent(c)] = 0
    t[c.addr("RIGHT_SENT")] = 0
    for (x, y) in body_cells:
        t[cell(c, x, y)] = ACTIVE
    t[cell(c, ax, ay)] = ANCHOR
    return t


def run_move(piece, rot, px, py, nrot, mdx, mdy, locked=None):
    c = _fresh()
    init = S.make_well_with_piece(c, piece, rot, px, py, locked)
    c.goto("LEFT_SENT")
    S.emit_try_move(c, piece, rot, nrot, mdx, mdy)
    tape, ptr, out = run_bf(c.build(), init_tape=init)
    return c, tape, ptr


# =====================================================================
# Subsystem A: SCAN-LOCATE (6 cases)
# =====================================================================
_TAG = 200
_SCAN_CASES = [
    (0, 0,  [(1, 0), (2, 0), (3, 0)]),
    (10, 0, [(9, 0), (11, 0), (10, 1)]),
    (19, 0, [(18, 0), (17, 0), (16, 0)]),
    (5, 20, [(5, 19), (5, 21), (6, 20)]),
    (19, 39, [(18, 39), (17, 39), (19, 38)]),
    (0, 39, [(1, 39), (2, 39), (0, 38)]),
]


@pytest.mark.parametrize("ax,ay,body", _SCAN_CASES)
def test_A_scan_locate(ax, ay, body):
    c = _fresh()
    init = build_well_with_anchor(c, ax, ay, body)
    c.goto(_well_base(c))
    S.emit_scan_to_anchor(c)
    c.emit("[-]")
    c.emit("+" * _TAG)            # tag the cell we landed on
    S.emit_resync_to_left_sentinel(c)
    tape, ptr, out = run_bf(c.build(), init_tape=init)

    anchor_cell = cell(c, ax, ay)
    # 1) landed exactly on the anchor
    assert tape[anchor_cell] == _TAG, "did not land on anchor (%d,%d)" % (ax, ay)
    # 2) non-destructive on every other well cell
    for x in range(W):
        for y in range(H):
            cc = cell(c, x, y)
            if cc == anchor_cell:
                continue
            exp = ACTIVE if (x, y) in body else EMPTY
            assert tape[cc] == exp, "destructive at (%d,%d)" % (x, y)
    # 3) pointer resynced to LEFT_SENT, sentinels intact
    assert ptr == _left_sent(c)
    assert tape[_left_sent(c)] == 0
    assert tape[c.addr("RIGHT_SENT")] == 0


# =====================================================================
# Subsystem C: CONDITIONAL MOVE (allowed) -- 8 checks
# =====================================================================
_C_CASES = [
    (2, 0, 5, 5, 0, 0, 1, "O down"),
    (2, 0, 5, 5, 0, 1, 0, "O right"),
    (2, 0, 5, 5, 0, -1, 0, "O left"),
    (1, 0, 3, 2, 0, 0, 1, "I horiz down"),
    (1, 0, 3, 2, 1, 0, 0, "I rotate to vertical"),
    (3, 0, 8, 4, 0, 0, 1, "T down"),
    (6, 0, 2, 10, 0, 1, 0, "J right"),
    (7, 0, 14, 6, 0, 0, 1, "L down"),
]


@pytest.mark.parametrize("piece,rot,px,py,nrot,mdx,mdy,label", _C_CASES)
def test_C_move_allowed(piece, rot, px, py, nrot, mdx, mdy, label):
    c, tape, ptr = run_move(piece, rot, px, py, nrot, mdx, mdy)
    npx, npy = px + mdx, py + mdy
    exp = sorted(cell(c, x, y) - _well_base(c)
                 for (x, y) in S.occupied_cells(piece, nrot, npx, npy))
    got = piece_cells_in_tape(c, tape)
    na = cell(c, npx, npy)
    sh = read_sh(c, tape, na)
    assert got == exp, "%s footprint %r != %r" % (label, got, exp)
    assert tape[na] == ANCHOR, "%s anchor missing" % label
    assert sh == (npx, npy, nrot), "%s shadow %r" % (label, sh)
    assert ptr == _left_sent(c)
    assert len(got) == 4


# =====================================================================
# Subsystem B: COLLISION (blocked moves: walls/floor + locked) -- 5 checks
# =====================================================================
_B_CASES = [
    (2, 0, 0, 5, 0, -1, 0, None, "O left into wall"),
    (2, 0, 18, 5, 0, 1, 0, None, "O right into wall"),
    (2, 0, 5, 38, 0, 0, 1, None, "O down into floor"),
    (2, 0, 5, 5, 0, 0, 1, [(5, 7, 3), (6, 7, 3)], "O down into locked"),
    (2, 0, 5, 5, 0, 1, 0, [(7, 5, 4), (7, 6, 4)], "O right into locked"),
]


@pytest.mark.parametrize("piece,rot,px,py,nrot,mdx,mdy,locked,label", _B_CASES)
def test_B_move_blocked(piece, rot, px, py, nrot, mdx, mdy, locked, label):
    c, tape, ptr = run_move(piece, rot, px, py, nrot, mdx, mdy, locked)
    # blocked => piece UNCHANGED at (px,py)
    exp = sorted(cell(c, x, y) - _well_base(c)
                 for (x, y) in S.occupied_cells(piece, rot, px, py))
    got = piece_cells_in_tape(c, tape)
    na = cell(c, px, py)
    sh = read_sh(c, tape, na)
    assert got == exp, "%s should stay put: %r != %r" % (label, got, exp)
    assert tape[na] == ANCHOR, "%s anchor moved" % label
    assert sh == (px, py, rot), "%s shadow changed %r" % (label, sh)
    assert ptr == _left_sent(c)


# =====================================================================
# Subsystem D: LOCK & SPAWN -- 5 checks
# =====================================================================
def test_D_lock_and_spawn():
    c = _fresh()
    piece, rot, px, py = 2, 0, 5, 38      # O occupies rows 38,39 (floor)
    new_piece, sx, sy = 3, 8, 0           # spawn T at top middle
    init = S.make_well_with_piece(c, piece, rot, px, py)
    c.goto("LEFT_SENT")
    S.emit_lock_and_spawn(c, piece, rot, new_piece, sx, sy)
    tape, ptr, out = run_bf(c.build(), init_tape=init)

    locked_ok = all(tape[cell(c, x, y)] == LOCKED(piece)
                    for (x, y) in S.occupied_cells(piece, rot, px, py))
    new_cells = S.occupied_cells(new_piece, 0, sx, sy)
    spawn_ok = (tape[cell(c, sx, sy)] == ANCHOR and
                all(tape[cell(c, x, y)] in (ACTIVE, ANCHOR) for (x, y) in new_cells))
    na = cell(c, sx, sy)
    sh = read_sh(c, tape, na)
    base = _well_base(c)
    nm = sum(1 for i in range(WELL_CELLS) if tape[base + i] in (ACTIVE, ANCHOR))

    assert locked_ok, "old piece not locked to id"
    assert spawn_ok, "new piece not spawned at top"
    assert nm == 4, "expected exactly 4 active markers, got %d" % nm
    assert sh == (sx, sy, 0), "shadow not reset to spawn pose: %r" % (sh,)
    assert ptr == _left_sent(c), "ptr not resynced to LEFT_SENT"


# =====================================================================
# Subsystem E: RESYNC + MULTI-FRAME CYCLE (>= 2 frames) -- 5 checks
# =====================================================================
def test_E_multiframe_cycle():
    c = _fresh()
    c.goto("LEFT_SENT")
    # frame 1: down (5,3)->(5,4)
    S.emit_try_move(c, 2, 0, 0, 0, 1)
    # frame 2: down (5,4)->(5,5)
    S.emit_try_move(c, 2, 0, 0, 0, 1)
    # frame 3: right (5,5)->(6,5)
    S.emit_try_move(c, 2, 0, 0, 1, 0)
    init = S.make_well_with_piece(c, 2, 0, 5, 3)
    tape, ptr, out = run_bf(c.build(), init_tape=init)

    na = cell(c, 6, 5)
    sh = read_sh(c, tape, na)
    base = _well_base(c)
    nm = sum(1 for i in range(WELL_CELLS) if tape[base + i] in (ACTIVE, ANCHOR))

    assert tape[na] == ANCHOR, "anchor not at (6,5): shadow=%r" % (sh,)
    assert sh == (6, 5, 0), "shadow inconsistent after 3 frames: %r" % (sh,)
    assert nm == 4, "expected exactly 4 markers, got %d" % nm
    assert ptr == _left_sent(c), "ptr not resynced to LEFT_SENT"
    assert well_no_internal_zero(c, tape, na), "resync path has a false zero"


# =====================================================================
# Sanity: the ported shape table matches the reference geometry contract.
# =====================================================================
def test_footprint_anchor_is_origin():
    for piece in range(1, 8):
        for rot in range(4):
            rel = S.footprint(piece, rot)
            assert rel[0] == (0, 0), "anchor must be origin for %d/%d" % (piece, rot)
            assert len(rel) == 4
