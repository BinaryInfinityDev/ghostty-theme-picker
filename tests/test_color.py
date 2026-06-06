import unittest

from ghostty_theme_picker.color import (
    RGB,
    Painter,
    best_text_on,
    contrast_ratio,
    detect_color_mode,
    is_light,
    parse_color,
    to_xterm256,
    visible_width,
)


class ParseColorTests(unittest.TestCase):
    def test_hash_six_digits(self):
        self.assertEqual(parse_color("#ff8800"), RGB(255, 136, 0))

    def test_no_hash(self):
        self.assertEqual(parse_color("282a36"), RGB(0x28, 0x2A, 0x36))

    def test_three_digit_shorthand(self):
        self.assertEqual(parse_color("#abc"), RGB(0xAA, 0xBB, 0xCC))

    def test_x11_rgb_form(self):
        self.assertEqual(parse_color("rgb:ff/00/80"), RGB(255, 0, 128))

    def test_whitespace_tolerated(self):
        self.assertEqual(parse_color("  #001122  "), RGB(0, 0x11, 0x22))

    def test_invalid_returns_none(self):
        for bad in ("", "nope", "#12", "#1234567", "rgb:1", None):
            self.assertIsNone(parse_color(bad))


class ColorMathTests(unittest.TestCase):
    def test_contrast_black_white_is_max(self):
        self.assertAlmostEqual(
            contrast_ratio(RGB(0, 0, 0), RGB(255, 255, 255)), 21.0, places=1
        )

    def test_contrast_is_symmetric(self):
        a, b = RGB(10, 20, 30), RGB(200, 100, 50)
        self.assertAlmostEqual(contrast_ratio(a, b), contrast_ratio(b, a))

    def test_is_light(self):
        self.assertTrue(is_light(RGB(255, 255, 255)))
        self.assertFalse(is_light(RGB(0, 0, 0)))

    def test_best_text_on(self):
        self.assertEqual(best_text_on(RGB(255, 255, 255)), RGB(0, 0, 0))
        self.assertEqual(best_text_on(RGB(0, 0, 0)), RGB(255, 255, 255))


class Xterm256Tests(unittest.TestCase):
    def test_pure_colors_in_range(self):
        for c in (RGB(0, 0, 0), RGB(255, 255, 255), RGB(255, 0, 0), RGB(128, 128, 128)):
            idx = to_xterm256(c)
            self.assertTrue(0 <= idx <= 255)

    def test_black_maps_low(self):
        self.assertEqual(to_xterm256(RGB(0, 0, 0)), 16)

    def test_white_maps_high(self):
        self.assertEqual(to_xterm256(RGB(255, 255, 255)), 231)


class PainterTests(unittest.TestCase):
    def test_truecolor_sequences(self):
        p = Painter("truecolor")
        self.assertEqual(p.fg(RGB(1, 2, 3)), "\x1b[38;2;1;2;3m")
        self.assertEqual(p.bg(RGB(4, 5, 6)), "\x1b[48;2;4;5;6m")

    def test_256_sequences(self):
        p = Painter("256")
        self.assertTrue(p.fg(RGB(255, 0, 0)).startswith("\x1b[38;5;"))
        self.assertTrue(p.bg(RGB(255, 0, 0)).startswith("\x1b[48;5;"))

    def test_bad_mode_raises(self):
        with self.assertRaises(ValueError):
            Painter("nope")


class MiscTests(unittest.TestCase):
    def test_visible_width_strips_escapes(self):
        styled = "\x1b[38;2;1;2;3mhello\x1b[0m"
        self.assertEqual(visible_width(styled), 5)

    def test_detect_color_mode(self):
        self.assertEqual(detect_color_mode({"COLORTERM": "truecolor"}), "truecolor")
        self.assertEqual(detect_color_mode({"TERM": "xterm-ghostty"}), "truecolor")
        self.assertEqual(detect_color_mode({"TERM": "xterm-256color"}), "256")
        self.assertEqual(detect_color_mode({}), "256")

    def test_blend(self):
        self.assertEqual(RGB(0, 0, 0).blend(RGB(255, 255, 255), 0.5), RGB(128, 128, 128))


if __name__ == "__main__":
    unittest.main()
