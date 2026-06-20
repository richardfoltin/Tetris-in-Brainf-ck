"""BF Tetris memory map + game assembly.

Layout philosophy (matches tests/memory_map.txt and the verified runtime
subsystem): a small block of absolutely-reachable registers + scratch, then the
ANSI/print/asm working area, then a SINGLE LEFT SENTINEL immediately left of a
CONTIGUOUS 800-cell well (20x40, biased encoding), then a RIGHT SENTINEL.

The contiguous well + single left sentinel is what makes the relative-pointer
runtime subsystem (scan-to-anchor, relative peeks, '[<]' resync) sound:
LEFT_SENT is the only 0 to the left of the well, every live well cell is >= 1.
"""

from src.dsl import (
    Compiler, copy, set_const, emit_str, switch_cascade, eq, if_then_consume,
    inc, clear, is_zero,
)

# ----------------------------------------------------------------------------
# Board / encoding constants
# ----------------------------------------------------------------------------
W = 20
H = 40
WELL_CELLS = W * H            # 800

EMPTY = 1                     # biased: 0 is reserved for sentinels
LOCK_BIAS = 1                 # locked piece id stored as logical id + LOCK_BIAS
ACTIVE = 9                    # active body marker
ANCHOR = 10                   # active anchor marker (exactly one)


def LOCKED(pid):
    """Logical piece id 1..7 -> stored locked value 2..8."""
    return pid + LOCK_BIAS


# ----------------------------------------------------------------------------
# Region spec (FIXED order). Consumed by alloc_memory + memory-map tests +
# the tests/memory_map.txt dump. Order is load-bearing: LEFT_SENT must sit
# immediately left of `well`, and `well` immediately left of RIGHT_SENT.
# ----------------------------------------------------------------------------
REGION_SPEC = [
    ("R_PX", 1), ("R_PY", 1), ("R_ROT", 1), ("R_PIECE", 1),
    ("R_NEXT", 1), ("R_COLLIDE", 1),
    ("score_bcd", 6), ("lines_bcd", 3), ("level", 1),
    ("gravity_tick", 1), ("drop_period", 1),
    ("rng_state", 2), ("frame_ctr", 1), ("input_last", 1),
    ("logical_ptr", 1),
    ("tmp0", 1), ("tmp1", 1), ("tmp2", 1), ("tmp3", 1),
    ("tmp4", 1), ("tmp5", 1), ("tmp6", 1), ("tmp7", 1),
    ("ansi_scratch", 2), ("print_scratch", 10),
    ("asm_depth", 1), ("asm_buf", 256),
    ("LEFT_SENT", 1), ("well", WELL_CELLS), ("RIGHT_SENT", 1),
    # The moving-piece subsystem's relative scratch/shadow bank rides at
    # anchor + ~804..819. For an anchor anywhere in the well that maps to
    # absolute well_base+804 .. well_base+1618, which MUST be dead, unused tape
    # -- otherwise it clobbers whatever is allocated next (registers!), e.g. the
    # shadow of a piece at (8,0) lands on the loop scratch cells. This pad
    # reserves that whole strip immediately after the well so nothing else is
    # placed there. Keep it the LAST core region: everything allocated afterward
    # (driver + loop cells) then sits safely beyond the scratch reach.
    ("SCRATCH_PAD", WELL_CELLS + 64),
]


def alloc_memory(c):
    """Reserve every region at a fixed absolute base, in REGION_SPEC order.

    Returns a {name: base} layout dict (also recorded in c.names)."""
    layout = {}
    for name, size in REGION_SPEC:
        layout[name] = c.alloc(name, size)
    return layout


def cell(c, x, y):
    """Absolute tape index of well cell (x, y). x in 0..W-1, y in 0..H-1.

    Contiguous stride-W well: cell = base(well) + y*W + x."""
    if not (0 <= x < W):
        raise ValueError("x out of range: %d" % x)
    if not (0 <= y < H):
        raise ValueError("y out of range: %d" % y)
    return c.addr("well") + y * W + x


def check_no_overlap(c):
    """Assert no two regions overlap; also assert the sentinel/well adjacency
    invariants the runtime subsystem depends on."""
    spans = []
    for name, size in REGION_SPEC:
        base = c.addr(name)
        spans.append((base, base + size, name))
    spans.sort()
    for i in range(1, len(spans)):
        prev_b, prev_e, prev_n = spans[i - 1]
        b, e, n = spans[i]
        assert b >= prev_e, "MEMORY OVERLAP: %s[%d:%d] vs %s[%d:%d]" % (
            prev_n, prev_b, prev_e, n, b, e)
    # adjacency invariants
    assert c.addr("LEFT_SENT") + 1 == c.addr("well"), \
        "LEFT_SENT must sit immediately left of well"
    assert c.addr("well") + WELL_CELLS == c.addr("RIGHT_SENT"), \
        "RIGHT_SENT must sit immediately right of well"
    return True


def make_empty_layout():
    """Helper: a fresh compiler with the full memory map allocated."""
    c = Compiler()
    alloc_memory(c)
    return c


def make_empty_well(c):
    """Return an init_tape dict for an empty, sentinel-bracketed well."""
    t = {}
    base = c.addr("well")
    for i in range(WELL_CELLS):
        t[base + i] = EMPTY
    t[c.addr("LEFT_SENT")] = 0
    t[c.addr("RIGHT_SENT")] = 0
    return t


def dump_memory_map(c, out_path):
    """Write a human-readable cell map (name base size end) to out_path."""
    import os
    lines = ["%-18s %5s %6s %6s" % ("name", "base", "size", "end")]
    for name, size in REGION_SPEC:
        base = c.addr(name)
        lines.append("%-18s %5d %6d %6d" % (name, base, size, base + size))
    total = c.addr(REGION_SPEC[-1][0]) + REGION_SPEC[-1][1]
    lines.append("%-18s %5s %6s %6d" % ("TOTAL CELLS", "", "", total))
    d = os.path.dirname(out_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out_path, "w", encoding="ascii", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


# Glyph for each well value when rendering (used by render_well).
_GLYPH = {
    0: " ", EMPTY: ".",
    2: "I", 3: "O", 4: "T", 5: "S", 6: "Z", 7: "J", 8: "L",
    ACTIVE: "#", ANCHOR: "@",
}


def render_well(tape, c):
    """Host-side ASCII render of the well from a tape (for debugging/tests)."""
    base = c.addr("well")
    rows = []
    for y in range(H):
        row = []
        for x in range(W):
            v = tape[base + y * W + x]
            row.append(_GLYPH.get(v, "?"))
        rows.append("".join(row))
    return "\n".join(rows)


# ----------------------------------------------------------------------------
# BF (in-Brainfuck) renderer: emits ANSI that draws the well to the terminal.
# The well IS the tape -- each cell's biased value maps to its BF-command glyph.
#   1 empty=' '  2 I='>'  3 O='<'  4 T='+'  5 S='-'  6 Z='.'  7 J='['  8 L=']'
#   9 active='@'  10 anchor='@'
# ----------------------------------------------------------------------------
GLYPH_BF = {1: 0x20, 2: 0x3e, 3: 0x3c, 4: 0x2b, 5: 0x2d, 6: 0x2e,
            7: 0x5b, 8: 0x5d, 9: 0x40, 10: 0x40}


def init_well(c):
    """Set every well cell to EMPTY (biased 1) by walking the well left->right.
    Ends with the pointer on RIGHT_SENT."""
    c.goto("well", 0)
    c.raw("[-]+>" * WELL_CELLS)           # each cell: clear, +1 (EMPTY), step right
    c.set_cursor("RIGHT_SENT")            # well[0] + WELL_CELLS == RIGHT_SENT
    return c


def _emit_render_cell(c, abs_cell):
    """Output one cell's glyph, cheaply. The glyph keys are exactly the
    contiguous values 1..10, so an early-stopping decrement cascade is both
    correct and fast: `work` is consumed at the match, so later candidates do
    no work (an empty cell, value 1, costs one pass). This avoids both the
    is_zero-on-wrapped-difference trap and running all 10 comparisons per cell.

    Non-destructive on the well cell. work=tmp0, g=tmp2, m=tmp3, t=tmp1."""
    copy(c, abs_cell, "tmp0", "tmp1")          # tmp0 = work = well[cell]
    clear(c, "ansi_scratch")
    for v, byte in GLYPH_BF.items():           # v = 1..10 (contiguous)
        set_const(c, "tmp2", 0)
        clear(c, "tmp1")
        c.goto("tmp0"); c.emit("[")            # g=work, t=work, work=0
        c.goto("tmp2"); c.emit("+")
        c.goto("tmp1"); c.emit("+")
        c.goto("tmp0"); c.emit("-]")
        c.goto("tmp1"); c.emit("[")            # restore work; t=0
        c.goto("tmp0"); c.emit("+")
        c.goto("tmp1"); c.emit("-]")
        c.goto("tmp2"); c.emit("[")            # if work != 0 (not yet matched):
        c.goto("tmp2"); c.emit("[-]")
        c.goto("tmp0"); c.emit("-")            #   work -= 1
        is_zero(c, "tmp0", "tmp3", "tmp1")     #   m = (work == 0) -> this value matched
        if_then_consume(c, "tmp3", lambda byte=byte: inc(c, "ansi_scratch", byte))
        c.goto("tmp2"); c.emit("]")
        c.goto("tmp2")
    c.goto("ansi_scratch")
    c.emit(".")
    clear(c, "ansi_scratch")
    return c


def emit_render_well(c):
    """Emit BF that renders the 800-cell well: ESC[H home, then 40 rows of 20
    biased-cell glyphs. Each row ends with ESC[K (erase to end of line) before
    CR+LF: the rows are only 20 cols wide, so without it anything previously
    drawn past column 20 (e.g. a scrolled HUD's trailing digits) would ghost.
    Static (compile-time) cell reads; non-destructive."""
    emit_str(c, "\x1b[H", "ansi_scratch")
    for y in range(H):
        for x in range(W):
            _emit_render_cell(c, cell(c, x, y))
        emit_str(c, "\x1b[K\r\n", "ansi_scratch")
    return c


def build_game(c=None):
    """Allocate the memory map and return the compiler. (The full game driver
    grows in later phases; for the subsystem integration this establishes the
    layout the runtime subsystem is emitted against.)"""
    if c is None:
        c = Compiler()
    alloc_memory(c)
    check_no_overlap(c)
    return c
