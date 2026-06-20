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
