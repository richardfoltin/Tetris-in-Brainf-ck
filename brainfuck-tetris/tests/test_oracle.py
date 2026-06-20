from src.oracle import run_bf, TAPE_SIZE


def test_plus_and_pointer():
    tape, dp, out = run_bf("+++>++")
    assert tape[0] == 3
    assert tape[1] == 2
    assert dp == 1
    assert out == b""


def test_clear_idiom():
    tape, dp, out = run_bf("+++++[-]")
    assert tape[0] == 0


def test_8bit_wrap_up():
    tape, dp, out = run_bf("+" * 256)
    assert tape[0] == 0


def test_8bit_wrap_down():
    tape, dp, out = run_bf("-")
    assert tape[0] == 255


def test_loop_move():
    tape, dp, out = run_bf("+++++[->+<]")
    assert tape[0] == 0
    assert tape[1] == 5


def test_output_byte():
    tape, dp, out = run_bf("+" * 65 + ".")
    assert out == b"A"


def test_input_consumed():
    tape, dp, out = run_bf(",.", input_bytes=b"Z")
    assert out == b"Z"
    assert tape[0] == ord("Z")


def test_input_eof_is_zero():
    tape, dp, out = run_bf(",", input_bytes=b"")
    assert tape[0] == 0


def test_nested_loops_balanced_jumps():
    tape, dp, out = run_bf("++[>+++<-]>")
    assert tape[1] == 6
    assert dp == 1


def test_with_steps_counts():
    tape, dp, out, steps = run_bf("+++", with_steps=True)
    assert steps == 3
    assert tape[0] == 3


def test_dp_clamp_prevents_underflow():
    # Without clamp this would raise; with clamp dp stays at 0.
    tape, dp, out = run_bf("<+", dp_clamp=True)
    assert dp == 0
    assert tape[0] == 1


def test_init_tape_preload():
    tape, dp, out = run_bf(".", init_tape={0: 70})
    assert out == b"F"


def test_tape_size_is_large():
    assert TAPE_SIZE >= 4096
