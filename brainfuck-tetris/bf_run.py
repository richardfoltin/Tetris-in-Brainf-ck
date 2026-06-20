"""
Host VM + terminal I/O for Brainfuck Tetris.

Layers (terminal-touching code kept behind seams so the logic is unit-testable):
  - BFVM            : optimized Brainfuck interpreter (run-length collapse,
                      precomputed bracket jumps, [-]/[+] clear op).
  - translate_key   : pure input-contract logic for ',' (non-blocking, returns
                      0 on no key, discards \\x00/\\xe0 function-key prefixes).
  - vt_mode         : pure Windows VT mode computation.
  - frame pacing     : pure deadline math (next_deadline / sleep_for).
  - balance_brackets / run_sandbox : the finale sandbox.

The actual msvcrt/console/loop wiring lives in main() and is exercised by the
end-to-end smoke test, not unit tests.
"""
import sys

try:
    from src.oracle import BFError
except Exception:  # pragma: no cover - allow running as a script from repo root
    class BFError(Exception):
        pass


# ---------------------------------------------------------------------------
# Optimized Brainfuck VM
# ---------------------------------------------------------------------------

class BFVM:
    def __init__(self, code, tape_size=32768):
        self.code = code
        self.tape_size = tape_size
        self.ops = self._compile(code)
        self.tape = None
        self.dp = 0

    @staticmethod
    def _strip(code):
        return [ch for ch in code if ch in "+-<>[].,"]

    def _compile(self, code):
        src = self._strip(code)
        n = len(src)
        ops = []
        i = 0
        while i < n:
            ch = src[i]
            if ch in "+-":
                net = 0
                while i < n and src[i] in "+-":
                    net += 1 if src[i] == "+" else -1
                    i += 1
                ops.append(["add", net & 0xFF])
            elif ch in "<>":
                net = 0
                while i < n and src[i] in "<>":
                    net += 1 if src[i] == ">" else -1
                    i += 1
                ops.append(["move", net])
            elif ch == ".":
                ops.append(["out"]); i += 1
            elif ch == ",":
                ops.append(["in"]); i += 1
            elif ch == "[":
                if i + 2 < n and src[i + 1] in "+-" and src[i + 2] == "]":
                    ops.append(["clear"]); i += 3
                else:
                    ops.append(["open", None]); i += 1
            elif ch == "]":
                ops.append(["close", None]); i += 1
            else:  # pragma: no cover
                i += 1
        # bracket matching over ops
        stack = []
        for idx, op in enumerate(ops):
            if op[0] == "open":
                stack.append(idx)
            elif op[0] == "close":
                if not stack:
                    raise BFError("unmatched ]")
                j = stack.pop()
                op[1] = j
                ops[j][1] = idx
        if stack:
            raise BFError("unmatched [")
        return ops

    def run(self, read_byte=None, write_byte=None, step_limit=None,
            dp_clamp=False, init_tape=None):
        ops = self.ops
        nops = len(ops)
        size = self.tape_size
        tape = [0] * size
        if init_tape is not None:
            items = init_tape.items() if isinstance(init_tape, dict) else enumerate(init_tape)
            for k, v in items:
                tape[k] = v & 0xFF
        dp = 0
        ip = 0
        steps = 0
        status = "ok"
        while ip < nops:
            op = ops[ip]
            k = op[0]
            steps += 1
            if step_limit is not None and steps > step_limit:
                status = "steplimit"
                break
            if k == "add":
                tape[dp] = (tape[dp] + op[1]) & 0xFF
            elif k == "move":
                dp += op[1]
                if dp < 0:
                    if dp_clamp:
                        dp = 0
                    else:
                        raise BFError("pointer < 0")
                elif dp >= size:
                    if dp_clamp:
                        dp = size - 1
                    else:
                        raise BFError("pointer >= tape_size")
            elif k == "clear":
                tape[dp] = 0
            elif k == "out":
                if write_byte is not None:
                    write_byte(tape[dp])
            elif k == "in":
                v = read_byte() if read_byte is not None else 0
                tape[dp] = v & 0xFF
            elif k == "open":
                if tape[dp] == 0:
                    ip = op[1]
            elif k == "close":
                if tape[dp] != 0:
                    ip = op[1]
            ip += 1
        self.tape = tape
        self.dp = dp
        return status


# ---------------------------------------------------------------------------
# Input contract for ','  (pure logic; real key source injected)
# ---------------------------------------------------------------------------

def translate_key(getch):
    """Translate one non-blocking keyboard read into a BF ',' value.

    `getch()` returns a 1-char str for a pending key, or None/'' if none.
    Returns an int 0..255 (0 == no key). For Windows function/arrow keys the
    first read is '\\x00' or '\\xe0'; we consume and discard the following scan
    code and report 0 (the game uses ASCII keys only).
    """
    ch = getch()
    if not ch:
        return 0
    if ch in ("\x00", "\xe0"):
        getch()  # discard the scan code so it can't register next poll
        return 0
    return ord(ch.lower()[:1]) & 0xFF


# ---------------------------------------------------------------------------
# Windows VT mode (pure)
# ---------------------------------------------------------------------------

ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004


def vt_mode(current_mode):
    """OR the VT-processing flag into an existing console mode."""
    return current_mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING


# ---------------------------------------------------------------------------
# Frame pacing (pure deadline math)
# ---------------------------------------------------------------------------

def next_deadline(prev, period):
    return prev + period


def sleep_for(next_tick, now):
    """Seconds to sleep to hit next_tick (never negative)."""
    d = next_tick - now
    return d if d > 0 else 0.0


# ---------------------------------------------------------------------------
# Finale sandbox
# ---------------------------------------------------------------------------

def balance_brackets(code):
    """Make an arbitrary (possibly streamed) BF buffer syntactically valid:
    drop any ']' that would underflow, and append a ']' for each still-open '['.
    Only BF command chars are kept."""
    out = []
    depth = 0
    for ch in code:
        if ch == "]":
            if depth == 0:
                continue
            depth -= 1
            out.append(ch)
        elif ch == "[":
            depth += 1
            out.append(ch)
        elif ch in "+-<>.,":
            out.append(ch)
    if depth:
        out.append("]" * depth)
    return "".join(out)


def run_sandbox(asm_code, step_limit=2_000_000, output_cap=4096, tape_size=4096):
    """Run a player-assembled BF program safely: balance brackets, bound steps,
    clamp the data pointer, cap output. Returns (output_bytes, status)."""
    code = balance_brackets(asm_code)
    vm = BFVM(code, tape_size=tape_size)
    out = bytearray()

    def wb(v):
        if len(out) < output_cap:
            out.append(v)

    status = vm.run(read_byte=lambda: 0, write_byte=wb,
                    step_limit=step_limit, dp_clamp=True)
    return bytes(out), status


# ---------------------------------------------------------------------------
# Real terminal wiring (not unit-tested; exercised by the smoke test)
# ---------------------------------------------------------------------------

def _enable_vt_windows():  # pragma: no cover
    import ctypes
    k = ctypes.windll.kernel32
    h = k.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    mode = ctypes.c_uint32()
    if not k.GetConsoleMode(h, ctypes.byref(mode)):
        return None
    if not k.SetConsoleMode(h, vt_mode(mode.value)):
        return None
    return (h, mode.value)


def _restore_console(saved):  # pragma: no cover
    if not saved:
        return
    import ctypes
    h, original = saved
    ctypes.windll.kernel32.SetConsoleMode(h, original)


def main(argv=None):  # pragma: no cover - integration path
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python bf_run.py tetris.bf")
        return 2
    with open(argv[0], "r", encoding="utf-8") as f:
        code = f.read()

    if not sys.stdin.isatty():
        sys.stderr.write("warning: run in a real console (Windows Terminal / conhost).\n")

    import time
    import msvcrt

    saved = _enable_vt_windows()
    sys.stdout.write("\x1b[?25l")  # hide cursor
    sys.stdout.flush()

    period = 1.0 / 30.0
    state = {"next_tick": time.perf_counter()}

    def read_byte():
        # frame pacing lives here: one ',' poll per frame
        now = time.perf_counter()
        time.sleep(sleep_for(state["next_tick"], now))
        state["next_tick"] = next_deadline(state["next_tick"], period)
        getch = (lambda: msvcrt.getwch() if msvcrt.kbhit() else None)
        return translate_key(getch)

    def write_byte(v):
        # immediate relay; a later phase buffers a whole frame per write+flush
        sys.stdout.buffer.write(bytes((v,)))
        if v == 0x0A:  # newline -> flush the line
            sys.stdout.buffer.flush()

    vm = BFVM(code)
    try:
        vm.run(read_byte=read_byte, write_byte=write_byte)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?25h")  # show cursor
        sys.stdout.flush()
        _restore_console(saved)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
