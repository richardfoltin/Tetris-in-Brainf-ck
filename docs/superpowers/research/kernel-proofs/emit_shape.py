"""
emit_shape: compile-time NESTED BRANCH DISPATCH for tetromino shape fetching.

NO runtime-indexed table. We emit a nested switch:
  outer 7-way switch on the runtime `piece` (1..7),
  inner 4-way switch on the runtime `rot` (0..3, used as rot+1 internally),
and on the single matching (piece,rot) leaf we set the four constant 4-bit row
masks into out0..out3. 28 leaves total; per OPERATION we walk one piece cascade
(<=7 steps) and, inside the matched piece, one rot cascade (<=4 steps) -- NOT 28
eq-compares against the runtime value.

WHY IT'S CHEAP
--------------
A naive "compare runtime value against each constant" costs O(N * value) because
every eq() copies+subtracts. Instead each switch is ONE decrement walk over a
working copy of the value (switch_cascade): per candidate we test (work == 1)
and, on the match, fire the body and zero work so all later candidates are
skipped. Total work ~ O(value + N) with a tiny constant -> low hundreds of steps
per switch, low thousands for the whole nested dispatch.

+1 BIAS on rotation
-------------------
rot is 0-based (0..3). The cascade matches values 1..N, so internally we use
wr = rot + 1 (candidate k = rot+1). This also defuses the classic empty-cell
failure mode: a zero/empty cell never spuriously matches a rotation, because the
bias means a real rotation is always >= 1 and an empty input (wr would need to
be 0 before bias) maps cleanly to "no match" if piece is also empty.

POINTER MODEL / RESYNC
----------------------
A goto-emitter Compiler tracks the data pointer at COMPILE TIME (Compiler.cursor)
and goto(target) emits the EXACT >/< (never hand-counted). Every loop is balanced
so the runtime pointer is back where the compiler thinks it is after each loop;
every branch body is pointer-neutral (returns the cursor to where it started).
Therefore, no matter WHICH runtime branch fires, the final cursor is identical at
compile time. The macro ends with goto('home') + assert_cursor('home'), which
statically proves the runtime data pointer is resynced to the absolute home cell.
"""


class Compiler:
    def __init__(self, names, tape_size=512):
        self.cells = dict(names)
        self.tape_size = tape_size
        self.cursor = 0
        self.buf = []

    def emit(self, s):
        if ">" in s or "<" in s:
            raise ValueError("raw >/< forbidden; use goto()")
        self.buf.append(s)

    def _raw_move(self, s):
        self.buf.append(s)

    def code(self):
        return "".join(self.buf)

    def addr(self, name):
        return self.cells[name] if isinstance(name, str) else name

    def goto(self, name):
        target = self.addr(name)
        if not (0 <= target < self.tape_size):
            raise ValueError(f"target {target} out of tape")
        delta = target - self.cursor
        if delta > 0:
            self._raw_move(">" * delta)
        elif delta < 0:
            self._raw_move("<" * (-delta))
        self.cursor = target
        return self

    def assert_cursor(self, name):
        target = self.addr(name)
        if self.cursor != target:
            raise AssertionError(
                f"cursor desync: at {self.cursor}, expected {target}")
        return self

    # ---- verified primitives ----
    def clear(self, name):
        self.goto(name); self.emit("[-]"); return self

    def set_const(self, name, v):
        self.clear(name); self.emit("+" * (v & 0xFF)); return self

    def inc(self, name, n=1):
        self.goto(name); self.emit("+" * n); return self

    def dec(self, name, n=1):
        self.goto(name); self.emit("-" * n); return self

    def move(self, src, dst):
        """dst += src; src -> 0 (dst NOT cleared first). Ends at src."""
        self.goto(src)
        self.emit("[")
        self.goto(dst); self.emit("+")
        self.goto(src); self.emit("-")
        self.emit("]")
        self.goto(src)
        return self

    def copy(self, src, dst, tmp):
        """dst = src (src preserved) via tmp. dst,tmp cleared first. Ends at tmp."""
        self.clear(dst); self.clear(tmp)
        self.goto(src)
        self.emit("[")
        self.goto(dst); self.emit("+")
        self.goto(tmp); self.emit("+")
        self.goto(src); self.emit("-")
        self.emit("]")
        self.goto(tmp)
        self.emit("[")
        self.goto(src); self.emit("+")
        self.goto(tmp); self.emit("-")
        self.emit("]")
        self.goto(tmp)
        return self


def if_then_consume(c, flag, body):
    """if flag != 0: flag = 0; body(). flag consumed. body MUST be
    pointer-neutral (enters & leaves cursor at `flag`). Ends at `flag`."""
    c.goto(flag)
    c.emit("[")
    c.goto(flag); c.emit("[-]")
    body()
    c.goto(flag)
    c.emit("]")
    c.goto(flag)
    return


def is_zero(c, x, out, t):
    """out = (x == 0) ? 1 : 0. x preserved. t scratch (left 0). Ends at `out`.

    Move x into t (x->0). Set out=1. Then drain t back into x; on the FIRST
    drained unit set out=0 (so out becomes 0 iff x was nonzero). The 'set out=0'
    must run only once -> we use out[-] which is idempotent (clears to 0)."""
    c.clear(t)
    c.move(x, t)                      # t = x ; x = 0   (ends at x)
    c.set_const(out, 1)              # assume zero
    c.goto(t)
    c.emit("[")                       # entered iff t != 0  (i.e. x was nonzero)
    c.goto(out); c.emit("[-]")        # out = 0 (idempotent, fine to repeat)
    c.goto(x); c.emit("+")            # restore one unit to x
    c.goto(t); c.emit("-")            # t -= 1
    c.goto(t)
    c.emit("]")                       # t now 0, x fully restored
    c.goto(out)
    return


def switch_cascade(c, work, candidates, g, m, t):
    """Exact-match switch over cell `work` (destructive; work -> 0 at end).

    candidates: list of (k, body_fn), k = 1-based, increasing, gapless from 1.
    body_k fires exactly once iff `work` originally == k. `work` outside 1..N
    fires nothing. Pointer-neutral (ends at `work`). body_fn must be
    pointer-neutral.

    Per candidate (g = guard, m = match flag, t = is_zero scratch):
        g = (work != 0)              # still searching? (work preserved)
        if g:  (consume g)
            work -= 1                # guarded -> no underflow past 0
            m = (work == 0)          # original == k  ->  match
            if m: body_k             # (consume m)
    Once work reaches 0 it stays 0 (g==0 skips the decrement), so at most one
    body fires and later candidates are nearly free.
    """
    for (k, body) in candidates:
        # g = work (copy): g is nonzero iff work is nonzero (work preserved).
        c.set_const(g, 0)
        c.clear(t)
        c.goto(work)
        c.emit("[")                   # drain work into g and t
        c.goto(g); c.emit("+")
        c.goto(t); c.emit("+")
        c.goto(work); c.emit("-")
        c.goto(work)
        c.emit("]")                   # work now 0
        c.goto(t)                     # refill work from t
        c.emit("[")
        c.goto(work); c.emit("+")
        c.goto(t); c.emit("-")
        c.goto(t)
        c.emit("]")                   # t = 0, work restored
        # if g (work was nonzero): consume g; work -= 1; m=(work==0); if m: body
        c.goto(g)
        c.emit("[")
        c.goto(g); c.emit("[-]")      # consume g (runs body once)
        c.goto(work); c.emit("-")     # work -= 1  (work was >= 1, no underflow)
        is_zero(c, work, m, t)        # m = (work == 0)
        if_then_consume(c, m, body)
        c.goto(g)
        c.emit("]")                   # g == 0 -> exit
        c.goto(work)
    c.clear(work)
    c.goto(work)
    return


# ---------------------------------------------------------------------------
# Tetromino mask data: SHAPES[piece][rot] = (m0,m1,m2,m3) 4-bit row masks.
# bit 3 (value 8) = leftmost column, bit 0 (value 1) = rightmost. Row 0 = top.
# Pieces: 1=I 2=O 3=T 4=S 5=Z 6=J 7=L ; rotations 0..3 clockwise.
# ---------------------------------------------------------------------------
SHAPES = {
    1: [  # I
        (0b0000, 0b1111, 0b0000, 0b0000),
        (0b0100, 0b0100, 0b0100, 0b0100),
        (0b0000, 0b0000, 0b1111, 0b0000),
        (0b0010, 0b0010, 0b0010, 0b0010),
    ],
    2: [  # O
        (0b0110, 0b0110, 0b0000, 0b0000),
        (0b0110, 0b0110, 0b0000, 0b0000),
        (0b0110, 0b0110, 0b0000, 0b0000),
        (0b0110, 0b0110, 0b0000, 0b0000),
    ],
    3: [  # T
        (0b0100, 0b1110, 0b0000, 0b0000),
        (0b0100, 0b0110, 0b0100, 0b0000),
        (0b0000, 0b1110, 0b0100, 0b0000),
        (0b0100, 0b1100, 0b0100, 0b0000),
    ],
    4: [  # S
        (0b0110, 0b1100, 0b0000, 0b0000),
        (0b0100, 0b0110, 0b0010, 0b0000),
        (0b0000, 0b0110, 0b1100, 0b0000),
        (0b1000, 0b1100, 0b0100, 0b0000),
    ],
    5: [  # Z
        (0b1100, 0b0110, 0b0000, 0b0000),
        (0b0010, 0b0110, 0b0100, 0b0000),
        (0b0000, 0b1100, 0b0110, 0b0000),
        (0b0100, 0b1100, 0b1000, 0b0000),
    ],
    6: [  # J
        (0b1000, 0b1110, 0b0000, 0b0000),
        (0b0110, 0b0100, 0b0100, 0b0000),
        (0b0000, 0b1110, 0b0010, 0b0000),
        (0b0100, 0b0100, 0b1100, 0b0000),
    ],
    7: [  # L
        (0b0010, 0b1110, 0b0000, 0b0000),
        (0b0100, 0b0100, 0b0110, 0b0000),
        (0b0000, 0b1110, 0b1000, 0b0000),
        (0b1100, 0b0100, 0b0100, 0b0000),
    ],
}


NAMES = {
    "home": 0,
    "piece": 1,     # runtime input: piece id 1..7 (0/other => empty)
    "rot": 2,       # runtime input: rotation 0..3
    "out0": 3,
    "out1": 4,
    "out2": 5,
    "out3": 6,
    "wp": 7,        # working copy of piece
    "wr": 8,        # working copy of rot+1
    "tmp": 9,       # copy scratch (inner)
    "tmp2": 10,     # copy scratch (outer-safe)
    "s0": 11,       # OUTER cascade scratch (guard)
    "s1": 12,       # OUTER cascade scratch (match)
    "s2": 13,       # OUTER cascade scratch (is_zero tmp)
    "t0": 14,       # INNER cascade scratch (guard)
    "t1": 15,       # INNER cascade scratch (match)
    "t2": 16,       # INNER cascade scratch (is_zero tmp)
}


def emit_shape(c: Compiler):
    """Nested switch dispatch. Reads piece (1..7), rot (0..3); writes out0..out3.
    Default (no match) => all-zero masks. Pointer-neutral: ends at 'home'."""
    c.clear("out0"); c.clear("out1"); c.clear("out2"); c.clear("out3")

    def set_masks(masks):
        c.set_const("out0", masks[0])
        c.set_const("out1", masks[1])
        c.set_const("out2", masks[2])
        c.set_const("out3", masks[3])

    c.copy("piece", "wp", "tmp")          # working copy (piece preserved)

    piece_cands = []
    for piece in range(1, 8):
        def piece_body(piece=piece):
            c.copy("rot", "wr", "tmp2")   # tmp2: distinct from outer 'tmp'
            c.inc("wr", 1)                # +1 BIAS: rot 0 -> candidate 1
            rot_cands = [
                (rot + 1, (lambda m=SHAPES[piece][rot]: set_masks(m)))
                for rot in range(4)
            ]
            switch_cascade(c, "wr", rot_cands, "t0", "t1", "t2")  # inner scratch
        piece_cands.append((piece, piece_body))

    switch_cascade(c, "wp", piece_cands, "s0", "s1", "s2")

    c.goto("home")
    c.assert_cursor("home")
    return c
