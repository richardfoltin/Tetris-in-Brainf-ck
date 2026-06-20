from bf import run_bf, Emitter
from layout import *
import tetris as T

e = Emitter(); e.goto(LEFT_SENT)
moves = [(0, 0, 1), (0, 0, 1), (0, 1, 0)]   # down, down, right
px, py, rot = 5, 5, 0
for (nrot, mdx, mdy) in moves:
    T.emit_try_move(e, 2, rot, nrot, mdx, mdy)
    px += mdx; py += mdy; rot = nrot
tape, ptr, out, steps = run_bf(e.code(), init_tape=T.make_well_with_piece(2, 0, 5, 5))
na = cell(px, py)
print(f"expect anchor@({px},{py}) rot{rot}")
print("  anchor ok:", tape[na] == ANCHOR,
      "shadow:", (tape[na + T.SH_PX], tape[na + T.SH_PY], tape[na + T.SH_ROT]))
nm = sum(1 for i in range(WELL_CELLS) if tape[WELL_BASE + i] in (ACTIVE, ANCHOR))
print("  markers:", nm, "ptr@LS:", ptr == LEFT_SENT, "steps:", steps, "per-move:", steps // 3)
