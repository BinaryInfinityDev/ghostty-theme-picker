import unittest
from pathlib import Path

from ghostty_theme_picker.color import RGB
from ghostty_theme_picker.themes import (
    discover_themes,
    load_themes_from_dir,
    parse_theme_text,
)

from . import SAMPLE_THEMES_DIR


class ParseThemeTests(unittest.TestCase):
    def test_parses_palette_and_simple_keys(self):
        text = """
        # a comment
        palette = 0=#101010
        palette = 7=ffffff
        background = 202020
        foreground = #c0c0c0
        cursor-color = #ff0000
        selection-background = 333333
        unknown-key = whatever
        """
        theme = parse_theme_text(text, name="Test")
        self.assertEqual(theme.name, "Test")
        self.assertEqual(theme.palette[0], RGB(0x10, 0x10, 0x10))
        self.assertEqual(theme.palette[7], RGB(255, 255, 255))
        self.assertEqual(theme.background, RGB(0x20, 0x20, 0x20))
        self.assertEqual(theme.foreground, RGB(0xC0, 0xC0, 0xC0))
        self.assertEqual(theme.cursor, RGB(255, 0, 0))
        self.assertEqual(theme.selection_bg, RGB(0x33, 0x33, 0x33))

    def test_defaults_when_missing(self):
        theme = parse_theme_text("background = 000000", name="Bare")
        # cursor falls back to foreground; selection is derived.
        self.assertEqual(theme.cursor_color, theme.foreground)
        self.assertIsNotNone(theme.selection_background)
        self.assertEqual(theme.palette_color(1), theme.palette_color(1))  # no crash

    def test_bad_palette_index_ignored(self):
        theme = parse_theme_text("palette = x=#fff", name="X")
        self.assertEqual(theme.palette, {})

    def test_light_and_contrast(self):
        light = parse_theme_text("background = ffffff\nforeground = 000000", name="L")
        dark = parse_theme_text("background = 000000\nforeground = ffffff", name="D")
        self.assertTrue(light.is_light)
        self.assertFalse(dark.is_light)
        self.assertGreater(light.contrast, 20)

    def test_scheme_property(self):
        light = parse_theme_text("background = ffffff", name="L")
        dark = parse_theme_text("background = 000000", name="D")
        self.assertEqual(light.scheme, "light")
        self.assertEqual(dark.scheme, "dark")
        self.assertTrue(dark.is_dark)
        self.assertFalse(light.is_dark)


class DiscoveryTests(unittest.TestCase):
    def test_load_sample_themes(self):
        themes = load_themes_from_dir(Path(SAMPLE_THEMES_DIR))
        self.assertIn("Dracula", themes)
        self.assertIn("Solarized Light", themes)
        self.assertTrue(themes["Solarized Light"].is_light)
        self.assertFalse(themes["Dracula"].is_light)

    def test_discover_with_override(self):
        themes = discover_themes(SAMPLE_THEMES_DIR)
        self.assertGreaterEqual(len(themes), 8)

    def test_faded_mono_low_contrast(self):
        themes = load_themes_from_dir(Path(SAMPLE_THEMES_DIR))
        self.assertLess(themes["Faded Mono"].contrast, 1.5)


if __name__ == "__main__":
    unittest.main()
