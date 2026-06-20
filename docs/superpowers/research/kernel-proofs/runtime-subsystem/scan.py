"""
Subsystem A primitives (contiguous well).

emit_scan_to_anchor: from WELL_BASE move the pointer onto the unique ANCHOR(10)
  cell via a value-scan. Non-destructive. O(cells). Enters a relative section
  with local offset 0 == anchor.

emit_resync_to_left_sentinel: '[<]' walks left while current != 0. Every well
  col cell is >= 1; LEFT_SENT (just left of WELL_BASE) is 0. So '[<]' lands
  exactly on LEFT_SENT. Then we resync the compiler cursor to LEFT_SENT.
"""

from layout import (WELL_BASE, LEFT_SENT, ANCHOR)


def emit_scan_to_anchor(e):
    """Scan to the UNIQUE cell with value EXACTLY 10 (the anchor). Lands on it;
    restores everything. Local offset 0 == anchor."""
    assert e.cursor == WELL_BASE, f"scan must start at WELL_BASE; cursor={e.cursor}"
    e.begin_rel()
    e.emit('-' * ANCHOR)          # cur -= 10
    e.emit('[')                   # while cur != 0 (not the anchor):
    e.emit('+' * ANCHOR)          #   restore this cell
    e.emit('>')                   #   step right
    e.emit('-' * ANCHOR)          #   subtract 10 from new current
    e.emit(']')
    e.emit('+' * ANCHOR)          # restore the anchor cell to 10
    e._rel_net = 0                # define local offset 0 == anchor
    return e


def emit_scan_to_anchor_ge(e, anchor_lo=ANCHOR):
    """
    Scan to the first cell with value >= anchor_lo (used when the anchor may be
    OVERLAID with a transported bit, e.g. 10 or 11). All well non-anchor cells
    are <= 9 < anchor_lo, so it lands on the (overlaid) anchor. Non-destructive.
    Mechanism: subtract (anchor_lo) using the same restore-and-step idiom; a cell
    with value v < anchor_lo gives v-anchor_lo != 0 (it wrapped, nonzero) -> keep
    going; the anchor (>= anchor_lo) ... we need value EXACTLY hitting 0. With
    overlay the anchor is anchor_lo or anchor_lo+1, so subtracting anchor_lo
    gives 0 or 1. We must STOP on either. So we instead stop on the first cell
    whose value, after subtracting (anchor_lo - 1), and a further test, ...
    Simpler: anchors are the ONLY cells >= 10. Stop on first cell with value
    that does NOT become 'still < 0-ish'. We implement: per cell compute
    (value - 9): cells 1..9 -> wraps to 248..0 (cell 9 -> 0!). Conflict.
    => Keep overlay to exactly {10, 11}. Scan for value 10 OR 11 by: subtract 10;
    a non-anchor (1..9) -> 247..255 (nonzero); anchor 10 -> 0 (stop); anchor 11
    -> 1 (NONzero -> would NOT stop). So a +1 overlay breaks the ==10 scan.
    Therefore we transport the wall bit a DIFFERENT way (see tetris.py: we keep
    the anchor EXACTLY 10 and seed ACC from walls via a pre-scan plant at a fixed
    well cell). This function is retained only for the == case.
    """
    return emit_scan_to_anchor(e)


def emit_resync_to_left_sentinel(e):
    """Pre: pointer riding a well cell (relative). Post: pointer on LEFT_SENT."""
    e.emit('[<]')
    e.resync(LEFT_SENT)
    return e
