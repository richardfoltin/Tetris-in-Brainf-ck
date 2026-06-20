"""
Measure executed BF steps for a full frame's worth of piece logic at 20x40.
A 'frame' here = one gravity/input action: scan-locate + walls + locked-collision
+ conditional move + resync (subsystems A,B,C,E). We report representative,
shallow, and deep positions, plus lock+spawn.
"""
from bf import run_bf, Emitter
from layout import *
import tetris as T

def frame_steps(piece, rot, px, py, nrot, mdx, mdy, locked=None):
    init = T.make_well_with_piece(piece, rot, px, py, locked)
    e = Emitter(); e.goto(LEFT_SENT)
    T.emit_try_move(e, piece, rot, nrot, mdx, mdy)
    _, _, _, s = run_bf(e.code(), init_tape=init)
    return s

print("=== FULL-FRAME STEP COUNTS (20x40) ===")
rows = [
    ("T piece, row 0 (top, shallow scan), move down",  3, 0, 8, 0, 0, 0, 1),
    ("T piece, row 5, move down",                       3, 0, 8, 5, 0, 0, 1),
    ("T piece, row 10 (representative), move down",     3, 0, 8, 10, 0, 0, 1),
    ("T piece, row 10, move right",                     3, 0, 8, 10, 0, 1, 0),
    ("T piece, row 10, rotate",                         3, 0, 8, 10, 1, 0, 0),
    ("T piece, row 20 (mid), move down",               3, 0, 8, 20, 0, 0, 1),
    ("T piece, row 35 (deep), move down",              3, 0, 8, 35, 0, 0, 1),
]
for (label, p, r, x, y, nr, dx, dy) in rows:
    s = frame_steps(p, r, x, y, nr, dx, dy)
    print(f"  {s:>7d}  {label}")

# lock+spawn frame
init = T.make_well_with_piece(2, 0, 5, 38)
e = Emitter(); e.goto(LEFT_SENT)
T.emit_lock_and_spawn(e, 2, 0, 3, 8, 0)
_, _, _, s = run_bf(e.code(), init_tape=init)
print(f"  {s:>7d}  lock+spawn (O at floor -> spawn T at top)")

print("\nNote: per-frame cost = O(rows-to-anchor) value-scan (~22 BF ops/cell)")
print("plus a fixed ~23k overhead (walls+locked+rewrite+resync).")
