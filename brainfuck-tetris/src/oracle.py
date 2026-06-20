"""Reference pure-Python Brainfuck VM (the oracle).

Plain interpreter (correctness over speed). 8-bit wrapping cells, large tape,
EOF / no-input on ',' returns 0. The canonical entry point is

    run_bf(code, input_bytes=b"") -> (tape, dp, output)

A few thin variants are provided for golden tests / debugging:
    run_bf(..., with_steps=True)   -> (tape, dp, output, steps)
    run_bf(..., dp_clamp=True)     -> clamp dp into [0, tape_size) each move
"""

TAPE_SIZE = 32768


def _bracket_map(code):
    """Precompute matching-bracket jump targets; validate balance."""
    stack = []
    jumps = {}
    for i, ch in enumerate(code):
        if ch == "[":
            stack.append(i)
        elif ch == "]":
            if not stack:
                raise ValueError("unmatched ']' at position %d" % i)
            j = stack.pop()
            jumps[i] = j
            jumps[j] = i
    if stack:
        raise ValueError("unmatched '[' at position %d" % stack[-1])
    return jumps


def run_bf(code, input_bytes=b"", tape_size=TAPE_SIZE, init_tape=None,
           with_steps=False, dp_clamp=False, max_steps=200_000_000):
    """Execute Brainfuck `code`. Returns (tape, dp, output_bytes).

    - tape: list[int] of length tape_size, each 0..255
    - dp: final data pointer
    - output: bytes written by '.'
    - ',' returns the next input byte, or 0 on EOF / no input.

    init_tape: optional {index: value} preload (values masked to 0..255).
    with_steps: if True, returns (tape, dp, output, steps).
    dp_clamp: if True, clamp dp into [0, tape_size) after every move.
    """
    jumps = _bracket_map(code)
    tape = [0] * tape_size
    if init_tape is not None:
        for k, v in init_tape.items():
            tape[k] = v & 0xFF
    dp = 0
    ip = 0
    out = bytearray()
    in_pos = 0
    steps = 0
    n = len(code)
    while ip < n:
        ch = code[ip]
        steps += 1
        if steps > max_steps:
            raise RuntimeError("step limit %d exceeded" % max_steps)
        if ch == "+":
            tape[dp] = (tape[dp] + 1) & 0xFF
        elif ch == "-":
            tape[dp] = (tape[dp] - 1) & 0xFF
        elif ch == ">":
            dp += 1
            if dp_clamp and dp >= tape_size:
                dp = tape_size - 1
            elif dp >= tape_size:
                raise IndexError("data pointer ran past tape end")
        elif ch == "<":
            dp -= 1
            if dp_clamp and dp < 0:
                dp = 0
            elif dp < 0:
                raise IndexError("data pointer ran below 0")
        elif ch == ".":
            out.append(tape[dp])
        elif ch == ",":
            if in_pos < len(input_bytes):
                tape[dp] = input_bytes[in_pos]
                in_pos += 1
            else:
                tape[dp] = 0
        elif ch == "[":
            if tape[dp] == 0:
                ip = jumps[ip]
        elif ch == "]":
            if tape[dp] != 0:
                ip = jumps[ip]
        # any other character is a comment (ignored)
        ip += 1
    if with_steps:
        return tape, dp, bytes(out), steps
    return tape, dp, bytes(out)
