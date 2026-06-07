import unittest

from ghostty_theme_picker.color import RGB, Painter, visible_width
from ghostty_theme_picker.preview import Span, build_preview, render_line
from ghostty_theme_picker.themes import Theme


def _theme():
    return Theme(
        name="Sample",
        path=None,
        palette={i: RGB(i * 10 % 256, 100, 150) for i in range(16)},
        background=RGB(20, 20, 30),
        foreground=RGB(200, 200, 210),
    )


class RenderLineTests(unittest.TestCase):
    def test_exact_width(self):
        theme = _theme()
        painter = Painter("truecolor")
        line = render_line([Span("hello")], 20, theme, painter)
        self.assertEqual(visible_width(line), 20)

    def test_truncates_overlong(self):
        theme = _theme()
        painter = Painter("truecolor")
        line = render_line([Span("x" * 50)], 10, theme, painter)
        self.assertEqual(visible_width(line), 10)

    def test_pads_short(self):
        theme = _theme()
        painter = Painter("256")
        line = render_line([], 8, theme, painter)
        self.assertEqual(visible_width(line), 8)


class BuildPreviewTests(unittest.TestCase):
    def test_dimensions(self):
        theme = _theme()
        painter = Painter("truecolor")
        for w, h in ((46, 18), (30, 10), (60, 24)):
            rows = build_preview(theme, w, h, painter)
            self.assertEqual(len(rows), h, f"row count for {w}x{h}")
            for row in rows:
                self.assertEqual(visible_width(row), w, f"width for {w}x{h}")

    def test_contains_theme_name(self):
        theme = _theme()
        painter = Painter("truecolor")
        rows = build_preview(theme, 50, 20, painter)
        # The name appears in the top border.
        self.assertIn("Sample", rows[0])

    def test_truecolor_has_24bit_sequences(self):
        theme = _theme()
        rows = build_preview(theme, 50, 20, Painter("truecolor"))
        self.assertIn("\x1b[48;2;", "".join(rows))

    def test_handles_tiny_size(self):
        theme = _theme()
        rows = build_preview(theme, 8, 3, Painter("256"))
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(visible_width(row), 8)


if __name__ == "__main__":
    unittest.main()
