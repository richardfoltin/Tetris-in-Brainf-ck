import sys

def run_bf(code, inp=b"", max_steps=100_000_000, tape_size=4096, init_tape=None, start_ptr=0):
    # Pre-match brackets
    jump = {}
    stack = []
    for i, c in enumerate(code):
        if c == '[':
            stack.append(i)
        elif c == ']':
            j = stack.pop()
            jump[i] = j
            jump[j] = i
    if stack:
        raise ValueError("unmatched [")

    if init_tape is not None:
        tape = list(init_tape) + [0] * (tape_size - len(init_tape))
        tape = tape[:tape_size]
    else:
        tape = [0] * tape_size
    ptr = start_ptr
    ip = 0
    out = bytearray()
    in_pos = 0
    steps = 0
    n = len(code)
    while ip < n:
        c = code[ip]
        if c == '>':
            ptr += 1
            if ptr >= tape_size:
                raise IndexError("ptr ran off right end")
        elif c == '<':
            ptr -= 1
            if ptr < 0:
                raise IndexError("ptr ran off left end")
        elif c == '+':
            tape[ptr] = (tape[ptr] + 1) & 0xFF
        elif c == '-':
            tape[ptr] = (tape[ptr] - 1) & 0xFF
        elif c == '.':
            out.append(tape[ptr])
        elif c == ',':
            if in_pos < len(inp):
                tape[ptr] = inp[in_pos]
                in_pos += 1
            else:
                tape[ptr] = 0  # EOF -> 0
        elif c == '[':
            if tape[ptr] == 0:
                ip = jump[ip]
        elif c == ']':
            if tape[ptr] != 0:
                ip = jump[ip]
        else:
            ip += 1
            continue  # comment char, not counted as a step
        steps += 1
        if steps > max_steps:
            raise RuntimeError("step limit exceeded")
        ip += 1
    return tape, ptr, bytes(out), steps


if __name__ == "__main__":
    # quick self test: print 'A'
    code = "+" * 65 + "."
    tape, ptr, out, steps = run_bf(code)
    print("selftest out:", out, "steps:", steps)
