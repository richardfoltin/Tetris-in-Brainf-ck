"""DSL -> Brainfuck goto-emitter compiler and verified primitive macros.

NEVER hand-count '>' or '<'. The Compiler tracks an absolute `cursor` and
goto() emits exactly abs(target - cursor) pointer moves, updating the cursor.
Every primitive macro is pointer-neutral: it returns the pointer to the cell it
started on and asserts it with assert_cursor.

This Compiler is a SUPERSET of the verified reference `Emitter` (bf.py): in
addition to the project's named-cell goto-emitter it carries the reference's
RELATIVE-SECTION machinery (begin_rel/rel_move/rgoto/resync and the relative
cell ops) with byte-for-byte identical semantics, so the verified runtime
subsystem can be ported onto it unchanged.
"""


class _BFError(Exception):
    pass


class Compiler:
    def __init__(self):
        self.code = []        # list of emitted BF fragments
        self.cursor = 0       # absolute cell the pointer is on (None inside rel)
        self.names = {}       # var name -> absolute base cell
        self.next_free = 0    # allocator high-water mark
        self._rel_net = 0     # net displacement inside a relative section
        self._in_rel = False  # True while riding a runtime-unknown origin

    # ---- raw emit + allocation ------------------------------------------
    def emit(self, s):
        """Append raw BF. Must NOT contain '>' or '<' (use goto for those)."""
        if ">" in s or "<" in s:
            raise ValueError(
                "emit() must not contain '>' or '<'; use goto() for pointer moves"
            )
        self.code.append(s)
        return self

    def _raw_move(self, s):
        self.code.append(s)

    def alloc(self, name, size=1):
        """Reserve a fixed absolute region of `size` cells; return its base."""
        if name in self.names:
            raise ValueError("duplicate alloc: %r" % name)
        if size < 1:
            raise ValueError("alloc size must be >= 1")
        base = self.next_free
        self.names[name] = base
        self.next_free += size
        return base

    def addr(self, name, offset=0):
        """Absolute cell index of name + offset. `name` may be an int."""
        if isinstance(name, int):
            return name + offset
        if name not in self.names:
            raise KeyError("unknown name: %r" % name)
        return self.names[name] + offset

    # ---- absolute movement ----------------------------------------------
    def goto(self, name, offset=0):
        """Emit abs(target-cursor) of '>' or '<' and update the cursor.

        `name` may be a registered name or a raw absolute int."""
        if self._in_rel:
            raise _BFError("goto() called inside a relative section; resync first")
        if self.cursor is None:
            raise _BFError("cursor unknown; resync to an absolute cell first")
        target = self.addr(name, offset)
        delta = target - self.cursor
        if delta > 0:
            self._raw_move(">" * delta)
        elif delta < 0:
            self._raw_move("<" * (-delta))
        self.cursor = target
        return self

    def assert_cursor(self, name, offset=0):
        """Raise if the cursor is not on name + offset (correctness guard)."""
        target = self.addr(name, offset)
        if self.cursor != target:
            raise AssertionError(
                "cursor %s != expected %d (%s+%d)"
                % (self.cursor, target, name, offset)
            )
        return self

    def set_cursor(self, name, offset=0):
        """Declare (without emitting) that the cursor sits on name+offset."""
        self.cursor = self.addr(name, offset)
        self._in_rel = False
        return self

    def at(self):
        if self.cursor is None or self._in_rel:
            raise _BFError("cursor not known absolutely")
        return self.cursor

    def build(self):
        """Return the concatenated BF program."""
        return "".join(self.code)

    # also accept the reference name
    def code_str(self):
        return self.build()

    # ---- reference Emitter superset: cell ops at the current cursor ------
    def add(self, v):
        """Add v (mod 256) at the current cell, using the shorter sign."""
        v &= 0xFF
        if v <= 128:
            self.emit("+" * v)
        else:
            self.emit("-" * (256 - v))
        return self

    def sub(self, v):
        return self.add((-v) & 0xFF)

    def zero(self):
        """Set current cell to 0 via [-]."""
        self.emit("[-]")
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

    def raw(self, s, cursor_after=None):
        """Emit raw BF (may contain >/<). If cursor_after is given, declare the
        absolute cursor after this snippet (for hand-proven movement)."""
        self.code.append(s)
        if cursor_after is not None:
            self.cursor = cursor_after
            self._in_rel = False
        return self

    # ---- relative sections (ported verbatim from reference Emitter) ------
    def begin_rel(self):
        """Enter a relative section. cursor becomes runtime-unknown."""
        self._in_rel = True
        self._rel_net = 0
        self.cursor = None
        return self

    def rel_move(self, d):
        """Move +d (right) or -d (left) inside a rel section; track net."""
        if not self._in_rel:
            raise _BFError("rel_move outside relative section")
        if d > 0:
            self.code.append(">" * d)
        elif d < 0:
            self.code.append("<" * (-d))
        self._rel_net += d
        return self

    def rel_net(self):
        return self._rel_net

    def rgoto(self, off):
        """Move so local offset becomes `off` (relative to the rel origin)."""
        if not self._in_rel:
            raise _BFError("rgoto outside relative section")
        self.rel_move(off - self._rel_net)
        return self

    def roff(self):
        return self._rel_net

    def radd(self, off, v):
        self.rgoto(off); self.add(v); return self

    def rsub(self, off, v):
        self.rgoto(off); self.sub(v); return self

    def rzero(self, off):
        self.rgoto(off); self.emit("[-]"); return self

    def rset(self, off, v):
        self.rgoto(off); self.emit("[-]"); self.add(v); return self

    def rmove_cell(self, src_off, dst_off):
        """dst_off += src_off; src_off -> 0. (relative move, auto-counted)"""
        self.rgoto(src_off)
        self.emit("[-")
        self.rgoto(dst_off); self.emit("+")
        self.rgoto(src_off); self.emit("]")
        self._rel_net = src_off
        return self

    def rcopy_cell(self, src_off, dst_off, tmp_off):
        """dst = src (src preserved). tmp 0 before/after. relative."""
        self.rzero(dst_off); self.rzero(tmp_off)
        self.rgoto(src_off); self.emit("[-")
        self.rgoto(dst_off); self.emit("+")
        self.rgoto(tmp_off); self.emit("+")
        self.rgoto(src_off); self.emit("]")
        self._rel_net = src_off
        self.rgoto(tmp_off); self.emit("[-")
        self.rgoto(src_off); self.emit("+")
        self.rgoto(tmp_off); self.emit("]")
        self._rel_net = tmp_off
        return self

    def resync(self, name, offset=0):
        """Declare the data pointer now sits on the absolute cell name+offset
        (because a proven absolute walk, e.g. '[<]' to a sentinel, was emitted).
        Leaves the relative section."""
        self._in_rel = False
        self._rel_net = 0
        self.cursor = self.addr(name, offset)
        return self


# =====================================================================
# Module-level verified primitives (absolute, named-cell, pointer-neutral).
# =====================================================================

def clear(c, v):
    """v = 0.  idiom: [-]"""
    c.goto(v)
    c.emit("[-]")
    c.assert_cursor(v)


def set_const(c, v, n):
    """v = n, 0 <= n <= 255.  clear then n '+'."""
    if not (0 <= n <= 255):
        raise ValueError("set_const value out of range 0..255: %r" % n)
    clear(c, v)
    c.goto(v)
    if n:
        c.emit("+" * n)
    c.assert_cursor(v)


def inc(c, v, n=1):
    c.goto(v)
    if n:
        c.emit("+" * n)
    c.assert_cursor(v)


def dec(c, v, n=1):
    c.goto(v)
    if n:
        c.emit("-" * n)
    c.assert_cursor(v)


def move(c, src, dst):
    """dst += src; src = 0.  idiom (at src): [ dst+ src- ]"""
    c.goto(src)
    c.emit("[")
    c.goto(dst)
    c.emit("+")
    c.goto(src)
    c.emit("-]")
    c.assert_cursor(src)


def copy(c, src, dst, tmp):
    """dst = src; src preserved; tmp clobbered.
    idiom: tmp[-] dst[-] src[ dst+ tmp+ src- ] tmp[ src+ tmp- ]"""
    clear(c, tmp)
    clear(c, dst)
    c.goto(src)
    c.emit("[")
    c.goto(dst)
    c.emit("+")
    c.goto(tmp)
    c.emit("+")
    c.goto(src)
    c.emit("-]")
    c.goto(tmp)
    c.emit("[")
    c.goto(src)
    c.emit("+")
    c.goto(tmp)
    c.emit("-]")
    c.goto(src)
    c.assert_cursor(src)


def add(c, dst, src, tmp):
    """dst += src; src preserved; tmp clobbered."""
    clear(c, tmp)
    c.goto(src)
    c.emit("[")
    c.goto(dst)
    c.emit("+")
    c.goto(tmp)
    c.emit("+")
    c.goto(src)
    c.emit("-]")
    c.goto(tmp)
    c.emit("[")
    c.goto(src)
    c.emit("+")
    c.goto(tmp)
    c.emit("-]")
    c.goto(dst)
    c.assert_cursor(dst)


def sub(c, dst, src, tmp):
    """dst -= src; src preserved; tmp clobbered."""
    clear(c, tmp)
    c.goto(src)
    c.emit("[")
    c.goto(dst)
    c.emit("-")
    c.goto(tmp)
    c.emit("+")
    c.goto(src)
    c.emit("-]")
    c.goto(tmp)
    c.emit("[")
    c.goto(src)
    c.emit("+")
    c.goto(tmp)
    c.emit("-]")
    c.goto(dst)
    c.assert_cursor(dst)


def mul(c, dst, src, tmp0, tmp1):
    """dst *= src; src preserved; tmp0/tmp1 clobbered. SETUP/SCORE ONLY."""
    clear(c, tmp0)
    clear(c, tmp1)
    c.goto(dst)
    c.emit("[")
    c.goto(tmp1)
    c.emit("+")
    c.goto(dst)
    c.emit("-]")
    c.goto(tmp1)
    c.emit("[")
    c.goto(src)
    c.emit("[")
    c.goto(dst)
    c.emit("+")
    c.goto(tmp0)
    c.emit("+")
    c.goto(src)
    c.emit("-]")
    c.goto(tmp0)
    c.emit("[")
    c.goto(src)
    c.emit("+")
    c.goto(tmp0)
    c.emit("-]")
    c.goto(tmp1)
    c.emit("-]")
    c.goto(dst)
    c.assert_cursor(dst)


def eq(c, dst, a, b, tmp0, tmp1):
    """dst = (a==b)?1:0 ; b preserved, a clobbered."""
    clear(c, dst)
    c.goto(a)
    c.emit("[")
    c.goto(dst)
    c.emit("+")
    c.goto(a)
    c.emit("-]")
    clear(c, tmp0)
    clear(c, tmp1)
    c.goto(dst)
    c.emit("[")
    c.goto(tmp1)
    c.emit("+")
    c.goto(dst)
    c.emit("-]+")
    c.goto(b)
    c.emit("[")
    c.goto(tmp1)
    c.emit("-")
    c.goto(tmp0)
    c.emit("+")
    c.goto(b)
    c.emit("-]")
    c.goto(tmp0)
    c.emit("[")
    c.goto(b)
    c.emit("+")
    c.goto(tmp0)
    c.emit("-]")
    c.goto(tmp1)
    c.emit("[")
    c.goto(dst)
    c.emit("-")
    c.goto(tmp1)
    c.emit("[-]]")
    c.goto(dst)
    c.assert_cursor(dst)


def neq(c, dst, a, b, tmp0, tmp1):
    """dst = (a!=b)?1:0 ; b preserved, a clobbered."""
    clear(c, dst)
    c.goto(a)
    c.emit("[")
    c.goto(dst)
    c.emit("+")
    c.goto(a)
    c.emit("-]")
    clear(c, tmp0)
    clear(c, tmp1)
    c.goto(dst)
    c.emit("[")
    c.goto(tmp1)
    c.emit("+")
    c.goto(dst)
    c.emit("-]")
    c.goto(b)
    c.emit("[")
    c.goto(tmp1)
    c.emit("-")
    c.goto(tmp0)
    c.emit("+")
    c.goto(b)
    c.emit("-]")
    c.goto(tmp0)
    c.emit("[")
    c.goto(b)
    c.emit("+")
    c.goto(tmp0)
    c.emit("-]")
    c.goto(tmp1)
    c.emit("[")
    c.goto(dst)
    c.emit("+")
    c.goto(tmp1)
    c.emit("[-]]")
    c.goto(dst)
    c.assert_cursor(dst)


def gt(c, dst, a, b, tmp0, tmp1):
    """dst = (a>b)?1:0. DESTRUCTIVE on a,b (copy first). Requires wrapping."""
    clear(c, tmp0)
    clear(c, tmp1)
    clear(c, dst)
    c.goto(a)
    c.emit("[")
    c.goto(tmp0)
    c.emit("+")
    c.goto(b)
    c.emit("[-")
    c.goto(tmp0)
    c.emit("[-]")
    c.goto(tmp1)
    c.emit("+")
    c.goto(b)
    c.emit("]")
    c.goto(tmp0)
    c.emit("[-")
    c.goto(dst)
    c.emit("+")
    c.goto(tmp0)
    c.emit("]")
    c.goto(tmp1)
    c.emit("[-")
    c.goto(b)
    c.emit("+")
    c.goto(tmp1)
    c.emit("]")
    c.goto(b)
    c.emit("-")
    c.goto(a)
    c.emit("-]")
    c.goto(dst)
    c.assert_cursor(dst)


def if_(c, cond, body_fn, tmp0, tmp1):
    """if cond!=0 run body_fn(c); cond clobbered. body_fn must be neutral."""
    clear(c, tmp0)
    clear(c, tmp1)
    c.goto(cond)
    c.emit("[")
    c.goto(tmp0)
    c.emit("+")
    c.goto(tmp1)
    c.emit("+")
    c.goto(cond)
    c.emit("-]")
    c.goto(tmp0)
    c.emit("[")
    c.goto(cond)
    c.emit("+")
    c.goto(tmp0)
    c.emit("-]")
    c.goto(tmp1)
    c.emit("[")
    start = c.cursor
    body_fn(c)
    if c.cursor != start:
        raise AssertionError("if_ body_fn is not pointer-neutral")
    c.goto(tmp1)
    c.emit("[-]]")
    c.goto(cond)
    c.assert_cursor(cond)


def if_else(c, cond, then_fn, else_fn, tmp0, tmp1):
    """if cond!=0 then_fn else else_fn; cond clobbered. Both branches neutral."""
    clear(c, tmp0)
    clear(c, tmp1)
    c.goto(cond)
    c.emit("[")
    c.goto(tmp0)
    c.emit("+")
    c.goto(tmp1)
    c.emit("+")
    c.goto(cond)
    c.emit("-]")
    c.goto(tmp0)
    c.emit("[")
    c.goto(cond)
    c.emit("+")
    c.goto(tmp0)
    c.emit("-]+")
    c.goto(tmp1)
    c.emit("[")
    start = c.cursor
    then_fn(c)
    if c.cursor != start:
        raise AssertionError("if_else then_fn is not pointer-neutral")
    c.goto(tmp0)
    c.emit("-")
    c.goto(tmp1)
    c.emit("[-]]")
    c.goto(tmp0)
    c.emit("[")
    start2 = c.cursor
    else_fn(c)
    if c.cursor != start2:
        raise AssertionError("if_else else_fn is not pointer-neutral")
    c.goto(tmp0)
    c.emit("-]")
    c.goto(cond)
    c.assert_cursor(cond)


def while_(c, cond_name, recompute_fn, body_fn):
    """while cond_name != 0 { body_fn ; recompute_fn }. Caller seeds cond first."""
    c.goto(cond_name)
    c.emit("[")
    start = c.cursor
    body_fn(c)
    if c.cursor != start:
        raise AssertionError("while_ body_fn is not pointer-neutral (cond)")
    recompute_fn(c)
    if c.cursor != start:
        raise AssertionError("while_ recompute_fn must end on cond_name")
    c.goto(cond_name)
    c.emit("]")
    c.goto(cond_name)
    c.assert_cursor(cond_name)


# ---- if-then-consume / is_zero / switch_cascade (from emit_shape.py) ----
def if_then_consume(c, flag, body):
    """if flag != 0: flag = 0; body(). flag consumed. body MUST be neutral."""
    c.goto(flag)
    c.emit("[")
    c.goto(flag); c.emit("[-]")
    body()
    c.goto(flag)
    c.emit("]")
    c.goto(flag)


def is_zero(c, x, out, t):
    """out = (x == 0) ? 1 : 0. x preserved. t scratch (left 0). Ends at out."""
    clear(c, t)
    move(c, x, t)                     # t = x ; x = 0 (ends at x)
    set_const(c, out, 1)
    c.goto(t)
    c.emit("[")
    c.goto(out); c.emit("[-]")
    c.goto(x); c.emit("+")
    c.goto(t); c.emit("-")
    c.goto(t)
    c.emit("]")
    c.goto(out)


def switch_cascade(c, work, candidates, g, m, t):
    """Exact-match switch over cell `work`: for each (k, body), run body() iff
    work == k. Matches by the KEY k (not list position). `work` is preserved
    across the tests and cleared to 0 at the end (destructive contract). g, m, t
    are scratch (left 0). Keys should be distinct so at most one body fires."""
    for (k, body) in candidates:
        # g = work (copy via t; work preserved)
        clear(c, g)
        clear(c, t)
        c.goto(work)
        c.emit("[")
        c.goto(g); c.emit("+")
        c.goto(t); c.emit("+")
        c.goto(work); c.emit("-]")          # work -> 0; g=t=work_orig
        c.goto(t)
        c.emit("[")
        c.goto(work); c.emit("+")
        c.goto(t); c.emit("-]")             # restore work; t=0
        # g -= k ; m = (g == 0) == (work == k)
        c.goto(g)
        if k:
            c.emit("-" * (k & 0xFF))
        is_zero(c, g, m, t)                  # m = (g==0); g preserved, t=0
        clear(c, g)
        if_then_consume(c, m, body)
    clear(c, work)
    c.goto(work)


# ---- print_dec (value-preserving decimal printer) -----------------------
# SETUP/HUD ONLY (O(value) ops). v is preserved; uses the 8 cells immediately
# RIGHT of v as scratch (left at 0). Pointer-neutral. Built on verified gt/copy.
def print_dec(c, v, scratch_base):
    """Print v (0..255) as decimal; v PRESERVED. scratch_base must be addr(v)+1
    and there must be 8 usable cells from there."""
    if c.addr(scratch_base) != c.addr(v) + 1:
        raise AssertionError(
            "print_dec scratch must be immediately right of value: "
            "addr(%s)=%d, addr(%s)=%d"
            % (scratch_base, c.addr(scratch_base), v, c.addr(v))
        )
    base = c.addr(v)
    work = base + 1     # remaining value (consumed)
    digit = base + 2    # current digit 0..9
    nz = base + 3       # a higher non-zero digit already printed
    cond = base + 4     # (work >= divisor) / print decision
    s0 = base + 5       # _ge_const + local scratch
    s1 = base + 6
    s2 = base + 7
    s3 = base + 8
    allcells = (work, digit, nz, cond, s0, s1, s2, s3)
    for x in allcells:
        clear(c, x)
    copy(c, v, work, s0)        # work = v (v preserved)

    def emit_one(divisor, force):
        # digit = work // divisor ; work %= divisor   (divisor 1,10,100)
        clear(c, digit)
        if divisor > 1:
            # while (work >= divisor): work -= divisor ; digit += 1
            _ge_const(c, work, divisor, cond, s0, s1, s2, s3)
            c.goto(cond)
            c.emit("[")
            c.goto(work); c.emit("-" * divisor)
            c.goto(digit); c.emit("+")
            _ge_const(c, work, divisor, cond, s0, s1, s2, s3)
            c.goto(cond)
            c.emit("]")
            c.goto(cond)
        else:
            move(c, work, digit)   # units = remaining
        # printable = force or nz or digit!=0  -> cond
        clear(c, cond)
        if force:
            set_const(c, cond, 1)
        else:
            copy(c, nz, cond, s0)              # cond = nz
            copy(c, digit, s1, s0)             # s1 = digit
            c.goto(s1)
            c.emit("[")
            c.goto(cond); c.emit("[-]+")
            c.goto(s1); c.emit("[-]]")
            c.goto(s1)
        # if cond: print '0'+digit ; nz = 1
        c.goto(cond)
        c.emit("[")
        c.goto(cond); c.emit("[-]")
        copy(c, digit, s1, s0)
        c.goto(s1); c.emit("+" * 48); c.emit(".")
        clear(c, s1)
        set_const(c, nz, 1)
        c.goto(cond)
        c.emit("]")
        c.goto(cond)

    emit_one(100, False)
    emit_one(10, False)
    emit_one(1, True)
    for x in allcells:
        clear(c, x)
    c.goto(v)
    c.assert_cursor(v)


def _ge_const(c, x, k, flag, t, under, g, zf):
    """flag = (x >= k) ? 1 : 0. x preserved. t,under,g,zf scratch (left 0).

    Verified guarded-countdown (ported from the reference emit_rel_ge_const):
    t = copy(x); under = 0; do k guarded decrements of t; if any decrement would
    underflow (t already 0) set under; flag = (under == 0)."""
    clear(c, t)
    clear(c, under)
    clear(c, g)
    clear(c, zf)
    copy(c, x, t, g)        # t = x  (g scratch)
    clear(c, under)
    for _ in range(k):
        # guarded dec of t; if t==0 this round, under += 1
        copy(c, t, g, zf)            # g = t
        set_const(c, zf, 1)         # zf = 1 (assume t != 0)
        c.goto(g)
        c.emit("[")                 # g != 0  -> t was nonzero
        c.goto(zf); c.emit("[-]")   # zf = 0 (not the zero case)
        c.goto(t); c.emit("-")      # t -= 1
        c.goto(g); c.emit("[-]")    # g = 0 (exit)
        c.goto(g)
        c.emit("]")
        c.goto(g)
        # if zf (t was 0): under += 1
        c.goto(zf)
        c.emit("[")
        c.goto(under); c.emit("+")
        c.goto(zf); c.emit("[-]")
        c.goto(zf)
        c.emit("]")
        c.goto(zf)
    clear(c, t)
    set_const(c, flag, 1)
    # if under != 0: flag = 0
    c.goto(under)
    c.emit("[")
    c.goto(flag); c.emit("[-]")
    c.goto(under); c.emit("[-]")
    c.goto(under)
    c.emit("]")
    c.goto(under)
    clear(c, g)
    clear(c, zf)



def emit_str(c, s, scratch):
    """Emit the literal bytes of s to output via delta-encoding in `scratch`.
    Leaves scratch at 0. s may be str (codepoints 0..255) or bytes."""
    if isinstance(s, str):
        data = [ord(ch) for ch in s]
        for code in data:
            if not (0 <= code <= 255):
                raise ValueError("emit_str codepoint out of range 0..255: %d" % code)
    else:
        data = list(s)
    clear(c, scratch)
    c.goto(scratch)
    prev = 0
    for code in data:
        delta = code - prev
        if delta > 0:
            c.emit("+" * delta)
        elif delta < 0:
            c.emit("-" * (-delta))
        c.emit(".")
        prev = code
    if prev > 0:
        c.emit("-" * prev)
    elif prev < 0:
        c.emit("+" * (-prev))
    c.assert_cursor(scratch)
