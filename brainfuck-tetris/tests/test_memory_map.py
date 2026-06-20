import os

from src.dsl import Compiler
from src.game import (
    REGION_SPEC, alloc_memory, check_no_overlap, cell,
    W, H, WELL_CELLS, EMPTY, ACTIVE, ANCHOR, LOCK_BIAS, LOCKED,
    make_empty_well, render_well,
)


EXPECTED = [
    ("R_PX", 1), ("R_PY", 1), ("R_ROT", 1), ("R_PIECE", 1),
    ("R_NEXT", 1), ("R_COLLIDE", 1),
    ("score_bcd", 6), ("lines_bcd", 3), ("level", 1),
    ("gravity_tick", 1), ("drop_period", 1),
    ("rng_state", 2), ("frame_ctr", 1), ("input_last", 1),
    ("logical_ptr", 1),
    ("tmp0", 1), ("tmp1", 1), ("tmp2", 1), ("tmp3", 1),
    ("tmp4", 1), ("tmp5", 1), ("tmp6", 1), ("tmp7", 1),
    ("ansi_scratch", 2), ("print_scratch", 10),
    ("asm_depth", 1), ("asm_buf", 256),
    ("LEFT_SENT", 1), ("well", WELL_CELLS), ("RIGHT_SENT", 1),
    ("SCRATCH_PAD", WELL_CELLS + 64),
]


def test_region_spec_exact():
    assert REGION_SPEC == EXPECTED


def test_all_names_allocated():
    c = Compiler()
    alloc_memory(c)
    for name, _size in EXPECTED:
        assert name in c.names, "%s not allocated" % name


def test_fixed_order_addresses_are_sequential():
    c = Compiler()
    alloc_memory(c)
    expect_base = 0
    for name, size in EXPECTED:
        assert c.addr(name) == expect_base, "%s base wrong" % name
        expect_base += size


def test_constants():
    assert W == 20
    assert H == 40
    assert WELL_CELLS == 800
    assert EMPTY == 1
    assert ACTIVE == 9
    assert ANCHOR == 10
    assert LOCK_BIAS == 1
    assert LOCKED(3) == 4


def test_no_region_overlap():
    c = Compiler()
    alloc_memory(c)
    assert check_no_overlap(c)


def test_left_sentinel_immediately_left_of_well():
    c = Compiler()
    alloc_memory(c)
    assert c.addr("LEFT_SENT") + 1 == c.addr("well")
    assert c.addr("well") + WELL_CELLS == c.addr("RIGHT_SENT")


def test_cell_addressing_contiguous_stride_w():
    c = Compiler()
    alloc_memory(c)
    base = c.addr("well")
    assert cell(c, 0, 0) == base
    assert cell(c, 19, 0) == base + 19
    assert cell(c, 0, 1) == base + W
    assert cell(c, 19, 39) == base + WELL_CELLS - 1


def test_make_empty_well_biased():
    c = Compiler()
    alloc_memory(c)
    t = make_empty_well(c)
    assert t[cell(c, 0, 0)] == EMPTY
    assert t[cell(c, 19, 39)] == EMPTY
    assert t[c.addr("LEFT_SENT")] == 0
    assert t[c.addr("RIGHT_SENT")] == 0


def test_matches_on_disk_memory_map_txt():
    # tests/memory_map.txt documents the canonical layout; the live allocator
    # must agree on every region's base/size.
    path = os.path.join(os.path.dirname(__file__), "memory_map.txt")
    if not os.path.exists(path):
        return  # artifact optional
    c = Compiler()
    alloc_memory(c)
    bases = {}
    with open(path, "r", encoding="ascii") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 3 and parts[0] in c.names:
                try:
                    base = int(parts[1])
                except ValueError:
                    continue
                bases[parts[0]] = base
    for name, base in bases.items():
        assert c.addr(name) == base, (
            "%s: live base %d != memory_map.txt base %d"
            % (name, c.addr(name), base))


def test_render_well_runs():
    c = Compiler()
    alloc_memory(c)
    tape = [0] * 32768
    base = c.addr("well")
    for i in range(WELL_CELLS):
        tape[base + i] = EMPTY
    tape[base] = ANCHOR
    s = render_well(tape, c)
    assert s.count("\n") == H - 1
    assert s[0] == "@"
