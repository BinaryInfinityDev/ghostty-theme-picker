import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ghostty_theme_picker.ghostty_config import apply_theme, set_theme_in_text


class SetThemeTextTests(unittest.TestCase):
    def test_append_when_absent(self):
        new, replaced, prev = set_theme_in_text("font-size = 13\n", "Dracula")
        self.assertFalse(replaced)
        self.assertIsNone(prev)
        self.assertIn("theme = Dracula", new)
        self.assertIn("font-size = 13", new)

    def test_replace_existing(self):
        text = "font-size = 13\ntheme = Old Theme\nbold = true\n"
        new, replaced, prev = set_theme_in_text(text, "Nord")
        self.assertTrue(replaced)
        self.assertEqual(prev, "Old Theme")
        self.assertIn("theme = Nord", new)
        self.assertNotIn("Old Theme", new)
        self.assertIn("bold = true", new)

    def test_preserves_commented_theme(self):
        text = "# theme = Commented\ntheme = Real\n"
        new, replaced, prev = set_theme_in_text(text, "New")
        self.assertTrue(replaced)
        self.assertEqual(prev, "Real")
        self.assertIn("# theme = Commented", new)
        self.assertIn("theme = New", new)

    def test_replaces_last_uncommented(self):
        text = "theme = First\ntheme = Second\n"
        new, replaced, prev = set_theme_in_text(text, "Third")
        self.assertEqual(prev, "Second")
        self.assertIn("theme = First", new)
        self.assertIn("theme = Third", new)
        self.assertNotIn("Second", new)

    def test_preserves_indentation(self):
        new, _, _ = set_theme_in_text("  theme = X\n", "Y")
        self.assertIn("  theme = Y", new)

    def test_theme_name_with_spaces(self):
        new, _, _ = set_theme_in_text("", "Solarized Dark")
        self.assertIn("theme = Solarized Dark", new)


class ApplyThemeTests(unittest.TestCase):
    def test_creates_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ghostty" / "config"
            result = apply_theme("Dracula", path, create=True)
            self.assertTrue(path.exists())
            self.assertTrue(result.created)
            self.assertIn("theme = Dracula", path.read_text())

    def test_backs_up_and_replaces(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_text("theme = Old\nfont-size = 12\n")
            result = apply_theme("Nord", path)
            self.assertTrue(result.replaced)
            self.assertIsNotNone(result.backup)
            self.assertTrue(result.backup.exists())
            self.assertEqual(result.backup.read_text(), "theme = Old\nfont-size = 12\n")
            self.assertIn("theme = Nord", path.read_text())
            self.assertEqual(result.previous, "Old")

    def test_no_backup_flag(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config"
            path.write_text("theme = Old\n")
            result = apply_theme("Nord", path, backup=False)
            self.assertIsNone(result.backup)

    def test_missing_without_create_raises(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                apply_theme("X", Path(tmp) / "nope", create=False)


if __name__ == "__main__":
    unittest.main()
