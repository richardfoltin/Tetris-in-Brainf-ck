from src.dsl import Compiler
from src.game import alloc_memory
from src.driver import alloc_driver, emit_decode_input, KEYCODE
from src.oracle import run_bf

FLAGS = list(KEYCODE.keys())


def _decode(keybyte):
    c = Compiler()
    alloc_memory(c)
    alloc_driver(c)
    emit_decode_input(c)
    tape, dp, out = run_bf(c.build(), init_tape={c.addr("input_last"): keybyte})
    return c, tape


def test_decode_each_key_one_hot_and_preserves_input():
    for flag, code in KEYCODE.items():
        c, tape = _decode(code)
        for f in FLAGS:
            expected = 1 if f == flag else 0
            assert tape[c.addr(f)] == expected, (chr(code), f, tape[c.addr(f)])
        assert tape[c.addr("input_last")] == code      # src preserved


def test_decode_no_key_all_flags_zero():
    c, tape = _decode(0)
    for f in FLAGS:
        assert tape[c.addr(f)] == 0


def test_decode_unknown_key_all_flags_zero():
    c, tape = _decode(ord("z"))
    for f in FLAGS:
        assert tape[c.addr(f)] == 0
