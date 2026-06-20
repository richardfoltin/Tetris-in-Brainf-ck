"""
Build entrypoint: compile the game to tetris.bf and emit the memory map.

  python build.py   -> writes tetris.bf + tests/memory_map.txt
"""
import os

from src.game import build_game, init_well, emit_render_well, dump_memory_map

ROOT = os.path.dirname(os.path.abspath(__file__))


def build():
    c = build_game()                 # allocate memory + assert no overlap
    init_well(c)                     # fill the well with EMPTY (biased 1)
    emit_render_well(c)              # one static ANSI render pass

    bf = c.build()
    with open(os.path.join(ROOT, "tetris.bf"), "w", encoding="utf-8") as f:
        f.write(bf)
    dump_memory_map(c, os.path.join(ROOT, "tests", "memory_map.txt"))

    print(f"tetris.bf: {len(bf)} BF chars")
    print(f"cells used: {c.next_free} (tape >= 32768 OK: {c.next_free <= 32768})")
    return c


if __name__ == "__main__":
    build()
