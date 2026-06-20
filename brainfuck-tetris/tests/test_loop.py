"""Regression tests for the game-loop assembly (src/loop.py): the feedback
bridge, runtime (piece,rot) dispatch, gravity/lock/spawn, line clear, RNG, and
game init. These run generated Brainfuck through the optimized host VM (fast) or
the reference oracle (authoritative) and assert against host-side ground truth.
"""
import random

import pytest

from src.dsl import Compiler, set_const
from src.oracle import run_bf
from src.game import (
    alloc_memory, cell, W, H, WELL_CELLS, EMPTY, ACTIVE, ANCHOR, LOCKED,
    make_empty_well,
)
from src.driver import alloc_driver
import src.subsystem as S
import src.loop as L
from bf_run import BFVM


def _fresh():
    c = Compiler()
    alloc_memory(c)
    alloc_driver(c)
    L.alloc_loop(c)
    return c


def _run_fast(c, init):
    vm = BFVM(c.build())
    st = vm.run(read_byte=lambda: 0, write_byte=lambda v: None,
                init_tape=init, step_limit=80_000_000)
    return vm.tape, st


def _anchors(c, tape):
    b = c.addr("well")
    return [(i % W, i // W) for i in range(WELL_CELLS)
            if tape[b + i] == ANCHOR]


def _active(c, tape):
    b = c.addr("well")
    return sum(1 for i in range(WELL_CELLS) if tape[b + i] in (ACTIVE, ANCHOR))


def _zeros(c, tape):
    b = c.addr("well")
    return sum(1 for i in range(WELL_CELLS) if tape[b + i] == 0)


# --------------------------------------------------------------- feedback bridge
@pytest.mark.parametrize("piece,rot,px,py", [
    (1, 0, 3, 2), (2, 0, 5, 5), (3, 1, 8, 4), (7, 3, 14, 6),
    (1, 1, 0, 0), (5, 2, 17, 37), (6, 0, 2, 10),
])
def test_read_anchor_recovers_pose(piece, rot, px, py):
    c = _fresh()
    init = S.make_well_with_piece(c, piece, rot, px, py)
    L.emit_read_anchor(c, read_rot=True)
    tape, _, _ = run_bf(c.build(), init_tape=init)
    assert (tape[c.addr("R_PX")], tape[c.addr("R_PY")], tape[c.addr("R_ROT")]) \
        == (px, py, rot)


# --------------------------------------------------------------- dispatch == subsystem
@pytest.mark.parametrize("piece,rot,px,py,mdx,mdy,rotate", [
    (2, 0, 5, 5, 0, 1, False),     # O down
    (2, 0, 0, 5, -1, 0, False),    # O into left wall (blocked)
    (2, 0, 18, 5, 1, 0, False),    # O into right wall (blocked)
    (1, 0, 3, 2, 0, 0, True),      # I rotate
    (3, 0, 8, 4, 0, 0, True),      # T rotate
    (7, 0, 14, 6, 1, 0, False),    # L right
])
def test_dispatch_matches_direct_try_move(piece, rot, px, py, mdx, mdy, rotate):
    nrot = (rot + 1) % 4 if rotate else rot
    # ground truth: the verified subsystem directly
    cg = _fresh()
    ig = S.make_well_with_piece(cg, piece, rot, px, py)
    cg.goto("LEFT_SENT")
    S.emit_try_move(cg, piece, rot, nrot, mdx, mdy)
    tg, _, _ = run_bf(cg.build(), init_tape=ig)
    g_well = [tg[cg.addr("well") + i] for i in range(WELL_CELLS)]
    # under test: runtime dispatch
    ct = _fresh()
    it = S.make_well_with_piece(ct, piece, rot, px, py)
    for n, v in [("R_PIECE", piece), ("R_ROT", rot), ("R_PX", px), ("R_PY", py)]:
        it[ct.addr(n)] = v
    L.emit_dispatch_trymove(ct, mdx, mdy, rotate=rotate)
    tt, _, _ = run_bf(ct.build(), init_tape=it)
    t_well = [tt[ct.addr("well") + i] for i in range(WELL_CELLS)]
    assert t_well == g_well
    assert _zeros(ct, tt) == 0


# --------------------------------------------------------------- line clear
def _ref_clear(rows):
    kept = [r for r in rows if any(v == EMPTY for v in r)]
    nc = H - len(kept)
    return [[EMPTY] * W for _ in range(nc)] + kept, nc


def test_clear_lines_matches_reference():
    random.seed(11)
    for _ in range(4):
        rows = [[random.choice([EMPTY, EMPTY, 2, 3, 5]) for _ in range(W)]
                for _ in range(H)]
        for _ in range(random.randint(1, 4)):
            ry = random.randint(0, H - 1)
            rows[ry] = [random.randint(2, 8) for _ in range(W)]
        c = _fresh()
        b = c.addr("well")
        init = {b + y * W + x: rows[y][x] for y in range(H) for x in range(W)}
        init[c.addr("LEFT_SENT")] = 0
        init[c.addr("RIGHT_SENT")] = 0
        L.emit_clear_lines(c)
        tape, _, _ = run_bf(c.build(), init_tape=init)
        got = [[tape[b + y * W + x] for x in range(W)] for y in range(H)]
        exp, nc = _ref_clear(rows)
        assert got == exp
        if nc < 10:
            assert tape[c.addr("lines_bcd")] == nc


# --------------------------------------------------------------- RNG
def test_next_piece_in_range_and_correct():
    for rng in (7, 38, 0, 255, 100, 250):
        c = _fresh()
        init = {c.addr("rng_state"): rng, c.addr("frame_ctr"): 0}
        L.emit_next_piece(c)
        tape, st = _run_fast(c, init)
        assert st == "ok"
        nxt = tape[c.addr("R_NEXT")]
        assert nxt == ((rng * 5 + 3) & 0xFF) % 7 + 1
        assert 1 <= nxt <= 7


# --------------------------------------------------------------- gravity cycle
def test_gravity_drop_lock_respawn():
    """O dropped from the top reaches the floor, locks (4 cells), and a new
    piece spawns; never any internal zero (no playfield corruption)."""
    c = _fresh()
    init = S.make_well_with_piece(c, 2, 0, L.SPAWN_X, L.SPAWN_Y)
    for n, v in [("R_PIECE", 2), ("R_ROT", 0), ("R_PX", L.SPAWN_X),
                 ("R_PY", L.SPAWN_Y), ("R_NEXT", 2), ("rng_state", 1)]:
        init[c.addr(n)] = v
    set_const(c, "g_t7", 45)
    c.goto("g_t7"); c.emit("[")
    c.goto("frame_ctr"); c.emit("+")
    L.emit_gravity_step(c, with_clear=True)
    c.goto("g_t7"); c.emit("-")
    c.goto("g_t7"); c.emit("]")
    tape, st = _run_fast(c, init)
    assert st == "ok"
    assert _zeros(c, tape) == 0
    # one O locked at the floor (4 cells) + a freshly spawned active piece
    assert sum(1 for i in range(WELL_CELLS)
               if 2 <= tape[c.addr("well") + i] <= 8) == 4
    assert _active(c, tape) == 4
    assert tape[c.addr("R_GAMEOVER")] == 0


# --------------------------------------------------------------- game init
def test_game_init_spawns_and_runs():
    c = _fresh()
    L.emit_game_init(c)
    tape, st = _run_fast(c, None)
    assert st == "ok"
    assert tape[c.addr("running")] == 1
    assert tape[c.addr("R_GAMEOVER")] == 0
    assert len(_anchors(c, tape)) == 1          # exactly one active piece
    assert _active(c, tape) == 4
    assert 1 <= tape[c.addr("R_PIECE")] <= 7
    assert 1 <= tape[c.addr("R_NEXT")] <= 7
