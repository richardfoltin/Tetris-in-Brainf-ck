"""
Absolute indexed READ/WRITE into a contiguous data region.
Classic moving-index / convoy ("Tritium" / brainfuck.org array) technique,
breadcrumb variant, robust to empty cells via +1 bias.

================================ TAPE LAYOUT =================================

Each logical array element i occupies STRIDE=4 contiguous cells:

    BASE + 4*i + 0 : SPACE   (0 at rest; used as breadcrumb during walk)
    BASE + 4*i + 1 : IDX     (0 at rest; carries outbound countdown)
    BASE + 4*i + 2 : DATA    (BIASED value: stored = logical+1; empty=1, ids 2..8)
    BASE + 4*i + 3 : VAL     (0 at rest; carries the value being read/written)

A "phantom element -1" header sits just below the region (the HOME element):

    HOME = BASE - 4
    HOME+0 SPACE  (HOME marker: we never set a breadcrumb here -> return stops)
    HOME+1 IDX    (caller writes requested index here before the op)
    HOME+2 DATA   (read result lands here; for write unused as data)
    HOME+3 VAL    (caller writes value-to-write here; for read unused)

The BF pointer starts and ends at HOME+0 (the known home cell).
The compiler cursor is resynced to HOME+0 at the very end (see resync note).

============================== THE ALGORITHM ================================

We carry a 2-cell convoy (IDX countdown, VAL payload) rightward from HOME to
the target element, dropping a breadcrumb (SPACE=1) on every element we LEAVE.
At the target we do the data op (read copies DATA->VAL, write moves VAL->DATA).
Then we walk LEFT following breadcrumbs (SPACE==1), clearing each, carrying VAL
home, until we reach HOME whose SPACE is 0 -> stop. VAL lands in HOME+3, then
for read we move it to HOME+2 (the documented result cell).

Crucially the walk NEVER reads a DATA cell to decide control flow, so empty
(biased=1) or zero-logical cells cannot break the [>]/[<]-free convoy. The only
[...] loops scan the SPACE lane (rest value strictly 0) and the IDX countdown.

The whole walk is written with the pointer physically standing on a SPACE cell,
moving in strides of 4. The compile-time cursor is therefore UNKNOWN during the
loop body (depends on runtime idx). We handle that by writing the convoy with a
LOCAL emitter whose cursor is element-relative (0..3) and RESET to a known
element-relative position after each loop, and resyncing the global cursor to
HOME at the end because the pointer provably returns to HOME+0.
"""

# ---------------------------------------------------------------------------
# Goto emitter
# ---------------------------------------------------------------------------
class Emitter:
    def __init__(self, cursor=0):
        self.buf = []
        self.cursor = cursor
    def raw(self, s):
        self.buf.append(s)
    def move(self, delta):
        if delta > 0: self.buf.append('>' * delta)
        elif delta < 0: self.buf.append('<' * (-delta))
        self.cursor += delta
    def goto(self, target):
        self.move(target - self.cursor)
    def plus(self, n=1): self.buf.append('+' * n)
    def minus(self, n=1): self.buf.append('-' * n)
    def out(self): self.buf.append('.')
    def inp(self): self.buf.append(',')
    def code(self): return ''.join(self.buf)


STRIDE = 4
SP, IX, DT, VL = 0, 1, 2, 3


def emit_macro(e, base, op):
    """
    Emit read/write macro. Pointer enters at HOME+SP (= base-4) and leaves at
    HOME+SP. e.cursor must equal base-4 on entry; on exit e.cursor is set to
    base-4 (HOME+SP) — resynced because the pointer provably returns home.

    Runtime preconditions:
      HOME+IX = requested index (0..region_len-1)
      write: HOME+VL = biased value to store (logical+1)
      read : HOME+VL = 0 (will receive result), HOME+DT receives result copy
    All element SPACE cells = 0, all non-DATA carry cells = 0 at rest.
    """
    home = base - STRIDE
    guard = home - STRIDE       # GUARD element (below HOME); also holds USER inputs
    assert e.cursor == home + SP

    # ---- NONDESTRUCTIVE PROLOGUE ----
    # The convoy CONSUMES HOME+IX (decrements it to 0) and HOME+VL. To keep the
    # caller's index/value variables intact we read them from USER cells and COPY
    # them into the staging cells, restoring the USER cells (classic copy-via-tmp).
    #   USER_IX = guard+IX (caller's index, preserved)
    #   USER_VL = guard+VL (caller's value, preserved)   [write only]
    #   tmp     = guard+DT (offset 2, scratch, left 0)
    #   guard+SP (offset 0) stays 0 (return walk relies on it as the stop sentinel)
    # This is exactly what the verified `copy(src,dst,tmp)` primitive does; we
    # inline it so the macro is self-contained and the proof can assert USER cells
    # survive. e.cursor is managed with absolute goto here (no runtime unknowns yet).
    def copy_preserve(src, dst, tmp):
        # dst += src, src preserved, tmp must be 0 and ends 0. dst assumed 0.
        e.goto(src); e.raw('[-')            # src -> dst and tmp
        e.goto(dst); e.raw('+')
        e.goto(tmp); e.raw('+')
        e.goto(src); e.raw(']')
        e.goto(tmp); e.raw('[-')            # tmp -> src (restore)
        e.goto(src); e.raw('+')
        e.goto(tmp); e.raw(']')
    copy_preserve(guard + IX, home + IX, guard + DT)
    if op == 'write':
        copy_preserve(guard + VL, home + VL, guard + DT)
    e.goto(home + SP)
    e.cursor = home + SP

    # We will physically walk in strides. During the walk the absolute cursor
    # is runtime-dependent, so we drive the emitter with element-relative deltas
    # and keep e.cursor tracking the *element base* lane (SP) symbolically by
    # only ever returning to SP (offset 0) before/after each structural piece.
    #
    # Convention inside walk: pointer sits on a SPACE cell (offset 0 of some
    # element). We use a tiny helper that emits relative moves and asserts we
    # come back to offset 0, WITHOUT touching e.cursor (we manage cursor at the
    # macro boundaries only).

    parts = []
    def R(s): parts.append(s)          # raw walk code (relative)
    def rel_to(cur, tgt):              # within-element move, returns new cur
        d = tgt - cur
        R('>'*d if d>0 else '<'*(-d))
        return tgt

    # ---- OUTBOUND WALK ----
    # Pointer at HOME+SP. We want to advance IDX-many elements, leaving a
    # breadcrumb behind on each element we leave (so we can return).
    #
    # We loop on the current element's IX cell:
    #   while IX != 0:
    #       IX-- (consume one hop)
    #       set this element's SP = 1 (breadcrumb)         [marks "I came from here going right"]
    #       move (IX,VL) into the NEXT element (+STRIDE)
    #       advance pointer +STRIDE to that next element (now on its SP)
    #   end
    # But IX is currently in HOME+IX while pointer is on HOME+SP. We restructure
    # so that at loop top the pointer is on the CURRENT element's SP and the
    # loop tests SP-adjacent IX. Implementation:

    # HOME is the phantom element -1; element 0 is one stride to the right.
    # Reaching logical element `idx` therefore needs idx+1 rightward hops.
    # We do ONE unconditional first hop (HOME -> element 0) that does NOT consume
    # the counter, then loop `idx` counter-consuming hops (element 0 -> element idx).
    #
    # A "hop from current element" means: breadcrumb current SP (+1), move IX and
    # VL one stride right, advance pointer one stride right onto the new IX cell.
    cur = SP

    # --- unconditional first hop: HOME -> element 0 ---
    R('+')                                   # breadcrumb HOME+SP
    cur = rel_to(cur, IX)                     # to HOME+IX
    R('[-' + '>'*STRIDE + '+' + '<'*STRIDE + ']')   # IX -> next IX
    cur = rel_to(cur, VL)                     # to HOME+VL
    R('[-' + '>'*STRIDE + '+' + '<'*STRIDE + ']')   # VL -> next VL
    cur = rel_to(cur, STRIDE + IX)           # to element 0's IX
    cur = IX                                  # renumber frame to element 0

    # --- counter-consuming hops: while IX>0 (element 0 -> element idx) ---
    # while current IX > 0:
    R('[')
    R('-')                                   # consume one hop
    cur = rel_to(cur, SP); R('+')            # breadcrumb current SP
    cur = rel_to(cur, IX)
    R('[-' + '>'*STRIDE + '+' + '<'*STRIDE + ']')   # IX -> next IX
    cur = rel_to(cur, VL)
    R('[-' + '>'*STRIDE + '+' + '<'*STRIDE + ']')   # VL -> next VL
    cur = rel_to(cur, STRIDE + IX)           # advance to next element's IX
    cur = IX                                  # renumber frame
    R(']')
    # Loop exits with pointer on the TARGET element's IX (==0), i.e. offset IX.

    # Pointer is on TARGET's IX (offset 1, value 0). Target's VL (offset 3) holds
    # the carried payload (the value to write, or 0 for read).

    # ---- DATA OP at target ----
    if op == 'write':
        # Overwrite DATA with carried VL. Clear DATA, then move VL->DATA.
        cur = rel_to(cur, DT); R('[-]')          # clear data (offset 2)
        cur = rel_to(cur, VL)                    # offset 3
        R('[-' + '<' + '+' + '>' + ']')          # VL(3) -> DATA(2)
        # pointer on VL (offset 3); VL now 0 (consumed) -> nothing to carry home.
    elif op == 'read':
        # Copy DATA into VL (to carry home) preserving DATA. Use IX (offset 1,==0)
        # as temp. DATA(2) -> VL(3) + IX(1); then restore DATA from IX.
        cur = rel_to(cur, DT)                    # offset 2
        R('[-' + '>' + '+' + '<<' + '+' + '>' + ']')   # DATA->VL(+1) & IX(-1); DATA=0
        cur = rel_to(cur, IX)                    # offset 1 (temp)
        R('[-' + '>' + '+' + '<' + ']')          # IX -> DATA(+1); IX cleared
        # pointer on IX (offset 1); VL(3) holds the data copy; DATA restored.
    else:
        raise ValueError(op)

    # ---- RETURN WALK ----
    # Breadcrumbs (SP==1) sit on HOME, elem0, ..., elem(idx-1). Target (current)
    # has SP==0 and holds VL in its VL cell.
    #
    # RETURN INVARIANT: pointer stands on element E's SP; the payload VL lives in
    # element (E+1)'s VL cell (one stride to the right). Loop:
    #     while SP(E) is a breadcrumb:
    #         clear breadcrumb
    #         pull VL from (E+1) into E   (VL moves one stride left, now in E)
    #         step left one element  (E := E-1; payload now sits one stride right of new ptr)
    # Setup the invariant: pointer is on target IX; VL is in target VL. Step left
    # one element onto elem(idx-1)'s SP. Now payload (target VL) is one stride to
    # the right of pointer -> invariant holds.
    cur = rel_to(cur, SP)                         # to target SP (offset 0)
    R('<'*STRIDE)                                 # step left -> elem(idx-1) SP
    cur = SP                                       # frame = elem(idx-1)
    R('[')                                         # while breadcrumb here:
    R('-')                                         #   clear breadcrumb
    cur = rel_to(cur, VL)                          #   go to this elem's VL (offset 3)
    R('>'*STRIDE + '[-' + '<'*STRIDE + '+' + '>'*STRIDE + ']' + '<'*STRIDE)
    #   ^ pull VL from right element (+STRIDE) into this VL, return to this VL
    cur = rel_to(cur, SP)                          #   back to this SP
    R('<'*STRIDE)                                  #   step left one element
    cur = SP
    R(']')
    # When pointer reaches HOME+SP (breadcrumb), body runs: clears it, pulls VL
    # from elem0 into HOME+VL, steps left onto guard cell (SP==0) -> exit.
    # Payload now in HOME+VL. Step right once to land on HOME+SP.
    R('>'*STRIDE)
    cur = SP
    # Now physically on HOME+SP. HOME+VL holds the carried value.

    # join walk code
    e.raw(''.join(parts))

    # ---- post-op fixups at HOME ----
    # We are physically at HOME+SP. Set cursor accordingly (RESYNC):
    e.cursor = home + SP
    if op == 'read':
        # move HOME+VL result into HOME+DT (documented result cell)
        e.goto(home + DT); e.raw('[-]')          # clear dest
        e.goto(home + VL)
        e.raw('[-' + '<' + '+' + '>' + ']')      # VL(home+3)->DATA(home+2)
        # pointer on HOME+VL
        e.cursor = home + VL
    # return pointer to HOME+SP (home cell)
    e.goto(home + SP)
