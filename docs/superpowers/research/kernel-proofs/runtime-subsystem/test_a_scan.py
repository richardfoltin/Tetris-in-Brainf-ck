"""
PROVE subsystem A: SCAN-LOCATE.

We build a well, place ACTIVE body cells (9) and exactly one ANCHOR (10) at a
chosen (x,y). We then emit:  goto(LEFT_SENT); scan_to_anchor; <mark current
cell distinctly> ; resync.  We verify:
  - the cell that got marked is exactly the intended anchor cell (so the
    pointer landed correctly), proving scan-locate without absolute indexing.
  - all OTHER well cells are unchanged (non-destructive).
  - after resync the pointer is on LEFT_SENT.
"""

from bf import run_bf, Emitter
from layout import (W, H, WELL_CELLS, WELL_BASE, LEFT_SENT, RIGHT_SENT,
                    cell, make_empty_well, EMPTY, ACTIVE, ANCHOR, WELL_BASE as WB)
from scan import emit_scan_to_anchor, emit_resync_to_left_sentinel

# A "tag" value we write where the pointer lands so we can detect the landing.
TAG = 200

def build_well_with_anchor(ax, ay, body_cells):
    t = make_empty_well()
    for (x, y) in body_cells:
        t[cell(x, y)] = ACTIVE
    t[cell(ax, ay)] = ANCHOR
    return t

def run_case(ax, ay, body_cells):
    init = build_well_with_anchor(ax, ay, body_cells)
    e = Emitter()
    # cursor starts at 0; move to WELL_BASE to begin the scan
    e.goto(WELL_BASE)
    emit_scan_to_anchor(e)
    # We are riding the anchor (relative). Write TAG into current cell to mark
    # where we landed (destructive ONLY to this cell, for the test).
    e.emit('[-]')                 # zero current (was 10)
    e.emit('+' * TAG)             # set TAG
    # now resync to left sentinel
    emit_resync_to_left_sentinel(e)
    # prove we are at LEFT_SENT by writing a recognizable value there
    e.emit('>')                   # step into well cell 0 ... no: just verify ptr
    # Actually verify ptr == LEFT_SENT directly via tape inspection of where we
    # ended. We'll instead not move; we read final ptr from interpreter.
    e.emit('<')                   # undo the > we just added
    code = e.code()
    tape, ptr, out, steps = run_bf(code, init_tape=init)
    return tape, ptr, steps, code

def main():
    cases = [
        # (anchor x, anchor y, body cells)
        (0, 0,  [(1,0),(2,0),(3,0)]),         # top-left
        (10, 0, [(9,0),(11,0),(10,1)]),       # top middle
        (19, 0, [(18,0),(17,0),(16,0)]),      # top-right
        (5, 20, [(5,19),(5,21),(6,20)]),      # middle of well
        (19, 39,[(18,39),(17,39),(19,38)]),   # bottom-right (last well cell)
        (0, 39, [(1,39),(2,39),(0,38)]),      # bottom-left
    ]
    all_ok = True
    print("=== SUBSYSTEM A: SCAN-LOCATE PROOF ===\n")
    for (ax, ay, body) in cases:
        tape, ptr, steps, code = run_case(ax, ay, body)
        anchor_cell = cell(ax, ay)
        # 1) landing: the TAG must be exactly at anchor_cell
        landed_ok = (tape[anchor_cell] == TAG)
        # 2) where is TAG actually?
        tag_positions = [i for i in range(WELL_BASE, RIGHT_SENT) if tape[i] == TAG]
        # 3) non-destructive: every other well cell holds its expected value
        ok_rest = True
        for x in range(W):
            for y in range(H):
                c = cell(x, y)
                if c == anchor_cell:
                    continue
                exp = ACTIVE if (x, y) in body else EMPTY
                if tape[c] != exp:
                    ok_rest = False
                    break
            if not ok_rest:
                break
        # 4) final pointer on LEFT_SENT
        ptr_ok = (ptr == LEFT_SENT)
        sent_ok = (tape[LEFT_SENT] == 0 and tape[RIGHT_SENT] == 0)
        ok = landed_ok and ok_rest and ptr_ok and sent_ok
        all_ok = all_ok and ok
        print(f"anchor=({ax:2d},{ay:2d}) cell={anchor_cell:3d}  "
              f"land@{tag_positions} expect[{anchor_cell}]  "
              f"land={'OK' if landed_ok else 'FAIL'}  "
              f"nondestr={'OK' if ok_rest else 'FAIL'}  "
              f"ptr={ptr}({'OK' if ptr_ok else 'FAIL'})  "
              f"sent={'OK' if sent_ok else 'FAIL'}  "
              f"steps={steps}  => {'PASS' if ok else 'FAIL'}")
    print()
    print("SUBSYSTEM A:", "ALL PASS" if all_ok else "FAILURES PRESENT")
    return all_ok

if __name__ == '__main__':
    import sys
    sys.exit(0 if main() else 1)
