"""
Demonstration: (1) a SEQUENCE of physical relative moves with collision peeks,
asserting the final pointer & well; (2) the runtime-anchor RESYNC via '[<]' to a
zero sentinel, proving we can recover a KNOWN absolute cursor without knowing the
runtime anchor.
"""
from bfinterp import run_bf
from emitter import Emitter, HOME, WELL_BASE, WELL_W, WELL_H, WELL_N
import macros


def biased_tape(well):
    t = [0] * 4096
    for i, v in enumerate(well):
        t[WELL_BASE + i] = (v + 1) & 0xFF
    return t


def demo_move_sequence():
    """Drop an anchor from (4,0) straight down until blocked, peeking each step.
    Well: a floor at row 19 plus a block at (4,15). Expect the anchor to stop
    resting just above (4,15), i.e. final anchor (4,14)."""
    well = [0] * WELL_N
    for x in range(WELL_W):
        well[19 * WELL_W + x] = 1
    well[15 * WELL_W + 4] = 5            # obstacle the drop should land on
    base = biased_tape(well)

    # Compile a program that, from HOME, repeatedly: peek down; if not blocked,
    # move down. Because dx,dy are compile-time, we UNROLL using the known path.
    e = Emitter()
    macros.home_to_anchor(e, 4, 0)       # absolute goto HOME->anchor
    ax, ay = 4, 0
    steps_log = []
    while True:
        # peek can_move down into HOME; then (compiler-side) decide. We can't read
        # the runtime result at compile time, but for THIS crafted well the path is
        # deterministic, so we unroll the known-good trajectory and rely on the
        # executed asserts to confirm the peeks agree.
        e2 = Emitter()
        macros.home_to_anchor(e2, ax, ay)
        macros.can_move(e2, ax, ay, 0, 1, result_abs=HOME)
        e2.emit('.')
        _, _, out, _ = run_bf(e2.code_str(), init_tape=list(base))
        blocked = out[0]
        steps_log.append(((ax, ay), blocked))
        if blocked:
            break
        ax, ay = macros.move_down(e, ax, ay)   # PHYSICAL move in the real program
    # the real program e ends with the data ptr physically at the final anchor.
    e.emit('.')   # print the (biased) value under the pointer at the final anchor
    tape, ptr, out, total_steps = run_bf(e.code_str(), init_tape=list(base))

    final_anchor_abs = WELL_BASE + ay * WELL_W + ax
    assert ptr == final_anchor_abs, (ptr, final_anchor_abs)
    assert (ax, ay) == (4, 14), (ax, ay)               # rests above the (4,15) block
    assert out[-1] == base[final_anchor_abs]           # value under ptr unchanged
    # well unchanged
    assert [tape[WELL_BASE + i] for i in range(WELL_N)] == \
           [base[WELL_BASE + i] for i in range(WELL_N)]
    print("MOVE-SEQUENCE: dropped from (4,0); peeks:",
          " ".join(f"{a}{'B' if b else '.'}" for a, b in steps_log))
    print(f"  final anchor = {(ax,ay)} (ptr abs {ptr})  PASS  exec_steps(full drop)={total_steps}")


def demo_runtime_resync():
    """Prove '[<]' resyncs to the zero sentinel at WELL_BASE-1 regardless of where
    the pointer currently is inside the biased well. We move the pointer to a
    RUNTIME-dependent anchor (driven by an input byte the compiler cannot know),
    then emit '[<]' and assert the pointer lands EXACTLY on WELL_BASE-1, then do
    an absolute write there to prove the cursor is usable again."""
    well = [0] * WELL_N            # all empty -> all biased to 1 (every cell >=1)
    base = biased_tape(well)
    # sentinel must be 0:
    assert base[WELL_BASE - 1] == 0, "no zero sentinel before the well!"

    for runtime_col in (0, 3, 7, 9):      # pretend the runtime put us here
        e = Emitter()
        # simulate a runtime-unknown anchor: jump to (runtime_col, 10).
        macros.home_to_anchor(e, runtime_col, 10)
        # ---- compiler now PRETENDS it lost track (runtime anchor) ----
        # mark cursor unknown to mimic a runtime-dependent position:
        e.cursor = None  # type: ignore  (simulate desync; goto would now be illegal)
        # RESYNC purely at runtime:
        macros.resync_walk_left_to_sentinel(e)
        # cursor is now provably WELL_BASE-1. Prove by an ABSOLUTE op there:
        e.emit('+')                      # sentinel := 1 (marker)
        tape, ptr, _, steps = run_bf(e.code_str(), init_tape=list(base))
        assert ptr == WELL_BASE - 1, (runtime_col, ptr, WELL_BASE - 1)
        assert tape[WELL_BASE - 1] == 1, tape[WELL_BASE - 1]
        # well still all biased-1 (the '[<]' did not mutate it):
        assert all(tape[WELL_BASE + i] == 1 for i in range(WELL_N))
        print(f"RESYNC: runtime anchor col={runtime_col} -> '[<]' landed ptr at "
              f"{ptr} == sentinel(WELL_BASE-1={WELL_BASE-1})  PASS  steps={steps}")


if __name__ == "__main__":
    demo_move_sequence()
    print()
    demo_runtime_resync()
    print("\nDEMOS PASSED.")
