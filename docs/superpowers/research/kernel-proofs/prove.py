import random
from bf import run_bf
from array_macro import Emitter, emit_macro, STRIDE, SP, IX, DT, VL

REGION_LEN = 200
BASE = 2*STRIDE             # leave a guard element below HOME
HOME = BASE - STRIDE        # = STRIDE
GUARD = HOME - STRIDE       # = 0 (never holds data; return-walk undershoots here)
TAPE = BASE + STRIDE*REGION_LEN + STRIDE + 16

def hcell(off): return HOME + off
def gcell(off): return GUARD + off          # USER input cells live in GUARD element
def ecell(i, off): return BASE + STRIDE*i + off
USER_IX = gcell(IX)
USER_VL = gcell(VL)

def build_tape(logical_values):
    tape = [0]*TAPE
    for i, v in enumerate(logical_values):
        tape[ecell(i, DT)] = (v + 1) & 0xFF      # +1 bias: empty(0)->1, id k->k+1
    return tape

def emit_op(op):
    # The compiler cursor enters at HOME+SP. run_bf starts the BF pointer at 0,
    # so we prepend a goto from 0 to HOME+SP (models the compiler having walked
    # the cursor to HOME before the macro). The macro itself assumes entry at HOME+SP.
    e = Emitter(cursor=0)
    e.goto(HOME + SP)          # position pointer at home
    e.cursor = HOME + SP       # macro's internal contract: cursor == HOME+SP
    emit_macro(e, BASE, op)
    return e.code(), e.cursor

CODE_READ, CUR_READ = emit_op('read')
CODE_WRITE, CUR_WRITE = emit_op('write')

def carry_lanes_clean(tape):
    bad = []
    for off in (SP, IX, VL):
        if tape[hcell(off)] != 0: bad.append(('HOME', off, tape[hcell(off)]))
    for i in range(REGION_LEN):
        for off in (SP, IX, VL):
            if tape[ecell(i, off)] != 0:
                bad.append((i, off, tape[ecell(i, off)]))
    return bad

def data_snapshot(tape):
    return [tape[ecell(i, DT)] for i in range(REGION_LEN)]

def do_read(logical_values, idx):
    tape = build_tape(logical_values)
    tape[USER_IX] = idx & 0xFF                   # caller's index in USER cell
    before = data_snapshot(tape)
    out_tape, ptr, _, steps = run_bf(CODE_READ, init_tape=tape, tape_size=TAPE)
    result_logical = out_tape[hcell(DT)] - 1
    assert ptr == HOME + SP, f"read: pointer not home: {ptr} != {HOME+SP}"
    after = data_snapshot(out_tape)
    assert after == before, f"read: region mutated at idx {idx}"
    lanes = carry_lanes_clean(out_tape)
    assert not lanes, f"read: dirty carry lanes {lanes[:5]}"
    assert out_tape[USER_IX] == (idx & 0xFF), (
        f"read[{idx}]: index NOT preserved (USER_IX={out_tape[USER_IX]})")
    assert result_logical == logical_values[idx], (
        f"read[{idx}] got logical {result_logical} expected {logical_values[idx]}")
    return result_logical, steps

def do_write(logical_values, idx, new_val):
    tape = build_tape(logical_values)
    tape[USER_IX] = idx & 0xFF
    tape[USER_VL] = (new_val + 1) & 0xFF        # biased value to store, USER cell
    out_tape, ptr, _, steps = run_bf(CODE_WRITE, init_tape=tape, tape_size=TAPE)
    assert ptr == HOME + SP, f"write: pointer not home: {ptr} != {HOME+SP}"
    lanes = carry_lanes_clean(out_tape)
    assert not lanes, f"write: dirty carry lanes {lanes[:5]}"
    assert out_tape[USER_IX] == (idx & 0xFF), (
        f"write[{idx}]: index NOT preserved (USER_IX={out_tape[USER_IX]})")
    assert out_tape[USER_VL] == ((new_val+1) & 0xFF), (
        f"write[{idx}]: value NOT preserved (USER_VL={out_tape[USER_VL]})")
    got = out_tape[ecell(idx, DT)] - 1
    assert got == new_val, f"write[{idx}] stored logical {got} expected {new_val}"
    for j in range(REGION_LEN):
        if j == idx: continue
        exp = (logical_values[j] + 1) & 0xFF
        assert out_tape[ecell(j, DT)] == exp, (
            f"write[{idx}] corrupted cell {j}: {out_tape[ecell(j,DT)]} != {exp}")
    return steps


def main():
    print(f"READ  macro length: {len(CODE_READ)} BF chars; end cursor={CUR_READ} (HOME+SP={HOME+SP})")
    print(f"WRITE macro length: {len(CODE_WRITE)} BF chars; end cursor={CUR_WRITE} (HOME+SP={HOME+SP})")
    assert CUR_READ == HOME + SP and CUR_WRITE == HOME + SP, "cursor not resynced to home!"

    random.seed(1234)
    base_pattern = [random.choice([0,0,0,1,2,3,4,5,6,7]) for _ in range(REGION_LEN)]
    for idx in (0, 1, 2, 198, 199):
        base_pattern[idx] = 0
    base_pattern[100] = 0

    # ---- PROVE READ over full range ----
    max_steps_read = 0; worst_read_idx = -1
    for idx in range(REGION_LEN):
        val, steps = do_read(base_pattern, idx)
        if steps > max_steps_read:
            max_steps_read, worst_read_idx = steps, idx
    print(f"READ : all {REGION_LEN} indices correct. worst steps={max_steps_read} @idx={worst_read_idx}")

    for idx in (0, 100, 199):
        v,_ = do_read(base_pattern, idx); assert v == 0
    print("READ : empty (logical 0 / stored 1) cells at idx 0,100,199 read back 0  OK")

    # ---- PROVE WRITE over full range ----
    write_plan = [(idx, (idx*3 + 1) % 8) for idx in range(REGION_LEN)]
    live = list(base_pattern)
    max_steps_write = 0; worst_write_idx = -1
    for idx, new_val in write_plan:
        steps = do_write(live, idx, new_val)
        live[idx] = new_val
        if steps > max_steps_write:
            max_steps_write, worst_write_idx = steps, idx
    print(f"WRITE: all {REGION_LEN} writes applied & verified (rest intact). "
          f"worst steps={max_steps_write} @idx={worst_write_idx}")

    for idx in range(REGION_LEN):
        v,_ = do_read(live, idx); assert v == live[idx], f"readback[{idx}] {v} != {live[idx]}"
    print(f"READBACK: all {REGION_LEN} indices match post-write pattern (incl. empties)")

    s = set(live)
    print(f"post-write value set present: {sorted(s)} (must include 0 and 1..7)")
    assert 0 in s and all(k in s for k in range(1,8))

    _, r199 = do_read(live, 199)
    w199 = do_write(live, 199, 7)
    print(f"\nSTEPS/OP @ worst index 199:  read={r199}  write={w199}")
    print("\nALL ASSERTIONS PASSED.")

if __name__ == "__main__":
    main()
