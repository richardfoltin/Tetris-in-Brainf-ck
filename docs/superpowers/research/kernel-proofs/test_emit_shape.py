"""
Verify emit_shape: run emitted BF on the interpreter for ALL 28 (piece,rot)
cases plus empty/zero edge cases. Assert out0..out3 equal SHAPES data.
Report worst-case executed steps/op.
"""
import sys
from bf import run_bf
from emit_shape import Compiler, NAMES, SHAPES, emit_shape


def build_and_run(piece, rot):
    c = Compiler(NAMES, tape_size=512)
    # Preload runtime inputs at compile-emit time by emitting set_const for the
    # GIVEN piece/rot at the start, so the runtime cells carry the test values.
    # (In the real game these come from gameplay; here we inject for testing.)
    c.set_const("piece", piece)
    c.set_const("rot", rot)
    emit_shape(c)
    code = c.code()
    tape, ptr, out, steps = run_bf(code)
    o = (tape[NAMES["out0"]], tape[NAMES["out1"]],
         tape[NAMES["out2"]], tape[NAMES["out3"]])
    return o, ptr, steps, code


def main():
    passed = 0
    failed = 0
    max_steps = 0
    transcript = []
    pname = {1: "I", 2: "O", 3: "T", 4: "S", 5: "Z", 6: "J", 7: "L"}

    # All 28 valid cases.
    for piece in range(1, 8):
        for rot in range(0, 4):
            expected = SHAPES[piece][rot]
            o, ptr, steps, code = build_and_run(piece, rot)
            ok = (o == expected) and (ptr == NAMES["home"])
            max_steps = max(max_steps, steps)
            status = "PASS" if ok else "FAIL"
            if ok:
                passed += 1
            else:
                failed += 1
            transcript.append(
                f"{status} p={piece}({pname[piece]}) r={rot} "
                f"got={tuple(format(x,'04b') for x in o)} "
                f"exp={tuple(format(x,'04b') for x in expected)} "
                f"ptr={ptr} steps={steps}")

    # Edge cases: invalid / empty inputs must yield ALL-ZERO masks (empty piece).
    # This is the classic empty-cell failure-mode test.
    edge = [
        (0, 0),   # piece 0 = empty
        (0, 3),
        (8, 0),   # piece 8 = out of range
        (1, 5),   # rot out of range (wraps in 8-bit but != 0..3)
        (255, 255),
    ]
    for piece, rot in edge:
        o, ptr, steps, code = build_and_run(piece, rot)
        # Expected: if (piece,rot) in valid table use it; else all zero.
        if 1 <= piece <= 7 and 0 <= rot <= 3:
            expected = SHAPES[piece][rot]
        else:
            expected = (0, 0, 0, 0)
        ok = (o == expected) and (ptr == NAMES["home"])
        max_steps = max(max_steps, steps)
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        transcript.append(
            f"{status} [EDGE] p={piece} r={rot} "
            f"got={tuple(format(x,'04b') for x in o)} "
            f"exp={tuple(format(x,'04b') for x in expected)} "
            f"ptr={ptr} steps={steps}")

    print("\n".join(transcript))
    print("-" * 60)
    print(f"PASSED={passed} FAILED={failed}")
    print(f"WORST-CASE STEPS/OP = {max_steps}")
    # show emitted code size for one case
    _, _, _, code = build_and_run(1, 0)
    print(f"emitted BF length (chars) for p=1,r=0 = {len(code)}")
    naive = 520000
    print(f"naive 112-cell compare ~= {naive} steps; "
          f"speedup ~= {naive/max_steps:.1f}x")
    assert failed == 0, "SOME CASES FAILED"
    print("ALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
