from src.dsl import Compiler
from src.game import alloc_memory, emit_render_well, cell, W, H, EMPTY
from src.oracle import run_bf


def _render(well_overrides):
    """Build alloc + emit_render_well, preload the whole well to EMPTY plus
    overrides, run in the oracle, return output bytes."""
    c = Compiler()
    alloc_memory(c)
    emit_render_well(c)
    base = c.addr("well")
    init = {base + i: EMPTY for i in range(W * H)}
    for (x, y, v) in well_overrides:
        init[cell(c, x, y)] = v
    tape, dp, out = run_bf(c.build(), init_tape=init)
    return out


def test_render_empty_well():
    out = _render([])
    assert out.startswith(b"\x1b[H")
    rows = out[3:].split(b"\r\n")
    assert len(rows) == H + 1          # 40 rows + trailing empty after last CRLF
    for r in rows[:H]:
        # each row is 20 space glyphs followed by ESC[K (erase to end of line)
        assert r == b" " * W + b"\x1b[K"


def test_render_pieces_glyphs():
    # I='>'(2) at (0,0); L=']'(8) at (5,3); T='+'(4) at (19,39)
    out = _render([(0, 0, 2), (5, 3, 8), (19, 39, 4)])
    rows = out[3:].split(b"\r\n")
    assert rows[0][0:1] == b">"
    assert rows[3][5:6] == b"]"
    assert rows[39][19:20] == b"+"
    assert rows[0][1:2] == b" "         # untouched neighbour stays a space


def test_render_all_glyph_kinds():
    overrides = [(i, 0, i + 1) for i in range(10)]   # biased 1..10 across row 0
    out = _render(overrides)
    row0 = out[3:].split(b"\r\n")[0]
    assert row0[:10] == b" ><+-.[]@@"
