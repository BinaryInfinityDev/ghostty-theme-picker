"""Tests for terminal frame composition.

The key regression guarded here: in raw mode a bare ``\\n`` moves the cursor
down but NOT back to column 1, so a frame whose rows are separated only by
``\\n`` cascades diagonally ("the screen goes crazy"). ``compose_frame`` must
position every row at column 1 explicitly.

We verify this with a minimal terminal emulator that models raw-mode line
feeds (down only), so a regression to bare ``\\n`` separators fails the test.
"""

import re
import unittest

from ghostty_theme_picker.terminal import compose_frame


def emulate(data: str, rows: int = 12, cols: int = 60) -> list[str]:
    """Apply a tiny subset of ANSI control codes, returning the screen grid.

    Models raw-mode semantics: ``\\n`` moves down without changing the column;
    ``\\r`` returns to column 1. Handles CUP (``H``), EL (``K``), ED (``J``)
    and ignores SGR (``m``) color codes.
    """
    grid = [[" "] * cols for _ in range(rows)]
    row = col = 0
    i, n = 0, len(data)
    while i < n:
        ch = data[i]
        if ch == "\x1b" and i + 1 < n and data[i + 1] == "[":
            m = re.match(r"\x1b\[([0-9;]*)([A-Za-z])", data[i:])
            if not m:
                i += 1
                continue
            nums = [int(p) for p in m.group(1).split(";") if p != ""]
            final = m.group(2)
            if final == "H":
                row = max(0, min(rows - 1, (nums[0] - 1) if len(nums) >= 1 else 0))
                col = max(0, min(cols - 1, (nums[1] - 1) if len(nums) >= 2 else 0))
            elif final == "K":
                mode = nums[0] if nums else 0
                start = 0 if mode == 2 else col
                for c in range(start, cols):
                    grid[row][c] = " "
            elif final == "J":
                mode = nums[0] if nums else 0
                if mode == 2:
                    grid = [[" "] * cols for _ in range(rows)]
                else:
                    for c in range(col, cols):
                        grid[row][c] = " "
                    for r in range(row + 1, rows):
                        grid[r] = [" "] * cols
            # other finals (e.g. 'm') ignored
            i += m.end()
            continue
        if ch == "\n":
            row = min(rows - 1, row + 1)  # raw-mode LF: down only
            i += 1
            continue
        if ch == "\r":
            col = 0
            i += 1
            continue
        if 0 <= row < rows and 0 <= col < cols:
            grid[row][col] = ch
        col = min(cols - 1, col + 1)
        i += 1
    return ["".join(r).rstrip() for r in grid]


class ComposeFrameTests(unittest.TestCase):
    def test_no_bare_newlines(self):
        out = compose_frame("alpha\nbeta\ngamma")
        self.assertNotIn("\n", out)

    def test_rows_land_at_column_zero(self):
        screen = emulate(compose_frame("alpha\nbeta\ngamma"))
        self.assertEqual(screen[0], "alpha")
        self.assertEqual(screen[1], "beta")
        self.assertEqual(screen[2], "gamma")

    def test_colored_rows_still_align(self):
        red = "\x1b[38;2;255;0;0m"
        reset = "\x1b[0m"
        frame = f"{red}one{reset}\n{red}two{reset}\nthree"
        screen = emulate(compose_frame(frame))
        self.assertEqual(screen[0], "one")
        self.assertEqual(screen[1], "two")
        self.assertEqual(screen[2], "three")

    def test_clears_taller_previous_frame(self):
        # A short frame must wipe leftovers from a taller one drawn before it.
        rows = 8
        grid = emulate(compose_frame("a\nb\nc\nd\ne"), rows=rows)
        # Re-run on same emulated screen is not stateful here; instead assert
        # the trailing ED is present so leftovers below get cleared.
        self.assertIn("\x1b[J", compose_frame("x"))

    def test_emulator_detects_the_staircase_bug(self):
        # Sanity check the test itself: bare-\n separators DO cascade, proving
        # this emulator would catch a regression.
        bad = emulate("\x1b[H" + "alpha\nbeta\ngamma")
        self.assertEqual(bad[0], "alpha")
        self.assertEqual(bad[1], "     beta")   # pushed right by len("alpha")
        self.assertEqual(bad[2], "         gamma")


if __name__ == "__main__":
    unittest.main()
