from src.oracle import run_bf
from bf_run import (BFVM, translate_key, vt_mode, next_deadline, sleep_for,
                    balance_brackets, run_sandbox,
                    ENABLE_VIRTUAL_TERMINAL_PROCESSING)


def _run_vm(code, inp=b"", tape_size=4096, init=None):
    vm = BFVM(code, tape_size=tape_size)
    out = bytearray()
    it = iter(inp)

    def rb():
        return next(it, 0)

    status = vm.run(read_byte=rb, write_byte=out.append, init_tape=init)
    return vm.tape, vm.dp, bytes(out), status


# ---- BFVM correctness, differential vs the reference oracle ----------------

DIFF_PROGS = [
    "+++>++",
    "+++++[->+<]",
    "+" * 65 + ".",
    "++[>+++<-]>",                  # 2*3 = 6 in cell 1
    "+++++++[>+++++++<-]>.",        # 7*7 = 49 = '1'
    ",.",                          # echo
    "[-]+++",                      # clear then 3
]


def test_bfvm_matches_oracle():
    for prog in DIFF_PROGS:
        inp = b"Z" if "," in prog else b""
        o_tape, o_dp, o_out = run_bf(prog, input_bytes=inp, tape_size=4096)
        v_tape, v_dp, v_out, status = _run_vm(prog, inp=inp)
        assert v_out == o_out, (prog, v_out, o_out)
        assert v_tape[:16] == o_tape[:16], (prog, v_tape[:16], o_tape[:16])
        assert v_dp == o_dp, (prog, v_dp, o_dp)
        assert status == "ok"


def test_bfvm_clear_opt():
    # [-] must compile to a single clear op, not a loop
    vm = BFVM("+++++[-]")
    assert ["clear"] in vm.ops
    tape, dp, out, status = _run_vm("+++++[-]")
    assert tape[0] == 0


def test_bfvm_wrap():
    tape, dp, out, status = _run_vm("+" * 256)
    assert tape[0] == 0
    tape, dp, out, status = _run_vm("-")
    assert tape[0] == 255


def test_bfvm_step_limit_halts_infinite_loop():
    vm = BFVM("+[]")            # cell=1, loop body empty -> infinite
    status = vm.run(read_byte=lambda: 0, write_byte=lambda v: None,
                    step_limit=10_000)
    assert status == "steplimit"


def test_bfvm_dp_clamp():
    vm = BFVM("<<<")
    status = vm.run(read_byte=lambda: 0, write_byte=lambda v: None,
                    dp_clamp=True)
    assert status == "ok"
    assert vm.dp == 0


# ---- input contract --------------------------------------------------------

def test_translate_key_normal():
    keys = iter(["A"])
    assert translate_key(lambda: next(keys, None)) == ord("a")


def test_translate_key_no_key():
    assert translate_key(lambda: None) == 0
    assert translate_key(lambda: "") == 0


def test_translate_key_function_prefix_discarded():
    seq = iter(["\xe0", "H"])   # arrow-up: prefix + scancode
    got = translate_key(lambda: next(seq, None))
    assert got == 0
    # the scancode 'H' was consumed, not left dangling
    assert next(seq, None) is None


def test_translate_key_space_and_letters():
    assert translate_key(lambda: " ") == 0x20
    assert translate_key(lambda: "Q") == ord("q")


# ---- VT mode ---------------------------------------------------------------

def test_vt_mode_ors_flag():
    assert vt_mode(0x0001) == (0x0001 | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    # idempotent if already set
    m = ENABLE_VIRTUAL_TERMINAL_PROCESSING | 0x0002
    assert vt_mode(m) == m


# ---- frame pacing ----------------------------------------------------------

def test_pacing_math():
    period = 1.0 / 30.0
    t0 = 100.0
    t1 = next_deadline(t0, period)
    assert abs(t1 - (t0 + period)) < 1e-12
    # behind schedule -> no sleep
    assert sleep_for(t1, now=t1 + 0.5) == 0.0
    # ahead -> positive sleep
    assert sleep_for(t1, now=t0) > 0.0


# ---- finale sandbox --------------------------------------------------------

def test_balance_brackets():
    assert balance_brackets("][+[") == "[+[]]"     # drop leading ], close opens
    assert balance_brackets("+++") == "+++"
    assert balance_brackets("[[[") == "[[[]]]"
    assert balance_brackets("]]]") == ""
    # non-command chars stripped
    assert balance_brackets("a+b-c") == "+-"


def test_balance_is_runnable():
    # a balanced program must parse/run without BFError
    code = balance_brackets("][+[")
    BFVM(code).run(read_byte=lambda: 0, write_byte=lambda v: None,
                   step_limit=1000)


def test_run_sandbox_prints():
    out, status = run_sandbox("+++++++[>+++++++<-]>.")  # 7*7=49='1'
    assert out == b"1"
    assert status == "ok"


def test_run_sandbox_infinite_halts():
    out, status = run_sandbox("+[", step_limit=5000)   # balances to +[] -> infinite
    assert status == "steplimit"


def test_run_sandbox_underflow_safe():
    out, status = run_sandbox("<<<<.")                 # clamped, no crash
    assert status == "ok"


def test_run_sandbox_output_cap():
    out, status = run_sandbox("+[.]", step_limit=100000, output_cap=10)
    assert len(out) <= 10
