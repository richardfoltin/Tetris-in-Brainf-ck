"""BF Tetris runtime moving-piece subsystem (A-E), ported from the verified
reference (docs/.../runtime-subsystem/{scan,shapes,tetris}.py) onto the
project's goto-emitter Compiler (src/dsl.py) and memory layout (src/game.py).

Semantics are byte-for-byte the reference's; only the address sources change:
    reference WELL_BASE   -> c.addr("well")
    reference LEFT_SENT   -> c.addr("LEFT_SENT")
    reference cell(x,y)   -> cell(c, x, y)
The contiguous 800-cell well + single LEFT_SENT immediately left of it (with all
live well cells >= 1, sentinels == 0) makes the relative-pointer machinery sound:
scan-to-anchor rides the unique ANCHOR=10 cell, every footprint/shadow access is
a compile-time relative peek, and '[<]' resyncs to LEFT_SENT.

POINTER MODEL (unchanged from reference)
  - active piece = 4 markers: 1 ANCHOR(10) + 3 ACTIVE(9); anchor = footprint[0].
  - px,py,rot live in 3 "shadow" well cells at FIXED relative offsets from the
    anchor (SH_PX/SH_PY/SH_ROT), stored BIASED by SH_BIAS so they can never be
    mistaken for a marker (9/10) or a well value (1..8).
  - every collision/move/update is done relative to the riding anchor.
"""

from src.dsl import Compiler
from src.game import (
    W, H, WELL_CELLS, EMPTY, ACTIVE, ANCHOR, LOCKED, cell, make_empty_well,
)

# ---------------------------------------------------------------------------
# Tetromino shapes (offsets relative to the anchor = first listed cell).
# Ported verbatim from shapes.py.
# ---------------------------------------------------------------------------
SHAPES = {
    1: {  # I
        0: [(0, 0), (1, 0), (2, 0), (3, 0)],
        1: [(0, 0), (0, 1), (0, 2), (0, 3)],
        2: [(0, 0), (1, 0), (2, 0), (3, 0)],
        3: [(0, 0), (0, 1), (0, 2), (0, 3)],
    },
    2: {  # O
        0: [(0, 0), (1, 0), (0, 1), (1, 1)],
        1: [(0, 0), (1, 0), (0, 1), (1, 1)],
        2: [(0, 0), (1, 0), (0, 1), (1, 1)],
        3: [(0, 0), (1, 0), (0, 1), (1, 1)],
    },
    3: {  # T
        0: [(0, 0), (1, 0), (2, 0), (1, 1)],
        1: [(1, 0), (0, 1), (1, 1), (1, 2)],
        2: [(1, 0), (0, 1), (1, 1), (2, 1)],
        3: [(0, 0), (0, 1), (1, 1), (0, 2)],
    },
    4: {  # S
        0: [(1, 0), (2, 0), (0, 1), (1, 1)],
        1: [(0, 0), (0, 1), (1, 1), (1, 2)],
        2: [(1, 0), (2, 0), (0, 1), (1, 1)],
        3: [(0, 0), (0, 1), (1, 1), (1, 2)],
    },
    5: {  # Z
        0: [(0, 0), (1, 0), (1, 1), (2, 1)],
        1: [(1, 0), (0, 1), (1, 1), (0, 2)],
        2: [(0, 0), (1, 0), (1, 1), (2, 1)],
        3: [(1, 0), (0, 1), (1, 1), (0, 2)],
    },
    6: {  # J
        0: [(0, 0), (0, 1), (1, 1), (2, 1)],
        1: [(0, 0), (1, 0), (0, 1), (0, 2)],
        2: [(0, 0), (1, 0), (2, 0), (2, 1)],
        3: [(1, 0), (1, 1), (0, 2), (1, 2)],
    },
    7: {  # L
        0: [(2, 0), (0, 1), (1, 1), (2, 1)],
        1: [(0, 0), (0, 1), (0, 2), (1, 2)],
        2: [(0, 0), (1, 0), (2, 0), (0, 1)],
        3: [(0, 0), (1, 0), (1, 1), (1, 2)],
    },
}

PIECE_NAMES = {1: 'I', 2: 'O', 3: 'T', 4: 'S', 5: 'Z', 6: 'J', 7: 'L'}


def footprint(piece, rot):
    """(dx,dy) of the 4 cells RELATIVE TO THE ANCHOR (= first listed cell)."""
    cells = SHAPES[piece][rot]
    ax, ay = cells[0]
    return [(x - ax, y - ay) for (x, y) in cells]


def occupied_cells(piece, rot, px, py):
    """Absolute (x,y) board coords of the 4 cells given anchor at (px,py)."""
    rel = footprint(piece, rot)
    return [(px + dx, py + dy) for (dx, dy) in rel]


# ---------------------------------------------------------------------------
# Relative temp bank / shadow (LOCAL offsets from the riding anchor).
# Ported from tetris.py. All offsets >= 4*W (dy>=4) so they are never footprint
# cells; valid tape; restored to 0 after use (except shadow cells, which persist)
# ---------------------------------------------------------------------------
# The relative scratch/shadow bank rides INSIDE the contiguous well at a fixed
# offset from the anchor. It MUST land past the well end for EVERY anchor
# position, otherwise its transient cells (and the [-] cleanup, which zeroes to 0
# not EMPTY) corrupt live playfield cells -- including planting phantom 9/10
# markers and internal zeros that break the '[<]' resync. The farthest an anchor
# can sit from the well end is WELL_CELLS-1 (anchor at (0,0)); an offset >=
# WELL_CELLS therefore guarantees the whole bank lands in unallocated tape to the
# right of RIGHT_SENT, no matter where the piece is. The optimized host VM
# collapses the long '>'/'<' runs into single moves, so this stays cheap at run
# time (only the generated .bf is larger). Footprint offsets (dy*W+dx, max 63)
# stay small and in-well, as required.
TB = WELL_CELLS + 4    # 804: first scratch offset, always past the well end
ACC = TB + 4
SH_PX = TB + 5
SH_PY = TB + 6
SH_ROT = TB + 7
WK = TB + 8       # WK..WK+7 general scratch

SH_BIAS = 100


# ---------------------------------------------------------------------------
# Subsystem A: scan-locate + resync.
# ---------------------------------------------------------------------------
def emit_scan_to_anchor(c):
    """Scan to the UNIQUE cell with value EXACTLY 10 (the anchor). Lands on it;
    restores everything. Local offset 0 == anchor. Pre: cursor at well base."""
    well = c.addr("well")
    assert c.cursor == well, "scan must start at well base; cursor=%s" % c.cursor
    c.begin_rel()
    c.emit('-' * ANCHOR)          # cur -= 10
    c.emit('[')                   # while cur != 0 (not the anchor):
    c.emit('+' * ANCHOR)          #   restore this cell
    c.raw('>')                    #   step right (raw rel move; net redefined below)
    c.emit('-' * ANCHOR)          #   subtract 10 from new current
    c.emit(']')
    c.emit('+' * ANCHOR)          # restore the anchor cell to 10
    c._rel_net = 0                # define local offset 0 == anchor
    return c


def emit_resync_to_left_sentinel(c):
    """Pre: pointer riding a well cell (relative). Post: pointer on LEFT_SENT."""
    c.raw('[<]')
    c.resync("LEFT_SENT")
    return c


# ---------------------------------------------------------------------------
# Relative primitives (all offsets LOCAL to the riding anchor). From tetris.py.
# ---------------------------------------------------------------------------
def rcopy(c, src, dst, tmp):
    """dst = src (preserved). tmp 0 before/after."""
    c.rzero(dst); c.rzero(tmp)
    c.rgoto(src); c.emit('[-')
    c.rgoto(dst); c.emit('+')
    c.rgoto(tmp); c.emit('+')
    c.rgoto(src); c.emit(']'); c._rel_net = src
    c.rgoto(tmp); c.emit('[-')
    c.rgoto(src); c.emit('+')
    c.rgoto(tmp); c.emit(']'); c._rel_net = tmp


def rmove(c, src, dst):
    c.rgoto(src); c.emit('[-')
    c.rgoto(dst); c.emit('+')
    c.rgoto(src); c.emit(']'); c._rel_net = src


def emit_rel_test_locked(c, off):
    """if value at local 'off' in 2..8: ACC += 1. 'off' restored.
       scratch TB(copy),TB+1(tmp),TB+2(flag),TB+3(et)."""
    cp, tmp, flag, et = TB, TB + 1, TB + 2, TB + 3
    rcopy(c, off, cp, tmp)
    c.rset(flag, 1)
    for k in (1, 9, 10):
        rcopy(c, cp, tmp, et)
        c.rgoto(tmp); c.sub(k)
        c.rset(et, 1)
        c.rgoto(tmp); c.emit('['); c.rset(et, 0); c.rset(tmp, 0)
        c.rgoto(tmp); c.emit(']'); c._rel_net = tmp
        c.rgoto(et); c.emit('['); c.rset(flag, 0); c.rset(et, 0)
        c.rgoto(et); c.emit(']'); c._rel_net = et
    c.rgoto(flag); c.emit('[-')
    c.rgoto(ACC); c.emit('+')
    c.rgoto(flag); c.emit(']'); c._rel_net = flag
    c.rzero(cp)


def _rguarded_dec(c, t, under, g, zf):
    rcopy(c, t, g, zf)
    c.rset(zf, 1)
    c.rgoto(g); c.emit('[')
    c.rset(zf, 0)
    c.rgoto(t); c.emit('-')
    c.rset(g, 0)
    c.rgoto(g); c.emit(']'); c._rel_net = g
    c.rgoto(zf); c.emit('[')
    c.rgoto(under); c.emit('+')
    c.rset(zf, 0)
    c.rgoto(zf); c.emit(']'); c._rel_net = zf


def emit_rel_ge_const(c, a, k, flag, t, under, g, zf):
    """flag = (a >= k). a preserved. all scratch local."""
    rcopy(c, a, t, g)
    c.rset(under, 0)
    for _ in range(k):
        _rguarded_dec(c, t, under, g, zf)
    c.rset(t, 0)
    c.rset(flag, 1)
    c.rgoto(under); c.emit('['); c.rset(flag, 0); c.rset(under, 0)
    c.rgoto(under); c.emit(']'); c._rel_net = under


def emit_rel_le_const(c, a, k, flag, t, under, g, zf):
    """flag = (a <= k) = NOT(a >= k+1). a preserved."""
    emit_rel_ge_const(c, a, k + 1, t, under, g, zf, flag)   # t = (a>=k+1)
    c.rset(flag, 1)
    c.rgoto(t); c.emit('['); c.rset(flag, 0); c.rset(t, 0)
    c.rgoto(t); c.emit(']'); c._rel_net = t


# ---------------------------------------------------------------------------
# B+C) A move attempt, fully relative. Pre: cursor at LEFT_SENT. Post: cursor at
# LEFT_SENT; well markers + shadow updated iff legal.
# ---------------------------------------------------------------------------
def emit_try_move(c, piece, rot, nrot, mdx, mdy):
    well = c.addr("well")
    old_rel = footprint(piece, rot)
    new_rel = footprint(piece, nrot)
    new_off = [(dx + mdx, dy + mdy) for (dx, dy) in new_rel]   # rel to OLD anchor
    max_dx = max(dx for dx, dy in new_rel)
    max_dy = max(dy for dx, dy in new_rel)

    c.goto(well)
    emit_scan_to_anchor(c)                  # ride OLD anchor

    min_dx = min(dx for dx, dy in new_rel)
    min_dy = min(dy for dx, dy in new_rel)
    lox = -(mdx + min_dx)
    hix = (W - 1) - mdx - max_dx
    loy = -(mdy + min_dy)
    hiy = (H - 1) - mdy - max_dy

    pxv, pyv = WK, WK + 1
    rcopy(c, SH_PX, pxv, WK + 2); c.rgoto(pxv); c.sub(SH_BIAS)
    rcopy(c, SH_PY, pyv, WK + 2); c.rgoto(pyv); c.sub(SH_BIAS)

    GO = WK + 3
    fa, fb = WK + 4, WK + 5
    c.rset(GO, 1)

    def _and_into_go(make_flag):
        make_flag(fa)
        c.rset(fb, 0)
        c.rgoto(GO); c.emit('[')
        c.rgoto(fa); c.emit('[')
        c.rset(fb, 1); c.rset(fa, 0)
        c.rgoto(fa); c.emit(']'); c._rel_net = fa
        c.rset(GO, 0)
        c.rgoto(GO); c.emit(']'); c._rel_net = GO
        c.rgoto(fb); c.emit('[')
        c.rset(GO, 1); c.rset(fb, 0)
        c.rgoto(fb); c.emit(']'); c._rel_net = fb

    if lox > 0:
        _and_into_go(lambda fl: emit_rel_ge_const(c, pxv, lox, fl, WK + 6, WK + 7, TB, TB + 1))
    if hix < W - 1:
        _and_into_go(lambda fl: emit_rel_le_const(c, pxv, hix, fl, WK + 6, WK + 7, TB, TB + 1))
    if loy > 0:
        _and_into_go(lambda fl: emit_rel_ge_const(c, pyv, loy, fl, WK + 6, WK + 7, TB, TB + 1))
    if hiy < H - 1:
        _and_into_go(lambda fl: emit_rel_le_const(c, pyv, hiy, fl, WK + 6, WK + 7, TB, TB + 1))

    # locked test of NEW footprint into ACC (non-destructive; ANDed with GO)
    c.rset(ACC, 0)
    for (dx, dy) in new_off:
        emit_rel_test_locked(c, dy * W + dx)

    # free = GO AND (ACC == 0)
    nohit = WK + 4
    c.rset(nohit, 1)
    c.rgoto(ACC); c.emit('['); c.rset(nohit, 0); c.rset(ACC, 0)
    c.rgoto(ACC); c.emit(']'); c._rel_net = ACC
    free = WK + 5
    c.rset(free, 0)
    c.rgoto(GO); c.emit('[')
    c.rgoto(nohit); c.emit('[')
    c.rset(free, 1); c.rset(nohit, 0)
    c.rgoto(nohit); c.emit(']'); c._rel_net = nohit
    c.rset(GO, 0)
    c.rgoto(GO); c.emit(']'); c._rel_net = GO

    anchor_new_off = new_off[0][1] * W + new_off[0][0]

    def do_move():
        c.rgoto(SH_PX); c.add(mdx & 0xFF)
        c.rgoto(SH_PY); c.add(mdy & 0xFF)
        c.rset(SH_ROT, nrot + SH_BIAS)
        stage = (WK + 4, WK + 5, WK + 6)
        srcs = (SH_PX, SH_PY, SH_ROT)
        for st, sh in zip(stage, srcs):
            c.rzero(st); rmove(c, sh, st)              # source -> 0, staged
        for st, sh in zip(stage, srcs):
            dst = anchor_new_off + sh
            c.rzero(dst); rmove(c, st, dst)            # staged -> new position
        # clear OLD markers to EMPTY
        for (dx, dy) in old_rel:
            c.rgoto(dy * W + dx); c.emit('[-]'); c.add(EMPTY)
        # set NEW markers (relative to OLD anchor); index 0 = ANCHOR
        for i, (dx, dy) in enumerate(new_off):
            c.rgoto(dy * W + dx); c.emit('[-]')
            c.add(ANCHOR if i == 0 else ACTIVE)
        c.rgoto(0)

    c.rgoto(free); c.emit('[')
    do_move()
    c.rgoto(free); c.emit('[-]')          # consume free
    c.rgoto(0)                            # both branches end at OLD-anchor off 0
    c.rgoto(free); c.emit(']'); c._rel_net = free

    # CLEANUP: zero every transient scratch cell we used.
    scratch_offsets = set()
    scratch_offsets.update(range(TB, TB + 4))
    scratch_offsets.add(ACC)
    scratch_offsets.update(range(WK, WK + 8))
    new_shadow = {anchor_new_off + SH_PX, anchor_new_off + SH_PY, anchor_new_off + SH_ROT}
    for off in sorted(scratch_offsets):
        if off in new_shadow:
            continue
        c.rgoto(off); c.emit('[-]')
    c.rgoto(0)

    emit_resync_to_left_sentinel(c)
    return c


# ---------------------------------------------------------------------------
# D) LOCK & SPAWN. Pre: cursor at LEFT_SENT. Converts the active piece to locked
# id 'piece' and spawns a NEW piece at (spawn_x, spawn_y).
# ---------------------------------------------------------------------------
def emit_lock_only(c, piece, rot):
    """Convert the active piece (compile-time piece,rot) into LOCKED(piece) cells
    and clear its shadow. Pre: cursor known. Post: cursor at LEFT_SENT. After
    this the well has NO anchor (no value 10) until a spawn runs."""
    well = c.addr("well")
    old_rel = footprint(piece, rot)
    c.goto(well)
    emit_scan_to_anchor(c)               # ride OLD anchor
    for (dx, dy) in old_rel:
        c.rgoto(dy * W + dx); c.emit('[-]'); c.add(LOCKED(piece))
    for sh in (SH_PX, SH_PY, SH_ROT):
        c.rgoto(sh); c.emit('[-]'); c.add(EMPTY)
    c.rgoto(0)
    emit_resync_to_left_sentinel(c)
    return c


def emit_spawn_only(c, new_piece, spawn_x, spawn_y):
    """Write a fresh piece's markers + shadow (rot 0) at (spawn_x, spawn_y),
    absolutely. Pre: cursor known. Post: cursor at LEFT_SENT."""
    new_rel = footprint(new_piece, 0)
    for i, (dx, dy) in enumerate(new_rel):
        cl = cell(c, spawn_x + dx, spawn_y + dy)
        c.set_at(cl, ANCHOR if i == 0 else ACTIVE)
    anchor_abs = cell(c, spawn_x, spawn_y)
    c.set_at(anchor_abs + SH_PX, spawn_x + SH_BIAS)
    c.set_at(anchor_abs + SH_PY, spawn_y + SH_BIAS)
    c.set_at(anchor_abs + SH_ROT, 0 + SH_BIAS)
    c.goto("LEFT_SENT")
    return c


def emit_lock_and_spawn(c, piece, rot, new_piece, spawn_x, spawn_y):
    emit_lock_only(c, piece, rot)
    emit_spawn_only(c, new_piece, spawn_x, spawn_y)
    return c


# ---------------------------------------------------------------------------
# Initial spawn helper for tests (well + shadow init_tape for a starting piece).
# ---------------------------------------------------------------------------
def make_well_with_piece(c, piece, rot, px, py, locked_cells=None):
    """Python-side ground-truth init_tape for a well with one active piece."""
    t = make_empty_well(c)
    if locked_cells:
        for (x, y, pid) in locked_cells:
            t[cell(c, x, y)] = LOCKED(pid)
    rel = footprint(piece, rot)
    for i, (dx, dy) in enumerate(rel):
        t[cell(c, px + dx, py + dy)] = ANCHOR if i == 0 else ACTIVE
    anchor_abs = cell(c, px, py)
    t[anchor_abs + SH_PX] = px + SH_BIAS
    t[anchor_abs + SH_PY] = py + SH_BIAS
    t[anchor_abs + SH_ROT] = rot + SH_BIAS
    return t
