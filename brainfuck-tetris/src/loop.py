"""Game-loop assembly: ties the verified building blocks into a playable,
pure-Brainfuck Tetris.

The keystone is the relative->absolute FEEDBACK BRIDGE (emit_read_anchor): the
verified moving-piece subsystem (src/subsystem.py) keeps the piece pose in well
"shadow" cells at anchor-relative offsets, which cannot be read across the
relative/absolute boundary. Instead of transporting a value out of the relative
section (which would corrupt the contiguous well), we RECONCILE: an unrolled,
COMPILE-TIME-ADDRESSED pass over all 800 well cells finds the unique ANCHOR(10)
cell and writes its (x,y) -- compile-time constants -- into the absolute
registers R_PX/R_PY, and reads R_ROT from that anchor's shadow cell (also a
compile-time address once x,y are known). Built only from verified primitives.

R_PIECE is loop-tracked (set at spawn); it is NOT recoverable from the well
(active markers are 9/10, not the piece id).
"""

from src.dsl import (
    Compiler, clear, set_const, inc, dec, copy, move, eq, neq, if_then_consume,
    if_, while_, mul, add, _ge_const,
)
from src.game import (
    W, H, WELL_CELLS, EMPTY, ACTIVE, ANCHOR, LOCKED, cell, alloc_memory,
    check_no_overlap, init_well, emit_render_well,
)
from src.driver import alloc_driver, emit_decode_input
import src.subsystem as S
from src.subsystem import SH_ROT, SH_BIAS, footprint
from src.dsl import emit_str

# ---------------------------------------------------------------------------
# Extra loop registers (allocated AFTER the core map + driver cells).
# ---------------------------------------------------------------------------
LOOP_CELLS = [
    ("R_MOVED", 1),      # set by gravity step: 1 if the down-move happened
    ("R_OLDPY", 1),      # py before a move attempt (for move-success compare)
    ("R_GAMEOVER", 1),   # 1 once the well tops out
    ("R_LINES_F", 1),    # rows cleared this lock (0..4)
    ("running", 1),      # main-loop condition (1 = keep playing)
    ("do_grav", 1),      # this frame's "apply gravity" flag
    ("g_t0", 1), ("g_t1", 1), ("g_t2", 1), ("g_t3", 1),
    ("g_t4", 1), ("g_t5", 1), ("g_t6", 1), ("g_t7", 1),
]

DROP_PERIOD = 12     # gravity ticks per cell-fall (host runs ~30 fps)
RNG_SEED = 7


def alloc_loop(c):
    for name, size in LOOP_CELLS:
        if name not in c.names:
            c.alloc(name, size)
    return c


# ---------------------------------------------------------------------------
# FEEDBACK BRIDGE: read the active piece pose out of the well into registers.
# ---------------------------------------------------------------------------
def emit_read_anchor(c, read_rot=False):
    """Scan all 800 well cells (compile-time addresses); for the unique cell that
    holds ANCHOR(10), set R_PX=x, R_PY=y. If read_rot, also read R_ROT from that
    anchor's shadow cell (compile-time address once x,y are known) -- this is the
    expensive part (a far goto emitted per cell), so callers that don't change the
    rotation (left/right/down) leave it off.

    Pre: cursor known (absolute). Post: cursor on R_PX. Non-destructive on the
    well. If no anchor exists the registers keep their previous values."""
    for y in range(H):
        for x in range(W):
            cc = cell(c, x, y)
            copy(c, cc, "g_t0", "g_t1")          # g_t0 = well[x,y]
            set_const(c, "g_t2", ANCHOR)         # g_t2 = 10 (preserved by eq)
            eq(c, "g_t3", "g_t0", "g_t2", "g_t4", "g_t5")  # g_t3 = (cell==10)

            def _body(x=x, y=y, cc=cc):
                set_const(c, "R_PX", x)
                set_const(c, "R_PY", y)
                if read_rot:
                    copy(c, cc + SH_ROT, "R_ROT", "g_t0")
                    dec(c, "R_ROT", SH_BIAS)     # unbias

            if_then_consume(c, "g_t3", _body)
    c.goto("R_PX")
    c.assert_cursor("R_PX")
    return c


# ---------------------------------------------------------------------------
# Runtime (piece, rot) dispatch over the verified emit_try_move.
# ---------------------------------------------------------------------------
def emit_dispatch_trymove(c, mdx, mdy, rotate=False, readback=True):
    """Attempt one move/rotate on the active piece, selecting the correct
    footprint by branching on (R_PIECE, R_ROT) at runtime. After the attempt,
    refresh R_PX/R_PY/R_ROT from the well (the bridge).

    Pre: cursor known. Post: cursor on R_PX (if readback) else LEFT_SENT-ish.
    rotate=True uses nrot=(rot+1)%4; otherwise nrot=rot."""
    for p in range(1, 8):
        copy(c, "R_PIECE", "g_t0", "g_t1")
        set_const(c, "g_t1", p)
        eq(c, "g_t2", "g_t0", "g_t1", "g_t3", "g_t4")   # g_t2 = (R_PIECE==p)

        def _pbody(p=p):
            for r in range(4):
                copy(c, "R_ROT", "g_t0", "g_t1")
                set_const(c, "g_t1", r)
                eq(c, "g_t5", "g_t0", "g_t1", "g_t3", "g_t4")   # g_t5=(R_ROT==r)
                nrot = (r + 1) % 4 if rotate else r

                def _rbody(p=p, r=r, nrot=nrot):
                    c.goto("LEFT_SENT")
                    S.emit_try_move(c, p, r, nrot, mdx, mdy)

                if_then_consume(c, "g_t5", _rbody)

        if_then_consume(c, "g_t2", _pbody)

    if readback:
        # only a rotation changes R_ROT; left/right/down keep it, so skip the
        # (expensive) shadow read on those.
        emit_read_anchor(c, read_rot=rotate)
    return c


# ---------------------------------------------------------------------------
# Spawn position (anchor) for a fresh piece.
# ---------------------------------------------------------------------------
SPAWN_X = 8
SPAWN_Y = 0


def emit_dispatch_lock(c):
    """Lock the active piece into LOCKED(piece) cells, selecting footprint by
    (R_PIECE, R_ROT). No read-back (no anchor remains). Post: cursor LEFT_SENT."""
    for p in range(1, 8):
        copy(c, "R_PIECE", "g_t0", "g_t1")
        set_const(c, "g_t1", p)
        eq(c, "g_t2", "g_t0", "g_t1", "g_t3", "g_t4")

        def _pbody(p=p):
            for r in range(4):
                copy(c, "R_ROT", "g_t0", "g_t1")
                set_const(c, "g_t1", r)
                eq(c, "g_t5", "g_t0", "g_t1", "g_t3", "g_t4")

                def _rbody(p=p, r=r):
                    c.goto("LEFT_SENT")
                    S.emit_lock_only(c, p, r)

                if_then_consume(c, "g_t5", _rbody)

        if_then_consume(c, "g_t2", _pbody)
    c.goto("LEFT_SENT")
    return c


def _emit_gameover_check(c, piece):
    """If any spawn cell of `piece` (rot 0) at SPAWN is already occupied
    (not EMPTY), set R_GAMEOVER = 1. Cursor known in/out."""
    for (dx, dy) in footprint(piece, 0):
        cc = cell(c, SPAWN_X + dx, SPAWN_Y + dy)
        copy(c, cc, "g_t0", "g_t1")
        set_const(c, "g_t1", EMPTY)
        neq(c, "g_t5", "g_t0", "g_t1", "g_t3", "g_t4")   # g_t5 = (cell != EMPTY)
        if_then_consume(c, "g_t5", lambda: set_const(c, "R_GAMEOVER", 1))
    return c


def emit_dispatch_spawn(c):
    """Spawn R_NEXT as the new active piece (rot 0) at SPAWN; set
    R_PIECE/R_ROT/R_PX/R_PY; flag game-over if the spawn area is blocked.
    Post: cursor LEFT_SENT-ish then registers set."""
    copy(c, "R_NEXT", "R_PIECE", "g_t0")
    set_const(c, "R_ROT", 0)
    set_const(c, "R_PX", SPAWN_X)
    set_const(c, "R_PY", SPAWN_Y)
    for np in range(1, 8):
        copy(c, "R_PIECE", "g_t0", "g_t1")
        set_const(c, "g_t1", np)
        eq(c, "g_t2", "g_t0", "g_t1", "g_t3", "g_t4")

        def _b(np=np):
            c.goto("LEFT_SENT")
            _emit_gameover_check(c, np)
            S.emit_spawn_only(c, np, SPAWN_X, SPAWN_Y)

        if_then_consume(c, "g_t2", _b)
    return c


def emit_gravity_step(c, with_clear=True):
    """One gravity tick: try to move the piece down. If it could not (py
    unchanged), lock it, clear full lines, and spawn the next piece. Cursor
    known in/out (ends on R_PX via read-back inside dispatch, or after spawn)."""
    copy(c, "R_PY", "R_OLDPY", "g_t0")            # save py
    emit_dispatch_trymove(c, 0, 1, rotate=False)  # attempt down; readback updates py
    copy(c, "R_PY", "g_t2", "g_t0")
    eq(c, "g_t6", "g_t2", "R_OLDPY", "g_t0", "g_t1")   # g_t6 = (py == oldpy) = blocked

    def _lock():
        emit_dispatch_lock(c)
        if with_clear:
            emit_clear_lines(c)
        emit_dispatch_spawn(c)
        emit_next_piece(c)

    if_then_consume(c, "g_t6", _lock)
    c.goto("R_PX")
    return c


# ---------------------------------------------------------------------------
# RNG: next piece (LCG mixed with the free-running frame counter, then mod 7).
# ---------------------------------------------------------------------------
def emit_next_piece(c):
    """R_NEXT = (advance(rng_state) mod 7) + 1. Mixes frame_ctr for entropy."""
    rng = c.addr("rng_state")            # first of 2 cells used as the byte state
    set_const(c, "g_t0", 5)
    mul(c, rng, "g_t0", "g_t1", "g_t2")  # rng *= 5
    inc(c, rng, 3)                       # rng += 3
    add(c, rng, "frame_ctr", "g_t0")     # rng += frame_ctr (player-timing entropy)
    copy(c, rng, "g_t0", "g_t1")         # g_t0 = rng
    # reduce g_t0 mod 7
    _ge_const(c, "g_t0", 7, "g_t5", "g_t1", "g_t2", "g_t3", "g_t4")
    c.goto("g_t5"); c.emit("[")
    c.goto("g_t0"); c.emit("-" * 7)
    _ge_const(c, "g_t0", 7, "g_t5", "g_t1", "g_t2", "g_t3", "g_t4")
    c.goto("g_t5"); c.emit("]")
    c.goto("g_t5")
    copy(c, "g_t0", "R_NEXT", "g_t1")
    inc(c, "R_NEXT", 1)                  # 1..7
    return c


# ---------------------------------------------------------------------------
# BCD increment (LSD-first) with ripple carry.
# ---------------------------------------------------------------------------
def emit_bcd_inc(c, base_name, n):
    """Add 1 to the n-digit LSD-first BCD number at base_name."""
    base = c.addr(base_name)
    inc(c, base, 1)
    for i in range(n - 1):
        di = base + i
        dn = base + i + 1
        copy(c, di, "g_t0", "g_t1")
        set_const(c, "g_t1", 10)
        eq(c, "g_t2", "g_t0", "g_t1", "g_t3", "g_t4")   # digit == 10 ?

        def _carry(di=di, dn=dn):
            set_const(c, di, 0)
            inc(c, dn, 1)

        if_then_consume(c, "g_t2", _carry)
    return c


# ---------------------------------------------------------------------------
# Line clear: remove full rows (shift rows above down), bump lines + score.
# ---------------------------------------------------------------------------
def emit_clear_lines(c):
    """Detect & remove full rows. Pre/post: cursor known. At call time the well
    holds only locked cells (no active markers), empty == EMPTY(1)."""
    for y in range(H):
        set_const(c, "g_t6", 1)          # full = True
        for x in range(W):
            copy(c, cell(c, x, y), "g_t0", "g_t1")
            set_const(c, "g_t1", EMPTY)
            eq(c, "g_t2", "g_t0", "g_t1", "g_t3", "g_t4")   # cell == EMPTY ?
            if_then_consume(c, "g_t2", lambda: set_const(c, "g_t6", 0))

        def _do_clear(y=y):
            # shift rows above down: row yy <- row yy-1, for yy=y..1. Use
            # clear+move (no far tmp) -> small gotos, compact BF. move leaves the
            # source 0, which the next-higher move overwrites; row 0 ends 0 and is
            # set to EMPTY below, so no internal zero remains.
            for yy in range(y, 0, -1):
                for x in range(W):
                    clear(c, cell(c, x, yy))
                    move(c, cell(c, x, yy - 1), cell(c, x, yy))
            for x in range(W):
                set_const(c, cell(c, x, 0), EMPTY)
            emit_bcd_inc(c, "lines_bcd", 3)
            emit_bcd_inc(c, "score_bcd", 6)

        if_then_consume(c, "g_t6", _do_clear)
    return c


# ---------------------------------------------------------------------------
# HUD / finale text output.
# ---------------------------------------------------------------------------
def emit_print_bcd(c, base_name, n):
    """Print the n-digit LSD-first BCD number at base_name as decimal (MSD
    first), all digits (with leading zeros). Uses ansi_scratch + g_t0."""
    base = c.addr(base_name)
    for i in range(n - 1, -1, -1):
        copy(c, base + i, "ansi_scratch", "g_t0")   # ansi_scratch = digit
        c.goto("ansi_scratch")
        c.emit("+" * 48); c.emit(".")               # output '0'+digit
        clear(c, "ansi_scratch")
    return c


def emit_render_frame(c):
    """Draw one frame: home cursor + the 800-cell well (glyphs) + a HUD line.
    The HUD ends with ESC[K (clear its tail) and NO trailing newline -- a newline
    on the last line would advance the cursor and scroll the whole board up one
    row every frame (that scroll is what smeared the score into several copies)."""
    emit_render_well(c)                              # ESC[H + 40 rows of glyphs
    emit_str(c, "LINES ", "ansi_scratch")
    emit_print_bcd(c, "lines_bcd", 3)
    emit_str(c, "  SCORE ", "ansi_scratch")
    emit_print_bcd(c, "score_bcd", 6)
    emit_str(c, "\x1b[K", "ansi_scratch")           # clear HUD tail; no newline
    return c


def emit_finale(c):
    """After the loop: clear screen, print GAME OVER + final score."""
    emit_str(c, "\x1b[2J\x1b[H", "ansi_scratch")
    emit_str(c, "GAME OVER\r\n", "ansi_scratch")
    emit_str(c, "LINES ", "ansi_scratch")
    emit_print_bcd(c, "lines_bcd", 3)
    emit_str(c, "\r\nSCORE ", "ansi_scratch")
    emit_print_bcd(c, "score_bcd", 6)
    emit_str(c, "\r\n", "ansi_scratch")
    return c


# ---------------------------------------------------------------------------
# Game init + main loop.
# ---------------------------------------------------------------------------
def emit_game_init(c):
    """Fill the well, seed RNG, spawn the first piece, set the preview, and
    initialize all counters/flags. Cursor known on exit."""
    init_well(c)                                    # well := EMPTY (cursor RIGHT_SENT)
    for name in ("score_bcd",):
        for i in range(6):
            set_const(c, c.addr(name) + i, 0)
    for i in range(3):
        set_const(c, c.addr("lines_bcd") + i, 0)
    set_const(c, "level", 0)
    set_const(c, "frame_ctr", 0)
    set_const(c, "gravity_tick", 0)
    set_const(c, "drop_period", DROP_PERIOD)
    set_const(c, "R_GAMEOVER", 0)
    set_const(c, "rng_state", RNG_SEED)
    set_const(c, c.addr("rng_state") + 1, 0)
    emit_next_piece(c)                              # R_NEXT = first piece
    emit_dispatch_spawn(c)                          # spawn it; R_PIECE/PX/PY/ROT set
    emit_next_piece(c)                              # R_NEXT = preview
    set_const(c, "R_GAMEOVER", 0)                   # spawn on empty well never tops out
    set_const(c, "running", 1)
    return c


def emit_main_loop(c):
    """The per-frame loop: render -> input -> moves -> gravity -> repeat, until
    game over or quit."""
    c.goto("running")
    c.emit("[")

    # --- input (one ',' per frame; the host paces the frame here) ---
    c.goto("input_last"); c.emit(",")
    emit_decode_input(c, "input_last")

    # --- horizontal + rotate ---
    if_then_consume(c, "F_LEFT", lambda: emit_dispatch_trymove(c, -1, 0))
    if_then_consume(c, "F_RIGHT", lambda: emit_dispatch_trymove(c, 1, 0))
    if_then_consume(c, "F_ROT", lambda: emit_dispatch_trymove(c, 0, 0, rotate=True))

    # --- gravity: fire if soft-drop held OR the drop timer elapsed ---
    inc(c, "gravity_tick", 1)
    # do_grav = F_SOFT
    copy(c, "F_SOFT", "do_grav", "g_t0")
    # if gravity_tick >= drop_period: gravity_tick = 0 ; do_grav = 1
    _ge_const(c, "gravity_tick", DROP_PERIOD, "g_t5", "g_t1", "g_t2", "g_t3", "g_t4")

    def _timer_elapsed():
        set_const(c, "gravity_tick", 0)
        set_const(c, "do_grav", 1)

    if_then_consume(c, "g_t5", _timer_elapsed)
    if_then_consume(c, "do_grav", lambda: emit_gravity_step(c, with_clear=True))

    # --- render the resulting frame ---
    emit_render_frame(c)

    # --- frame counter (RNG entropy) ---
    inc(c, "frame_ctr", 1)

    # --- loop condition: stop on game over or quit ---
    copy(c, "R_GAMEOVER", "g_t0", "g_t1")
    if_then_consume(c, "g_t0", lambda: set_const(c, "running", 0))
    copy(c, "F_QUIT", "g_t0", "g_t1")
    if_then_consume(c, "g_t0", lambda: set_const(c, "running", 0))

    c.goto("running")
    c.emit("]")
    c.goto("running")
    return c


def build_full_game(c=None):
    """Allocate memory, assemble init + main loop + finale. Returns the
    compiler (call c.build() for the .bf)."""
    if c is None:
        c = Compiler()
    alloc_memory(c)
    alloc_driver(c)
    alloc_loop(c)
    check_no_overlap(c)
    emit_str(c, "\x1b[2J\x1b[?25l", "ansi_scratch")   # clear + hide cursor
    emit_game_init(c)
    emit_main_loop(c)
    emit_finale(c)
    emit_str(c, "\x1b[?25h", "ansi_scratch")          # show cursor
    return c

