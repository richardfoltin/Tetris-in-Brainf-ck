"""
Tetromino shapes as 4 (dx,dy) cell offsets RELATIVE TO THE ANCHOR.

The anchor is one of the 4 occupied cells (offset (0,0) is always occupied and
is the anchor). Offsets are small integers; well cell of an occupied square is
cell(px+dx, py+dy) = ANCHOR_CELL + dy*W + dx, a COMPILE-TIME-known tape delta
from the anchor cell. This is what makes relative peeks possible.

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
