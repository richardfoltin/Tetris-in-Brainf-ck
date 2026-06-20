"""Game-driver building blocks.

These are the absolute-phase pieces of the per-frame loop (input decoding now;
gravity/dispatch wiring grows here in later phases). They allocate their own
cells AFTER the core memory map (src/game.alloc_memory) so REGION_SPEC and the
on-disk memory_map.txt stay untouched.

NOTE (honest): the full closed real-time loop additionally needs a
relative->absolute "did the move/down get blocked" feedback bridge and a
runtime (piece,rot) dispatch over the verified subsystem. Those are tracked as
remaining work; this module currently provides the verified, self-contained
input decoder.
"""
from src.dsl import eq, set_const, copy

# One-hot action flags + decode scratch (allocated by alloc_driver).
DRIVER_CELLS = [
    ("F_LEFT", 1), ("F_RIGHT", 1), ("F_SOFT", 1),
    ("F_ROT", 1), ("F_HARD", 1), ("F_QUIT", 1),
    ("d_a", 1), ("d_b", 1), ("d_t0", 1), ("d_t1", 1),
]

# action flag -> key byte
KEYCODE = {
    "F_LEFT": ord("a"),
    "F_RIGHT": ord("d"),
    "F_SOFT": ord("s"),
    "F_ROT": ord("w"),
    "F_HARD": ord(" "),
    "F_QUIT": ord("q"),
}


def alloc_driver(c):
    for name, size in DRIVER_CELLS:
        if name not in c.names:
            c.alloc(name, size)
    return c


def emit_decode_input(c, src="input_last"):
    """Set the one-hot action flags from the key byte in `src` (preserved).

    For each action: flag = (src == keycode). Exactly one flag is 1 for a
    recognized key; all 0 for an unrecognized key or 0 (no key)."""
    for flag, code in KEYCODE.items():
        copy(c, src, "d_b", "d_t1")          # d_b = key (src preserved)
        set_const(c, "d_a", code)            # d_a = keycode (preserved by eq)
        eq(c, flag, "d_b", "d_a", "d_t0", "d_t1")   # flag = (key == code)
    return c
