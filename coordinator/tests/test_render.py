"""Unit tests for the cell-model screen reconstruction (_render) — the
plain-text, cursor-move, OSC and scroll semantics the pty driver's
anchored turns (`after`, pickers) depend on. These run in the
coordinator image build, so every gate run executes them."""

import unittest

from gentar.pty_driver import _render


class RenderPlainTest(unittest.TestCase):
    def test_plain_text_identity(self):
        self.assertEqual(_render("hello world"), "hello world")

    def test_cr_lf_pair(self):
        self.assertEqual(_render("abc\r\ndef"), "abc\ndef")


class RenderCursorTest(unittest.TestCase):
    def test_cha_word_gap(self):
        # The diff-rendering TUI skips unchanged trailing cells and
        # jumps the cursor past them: "ab" + jump to col 4 + "cd"
        # renders "ab cd" — the gap is a cursor move, not space bytes
        # (proven live, probe 5).
        self.assertEqual(_render("ab\x1b[4Gcd"), "ab cd")

    def test_cup_absolute(self):
        self.assertEqual(_render("overwrite\x1b[1;3HXX"), "ovXXwrite")

    def test_el_clears_row_from_cursor(self):
        self.assertEqual(_render("hello\x1b[3G\x1b[K"), "he")

    def test_ed2_clears_screen(self):
        self.assertEqual(_render("old text\n\x1b[2J\x1b[Hnew"), "new")


class RenderOSCTest(unittest.TestCase):
    def test_osc_bel_dropped(self):
        self.assertEqual(_render("before\x1b]0;title\x07after"),
                         "beforeafter")

    def test_osc_st_dropped_completely(self):
        # Regression (PR #26 review): ST is TWO bytes; landing on the
        # backslash rendered it as a visible cell and shifted every
        # column after it.
        self.assertEqual(_render("a\x1b]0;t\x1b\\b"), "ab")

    def test_osc_hyperlink_pair(self):
        self.assertEqual(
            _render("\x1b]8;;http://x\x1b\\link\x1b]8;;\x1b\\ok"),
            "linkok")


class RenderScrollTest(unittest.TestCase):
    # 15 lines on a 10-row screen, then clear the viewport's first
    # line and write a title at it.
    STREAM = ("\n".join(f"line{i}" for i in range(1, 16))
              + "\x1b[1;1H\x1b[2KTOP")

    def test_scrolling_viewport_keeps_absolute_writes_visible(self):
        # Regression (PR #26 review): after the screen scrolls, CUP 1;1
        # addresses the VIEWPORT top — the write must land visible, not
        # on history row 0 where the unbounded model parks it.
        lines = _render(self.STREAM, 10).splitlines()
        self.assertEqual(lines[0], "TOP")
        self.assertEqual(lines[-1], "line15")
        self.assertNotIn("line1", lines)   # scrolled away
        self.assertNotIn("line6", lines)   # cleared + overwritten by TOP

    def test_unbounded_model_keeps_history(self):
        lines = _render(self.STREAM).splitlines()
        self.assertEqual(lines[0], "TOP")
        self.assertIn("line2", lines)      # history preserved
        self.assertIn("line15", lines)
        self.assertNotIn("line1", lines)   # row 0 cleared + overwritten

    def test_viewport_never_grows_past_height(self):
        # A 5-row viewport after 12 lines: the trailing LF scrolled a
        # blank row in — five rows, the fifth blank (split keeps it;
        # splitlines would drop the trailing empty line).
        self.assertEqual(_render("a\n" * 12, 5).split("\n"),
                         ["a"] * 4 + [""])


if __name__ == "__main__":
    unittest.main()
