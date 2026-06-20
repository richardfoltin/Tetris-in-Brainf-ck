"""
BF Tetris runtime moving-piece subsystem (A-E), final architecture.

CURSOR / POINTER MODEL
----------------------
  - The active piece is 4 well markers: 1 ANCHOR(10) + 3 ACTIVE(9). The anchor
    is footprint cell index 0.
  - GEOMETRY RIDES WITH THE ANCHOR: px, py, rot live in 3 well cells at FIXED
    relative offsets from the anchor (the "shadow" cells, far below the piece so
    they are never footprint cells). Because they are at fixed relative offsets,
    every collision/move/update is done with COMPILE-TIME relative addressing
    while the pointer rides the anchor. This removes the need to transport any
    runtime value to an absolute register.
  - A frame:
      RESYNC absolute at LEFT_SENT (render/HUD can run here, static offsets) [E]
      goto WELL_BASE, SCAN-LOCATE the anchor (==10 scan; lands on the unique
        anchor, leftmost 10). Pointer rides it; emitter enters a RELATIVE
        section, local offset 0 = anchor. [A]
      Do the action entirely relative to the anchor:
        - candidate px/py/rot from shadow (relative) + compile-time displacement
        - WALL/FLOOR test from shadow values (relative) [B walls]
        - LOCKED test by peeking destination footprint cells (relative) [B lock]
        - if free: clear OLD markers, set NEW markers, update shadow [C]
          (the anchor marker moves -> pointer must end on the NEW anchor)
        - lock+spawn handled by emit_lock_and_spawn [D]
      RESYNC '[<]' to LEFT_SENT. [E]

  RELATIVE TEMP BANK / SHADOW (local offsets from anchor):
      TB   = 4*W      copy scratch
      TB+1 .. TB+3    classify scratch
      ACC  = TB+4     locked-hit accumulator
      SH_PX= TB+5     shadow px
      SH_PY= TB+6     shadow py
      SH_ROT=TB+7     shadow rot
      WK0..WK7 = TB+8 .. TB+15   general relative scratch
    All are at local offset >= 4*W (dy>=4 region), never footprint cells, valid
    tape (free 0 cells if they overrun RIGHT_SENT), and restored to 0 after use
    (except the shadow cells which persist).

ENCODING: empty=1, locked=2..8, ACTIVE=9, ANCHOR=10. LOCKED test: value in 2..8.
"""

from bf import Emitter, run_bf
from layout import (W, H, WELL_BASE, LEFT_SENT, RIGHT_SENT, cell,
                    EMPTY, ACTIVE, ANCHOR, LOCKED, REG_PX, REG_PY, REG_ROT,
                    REG_PIECE)
from scan import emit_scan_to_anchor, emit_resync_to_left_sentinel
from shapes import footprint

TB   = 3 * W + 4   # 64: first local offset that can NEVER be a footprint cell
                   # (footprint offsets dy*W+dx, dx<=3,dy<=3 -> max 3*W+3=63).
ACC  = TB + 4
SH_PX  = TB + 5
SH_PY  = TB + 6
SH_ROT = TB + 7
WK = TB + 8   # WK..WK+7 general scratch

# Shadow cells store (logical value + SH_BIAS) so they can NEVER equal a marker
# value (9 or 10) or any well value (1..8); this keeps the scan/marker counting
# unambiguous even when px/py == 9 or 10.
SH_BIAS = 100


# ---------------------------------------------------------------------------
# Relative primitives (all offsets LOCAL to the riding anchor).
# ---------------------------------------------------------------------------
def rcopy(e, src, dst, tmp):
    """dst = src (preserved). tmp 0 before/after."""
    e.rzero(dst); e.rzero(tmp)
    e.rgoto(src); e.emit('[-')
    e.rgoto(dst); e.emit('+')
    e.rgoto(tmp); e.emit('+')
    e.rgoto(src); e.emit(']'); e._rel_net = src
    e.rgoto(tmp); e.emit('[-')
    e.rgoto(src); e.emit('+')
    e.rgoto(tmp); e.emit(']'); e._rel_net = tmp

def rmove(e, src, dst):
    e.rgoto(src); e.emit('[-')
    e.rgoto(dst); e.emit('+')
    e.rgoto(src); e.emit(']'); e._rel_net = src

def r_if_then(e, cond, body):
    """run-once relative if: if cond != 0 { body(); } cond consumed to 0.
       body must net-zero the local offset bookkeeping (it ends wherever; we
       reset to cond after)."""
    e.rgoto(cond); e.emit('[')
    body()
    e.rgoto(cond); e.emit('[-]')
    e.rgoto(cond); e.emit(']'); e._rel_net = cond

def emit_rel_test_locked(e, off):
    """if value at local 'off' in 2..8: ACC += 1. 'off' restored.
       scratch TB(copy),TB+1(tmp),TB+2(flag),TB+3(et)."""
    cp, tmp, flag, et = TB, TB + 1, TB + 2, TB + 3
    rcopy(e, off, cp, tmp)
    e.rset(flag, 1)
    for k in (1, 9, 10):
        rcopy(e, cp, tmp, et)
        e.rgoto(tmp); e.sub(k)
        e.rset(et, 1)
        e.rgoto(tmp); e.emit('['); e.rset(et, 0); e.rset(tmp, 0)
        e.rgoto(tmp); e.emit(']'); e._rel_net = tmp
        e.rgoto(et); e.emit('['); e.rset(flag, 0); e.rset(et, 0)
        e.rgoto(et); e.emit(']'); e._rel_net = et
    e.rgoto(flag); e.emit('[-')
    e.rgoto(ACC); e.emit('+')
    e.rgoto(flag); e.emit(']'); e._rel_net = flag
    e.rzero(cp)

# relative comparison: flag = (a >= k), a preserved. scratch t,under,g,zf
def _rguarded_dec(e, t, under, g, zf):
    rcopy(e, t, g, zf)
    e.rset(zf, 1)
    e.rgoto(g); e.emit('[')
    e.rset(zf, 0)
    e.rgoto(t); e.emit('-')
    e.rset(g, 0)
    e.rgoto(g); e.emit(']'); e._rel_net = g
    e.rgoto(zf); e.emit('[')
    e.rgoto(under); e.emit('+')
    e.rset(zf, 0)
    e.rgoto(zf); e.emit(']'); e._rel_net = zf

def emit_rel_ge_const(e, a, k, flag, t, under, g, zf):
    """flag = (a >= k). a preserved. all scratch local."""
    rcopy(e, a, t, g)
    e.rset(under, 0)
    for _ in range(k):
        _rguarded_dec(e, t, under, g, zf)
    e.rset(t, 0)
    e.rset(flag, 1)
    e.rgoto(under); e.emit('['); e.rset(flag, 0); e.rset(under, 0)
    e.rgoto(under); e.emit(']'); e._rel_net = under

def emit_rel_le_const(e, a, k, flag, t, under, g, zf):
    """flag = (a <= k) = NOT(a >= k+1). a preserved."""
    emit_rel_ge_const(e, a, k + 1, t, under, g, zf, flag)   # t = (a>=k+1)
    e.rset(flag, 1)
    e.rgoto(t); e.emit('['); e.rset(flag, 0); e.rset(t, 0)
    e.rgoto(t); e.emit(']'); e._rel_net = t


# ---------------------------------------------------------------------------
# A move attempt, fully relative. Pre: cursor at LEFT_SENT. Post: cursor at
# LEFT_SENT; well markers + shadow updated iff legal.
# ---------------------------------------------------------------------------
def emit_try_move(e, piece, rot, nrot, mdx, mdy):
    old_rel = footprint(piece, rot)
    new_rel = footprint(piece, nrot)
    new_off = [(dx + mdx, dy + mdy) for (dx, dy) in new_rel]   # rel to OLD anchor
    max_dx = max(dx for dx, dy in new_rel)
    max_dy = max(dy for dx, dy in new_rel)

    e.goto(WELL_BASE)
    emit_scan_to_anchor(e)                  # ride OLD anchor

    # WALLS, direction-aware, using OLD px,py (never wrapped, so comparisons stay
    # cheap). The NEW footprint anchored at (px+mdx,py+mdy) is on-board iff:
    #   px+mdx+min_dx >= 0      -> px >= -(mdx+min_dx)           [lox]
    #   px+mdx+max_dx <= W-1    -> px <= W-1-mdx-max_dx          [hix]
    #   py+mdy+min_dy >= 0      -> py >= -(mdy+min_dy)           [loy]
    #   py+mdy+max_dy <= H-1    -> py <= H-1-mdy-max_dy          [hiy]
    # We read px,py from the BIASED shadow into temps, unbias, and compare. Values
    # are small (no wrap), so guarded-dec counts stay bounded.
    min_dx = min(dx for dx, dy in new_rel)
    min_dy = min(dy for dx, dy in new_rel)
    lox = -(mdx + min_dx)
    hix = (W - 1) - mdx - max_dx
    loy = -(mdy + min_dy)
    hiy = (H - 1) - mdy - max_dy

    pxv, pyv = WK, WK + 1
    rcopy(e, SH_PX, pxv, WK + 2); e.rgoto(pxv); e.sub(SH_BIAS)
    rcopy(e, SH_PY, pyv, WK + 2); e.rgoto(pyv); e.sub(SH_BIAS)

    GO = WK + 3
    fa, fb = WK + 4, WK + 5
    e.rset(GO, 1)
    def _and_into_go(make_flag):
        make_flag(fa)
        # GO = GO AND fa
        e.rset(fb, 0)
        e.rgoto(GO); e.emit('[')
        e.rgoto(fa); e.emit('[')
        e.rset(fb, 1); e.rset(fa, 0)
        e.rgoto(fa); e.emit(']'); e._rel_net = fa
        e.rset(GO, 0)
        e.rgoto(GO); e.emit(']'); e._rel_net = GO
        e.rgoto(fb); e.emit('[')
        e.rset(GO, 1); e.rset(fb, 0)
        e.rgoto(fb); e.emit(']'); e._rel_net = fb
    # only emit the comparisons that can actually fail (skip trivially-true ones)
    if lox > 0:
        _and_into_go(lambda fl: emit_rel_ge_const(e, pxv, lox, fl, WK + 6, WK + 7, TB, TB + 1))
    if hix < W - 1:
        _and_into_go(lambda fl: emit_rel_le_const(e, pxv, hix, fl, WK + 6, WK + 7, TB, TB + 1))
    if loy > 0:
        _and_into_go(lambda fl: emit_rel_ge_const(e, pyv, loy, fl, WK + 6, WK + 7, TB, TB + 1))
    if hiy < H - 1:
        _and_into_go(lambda fl: emit_rel_le_const(e, pyv, hiy, fl, WK + 6, WK + 7, TB, TB + 1))

    # locked test of NEW footprint into ACC (only meaningful if walls ok, but it
    # is non-destructive so we always run it; final decision ANDs with GO)
    e.rset(ACC, 0)
    for (dx, dy) in new_off:
        emit_rel_test_locked(e, dy * W + dx)

    # free = GO AND (ACC == 0)
    nohit = WK + 4
    e.rset(nohit, 1)
    e.rgoto(ACC); e.emit('['); e.rset(nohit, 0); e.rset(ACC, 0)
    e.rgoto(ACC); e.emit(']'); e._rel_net = ACC
    free = WK + 5
    e.rset(free, 0)
    e.rgoto(GO); e.emit('[')
    e.rgoto(nohit); e.emit('[')
    e.rset(free, 1); e.rset(nohit, 0)
    e.rgoto(nohit); e.emit(']'); e._rel_net = nohit
    e.rset(GO, 0)
    e.rgoto(GO); e.emit(']'); e._rel_net = GO

    # if free: rewrite markers + shadow. The anchor marker MOVES, so the NEW
    # anchor is at local offset 'anchor_new_off'. We rewrite EVERYTHING relative
    # to the OLD anchor (origin unchanged), so the compile-time local offset
    # never diverges between branches. The pointer ends at OLD-anchor offset 0 in
    # BOTH branches, so the resync '[<]' (walking LEFT, away from all right-side
    # scratch) is safe regardless of whether the move happened.
    anchor_new_off = new_off[0][1] * W + new_off[0][0]
    def do_move():
        # relocate shadow cells from OLD-relative SH_* to NEW-relative SH_*
        # (= OLD offset anchor_new_off + SH_*). The source/destination ranges can
        # OVERLAP for small displacements, so we first apply the displacement in
        # place, then DRAIN all three sources to 0 into a staging area (WK+4..+6),
        # then write the staging values into the new positions. WK+4..+6 are far
        # from both shadow ranges, so no overlap.
        # shadow stays BIASED; displacement preserves bias.
        e.rgoto(SH_PX); e.add(mdx & 0xFF)
        e.rgoto(SH_PY); e.add(mdy & 0xFF)
        e.rset(SH_ROT, nrot + SH_BIAS)
        stage = (WK + 4, WK + 5, WK + 6)
        srcs = (SH_PX, SH_PY, SH_ROT)
        for st, sh in zip(stage, srcs):
            e.rzero(st); rmove(e, sh, st)              # source -> 0, staged
        for st, sh in zip(stage, srcs):
            dst = anchor_new_off + sh
            e.rzero(dst); rmove(e, st, dst)            # staged -> new position
        # clear OLD markers to EMPTY
        for (dx, dy) in old_rel:
            e.rgoto(dy * W + dx); e.emit('[-]'); e.add(EMPTY)
        # set NEW markers (relative to OLD anchor); index 0 = ANCHOR
        for i, (dx, dy) in enumerate(new_off):
            e.rgoto(dy * W + dx); e.emit('[-]')
            e.add(ANCHOR if i == 0 else ACTIVE)
        # NOTE: if the new footprint overlaps the OLD anchor cell (offset 0), the
        # ANCHOR marker for the old position may have been overwritten by EMPTY
        # then by a NEW marker -- handled because we clear OLD then set NEW.
        # return to OLD-anchor origin (offset 0) so both branches converge
        e.rgoto(0)
    e.rgoto(free); e.emit('[')
    do_move()
    e.rgoto(free); e.emit('[-]')          # consume free (offset 'free', origin unchanged)
    e.rgoto(0)                            # both branches end at OLD-anchor offset 0
    e.rgoto(free); e.emit(']'); e._rel_net = free

    # CLEANUP: zero every transient scratch cell we used (candidates, flags, ACC,
    # comparison temps). Otherwise a leftover scratch holding value 9/10 (e.g.
    # ny == 10) would masquerade as an ACTIVE/ANCHOR marker. These cells are all
    # to the RIGHT of the OLD anchor (local offset >= 4*W), so leaving them 0 is
    # safe: the resync '[<]' walks LEFT and the next scan stops at the leftmost
    # anchor before reaching them. We do NOT zero the shadow cells (SH_* at the
    # NEW anchor's frame) which must persist.
    scratch_offsets = set()
    scratch_offsets.update(range(TB, TB + 4))          # classify bank
    scratch_offsets.add(ACC)
    scratch_offsets.update(range(WK, WK + 8))          # nx,ny,GO,flags,staging
    # also the NEW-anchor-relative versions of WK staging we may have written
    for sh in (SH_PX, SH_PY, SH_ROT):
        keep = anchor_new_off + sh
    # zero all scratch (OLD-anchor relative), but DON'T touch the NEW shadow cells
    new_shadow = {anchor_new_off + SH_PX, anchor_new_off + SH_PY, anchor_new_off + SH_ROT}
    for off in sorted(scratch_offsets):
        if off in new_shadow:
            continue
        e.rgoto(off); e.emit('[-]')
    e.rgoto(0)                            # ensure pointer on OLD anchor offset 0

    # resync absolute ('[<]' walks left through real well cells only)
    emit_resync_to_left_sentinel(e)
    return e


# ---------------------------------------------------------------------------
# D) LOCK & SPAWN. Pre: cursor at LEFT_SENT. Converts the active piece to locked
# id 'piece' (stored LOCKED(piece)=piece+1) and spawns a NEW piece's markers at
# the top with anchor at (spawn_x, spawn_y). Done relative to the OLD anchor for
# the lock, then absolute for the spawn (spawn position is compile-time fixed).
# ---------------------------------------------------------------------------
def emit_lock_and_spawn(e, piece, rot, new_piece, spawn_x, spawn_y):
    old_rel = footprint(piece, rot)
    e.goto(WELL_BASE)
    emit_scan_to_anchor(e)               # ride OLD anchor
    # convert markers to LOCKED(piece)
    for (dx, dy) in old_rel:
        e.rgoto(dy * W + dx); e.emit('[-]'); e.add(LOCKED(piece))
    # clear shadow cells to EMPTY (never 0 inside the well, to keep '[<]' safe)
    for sh in (SH_PX, SH_PY, SH_ROT):
        e.rgoto(sh); e.emit('[-]'); e.add(EMPTY)
    # return to OLD anchor (offset 0) so resync walks left through real cells only
    e.rgoto(0)
    # resync
    emit_resync_to_left_sentinel(e)
    # spawn NEW piece at compile-time-fixed (spawn_x, spawn_y): write markers +
    # shadow absolutely. Shadow stored BIASED.
    new_rel = footprint(new_piece, 0)
    for i, (dx, dy) in enumerate(new_rel):
        c = cell(spawn_x + dx, spawn_y + dy)
        e.set_at(c, ANCHOR if i == 0 else ACTIVE)
    anchor_abs = cell(spawn_x, spawn_y)
    e.set_at(anchor_abs + SH_PX, spawn_x + SH_BIAS)
    e.set_at(anchor_abs + SH_PY, spawn_y + SH_BIAS)
    e.set_at(anchor_abs + SH_ROT, 0 + SH_BIAS)
    e.goto(LEFT_SENT)
    return e


# ---------------------------------------------------------------------------
# Initial spawn helper for tests (writes well + shadow for a starting piece).
# ---------------------------------------------------------------------------
def make_well_with_piece(piece, rot, px, py, locked_cells=None):
    """Python-side ground truth init_tape for a well with one active piece."""
    from layout import make_empty_well
    t = make_empty_well()
    if locked_cells:
        for (x, y, pid) in locked_cells:
            t[cell(x, y)] = LOCKED(pid)
    rel = footprint(piece, rot)
    for i, (dx, dy) in enumerate(rel):
        t[cell(px + dx, py + dy)] = ANCHOR if i == 0 else ACTIVE
    anchor_abs = cell(px, py)
    t[anchor_abs + SH_PX] = px + SH_BIAS
    t[anchor_abs + SH_PY] = py + SH_BIAS
    t[anchor_abs + SH_ROT] = rot + SH_BIAS
    return t
