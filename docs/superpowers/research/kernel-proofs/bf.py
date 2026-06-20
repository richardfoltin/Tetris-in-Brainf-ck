import sys

def run_bf(code, inp=b"", tape_size=4096, max_steps=50_000_000, init_tape=None):
    # Precompute bracket matching
    jmp = {}
    stack = []
    for i, c in enumerate(code):
        if c == '[':
            stack.append(i)
        elif c == ']':
            j = stack.pop()
            jmp[i] = j
            jmp[j] = i
    if stack:
        raise ValueError("unmatched [")

    if init_tape is not None:
        if len(init_tape) > tape_size:
            tape_size = len(init_tape)
        tape = [x & 0xFF for x in init_tape] + [0] * (tape_size - len(init_tape))
    else:
        tape = [0] * tape_size
    ptr = 0
    pc = 0
    ip = 0  # input index
    out = bytearray()
    steps = 0
    n = len(code)
    while pc < n:
        c = code[pc]
        if c == '>':
            ptr += 1
            if ptr >= tape_size:
                raise IndexError("ptr out of bounds (>)")
        elif c == '<':
            ptr -= 1
            if ptr < 0:
                raise IndexError("ptr out of bounds (<)")
        elif c == '+':
            tape[ptr] = (tape[ptr] + 1) & 0xFF
        elif c == '-':
            tape[ptr] = (tape[ptr] - 1) & 0xFF
        elif c == '.':
            out.append(tape[ptr] & 0xFF)
        elif c == ',':
            if ip < len(inp):
                tape[ptr] = inp[ip] & 0xFF
                ip += 1
            else:
                tape[ptr] = 0  # EOF -> 0
        elif c == '[':
            if tape[ptr] == 0:
                pc = jmp[pc]
        elif c == ']':
            if tape[ptr] != 0:
                pc = jmp[pc]
        else:
            pc += 1
            continue  # don't count non-command chars as steps
        steps += 1
        if steps > max_steps:
            raise RuntimeError("step limit exceeded")
        pc += 1
    return tape, ptr, bytes(out), steps


if __name__ == "__main__":
    # quick self-test: 'Hello World!' classic
    hw = "++++++++[>++++[>++>+++>+++>+<<<<-]>+>+>->>+[<]<-]>>.>---.+++++++..+++.>>.<-.<.+++.------.--------.>>+.>++."
    tape, ptr, out, steps = run_bf(hw)
    print("OUT:", out.decode())
    print("STEPS:", steps)
