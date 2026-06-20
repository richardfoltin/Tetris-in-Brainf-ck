"""
Brainfuck interpreter + goto-emitter for BF Tetris.

Interpreter:
  - 8-bit WRAPPING cells (0..0xFF), tape >= 4096 ints
  - ',' returns 0 on EOF
  - '.' collects output bytes
  - STEP COUNTER (counts executed BF commands; loop bracket tests count too)
  - raises on pointer out of [0, tape)
"""

# ----------------------------------------------------------------------------
# Interpreter
# ----------------------------------------------------------------------------

class BFError(Exception):
    pass


def run_bf(src, tape_size=4096, inp=b"", max_steps=50_000_000, init_tape=None):
    """Execute Brainfuck source. Returns (tape, ptr, output_bytes, steps)."""
    # strip to valid commands only
    code = [c for c in src if c in "+-<>[].,"]
    n = len(code)

    # precompute bracket matches
    jump = {}
    stack = []
    for i, c in enumerate(code):
        if c == '[':
            stack.append(i)
        elif c == ']':
            if not stack:
                raise BFError("unmatched ]")
            j = stack.pop()
            jump[i] = j
            jump[j] = i
    if stack:
        raise BFError("unmatched [")

    tape = [0] * tape_size
    if init_tape is not None:
        for k, v in init_tape.items():
            tape[k] = v & 0xFF

    ptr = 0
    ip = 0
    steps = 0
    out = bytearray()
    in_pos = 0

    while ip < n:
        c = code[ip]
        steps += 1
        if steps > max_steps:
            raise BFError(f"step limit {max_steps} exceeded")
        if c == '+':
            tape[ptr] = (tape[ptr] + 1) & 0xFF
        elif c == '-':
            tape[ptr] = (tape[ptr] - 1) & 0xFF
        elif c == '>':
            ptr += 1
            if ptr >= tape_size:
                raise BFError(f"pointer out of range (>= {tape_size})")
        elif c == '<':
            ptr -= 1
            if ptr < 0:
                raise BFError("pointer out of range (< 0)")
        elif c == '.':
            out.append(tape[ptr])
        elif c == ',':
            if in_pos < len(inp):
                tape[ptr] = inp[in_pos]
                in_pos += 1
            else:
                tape[ptr] = 0
        elif c == '[':
            if tape[ptr] == 0:
                ip = jump[ip]
        elif c == ']':
            if tape[ptr] != 0:
                ip = jump[ip]
        ip += 1

    return tape, ptr, bytes(out), steps


# ----------------------------------------------------------------------------
# Goto-emitter
# ----------------------------------------------------------------------------
#
# The emitter tracks a COMPILE-TIME 'cursor': the tape index the data pointer
# is known to be at, statically. goto(target) emits the exact run of >/< to
# move from cursor to target and updates cursor. We NEVER hand-count >/<.
#
# RELATIVE SECTIONS: sometimes the data pointer rides a RUNTIME position that
# the compiler does NOT know (e.g. after a value-scan '[>]' lands on an
# unknown cell). During such a section, cursor is meaningless and the emitter
# refuses absolute goto. You operate with hand-authored relative moves whose
# net displacement you DO know at compile time (e.g. peeking +offset then
# returning -offset). To leave a relative section you must RESYNC: emit a
# proven walk to a known ABSOLUTE cell (e.g. sentinel-walk '[<]' to a 0 cell),
# then call resync(abs_cell) to set cursor back to a known value.

class Emitter:
    def __init__(self):
        self.parts = []
        self.cursor = 0          # known absolute tape index, or None if relative
        self._rel_net = 0        # net displacement accumulated inside a rel section
        self._in_rel = False

    def emit(self, s):
        self.parts.append(s)
        return self

    # -- absolute movement ----------------------------------------------------
    def goto(self, target):
        if self._in_rel:
            raise BFError("goto() called inside a relative section; resync first")
        if self.cursor is None:
            raise BFError("cursor unknown; resync to an absolute cell first")
        d = target - self.cursor
        if d > 0:
            self.emit('>' * d)
        elif d < 0:
            self.emit('<' * (-d))
        self.cursor = target
        return self

    def at(self):
        if self.cursor is None or self._in_rel:
            raise BFError("cursor not known absolutely")
        return self.cursor

    # -- cell ops at current cursor -------------------------------------------
    def add(self, v):
        v &= 0xFF
        if v <= 128:
            self.emit('+' * v)
        else:
            self.emit('-' * (256 - v))
        return self

    def sub(self, v):
        return self.add((-v) & 0xFF)

    def zero(self):
        """Set current cell to 0 via [-]."""
        self.emit('[-]')
        return self

    def setval(self, v):
        self.zero()
        self.add(v)
        return self

    def set_at(self, cell, v):
        self.goto(cell)
        self.setval(v)
        return self

    def add_at(self, cell, v):
        self.goto(cell)
        self.add(v)
        return self

    # -- relative sections ----------------------------------------------------
    def begin_rel(self):
        """Enter a relative section. cursor becomes runtime-unknown."""
        self._in_rel = True
        self._rel_net = 0
        self.cursor = None
        return self

    def rel_move(self, d):
        """Move +d (right) or -d (left) inside a rel section; track net."""
        if not self._in_rel:
            raise BFError("rel_move outside relative section")
        if d > 0:
            self.emit('>' * d)
        elif d < 0:
            self.emit('<' * (-d))
        self._rel_net += d
        return self

    def rel_net(self):
        return self._rel_net

    # -- relative LOCAL-OFFSET addressing -------------------------------------
    # Inside a relative section the data pointer rides a runtime ORIGIN. We
    # track a compile-time LOCAL OFFSET (= _rel_net) from that origin and emit
    # exact >/< for rgoto, exactly like absolute goto but origin-relative.
    def rgoto(self, off):
        """Move so local offset becomes `off` (relative to the rel origin)."""
        if not self._in_rel:
            raise BFError("rgoto outside relative section")
        self.rel_move(off - self._rel_net)
        return self

    def roff(self):
        return self._rel_net

    def radd(self, off, v):
        self.rgoto(off); self.add(v); return self

    def rsub(self, off, v):
        self.rgoto(off); self.sub(v); return self

    def rzero(self, off):
        self.rgoto(off); self.emit('[-]'); return self

    def rset(self, off, v):
        self.rgoto(off); self.emit('[-]'); self.add(v); return self

    def rmove_cell(self, src_off, dst_off):
        """dst_off += src_off; src_off -> 0. (relative move, auto-counted)"""
        self.rgoto(src_off)
        self.emit('[-')
        self.rgoto(dst_off); self.emit('+')
        self.rgoto(src_off); self.emit(']')
        # loop leaves pointer at src_off (its value 0)
        self._rel_net = src_off
        return self

    def rcopy_cell(self, src_off, dst_off, tmp_off):
        """dst = src (src preserved). tmp 0 before/after. relative."""
        self.rzero(dst_off); self.rzero(tmp_off)
        self.rgoto(src_off); self.emit('[-')
        self.rgoto(dst_off); self.emit('+')
        self.rgoto(tmp_off); self.emit('+')
        self.rgoto(src_off); self.emit(']')
        self._rel_net = src_off
        self.rgoto(tmp_off); self.emit('[-')
        self.rgoto(src_off); self.emit('+')
        self.rgoto(tmp_off); self.emit(']')
        self._rel_net = tmp_off
        return self

    def resync(self, abs_cell):
        """
        Declare that the data pointer is now KNOWN to sit on abs_cell (because
        you just emitted a proven absolute walk, e.g. '[<]' to a sentinel).
        Leaves the relative section.
        """
        self._in_rel = False
        self._rel_net = 0
        self.cursor = abs_cell
        return self

    def raw(self, s, cursor_after=None):
        """
        Emit raw BF. If cursor_after is given, declare the absolute cursor
        after this snippet (used for hand-proven movement primitives).
        """
        self.emit(s)
        if cursor_after is not None:
            self.cursor = cursor_after
            self._in_rel = False
        return self

    def code(self):
        return ''.join(self.parts)
