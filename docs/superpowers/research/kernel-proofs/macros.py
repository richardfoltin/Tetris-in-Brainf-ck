"""
Relative "pointer rides the well" macros built on emitter.Emitter.

Crux insight that makes relative + absolute coexist:
  Inside a relative section the data ptr sits at anchor + rel.  We do NOT know
  the anchor's absolute index *at the well level*, BUT the compiler still holds
  anchor_abs (the absolute cursor it believed when entering).  Because every
  relative section nets zero displacement, anchor_abs stays physically correct.
  Therefore, from the anchor (rel==0) the offset to ANY fixed absolute cell C
  is the COMPILE-TIME CONSTANT (C - anchor_abs).  So we can shuttle a peek
  result from a well neighbor all the way to an absolute accumulator (e.g. HOME)
  using only relative >/< whose count is known at compile time.

  We expose this as rel_off_to(abs_cell): returns abs_cell - anchor_abs.
"""

from emitter import (Emitter, HOME, RET, T0, T1, T2, T3, T4, WELL_BASE, WELL_W,
                     WELL_H, WELL_N, POST0, POST1, pick_scratch, pick_scratch4,
                     pick_scratch6, PRE_STRIP, POST_STRIP)


# --- relative helpers added as methods via monkeypatch-style functions ---

def rel_off_to(e, abs_cell):
    """Compile-time relative offset from the anchor to a fixed absolute cell."""
    assert e.rel is not None
    return abs_cell - e.anchor_abs


def r_clear(e, off):
    e.rgoto(off)
    e.emit('[-]')


def r_move_add(e, src_off, dst_off):
    """dst += src; src = 0.  Pure relative.  Loop is safe because biased cells
    are bounded; we drain src into dst."""
    e.rgoto(src_off)
    e.emit('[')
    e.emit('-')
    e.rgoto(dst_off)
    e.emit('+')
    e.rgoto(src_off)
    e.emit(']')
    # ptr ends at src_off with value 0


def r_copy(e, src_off, dst_off, tmp_off):
    """dst = src using tmp; non-destructive to src.  Pure relative."""
    r_clear(e, dst_off)
    r_clear(e, tmp_off)
    # src -> dst and tmp
    e.rgoto(src_off)
    e.emit('[')
    e.emit('-')
    e.rgoto(dst_off); e.emit('+')
    e.rgoto(tmp_off); e.emit('+')
    e.rgoto(src_off)
    e.emit(']')
    # tmp -> src
    e.rgoto(tmp_off)
    e.emit('[')
    e.emit('-')
    e.rgoto(src_off); e.emit('+')
    e.rgoto(tmp_off)
    e.emit(']')
    e.rgoto(src_off)


# ---------------------------------------------------------------------------
# Geometry helpers (compile-time): which relative offset is a given (dx,dy)?
# A neighbor (dx,dy) from the anchor is at relative offset dy*WELL_W + dx,
# AS LONG AS it is in-bounds. Out-of-bounds must be detected separately
# because the flat tape has no row structure -- moving +1 from x=9 wraps to the
# next row's x=0 on the tape.  We therefore compute bounds from the KNOWN
# anchor (x,y) at compile time per anchor position.  Since x,y are runtime in a
# real game, we instead pass them to the emitter to generate code for a SPECIFIC
# anchor (the macro is specialized per anchor cell). This matches "compile-time
# offsets from the anchor".
# ---------------------------------------------------------------------------


def rel_offset(dx, dy):
    return dy * WELL_W + dx


def peek_collision_4x4(e, ax, ay, result_abs=HOME):
    """
    Scan the 4x4 neighborhood (anchor = top-left, (ax,ay)). COLLISION iff a cell
    is OUT-OF-BOUNDS or OCCUPIED (biased value != 1, i.e. logical != empty). OR
    all collisions into absolute cell result_abs (0/1).

    CHEAP, CORRECT, pointer-rides-the-well:
      * ACC (running collision count; nonzero => collision) lives in absolute
        scratch cell RACC.
      * We borrow TWO well cells ADJACENT to the anchor as relative copy temps
        TA,TB (rel +1,+2 or -1,-2 near the right wall). Adjacent => the only
        |off|-scaled transfers are the neighbor<->temp copies, whose value is the
        biased cell (<= 8), so every value-loop is short.
      * The anchor and the two borrowed cells are tested for occupancy in the
        ABSOLUTE regime (they sit at known absolute addresses), then freed to 0;
        restored from saves in the epilogue. So the relative scan handles only the
        other (up to 13) neighbors and OOB markers.
      * Relative scan, per in-bounds non-borrowed neighbor at offset off:
            TA=TB=0
            neighbor -> TA + TB        (<=8 units * |off|)
            TB -> neighbor (rebuild)   (<=8 units * |off|)
            TA -= 1 ; if TA!=0 -> ACC++ (TA is anchor-adjacent: short)
        OOB neighbor: ACC++ (anchor-adjacent op).

    Pointer returns to the anchor; resyncs to result_abs. Well is never mutated.
    Precondition: data ptr at anchor; cursor == anchor_abs.
    """
    anchor_abs = WELL_BASE + ay * WELL_W + ax
    assert e.cursor == anchor_abs, (e.cursor, anchor_abs)

    # Borrow THREE well cells adjacent to the anchor (rel +1,+2,+3 or -1,-2,-3):
    #   a1 = relative ACCUMULATOR (cheap: distance 1 from anchor; the hot path)
    #   a2,a3 = relative copy temps for the non-destructive neighbor test.
    # A 10-wide well always has >=3 columns of room on one side.
    sgn = 1 if ax + 3 < WELL_W else -1
    a1, a2, a3 = sgn * 1, sgn * 2, sgn * 3
    acc_abs = anchor_abs + a1
    ta_abs = anchor_abs + a2
    tb_abs = anchor_abs + a3

    # 6 absolute scratch cells on whichever side of the well is closer to this
    # anchor, so every prelude/epilogue shuttle is bounded to ~half the well.
    sb = pick_scratch6(anchor_abs)
    RACC = sb                 # absolute accumulator (folds occupancy of borrowed
                              # cells + anchor + relative-ACC at the end)
    SAV_ANCHOR = sb + 1
    SAV_A1 = sb + 2
    SAV_A2 = sb + 3
    SAV_A3 = sb + 4
    CONSUME = sb + 5          # consumable copy for absolute occupancy tests

    # ---- absolute prelude ----
    e.clear(RACC)
    # SAVE + FREE the anchor and the THREE borrowed cells (the contiguous run
    # anchor..anchor+3*sgn) into the contiguous saves SAV_ANCHOR..SAV_A3.  Each is
    # one drain (distance*value).  Then TEST each save's occupancy LOCALLY in the
    # strip (the saves are adjacent, so these tests are distance-1, cheap) and
    # fold into RACC.  This keeps the far traversals to just the 4 unavoidable
    # save drains rather than many per-cell scratch round-trips.
    save_of = {anchor_abs: SAV_ANCHOR, acc_abs: SAV_A1, ta_abs: SAV_A2, tb_abs: SAV_A3}
    for cell_abs, save in save_of.items():
        e.clear(save)
        e.goto(cell_abs)
        e.emit("[")
        e.goto(save); e.emit("+")
        e.goto(cell_abs); e.emit("-")
        e.emit("]")
    # local occupancy tests on the saves (adjacent strip cells), using CONSUME.
    # All cells (save, CONSUME, RACC) are within the strip => distance-1 loops.
    for save in (SAV_ANCHOR, SAV_A1, SAV_A2, SAV_A3):
        # test (save != 1) non-destructively: save-=1; drain to CONSUME; rebuild;
        # RACC += (value-1) (nonzero => occupied).
        e.goto(save); e.emit("-")               # save = value-1
        e.clear(CONSUME)
        e.goto(save)
        e.emit("[")                             # drain (value-1) into CONSUME
        e.goto(CONSUME); e.emit("+")
        e.goto(save); e.emit("-")
        e.emit("]")
        # save==0, CONSUME==value-1. rebuild save and fold into RACC.
        e.goto(CONSUME)
        e.emit("[")
        e.goto(save); e.emit("+")               # rebuild save = value-1
        e.goto(RACC); e.emit("+")               # RACC += (value-1)
        e.goto(CONSUME); e.emit("-")
        e.emit("]")
        e.goto(save); e.emit("+")               # save = value (restored)
    e.goto(anchor_abs)

    e.anchor()
    ACC, TA, TB = a1, a2, a3   # relative offsets (all distance <=3 from anchor)

    for dy in range(4):
        for dx in range(4):
            tx, ty = ax + dx, ay + dy
            if not (0 <= tx < WELL_W and 0 <= ty < WELL_H):
                e.rgoto(ACC); e.emit("+")             # OOB -> collision (distance 1)
                continue
            off = rel_offset(dx, dy)
            if off in (0, a1, a2, a3):
                continue                               # anchor/borrowed: done abs
            # NON-destructive occupancy test of neighbor[off] using the freed
            # anchor cell (rel 0) plus one anchor-adjacent temp TA. Empty cells
            # (biased 1) make the value-loops run only ONCE, so sparse (realistic)
            # wells are cheap. Cost scales with the neighbor distance |off| because
            # the temps live next to the anchor (the relative-model trade-off).
            r_clear(e, TA)
            #   neighbor -= 1          (in place; empty 1->0, occupied k+1->k>=1)
            e.rgoto(off); e.emit("-")
            #   move (neighbor) into anchor(rel0), and rebuild neighbor in the
            #   SAME loop by also depositing into TA (anchor-adjacent):
            #     while neighbor: anchor++ ; TA++ ; neighbor--   (TA = anchor = v-1)
            e.emit("[")                                # ptr at off
            e.rgoto(0); e.emit("+")
            e.rgoto(TA); e.emit("+")
            e.rgoto(off); e.emit("-")
            e.emit("]")
            #   neighbor==0, anchor==TA==value-1. rebuild neighbor from anchor:
            e.rgoto(0)
            e.emit("[")
            e.rgoto(off); e.emit("+")
            e.rgoto(0); e.emit("-")
            e.emit("]")
            e.rgoto(off); e.emit("+")                  # neighbor += 1 (restored = value)
            #   occupancy flag is (TA != 0); one-shot ACC++ (TA,ACC anchor-adjacent)
            e.rgoto(TA)
            e.emit("[")
            e.emit("[-]")
            e.rgoto(ACC); e.emit("+")
            e.rgoto(TA)
            e.emit("]")

    # fold the relative ACC (at rel a1) into RACC, leaving the rel-ACC cell 0
    # (it gets overwritten by the restore anyway). One transfer, distance once.
    racc_off = rel_off_to(e, RACC)
    e.rgoto(ACC)
    e.emit("[")
    e.rgoto(racc_off); e.emit("+")
    e.rgoto(ACC); e.emit("-")
    e.emit("]")

    e.rgoto(0)
    e.resync()

    # ---- absolute epilogue ----
    # 1) result = (RACC != 0) ? 1 : 0   (read BEFORE restoring the borrowed cells)
    e.set_const(result_abs, 0)
    e.goto(RACC)
    e.emit("[")
    e.emit("[-]")
    e.goto(result_abs); e.emit("[-]+")
    e.goto(RACC)
    e.emit("]")
    # 2) restore anchor + borrowed cells from saves.
    for save_abs, cabs in ((SAV_ANCHOR, anchor_abs), (SAV_A1, acc_abs),
                           (SAV_A2, ta_abs), (SAV_A3, tb_abs)):
        e.goto(save_abs)
        e.emit("[")
        e.goto(cabs); e.emit("+")
        e.goto(save_abs); e.emit("-")
        e.emit("]")
    e.goto(result_abs)


# ---------------------------------------------------------------------------
# Single-step relative moves with bound/collision check.  Each returns a
# boolean "blocked" in absolute result cell; if not blocked it actually moves
# the *logical anchor record*... but the data pointer model: a "move-right"
# means we will re-anchor one cell to the right.  Here we implement the PEEK
# (can we move?) purely relatively, returning ptr to current anchor.
# The caller, knowing ax,ay at compile time, then re-anchors by goto(neighbor).
# ---------------------------------------------------------------------------


def can_move(e, ax, ay, dx, dy, result_abs=HOME):
    """Peek whether moving the piece-cell at anchor by (dx,dy) is BLOCKED.
    Blocked iff the single target cell (ax+dx, ay+dy) is OOB or occupied.
    Pure-relative peek using anchor-adjacent temps (cheap, value-loops distance
    <=2); pointer returns to anchor and the section resyncs to a known absolute
    cell (result_abs). The well is never mutated."""
    anchor_abs = WELL_BASE + ay * WELL_W + ax
    assert e.cursor == anchor_abs
    tx, ty = ax + dx, ay + dy

    if not (0 <= tx < WELL_W and 0 <= ty < WELL_H):
        # OUT OF BOUNDS is a pure compile-time fact: just set result = 1.
        e.set_const(result_abs, 1)
        e.goto(result_abs)
        return

    # borrow two anchor-adjacent well cells as copy temps. They must be IN-BOUNDS
    # and DISTINCT from the target neighbor (else we'd blank the cell we test).
    off = rel_offset(dx, dy)
    cand = []
    for r in (1, 2, 3, -1, -2, -3):
        cx = ax + r
        if 0 <= cx < WELL_W and r != off:   # same row; in-bounds; not the target
            cand.append(r)
        if len(cand) == 2:
            break
    a1, a2 = cand[0], cand[1]
    ta_abs, tb_abs = anchor_abs + a1, anchor_abs + a2
    sb = pick_scratch6(anchor_abs)
    SAV_A1, SAV_A2 = sb, sb + 1
    e.set_const(result_abs, 0)
    # save & free the two borrowed cells (absolute)
    for cabs, save in ((ta_abs, SAV_A1), (tb_abs, SAV_A2)):
        e.clear(save)
        e.goto(cabs)
        e.emit('[')
        e.goto(save); e.emit('+')
        e.goto(cabs); e.emit('-')
        e.emit(']')
    e.goto(anchor_abs)

    e.anchor()
    res_off = rel_off_to(e, result_abs)
    TA, TB = a1, a2
    # non-destructive occupancy test of the target neighbor:
    r_clear(e, TA); r_clear(e, TB)
    e.rgoto(off)
    e.emit('[')
    e.rgoto(TA); e.emit('+')
    e.rgoto(TB); e.emit('+')
    e.rgoto(off); e.emit('-')
    e.emit(']')
    e.rgoto(TB)
    e.emit('[')
    e.rgoto(off); e.emit('+')
    e.rgoto(TB); e.emit('-')
    e.emit(']')
    e.rgoto(TA); e.emit('-')                # TA = value-1
    e.emit('[')
    e.emit('[-]')
    e.rgoto(res_off); e.emit('[-]+')        # result = 1 (occupied)
    e.rgoto(TA)
    e.emit(']')
    e.rgoto(0)
    e.resync()
    # restore borrowed cells (absolute)
    for cabs, save in ((ta_abs, SAV_A1), (tb_abs, SAV_A2)):
        e.goto(save)
        e.emit('[')
        e.goto(cabs); e.emit('+')
        e.goto(save); e.emit('-')
        e.emit(']')
    # resync to a known absolute home cell for a uniform op contract.
    e.goto(HOME)


# ---------------------------------------------------------------------------
# PHYSICAL relative moves: the data pointer RIDES the well. A move is a single
# relative >/< (or +/- WELL_W) that re-anchors one cell. The compiler tracks the
# new anchor at compile time (we know dx,dy), so it can still emit absolute gotos
# afterwards. Each helper asserts the cursor invariant.
# ---------------------------------------------------------------------------

def move_right(e, ax, ay):
    """Physically move the data pointer one cell right (anchor -> anchor+1).
    Pure relative: a single '>'. Returns the new (ax,ay)."""
    assert e.rel is None and e.cursor == WELL_BASE + ay * WELL_W + ax
    assert ax + 1 < WELL_W, "caller must peek can_move first; this is unguarded"
    e.emit('>'); e.cursor += 1
    return ax + 1, ay


def move_left(e, ax, ay):
    """anchor -> anchor-1 (single '<')."""
    assert e.rel is None and e.cursor == WELL_BASE + ay * WELL_W + ax
    assert ax - 1 >= 0
    e.emit('<'); e.cursor -= 1
    return ax - 1, ay


def move_down(e, ax, ay):
    """anchor -> anchor+WELL_W (a relative '+10' in tape terms: WELL_W '>')."""
    assert e.rel is None and e.cursor == WELL_BASE + ay * WELL_W + ax
    assert ay + 1 < WELL_H
    e.emit('>' * WELL_W); e.cursor += WELL_W
    return ax, ay + 1


def home_to_anchor(e, ax, ay):
    """ABSOLUTE: move the data ptr from HOME to the anchor (ax,ay). The compiler
    knows the target absolute index, so this is a normal goto."""
    e.goto(WELL_BASE + ay * WELL_W + ax)


# ---------------------------------------------------------------------------
# RUNTIME-anchor resync variant (when the anchor is NOT known at compile time).
# If a program walked the data pointer by a runtime-dependent amount, the
# compiler cursor would be desynced. We can still re-establish a KNOWN absolute
# cursor WITHOUT knowing the anchor, by scanning to a structural ZERO sentinel.
# With the +1 BIAS, every well cell is >= 1, and the cell just BEFORE the well
# (WELL_BASE-1) is reserved as a 0 sentinel. So '[<]' walks left over nonzero
# well cells and STOPS on the sentinel -> a known absolute cell (WELL_BASE-1).
# After that, e.cursor := WELL_BASE-1 is provably correct regardless of the
# runtime anchor. (Our main macros don't need this because every relative
# section nets zero displacement, keeping anchor_abs valid; this is the fallback
# the prompt asks us to describe and is demonstrated in test_resync.py.)
# ---------------------------------------------------------------------------

def resync_walk_left_to_sentinel(e):
    """Emit '[<]' : walk left while the current cell is nonzero, stopping ON the
    first zero (the reserved sentinel at WELL_BASE-1). Sets the compiler cursor to
    that known absolute cell. Requires: ptr currently somewhere in the BIASED
    well (all cells >=1) with a 0 sentinel immediately left of WELL_BASE."""
    e.emit('[<]')
    e.cursor = WELL_BASE - 1   # provably where '[<]' lands, independent of anchor
    e.rel = None
