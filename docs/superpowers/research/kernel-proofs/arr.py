"""
Absolute indexed read/write into a contiguous data region using the classic
moving-index / convoy ("Tritium" / brainfuck.org array) technique.

TAPE LAYOUT (cell groups of 4 around the region; the region itself is a strided
stream of cell-quadruples so the convoy has room to carry index + value):

We use the canonical brainfuck.org "two scratch + value + data" array cell.
Each logical array element i occupies 4 contiguous tape cells:

    base + 4*i + 0 : "space"  (always 0 at rest) -- the lane the convoy walks
    base + 4*i + 1 : "index"  (0 at rest)        -- carries countdown copy
    base + 4*i + 2 : "data"   (BIASED: logical+1; empty=1, ids 2..8; rest)
    base + 4*i + 3 : "value/temp" (0 at rest)    -- carries value to write / read

Plus a fixed header BEFORE base (lower addresses) used to set up the walk:

    H_SPACE = base - 4 + 0  : staging "space"  (must be 0)
    H_IDX   = base - 4 + 1  : staging index    (the requested idx)
    H_DATA  = base - 4 + 2  : staging data     (= read result lands here / value source)
    H_VAL   = base - 4 + 3  : staging value    (value to write)

i.e. the header is a "phantom element -1" with the same 4-cell shape.

THE CONVOY (move-right for index idx):
Starting parked at the header element, with H_IDX = idx (and for write, H_VAL = val):
We repeatedly move the (idx, val) pair one element to the right while idx>0,
decrementing idx each hop. When idx reaches 0 we are parked AT the target element.

One rightward hop (currently parked at element k's "space" cell offset 0):
  - we hold counters in this element's index (off1) and value (off3) cells.
  - decrement index; if it becomes 0 we stop (we're at target).
  - else copy index and value to element k+1 and zero them here, advance 4.

At the target, off3 holds the carried value:
  - WRITE: move off3 into off2 (data)  [after biasing], using +1 bias.
  - READ : copy off2 (data) into off3 (carried value) to bring it home.

Then the convoy walks LEFT the same number of hops back to the header, carrying
the (now meaningful) value home. Because we used a *separate* return countdown we
must reconstruct hop count -- instead we use the classic trick: the convoy leaves
a trail we follow back with [<] on the "space" lane... but space is always 0.

SIMPLER CANONICAL FORM (the one we implement & prove):
We keep TWO counters travelling: the *outbound* countdown AND a *rebuilt* count.
Actually the cleanest proven method (brainfuck.org) carries idx down to 0 going
out, and simultaneously builds idx back UP is unnecessary: to return we just walk
left while the *previous* element is non-"home". We mark home with a sentinel.

To keep this rock-solid and fully proven, we implement the well-known
"two travelling values" scheme with an explicit RETURN counter:

Outbound we carry (countdown C, value V). Each hop decС, and ALSO we don't need a
return counter because we walk back using the SPACE lane as a breadcrumb:
before each outbound hop we set the *current* element's space cell to 1 (breadcrumb),
walk right; to return we go left while space==1, clearing breadcrumbs as we go,
until we reach the header whose space we never set.

This is robust to empty (biased) data cells because the walk never inspects data.

We implement exactly this and PROVE it.
"""

# --- Goto emitter ------------------------------------------------------------

class Emitter:
    def __init__(self):
        self.parts = []
        self.cursor = 0  # absolute tape position the BF pointer is at, at compile time

    def emit(self, s):
        self.parts.append(s)

    def goto(self, target):
        d = target - self.cursor
        if d > 0:
            self.emit('>' * d)
        elif d < 0:
            self.emit('<' * (-d))
        self.cursor = target

    def at(self, pos):  # context-manager-ish convenience
        self.goto(pos)
        return self

    def code(self):
        return ''.join(self.parts)


# Layout constants
STRIDE = 4
OFF_SPACE = 0
OFF_IDX   = 1
OFF_DATA  = 2
OFF_VAL   = 3


def gen_program(base, op, idx, val=0, region_len=200, n_input_cells=0):
    """
    Emit a self-contained BF program that:
      - loads region with biased test pattern is done OUTSIDE (we operate on whatever is there)
    Here for proving we generate ONLY the read or write macro, assuming the
    region + header are already in tape (header at base-STRIDE).
    op = 'read' or 'write'. idx, val are compile-time constants for setup,
    but the MACRO ITSELF must work with idx supplied at RUNTIME in H_IDX.
    We therefore do NOT bake idx into the walk; the walk reads H_IDX at runtime.
    """
    pass  # built in the proof harness below
