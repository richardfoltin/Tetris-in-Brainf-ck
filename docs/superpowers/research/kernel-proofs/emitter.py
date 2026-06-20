"""
"Pointer rides the well" macro emitter + proof harness.

LAYOUT (absolute tape):
  [0]            : HOME / cursor-sync cell (structural, always reachable absolutely)
  [1]            : RET  scratch (used by absolute primitives)
  [2..6]         : general scratch t0..t4 (absolute regime)
  [10 .. 10+199] : the WELL, 200 cells, 10 wide x 20 tall, row-major.
                   well[y*10+x] lives at absolute (WELL_BASE + y*10 + x).

BIAS: every well cell stores logical+1.  Empty=1, ids=2..8, and 0 is reserved
as a structural / out-of-bounds delimiter so that a [..] loop over a well cell
always terminates and we can distinguish "empty" (1) from "0=delimiter".

Two cursor regimes
==================
ABSOLUTE regime: self.cursor is the known absolute tape index of the data ptr.
   goto(abs) emits exact > / < to move cursor to abs.

RELATIVE section: entered with anchor() once the data ptr physically sits on
   the well anchor cell.  Inside, self.rel is the offset from the anchor and
   absolute goto is FORBIDDEN (asserts).  Emits use rgoto(off) which moves the
   data ptr by relative > / < only.  The section MUST end with self.rel==0
   (ptr back on anchor).  We never need the anchor's absolute value inside.

Resync after a relative section (the crux):
   The runtime anchor index is unknown at compile time, so we cannot just set
   self.cursor to it.  Instead the *physical* contract is: when the relative
   section ends, the data ptr is back exactly on the anchor cell.  To re-enter
   the absolute regime we must restore a KNOWN absolute cursor.  We do that by
   having recorded, at anchor-entry time, the absolute cursor value the
   compiler believed (anchor_abs).  Because every relative move is balanced
   (rel returns to 0), the physical ptr is again at exactly that same absolute
   cell -- the compiler's bookkeeping (anchor_abs) is therefore STILL VALID.
   So resync = restore self.cursor = anchor_abs, self.rel = None.  This is
   sound precisely because the net pointer displacement over the section is 0,
   which we enforce.  (If the anchor itself were computed at runtime and the
   compiler genuinely did not know it, we'd instead resync by walking home: a
   '[<]'-to-a-zero-sentinel scan; that variant is discussed in the report.)
"""

WELL_W = 10
WELL_H = 20
WELL_N = WELL_W * WELL_H

HOME = 0
RET = 1
T0, T1, T2, T3, T4 = 2, 3, 4, 5, 6

# LAYOUT: leave room on BOTH sides of the well for an 18-cell scan strip so the
# gather pass for an anchor near either edge has a NEARBY strip (bounded cost).
#   [0..6]            structural: HOME, RET, T0..T4
#   [PRE_STRIP..+17]  pre-well scan strip (18 cells)
#   [WELL_BASE..+199] the well (200 cells)
#   [POST_STRIP..+17] post-well scan strip (18 cells)
PRE_STRIP = 8                          # 8..25  (18 cells)
WELL_BASE = PRE_STRIP + 18 + 2         # = 28 ; small gap then well 28..227
WELL_N_ = WELL_W * WELL_H
POST_STRIP = WELL_BASE + WELL_N + 2    # strip after well

# Pre-well scratch block: 4 contiguous cells (abs 2..5).
PRE_SCRATCH = T0                  # base = 2, cells 2,3,4,5
# Post-well scratch block: 4 contiguous cells right after the 200-cell well.
POST_SCRATCH = WELL_BASE + WELL_N     # right after the well
POST0 = POST_SCRATCH
POST1 = POST_SCRATCH + 1


def pick_scratch(anchor_abs):
    """Return base of a 2+ cell scratch pair on whichever side of the well is
    closer to the anchor, to bound relative shuttle distance."""
    return pick_scratch4(anchor_abs)


def pick_scratch6(anchor_abs):
    """Return base of a >=6-cell scratch block on whichever side of the well is
    closer to the anchor (the 18-cell PRE/POST strips). Both lie OUTSIDE the
    well, so using them never disturbs well data. Bounds every prelude/epilogue
    absolute shuttle to about half the well height."""
    pre_mid = PRE_STRIP + 9
    post_mid = POST_STRIP + 9
    if abs(anchor_abs - pre_mid) <= abs(anchor_abs - post_mid):
        return PRE_STRIP
    return POST_STRIP


def pick_scratch4(anchor_abs):
    """Return base of a 4-contiguous-cell scratch block on whichever side of the
    well is closer to the anchor. Both sides are OUTSIDE the 200-cell well, so
    using them never disturbs well data."""
    pre = PRE_SCRATCH       # abs 2..5
    post = POST_SCRATCH     # abs 210..213
    # distance measured to the block midpoint
    if abs(anchor_abs - (pre + 1)) <= abs(anchor_abs - (post + 1)):
        return pre
    return post


class Emitter:
    def __init__(self):
        self.code = []
        self.cursor = 0            # absolute index of data ptr (absolute regime)
        self.rel = None            # offset from anchor (relative regime) or None
        self.anchor_abs = None     # absolute cursor remembered at anchor entry

    def emit(self, s):
        self.code.append(s)

    # ---------- absolute regime ----------
    def goto(self, target):
        assert self.rel is None, "absolute goto forbidden inside relative section"
        d = target - self.cursor
        if d > 0:
            self.emit('>' * d)
        elif d < 0:
            self.emit('<' * (-d))
        self.cursor = target

    def clear(self, cell):
        self.goto(cell)
        self.emit('[-]')

    def set_const(self, cell, v):
        self.clear(cell)
        self.goto(cell)
        self.emit('+' * (v & 0xFF))

    def inc(self, cell, v=1):
        self.goto(cell)
        self.emit('+' * v)

    def dec(self, cell, v=1):
        self.goto(cell)
        self.emit('-' * v)

    # ---------- relative regime ----------
    def anchor(self):
        """Declare: data ptr physically sits on the anchor (== current cursor)."""
        assert self.rel is None
        self.anchor_abs = self.cursor
        self.rel = 0

    def rgoto(self, off):
        """Move data ptr to anchor+off using only relative >/<."""
        assert self.rel is not None, "rgoto only inside relative section"
        d = off - self.rel
        if d > 0:
            self.emit('>' * d)
        elif d < 0:
            self.emit('<' * (-d))
        self.rel = off

    def resync(self):
        """End relative section: require ptr back on anchor, restore absolute."""
        assert self.rel == 0, f"must return to anchor before resync (rel={self.rel})"
        self.cursor = self.anchor_abs
        self.rel = None
        self.anchor_abs = None

    def code_str(self):
        return ''.join(self.code)
