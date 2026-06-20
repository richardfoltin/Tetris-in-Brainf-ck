"""
BF TETRIS -- runtime moving-piece subsystem (A-E), consolidated & self-testing.
Run: python bftetris_all.py   (executes real Brainfuck and asserts A-E).
Contains: BF interpreter (8-bit wrapping, step counter, bounds-checked) +
goto-emitter (compile-time cursor + relative sections) + shapes + all macros.
"""

# ======================================================================
# module: bf
# ======================================================================
"""
Brainfuck interpreter + goto-emitter for BF Tetris.

Interpreter:
  - 8-bit WRAPPING cells (0..0xFF), tape >= 4096 ints
  - ',' returns 0 on EOF
  - '.' collects output bytes
  - STEP COUNTER (counts executed BF commands; loop bracket tests count too)
  - raises on pointer out of [0, tape)
"""

# ----------------------------------------------------------------------------
# Interpreter
# ----------------------------------------------------------------------------

class BFError(Exception):
    pass


def run_bf(src, tape_size=4096, inp=b"", max_steps=50_000_000, init_tape=None):
    """Execute Brainfuck source. Returns (tape, ptr, output_bytes, steps)."""
    # strip to valid commands only
    code = [c for c in src if c in "+-<>[].,"]
    n = len(code)

    # precompute bracket matches
    jump = {}
    stack = []
    for i, c in enumerate(code):
        if c == '[':
            stack.append(i)
        elif c == ']':
            if not stack:
                raise BFError("unmatched ]")
            j = stack.pop()
            jump[i] = j
            jump[j] = i
    if stack:
        raise BFError("unmatched [")

    tape = [0] * tape_size
    if init_tape is not None:
        for k, v in init_tape.items():
            tape[k] = v & 0xFF

    ptr = 0
    ip = 0
    steps = 0
    out = bytearray()
    in_pos = 0

    while ip < n:
        c = code[ip]
        steps += 1
        if steps > max_steps:
            raise BFError(f"step limit {max_steps} exceeded")
        if c == '+':
            tape[ptr] = (tape[ptr] + 1) & 0xFF
        elif c == '-':
            tape[ptr] = (tape[ptr] - 1) & 0xFF
        elif c == '>':
            ptr += 1
            if ptr >= tape_size:
                raise BFError(f"pointer out of range (>= {tape_size})")
        elif c == '<':
            ptr -= 1
            if ptr < 0:
                raise BFError("pointer out of range (< 0)")
        elif c == '.':
            out.append(tape[ptr])
        elif c == ',':
            if in_pos < len(inp):
                tape[ptr] = inp[in_pos]
                in_pos += 1
            else:
                tape[ptr] = 0
        elif c == '[':
            if tape[ptr] == 0:
                ip = jump[ip]
        elif c == ']':
            if tape[ptr] != 0:
                ip = jump[ip]
        ip += 1

    return tape, ptr, bytes(out), steps


# ----------------------------------------------------------------------------
# Goto-emitter
# ----------------------------------------------------------------------------
#
# The emitter tracks a COMPILE-TIME 'cursor': the tape index the data pointer
# is known to be at, statically. goto(target) emits the exact run of >/< to
# move from cursor to target and updates cursor. We NEVER hand-count >/<.
#
# RELATIVE SECTIONS: sometimes the data pointer rides a RUNTIME position that
# the compiler does NOT know (e.g. after a value-scan '[>]' lands on an
# unknown cell). During such a section, cursor is meaningless and the emitter
# refuses absolute goto. You operate with hand-authored relative moves whose
# net displacement you DO know at compile time (e.g. peeking +offset then
# returning -offset). To leave a relative section you must RESYNC: emit a
# proven walk to a known ABSOLUTE cell (e.g. sentinel-walk '[<]' to a 0 cell),
# then call resync(abs_cell) to set cursor back to a known value.

class Emitter:
    def __init__(self):
        self.parts = []
        self.cursor = 0          # known absolute tape index, or None if relative
        self._rel_net = 0        # net displacement accumulated inside a rel section
        self._in_rel = False

    def emit(self, s):
        self.parts.append(s)
        return self

    # -- absolute movement ----------------------------------------------------
    def goto(self, target):
        if self._in_rel:
            raise BFError("goto() called inside a relative section; resync first")
        if self.cursor is None:
            raise BFError("cursor unknown; resync to an absolute cell first")
        d = target - self.cursor
        if d > 0:
            self.emit('>' * d)
        elif d < 0:
            self.emit('<' * (-d))
        self.cursor = target
        return self

    def at(self):
        if self.cursor is None or self._in_rel:
            raise BFError("cursor not known absolutely")
        return self.cursor

    # -- cell ops at current cursor -------------------------------------------
    def add(self, v):
        v &= 0xFF
        if v <= 128:
            self.emit('+' * v)
        else:
            self.emit('-' * (256 - v))
        return self

    def sub(self, v):
        return self.add((-v) & 0xFF)

    def zero(self):
        """Set current cell to 0 via [-]."""
        self.emit('[-]')
        return self

    def setval(self, v):
        self.zero()
        self.add(v)
        return self

    def set_at(self, cell, v):
        self.goto(cell)
        self.setval(v)
        return self

    def add_at(self, cell, v):
        self.goto(cell)
        self.add(v)
        return self

    # -- relative sections ----------------------------------------------------
    def begin_rel(self):
        """Enter a relative section. cursor becomes runtime-unknown."""
        self._in_rel = True
        self._rel_net = 0
        self.cursor = None
        return self

    def rel_move(self, d):
        """Move +d (right) or -d (left) inside a rel section; track net."""
        if not self._in_rel:
            raise BFError("rel_move outside relative section")
        if d > 0:
            self.emit('>' * d)
        elif d < 0:
            self.emit('<' * (-d))
        self._rel_net += d
        return self

    def rel_net(self):
        return self._rel_net

    # -- relative LOCAL-OFFSET addressing -------------------------------------
    # Inside a relative section the data pointer rides a runtime ORIGIN. We
    # track a compile-time LOCAL OFFSET (= _rel_net) from that origin and emit
    # exact >/< for rgoto, exactly like absolute goto but origin-relative.
    def rgoto(self, off):
        """Move so local offset becomes `off` (relative to the rel origin)."""
        if not self._in_rel:
            raise BFError("rgoto outside relative section")
        self.rel_move(off - self._rel_net)
        return self

    def roff(self):
        return self._rel_net

    def radd(self, off, v):
        self.rgoto(off); self.add(v); return self

    def rsub(self, off, v):
        self.rgoto(off); self.sub(v); return self

    def rzero(self, off):
        self.rgoto(off); self.emit('[-]'); return self

    def rset(self, off, v):
        self.rgoto(off); self.emit('[-]'); self.add(v); return self

    def rmove_cell(self, src_off, dst_off):
        """dst_off += src_off; src_off -> 0. (relative move, auto-counted)"""
        self.rgoto(src_off)
        self.emit('[-')
        self.rgoto(dst_off); self.emit('+')
        self.rgoto(src_off); self.emit(']')
        # loop leaves pointer at src_off (its value 0)
        self._rel_net = src_off
        return self

    def rcopy_cell(self, src_off, dst_off, tmp_off):
        """dst = src (src preserved). tmp 0 before/after. relative."""
        self.rzero(dst_off); self.rzero(tmp_off)
        self.rgoto(src_off); self.emit('[-')
        self.rgoto(dst_off); self.emit('+')
        self.rgoto(tmp_off); self.emit('+')
        self.rgoto(src_off); self.emit(']')
        self._rel_net = src_off
        self.rgoto(tmp_off); self.emit('[-')
        self.rgoto(src_off); self.emit('+')
        self.rgoto(tmp_off); self.emit(']')
        self._rel_net = tmp_off
        return self

    def resync(self, abs_cell):
        """
        Declare that the data pointer is now KNOWN to sit on abs_cell (because
        you just emitted a proven absolute walk, e.g. '[<]' to a sentinel).
        Leaves the relative section.
        """
        self._in_rel = False
        self._rel_net = 0
        self.cursor = abs_cell
        return self

    def raw(self, s, cursor_after=None):
        """
        Emit raw BF. If cursor_after is given, declare the absolute cursor
        after this snippet (used for hand-proven movement primitives).
        """
        self.emit(s)
        if cursor_after is not None:
            self.cursor = cursor_after
            self._in_rel = False
        return self

    def code(self):
        return ''.join(self.parts)

# ======================================================================
# module: layout
# ======================================================================
"""
FINAL memory layout for BF Tetris 20x40 (CONTIGUOUS well, single sentinel).

We use a CONTIGUOUS well (no guard column). The active piece is found by a
value-scan (subsystem A), and all well reads are RELATIVE peeks from the anchor
with compile-time offsets dy*W + dx. Resync to absolute is the proven '[<]'
walk to a single LEFT SENTINEL (the only 0 to the left of the well).

Tape map (absolute):
    0 .. 29         : REGISTERS + scratch (small, reachable absolutely)
    LEFT_SENT = 30  : LEFT SENTINEL, always 0  ('[<]' from any well cell -> here)
    WELL_BASE = 31  : well cell (0,0)
    WELL_BASE .. WELL_BASE+799 : the 20x40 = 800 well cells, +1 biased
    RIGHT_SENT = WELL_BASE+800 : RIGHT SENTINEL, always 0 ('[>]' -> here)

Cell addressing (contiguous, STRIDE = W):
    cell(x,y) = WELL_BASE + y*W + x        (x in 0..19, y in 0..39)

Biased encoding:
    0  : RESERVED (sentinels only; never inside well)
    1  : empty
    2..8 : locked piece ids (logical 1..7)
    9  : ACTIVE body marker
    10 : ACTIVE ANCHOR marker (exactly one)
"""

W = 20
H = 40
STRIDE = W                # contiguous
WELL_CELLS = W * H        # 800

REG_PX     = 0    # anchor column 0..W-1
REG_PY     = 1    # anchor row    0..H-1
REG_ROT    = 2    # rotation 0..3
REG_PIECE  = 3    # piece id logical 1..7
REG_COLL   = 4    # collision result (0 = free, 1 = collision)
REG_T0     = 5
REG_T1     = 6
REG_T2     = 7
REG_T3     = 8
REG_T4     = 9
REG_NX     = 10   # candidate x
REG_NY     = 11   # candidate y
REG_NROT   = 12   # candidate rot
REG_CNT    = 13
REG_T5     = 14
REG_T6     = 15
REG_GO     = 16   # wall/floor OK flag (gates the ride)
REG_T7     = 17
REG_T8     = 18
REG_T9     = 19
REG_DXY    = 20   # spare

LEFT_SENT  = 30
WELL_BASE  = 31
RIGHT_SENT = WELL_BASE + WELL_CELLS   # 831

TAPE_SIZE  = 4096

EMPTY  = 1
ACTIVE = 9
ANCHOR = 10
def LOCKED(pid):
    return pid + 1     # logical 1..7 -> 2..8

def cell(x, y):
    return WELL_BASE + y * W + x

def well_index(x, y):
    return y * W + x

def make_empty_well():
    t = {}
    for i in range(WELL_CELLS):
        t[WELL_BASE + i] = EMPTY
    t[LEFT_SENT] = 0
    t[RIGHT_SENT] = 0
    return t

# ======================================================================
# module: shapes
# ======================================================================
"""
Tetromino shapes as 4 (dx,dy) cell offsets RELATIVE TO THE ANCHOR.

The anchor is one of the 4 occupied cells (offset (0,0) is always occupied and
is the anchor). Offsets are small integers; well cell of an occupied square is
cell(px+dx, py+dy) = ANCHOR_CELL + dy*W + dx, a COMPILE-TIME-known tape delta

We provide a Python ground-truth model AND, separately, an inline BF
"emit_shape" is not needed for collision because we hard-emit the 4 offsets
per (piece,rot) at compile time (branch dispatch on piece/rot would just pick
which offset-set to inline). For the proof we drive offsets from this table;
the BF code that gets emitted bakes in the specific offsets for the case under
test, exactly as a per-(piece,rot) branch would.

Standard tetromino set (1..7 = I,O,T,S,Z,J,L). Anchor chosen as a cell present
in all rotations where convenient.
"""

# offsets[piece][rot] = list of 4 (dx,dy); (0,0) included = anchor.
SHAPES = {
    1: {  # I
        0: [(0,0),(1,0),(2,0),(3,0)],     # horizontal, anchor leftmost
        1: [(0,0),(0,1),(0,2),(0,3)],     # vertical
        2: [(0,0),(1,0),(2,0),(3,0)],
        3: [(0,0),(0,1),(0,2),(0,3)],
    },
    2: {  # O
        0: [(0,0),(1,0),(0,1),(1,1)],
        1: [(0,0),(1,0),(0,1),(1,1)],
        2: [(0,0),(1,0),(0,1),(1,1)],
        3: [(0,0),(1,0),(0,1),(1,1)],
    },
    3: {  # T
        0: [(0,0),(1,0),(2,0),(1,1)],     # pointing down
        1: [(1,0),(0,1),(1,1),(1,2)],     # pointing left
        2: [(1,0),(0,1),(1,1),(2,1)],     # pointing up
        3: [(0,0),(0,1),(1,1),(0,2)],     # pointing right
    },
    4: {  # S
        0: [(1,0),(2,0),(0,1),(1,1)],
        1: [(0,0),(0,1),(1,1),(1,2)],
        2: [(1,0),(2,0),(0,1),(1,1)],
        3: [(0,0),(0,1),(1,1),(1,2)],
    },
    5: {  # Z
        0: [(0,0),(1,0),(1,1),(2,1)],
        1: [(1,0),(0,1),(1,1),(0,2)],
        2: [(0,0),(1,0),(1,1),(2,1)],
        3: [(1,0),(0,1),(1,1),(0,2)],
    },
    6: {  # J
        0: [(0,0),(0,1),(1,1),(2,1)],
        1: [(0,0),(1,0),(0,1),(0,2)],
        2: [(0,0),(1,0),(2,0),(2,1)],
        3: [(1,0),(1,1),(0,2),(1,2)],
    },
    7: {  # L
        0: [(2,0),(0,1),(1,1),(2,1)],
        1: [(0,0),(0,1),(0,2),(1,2)],
        2: [(0,0),(1,0),(2,0),(0,1)],
        3: [(0,0),(1,0),(1,1),(1,2)],
    },
}

PIECE_NAMES = {1:'I',2:'O',3:'T',4:'S',5:'Z',6:'J',7:'L'}

# We always make the FIRST offset the anchor. Ensure (it may not be (0,0) for
# some pieces above) -- normalize so anchor = offsets[0], and recompute others
# relative to it. We keep anchor as listed first; offsets relative to that.

def footprint(piece, rot):
    """Return (anchor_local, rel_offsets) where rel_offsets are (dx,dy)
    relative to the anchor (= first listed cell), including (0,0) for anchor."""
    cells = SHAPES[piece][rot]
    ax, ay = cells[0]
    rel = [(x - ax, y - ay) for (x, y) in cells]
    return rel

def occupied_cells(piece, rot, px, py):
    """Absolute (x,y) board coords of the 4 cells given anchor at (px,py)."""
    rel = footprint(piece, rot)
    return [(px + dx, py + dy) for (dx, dy) in rel]

# ======================================================================
# module: regops
# ======================================================================
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

# ======================================================================
# module: scan
# ======================================================================
"""
Subsystem A primitives (contiguous well).

emit_scan_to_anchor: from WELL_BASE move the pointer onto the unique ANCHOR(10)
  cell via a value-scan. Non-destructive. O(cells). Enters a relative section
  with local offset 0 == anchor.

emit_resync_to_left_sentinel: '[<]' walks left while current != 0. Every well
  col cell is >= 1; LEFT_SENT (just left of WELL_BASE) is 0. So '[<]' lands
  exactly on LEFT_SENT. Then we resync the compiler cursor to LEFT_SENT.
"""



def emit_scan_to_anchor(e):
    """Scan to the UNIQUE cell with value EXACTLY 10 (the anchor). Lands on it;
    restores everything. Local offset 0 == anchor."""
    assert e.cursor == WELL_BASE, f"scan must start at WELL_BASE; cursor={e.cursor}"
    e.begin_rel()
    e.emit('-' * ANCHOR)          # cur -= 10
    e.emit('[')                   # while cur != 0 (not the anchor):
    e.emit('+' * ANCHOR)          #   restore this cell
    e.emit('>')                   #   step right
    e.emit('-' * ANCHOR)          #   subtract 10 from new current
    e.emit(']')
    e.emit('+' * ANCHOR)          # restore the anchor cell to 10
    e._rel_net = 0                # define local offset 0 == anchor
    return e


def emit_scan_to_anchor_ge(e, anchor_lo=ANCHOR):
    """
    Scan to the first cell with value >= anchor_lo (used when the anchor may be
    OVERLAID with a transported bit, e.g. 10 or 11). All well non-anchor cells
    are <= 9 < anchor_lo, so it lands on the (overlaid) anchor. Non-destructive.
    Mechanism: subtract (anchor_lo) using the same restore-and-step idiom; a cell
    with value v < anchor_lo gives v-anchor_lo != 0 (it wrapped, nonzero) -> keep
    going; the anchor (>= anchor_lo) ... we need value EXACTLY hitting 0. With
    overlay the anchor is anchor_lo or anchor_lo+1, so subtracting anchor_lo
    gives 0 or 1. We must STOP on either. So we instead stop on the first cell
    whose value, after subtracting (anchor_lo - 1), and a further test, ...
    Simpler: anchors are the ONLY cells >= 10. Stop on first cell with value
    that does NOT become 'still < 0-ish'. We implement: per cell compute
    (value - 9): cells 1..9 -> wraps to 248..0 (cell 9 -> 0!). Conflict.
    => Keep overlay to exactly {10, 11}. Scan for value 10 OR 11 by: subtract 10;
    a non-anchor (1..9) -> 247..255 (nonzero); anchor 10 -> 0 (stop); anchor 11
    -> 1 (NONzero -> would NOT stop). So a +1 overlay breaks the ==10 scan.
    Therefore we transport the wall bit a DIFFERENT way (see tetris.py: we keep
    the anchor EXACTLY 10 and seed ACC from walls via a pre-scan plant at a fixed
    well cell). This function is retained only for the == case.
    """
    return emit_scan_to_anchor(e)


def emit_resync_to_left_sentinel(e):
    """Pre: pointer riding a well cell (relative). Post: pointer on LEFT_SENT."""
    e.emit('[<]')
    e.resync(LEFT_SENT)
    return e

# ======================================================================
# module: tetris
# ======================================================================
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

                    EMPTY, ACTIVE, ANCHOR, LOCKED, REG_PX, REG_PY, REG_ROT,
                    REG_PIECE)

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


# ===========================================================================
# SELF-TEST: prove A-E by executing real Brainfuck.
# ===========================================================================
def _selftest():
    oc = lambda p, r, x, y: [(x + dx, y + dy) for (dx, dy) in footprint(p, r)]
    ok_all = True
    def chk(name, cond, extra=""):
        nonlocal ok_all
        ok_all = ok_all and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {name} {extra}")

    print("A) SCAN-LOCATE")
    for (ax, ay) in [(0, 0), (19, 0), (0, 39), (19, 39), (7, 15)]:
        t0 = make_empty_well(); t0[cell(ax, ay)] = ANCHOR
        e = Emitter(); e.goto(WELL_BASE); emit_scan_to_anchor(e)
        e.emit('[-]'); e.add(200)            # tag landing
        tape, ptr, _, steps = run_bf(e.code(), init_tape=t0)
        chk(f"land on anchor ({ax},{ay})", tape[cell(ax, ay)] == 200, f"steps={steps}")

    print("B/C) MOVE allowed + blocked")
    t = make_well_with_piece(2, 0, 5, 5)
    e = Emitter(); e.goto(LEFT_SENT); emit_try_move(e, 2, 0, 0, 0, 1)
    tape, ptr, _, s = run_bf(e.code(), init_tape=t)
    chk("O down -> anchor moved to (5,6)", tape[cell(5, 6)] == ANCHOR and ptr == LEFT_SENT, f"steps={s}")
    t = make_well_with_piece(2, 0, 0, 5)
    e = Emitter(); e.goto(LEFT_SENT); emit_try_move(e, 2, 0, 0, -1, 0)
    tape, ptr, _, s = run_bf(e.code(), init_tape=t)
    chk("O left into wall -> stays at (0,5)", tape[cell(0, 5)] == ANCHOR, f"steps={s}")
    t = make_well_with_piece(2, 0, 5, 5, [(5, 7, 3), (6, 7, 3)])
    e = Emitter(); e.goto(LEFT_SENT); emit_try_move(e, 2, 0, 0, 0, 1)
    tape, ptr, _, s = run_bf(e.code(), init_tape=t)
    chk("O down into locked -> stays at (5,5)", tape[cell(5, 5)] == ANCHOR, f"steps={s}")

    print("D) LOCK & SPAWN")
    t = make_well_with_piece(2, 0, 5, 38)
    e = Emitter(); e.goto(LEFT_SENT); emit_lock_and_spawn(e, 2, 0, 3, 8, 0)
    tape, ptr, _, s = run_bf(e.code(), init_tape=t)
    locked = all(tape[cell(x, y)] == LOCKED(2) for (x, y) in oc(2, 0, 5, 38))
    spawned = tape[cell(8, 0)] == ANCHOR
    nm = sum(1 for i in range(WELL_CELLS) if tape[WELL_BASE + i] in (ACTIVE, ANCHOR))
    chk("old locked + new spawned + 4 markers", locked and spawned and nm == 4, f"steps={s}")

    print("E) MULTI-FRAME CYCLE (3 frames, one program)")
    e = Emitter(); e.goto(LEFT_SENT)
    emit_try_move(e, 2, 0, 0, 0, 1)
    emit_try_move(e, 2, 0, 0, 0, 1)
    emit_try_move(e, 2, 0, 0, 1, 0)
    tape, ptr, _, s = run_bf(e.code(), init_tape=make_well_with_piece(2, 0, 5, 3))
    nm = sum(1 for i in range(WELL_CELLS) if tape[WELL_BASE + i] in (ACTIVE, ANCHOR))
    chk("anchor at (6,5), 4 markers, resynced", tape[cell(6, 5)] == ANCHOR and nm == 4 and ptr == LEFT_SENT, f"steps={s} ~{s//3}/frame")

    print("\nRESULT:", "ALL PASS" if ok_all else "FAILURES")
    return ok_all


if __name__ == "__main__":
    import sys
    sys.exit(0 if _selftest() else 1)
