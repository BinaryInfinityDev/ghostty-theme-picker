"""Tests for the interactive App's pure state logic (no TTY required)."""

import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import ghostty_theme_picker.tui as tui_mod
from ghostty_theme_picker.color import Painter
from ghostty_theme_picker.config import State, load_state
from ghostty_theme_picker.themes import load_themes_from_dir
from ghostty_theme_picker.tui import App

from . import SAMPLE_THEMES_DIR


class _FakeTerm:
    def __init__(self):
        self.last = ""

    def render(self, text):
        self.last = text


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

    def _draw_with_size(self, cols, rows):
        with TemporaryDirectory() as tmp:
            app, _ = self.make_app(tmp)
            app.term = _FakeTerm()
            orig = tui_mod.get_size
            tui_mod.get_size = lambda: types.SimpleNamespace(cols=cols, rows=rows)
            try:
                ok = app.draw_compare(
                    "Dracula", "Nord", [("Dracula", "Nord")], 0, finals=False
                )
            finally:
                tui_mod.get_size = orig
            return ok, app.term.last

    def test_draw_compare_too_small_returns_false(self):
        # Guards run_queue against recording a vote when previews can't render.
        ok, rendered = self._draw_with_size(10, 5)
        self.assertFalse(ok)
        self.assertIn("too small", rendered)

    def test_draw_compare_large_returns_true(self):
        ok, _ = self._draw_with_size(120, 40)
        self.assertTrue(ok)

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

    def test_groups_for_finals_uses_favorites(self):
        with TemporaryDirectory() as tmp:
            app, _ = self.make_app(tmp, State(favorites=["Dracula", "Nord"]))
            groups = app._groups_for(finals=True)
            self.assertEqual(set(groups["dark"]), {"Dracula", "Nord"})
            self.assertEqual(groups["light"], [])

    def test_comparisons_are_within_scheme(self):
        from ghostty_theme_picker import ranking

        with TemporaryDirectory() as tmp:
            app, _ = self.make_app(tmp)  # scheme defaults to "all"
            groups = app.state.active_groups(app.available)
            queue = ranking.remaining_pairs_in_groups(groups, app.state.comparisons)
            self.assertTrue(queue)  # there are matchups to do
            for a, b in queue:
                self.assertEqual(
                    app.available[a].scheme, app.available[b].scheme,
                    f"cross-scheme pair: {a} vs {b}",
                )

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
