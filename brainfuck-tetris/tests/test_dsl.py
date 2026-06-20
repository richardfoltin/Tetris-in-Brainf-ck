import pytest

from src.dsl import (
    Compiler, clear, set_const, move, copy, add, sub, mul,
    eq, neq, gt, if_, if_else, while_, print_dec, emit_str,
    is_zero, if_then_consume, switch_cascade,
)
from src.oracle import run_bf


def _prog(build_fn):
    c = Compiler()
    build_fn(c)
    return run_bf(c.build())


# ---------------------------------------------------------------- Compiler
def test_alloc_assigns_increasing_bases():
    c = Compiler()
    a = c.alloc("a")
    b = c.alloc("b")
    well = c.alloc("well", 200)
    after = c.alloc("after")
    assert a == 0
    assert b == 1
    assert well == 2
    assert after == 202


def test_addr_offset():
    c = Compiler()
    c.alloc("region", 4)
    assert c.addr("region") == 0
    assert c.addr("region", 3) == 3


def test_addr_accepts_int():
    c = Compiler()
    assert c.addr(5) == 5
    assert c.addr(5, 2) == 7


def test_alloc_duplicate_raises():
    c = Compiler()
    c.alloc("x")
    with pytest.raises(ValueError):
        c.alloc("x")


def test_goto_emits_correct_moves_and_updates_cursor():
    c = Compiler()
    c.alloc("a")
    c.alloc("b")
    c.alloc("c")
    c.goto("c")
    assert c.cursor == 2
    assert c.build() == ">>"
    c.goto("a")
    assert c.cursor == 0
    assert c.build() == ">><<"


def test_goto_accepts_int_target():
    c = Compiler()
    c.goto(3)
    assert c.cursor == 3
    assert c.build() == ">>>"


def test_emit_rejects_raw_pointer_moves():
    c = Compiler()
    with pytest.raises(ValueError):
        c.emit(">")
    with pytest.raises(ValueError):
        c.emit("<")


def test_assert_cursor_ok_and_fail():
    c = Compiler()
    c.alloc("a")
    c.alloc("b")
    c.goto("b")
    c.assert_cursor("b")
    with pytest.raises(AssertionError):
        c.assert_cursor("a")


def test_build_program_runs_on_oracle():
    c = Compiler()
    c.alloc("a")
    c.alloc("b")
    c.goto("a")
    c.emit("+++")
    c.goto("b")
    c.emit("++")
    tape, dp, out = run_bf(c.build())
    assert tape[0] == 3
    assert tape[1] == 2
    assert dp == 1


# ---------------------------------------------------------- clear/set_const
def test_clear_zeroes_cell_and_is_neutral():
    def b(c):
        c.alloc("v")
        c.goto("v")
        c.emit("+++++")
        clear(c, "v")
        c.assert_cursor("v")
    tape, dp, out = _prog(b)
    assert tape[0] == 0


def test_set_const_small():
    def b(c):
        c.alloc("v")
        set_const(c, "v", 7)
        c.assert_cursor("v")
    tape, dp, out = _prog(b)
    assert tape[0] == 7


def test_set_const_overwrites_existing():
    def b(c):
        c.alloc("v")
        c.goto("v")
        c.emit("+" * 15)
        set_const(c, "v", 3)
    tape, dp, out = _prog(b)
    assert tape[0] == 3


def test_set_const_max():
    def b(c):
        c.alloc("v")
        set_const(c, "v", 255)
    tape, dp, out = _prog(b)
    assert tape[0] == 255


def test_set_const_out_of_range_raises():
    c = Compiler()
    c.alloc("v")
    with pytest.raises(ValueError):
        set_const(c, "v", 256)


# ---------------------------------------------------------------- move/copy
def test_move_adds_src_into_dst_and_zeroes_src():
    def b(c):
        c.alloc("src")
        c.alloc("dst")
        set_const(c, "src", 9)
        set_const(c, "dst", 4)
        move(c, "src", "dst")
        c.assert_cursor("src")
    tape, dp, out = _prog(b)
    assert tape[0] == 0
    assert tape[1] == 13


def test_copy_preserves_src_sets_dst():
    def b(c):
        c.alloc("src")
        c.alloc("dst")
        c.alloc("tmp")
        set_const(c, "src", 12)
        set_const(c, "dst", 99)
        set_const(c, "tmp", 77)
        copy(c, "src", "dst", "tmp")
        c.assert_cursor("src")
    tape, dp, out = _prog(b)
    assert tape[0] == 12
    assert tape[1] == 12
    assert tape[2] == 0


# ----------------------------------------------------------------- add/sub
def test_add_preserves_src():
    def b(c):
        c.alloc("dst")
        c.alloc("src")
        c.alloc("tmp")
        set_const(c, "dst", 10)
        set_const(c, "src", 7)
        add(c, "dst", "src", "tmp")
    tape, dp, out = _prog(b)
    assert tape[0] == 17
    assert tape[1] == 7
    assert tape[2] == 0


def test_add_wraps():
    def b(c):
        c.alloc("dst")
        c.alloc("src")
        c.alloc("tmp")
        set_const(c, "dst", 250)
        set_const(c, "src", 10)
        add(c, "dst", "src", "tmp")
    tape, dp, out = _prog(b)
    assert tape[0] == 4


def test_sub_preserves_src():
    def b(c):
        c.alloc("dst")
        c.alloc("src")
        c.alloc("tmp")
        set_const(c, "dst", 20)
        set_const(c, "src", 8)
        sub(c, "dst", "src", "tmp")
    tape, dp, out = _prog(b)
    assert tape[0] == 12
    assert tape[1] == 8


def test_sub_wraps_below_zero():
    def b(c):
        c.alloc("dst")
        c.alloc("src")
        c.alloc("tmp")
        set_const(c, "dst", 3)
        set_const(c, "src", 5)
        sub(c, "dst", "src", "tmp")
    tape, dp, out = _prog(b)
    assert tape[0] == 254


# --------------------------------------------------------------------- mul
def test_mul_7_times_9_is_63():
    def b(c):
        c.alloc("dst"); c.alloc("src"); c.alloc("t0"); c.alloc("t1")
        set_const(c, "dst", 7)
        set_const(c, "src", 9)
        mul(c, "dst", "src", "t0", "t1")
    tape, dp, out = _prog(b)
    assert tape[0] == 63
    assert tape[1] == 9
    assert tape[2] == 0
    assert tape[3] == 0


def test_mul_by_zero():
    def b(c):
        c.alloc("dst"); c.alloc("src"); c.alloc("t0"); c.alloc("t1")
        set_const(c, "dst", 14)
        set_const(c, "src", 0)
        mul(c, "dst", "src", "t0", "t1")
    tape, dp, out = _prog(b)
    assert tape[0] == 0


def test_mul_wraps():
    def b(c):
        c.alloc("dst"); c.alloc("src"); c.alloc("t0"); c.alloc("t1")
        set_const(c, "dst", 20)
        set_const(c, "src", 20)
        mul(c, "dst", "src", "t0", "t1")
    tape, dp, out = _prog(b)
    assert tape[0] == 144


# ----------------------------------------------------------------- eq/neq
def _eq_case(av, bv):
    def b(c):
        for n in ("dst", "a", "b", "t0", "t1"):
            c.alloc(n)
        set_const(c, "a", av)
        set_const(c, "b", bv)
        eq(c, "dst", "a", "b", "t0", "t1")
    return _prog(b)


def test_eq_true():
    tape, dp, out = _eq_case(5, 5)
    assert tape[0] == 1
    assert tape[2] == 5


def test_eq_false():
    tape, dp, out = _eq_case(5, 8)
    assert tape[0] == 0
    assert tape[2] == 8


def test_eq_zero_zero_true():
    tape, dp, out = _eq_case(0, 0)
    assert tape[0] == 1


def _neq_case(av, bv):
    def b(c):
        for n in ("dst", "a", "b", "t0", "t1"):
            c.alloc(n)
        set_const(c, "a", av)
        set_const(c, "b", bv)
        neq(c, "dst", "a", "b", "t0", "t1")
    return _prog(b)


def test_neq_true():
    tape, dp, out = _neq_case(2, 9)
    assert tape[0] == 1


def test_neq_false():
    tape, dp, out = _neq_case(7, 7)
    assert tape[0] == 0


# --------------------------------------------------------------------- gt
def _gt_case(av, bv):
    def b(c):
        for n in ("dst", "a", "b", "t0", "t1"):
            c.alloc(n)
        set_const(c, "a", av)
        set_const(c, "b", bv)
        gt(c, "dst", "a", "b", "t0", "t1")
    return _prog(b)


def test_gt_greater():
    assert _gt_case(9, 3)[0][0] == 1


def test_gt_equal_is_false():
    assert _gt_case(7, 7)[0][0] == 0


def test_gt_less_is_false():
    assert _gt_case(2, 200)[0][0] == 0


def test_gt_max_vs_zero():
    assert _gt_case(255, 0)[0][0] == 1


# ----------------------------------------------------------------- if_/else
def _neutral(c, work_fn):
    """Run work_fn but return the cursor to where the body started (so the body
    is pointer-neutral, as if_/if_else require)."""
    start = c.cursor
    work_fn(c)
    c.goto(start)


def test_if_runs_body_when_true():
    def b(c):
        c.alloc("cond"); c.alloc("out"); c.alloc("t0"); c.alloc("t1")
        set_const(c, "cond", 1)
        set_const(c, "out", 5)
        if_(c, "cond",
            lambda c: _neutral(c, lambda c: set_const(c, "out", 42)),
            "t0", "t1")
    tape, dp, out = _prog(b)
    assert tape[1] == 42


def test_if_skips_body_when_false():
    def b(c):
        c.alloc("cond"); c.alloc("out"); c.alloc("t0"); c.alloc("t1")
        set_const(c, "cond", 0)
        set_const(c, "out", 5)
        if_(c, "cond",
            lambda c: _neutral(c, lambda c: set_const(c, "out", 42)),
            "t0", "t1")
    tape, dp, out = _prog(b)
    assert tape[1] == 5


def test_if_else_then_branch():
    def b(c):
        c.alloc("cond"); c.alloc("out"); c.alloc("t0"); c.alloc("t1")
        set_const(c, "cond", 1)
        if_else(c, "cond",
                lambda c: _neutral(c, lambda c: set_const(c, "out", 11)),
                lambda c: _neutral(c, lambda c: set_const(c, "out", 22)),
                "t0", "t1")
    tape, dp, out = _prog(b)
    assert tape[1] == 11


def test_if_else_else_branch():
    def b(c):
        c.alloc("cond"); c.alloc("out"); c.alloc("t0"); c.alloc("t1")
        set_const(c, "cond", 0)
        if_else(c, "cond",
                lambda c: _neutral(c, lambda c: set_const(c, "out", 11)),
                lambda c: _neutral(c, lambda c: set_const(c, "out", 22)),
                "t0", "t1")
    tape, dp, out = _prog(b)
    assert tape[1] == 22


# ------------------------------------------------------------------- while_
def test_while_counts_down_and_accumulates():
    def b(c):
        for n in ("cond", "i", "acc", "one", "tmp"):
            c.alloc(n)
        set_const(c, "i", 5)
        set_const(c, "acc", 0)
        set_const(c, "one", 1)
        def recompute(c):
            copy(c, "i", "cond", "tmp")
            c.goto("cond")
        def body(c):
            add(c, "acc", "one", "tmp")
            sub(c, "i", "one", "tmp")
            c.goto("cond")
        recompute(c)
        while_(c, "cond", recompute, body)
    tape, dp, out = _prog(b)
    # acc == 5, i == 0
    c = Compiler()
    for n in ("cond", "i", "acc", "one", "tmp"):
        c.alloc(n)
    assert tape[c.addr("i")] == 0
    assert tape[c.addr("acc")] == 5


def test_while_zero_cond_runs_zero_times():
    def b(c):
        for n in ("cond", "acc", "one", "tmp"):
            c.alloc(n)
        set_const(c, "acc", 0)
        set_const(c, "one", 1)
        set_const(c, "cond", 0)
        while_(c, "cond",
               lambda c: c.goto("cond"),
               lambda c: add(c, "acc", "one", "tmp") or c.goto("cond"))
    tape, dp, out = _prog(b)
    assert tape[1] == 0


# ----------------------------------------------------------------- print_dec
def _print_dec(value):
    c = Compiler()
    c.alloc("v")
    c.alloc("scratch", 8)
    set_const(c, "v", value)
    print_dec(c, "v", "scratch")
    tape, dp, out = run_bf(c.build())
    return out, tape[c.addr("v")]


def test_print_dec_zero():
    out, v = _print_dec(0)
    assert out == b"0"
    assert v == 0


def test_print_dec_42_preserves_value():
    out, v = _print_dec(42)
    assert out == b"42"
    assert v == 42


def test_print_dec_255():
    out, v = _print_dec(255)
    assert out == b"255"
    assert v == 255


def test_print_dec_requires_adjacent_scratch():
    c = Compiler()
    c.alloc("v")
    c.alloc("gap")
    c.alloc("scratch", 9)
    with pytest.raises(AssertionError):
        print_dec(c, "v", "scratch")


# ------------------------------------------------------------------ emit_str
def test_emit_str_ascii():
    def b(c):
        c.alloc("s")
        emit_str(c, "Hi", "s")
        c.assert_cursor("s")
    tape, dp, out = _prog(b)
    assert out == b"Hi"
    assert tape[0] == 0


def test_emit_str_ansi_escape_home():
    def b(c):
        c.alloc("s")
        emit_str(c, "\x1b[H", "s")
    tape, dp, out = _prog(b)
    assert out == b"\x1b[H"


def test_emit_str_empty():
    def b(c):
        c.alloc("s")
        emit_str(c, "", "s")
    tape, dp, out = _prog(b)
    assert out == b""


def test_emit_str_accepts_bytes():
    def b(c):
        c.alloc("s")
        emit_str(c, b"\x00A", "s")
    tape, dp, out = _prog(b)
    assert out == b"\x00A"


# --------------------------------------------- is_zero / switch_cascade
def test_is_zero_true_and_false():
    def b(c):
        c.alloc("x"); c.alloc("out"); c.alloc("t")
        set_const(c, "x", 0)
        is_zero(c, "x", "out", "t")
    tape, dp, out = _prog(b)
    assert tape[1] == 1

    def b2(c):
        c.alloc("x"); c.alloc("out"); c.alloc("t")
        set_const(c, "x", 7)
        is_zero(c, "x", "out", "t")
    tape2, dp2, out2 = _prog(b2)
    assert tape2[1] == 0
    assert tape2[0] == 7  # preserved


def test_switch_cascade_fires_matching_branch():
    def b(c):
        for n in ("work", "r0", "r1", "r2", "g", "m", "t"):
            c.alloc(n)
        set_const(c, "work", 2)
        cands = [
            (1, lambda: set_const(c, "r0", 100) or c.goto("work")),
            (2, lambda: set_const(c, "r1", 200) or c.goto("work")),
            (3, lambda: set_const(c, "r2", 50) or c.goto("work")),
        ]
        switch_cascade(c, "work", cands, "g", "m", "t")
    tape, dp, out = _prog(b)
    c = Compiler()
    for n in ("work", "r0", "r1", "r2", "g", "m", "t"):
        c.alloc(n)
    assert tape[c.addr("r0")] == 0
    assert tape[c.addr("r1")] == 200
    assert tape[c.addr("r2")] == 0


def test_switch_cascade_no_match():
    def b(c):
        for n in ("work", "r0", "r1", "g", "m", "t"):
            c.alloc(n)
        set_const(c, "work", 9)
        cands = [
            (1, lambda: set_const(c, "r0", 100) or c.goto("work")),
            (2, lambda: set_const(c, "r1", 200) or c.goto("work")),
        ]
        switch_cascade(c, "work", cands, "g", "m", "t")
    tape, dp, out = _prog(b)
    assert tape[1] == 0
    assert tape[2] == 0
