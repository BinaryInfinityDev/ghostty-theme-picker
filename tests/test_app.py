"""Tests for the interactive App's pure state logic (no TTY required)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ghostty_theme_picker.color import Painter
from ghostty_theme_picker.config import State, load_state
from ghostty_theme_picker.themes import load_themes_from_dir
from ghostty_theme_picker.tui import App

from . import SAMPLE_THEMES_DIR


class AppLogicTests(unittest.TestCase):
    def make_app(self, tmp, state=None):
        available = load_themes_from_dir(Path(SAMPLE_THEMES_DIR))
        cfg = Path(tmp) / "picker.toml"
        return App(
            state or State(),
            available,
            cfg,
            Painter("256"),
            Path(tmp) / "ghostty.config",
        ), cfg

    def test_vote_records_and_persists(self):
        with TemporaryDirectory() as tmp:
            app, cfg = self.make_app(tmp)
            app.do_vote("Dracula", "Nord")
            self.assertEqual(app.state.comparisons, [("Dracula", "Nord")])
            self.assertEqual(load_state(cfg).comparisons, [("Dracula", "Nord")])

    def test_undo_vote(self):
        with TemporaryDirectory() as tmp:
            app, _ = self.make_app(tmp)
            app.do_vote("Dracula", "Nord")
            app.undo()
            self.assertEqual(app.state.comparisons, [])

    def test_undo_restores_replaced_verdict(self):
        with TemporaryDirectory() as tmp:
            app, _ = self.make_app(tmp)
            app.do_vote("Dracula", "Nord")
            app.do_vote("Nord", "Dracula")  # reverse; replaces prior
            self.assertEqual(app.state.comparisons, [("Nord", "Dracula")])
            app.undo()
            self.assertEqual(app.state.comparisons, [("Dracula", "Nord")])

    def test_exclude_and_undo(self):
        with TemporaryDirectory() as tmp:
            app, _ = self.make_app(tmp)
            app.do_exclude("Faded Mono")
            self.assertIn("Faded Mono", app.state.excluded)
            self.assertNotIn("Faded Mono", app.state.active_themes(app.available))
            app.undo()
            self.assertNotIn("Faded Mono", app.state.excluded)

    def test_favorite_toggle_and_undo(self):
        with TemporaryDirectory() as tmp:
            app, _ = self.make_app(tmp)
            added = app.do_favorite("Dracula")
            self.assertTrue(added)
            self.assertIn("Dracula", app.state.favorites)
            app.undo()
            self.assertNotIn("Dracula", app.state.favorites)

    def test_pool_for_finals_uses_favorites(self):
        with TemporaryDirectory() as tmp:
            app, _ = self.make_app(tmp, State(favorites=["Dracula", "Nord"]))
            self.assertEqual(set(app._pool_for(finals=True)), {"Dracula", "Nord"})

    def test_swatch_renders(self):
        with TemporaryDirectory() as tmp:
            app, _ = self.make_app(tmp)
            swatch = app._swatch(app.available["Dracula"])
            self.assertIn("\x1b[", swatch)

    def test_clip_preserves_escapes(self):
        with TemporaryDirectory() as tmp:
            app, _ = self.make_app(tmp)
            styled = "\x1b[1mhello world\x1b[0m"
            clipped = app._clip(styled, 5)
            self.assertEqual(app._visible_len(clipped), 5)


if __name__ == "__main__":
    unittest.main()
