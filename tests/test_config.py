import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ghostty_theme_picker.config import Filters, State, load_state, save_state
from ghostty_theme_picker.themes import load_themes_from_dir
from ghostty_theme_picker.toml_writer import escape_string, format_keyval

from . import SAMPLE_THEMES_DIR


class TomlWriterTests(unittest.TestCase):
    def test_escape_string(self):
        self.assertEqual(escape_string('a"b'), '"a\\"b"')
        self.assertEqual(escape_string("a\\b"), '"a\\\\b"')
        self.assertEqual(escape_string("tab\there"), '"tab\\there"')

    def test_format_keyval_quotes_when_needed(self):
        self.assertEqual(format_keyval("name", "Solarized Dark"), 'name = "Solarized Dark"')
        self.assertEqual(format_keyval("version", 1), "version = 1")
        self.assertEqual(format_keyval("ok", True), "ok = true")
        self.assertEqual(format_keyval("list", ["a", "b"]), 'list = ["a", "b"]')


class StateRoundTripTests(unittest.TestCase):
    def test_to_toml_is_valid_and_round_trips(self):
        state = State(
            selected="Solarized Dark",
            pool=["Dracula", "Nord", "Solarized Dark"],
            excluded=["Faded Mono"],
            favorites=["Dracula"],
            filters=Filters(exclude_light=True, min_contrast=4.5),
            comparisons=[("Dracula", "Nord"), ("Solarized Dark", "Nord")],
        )
        text = state.to_toml()
        data = tomllib.loads(text)  # must parse
        self.assertEqual(data["selected"], "Solarized Dark")
        self.assertEqual(data["filters"]["min_contrast"], 4.5)
        self.assertTrue(data["filters"]["exclude_light"])
        self.assertEqual(len(data["comparison"]), 2)

        restored = State.from_dict(data)
        self.assertEqual(restored.selected, state.selected)
        self.assertEqual(restored.pool, state.pool)
        self.assertEqual(restored.excluded, state.excluded)
        self.assertEqual(restored.favorites, state.favorites)
        self.assertEqual(restored.comparisons, state.comparisons)
        self.assertEqual(restored.filters.exclude_light, True)
        self.assertEqual(restored.filters.min_contrast, 4.5)

    def test_save_and_load(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "picker.toml"
            state = State(selected="Nord", comparisons=[("Nord", "Dracula")])
            save_state(path, state)
            self.assertTrue(path.exists())
            loaded = load_state(path)
            self.assertEqual(loaded.selected, "Nord")
            self.assertEqual(loaded.comparisons, [("Nord", "Dracula")])

    def test_load_missing_returns_fresh(self):
        with TemporaryDirectory() as tmp:
            loaded = load_state(Path(tmp) / "nope.toml")
            self.assertEqual(loaded.comparisons, [])
            self.assertEqual(loaded.excluded, [])


class ActiveThemesTests(unittest.TestCase):
    def setUp(self):
        self.available = load_themes_from_dir(Path(SAMPLE_THEMES_DIR))

    def test_excluded_removed(self):
        state = State(excluded=["Dracula"])
        active = state.active_themes(self.available)
        self.assertNotIn("Dracula", active)
        self.assertIn("Nord", active)

    def test_pool_restricts(self):
        state = State(pool=["Dracula", "Nord", "Ghost Of Nonexistence"])
        active = state.active_themes(self.available)
        self.assertEqual(set(active), {"Dracula", "Nord"})

    def test_filter_excludes_light(self):
        state = State(filters=Filters(exclude_light=True))
        active = state.active_themes(self.available)
        self.assertNotIn("Solarized Light", active)
        self.assertNotIn("GitHub Light", active)
        self.assertIn("Dracula", active)

    def test_filter_min_contrast(self):
        state = State(filters=Filters(min_contrast=2.0))
        active = state.active_themes(self.available)
        self.assertNotIn("Faded Mono", active)

    def test_record_replaces_prior_verdict(self):
        state = State()
        state.record("Nord", "Dracula")
        state.record("Dracula", "Nord")  # reverse the decision
        self.assertEqual(state.comparisons, [("Dracula", "Nord")])

    def test_exclude_drops_from_favorites(self):
        state = State(favorites=["Dracula"])
        state.exclude("Dracula")
        self.assertIn("Dracula", state.excluded)
        self.assertNotIn("Dracula", state.favorites)

    def test_recompute_ranking(self):
        state = State(comparisons=[("Dracula", "Nord")])
        ranked = state.recompute_ranking(self.available)
        self.assertEqual(ranked[0], "Dracula")
        self.assertEqual(state.ranking, ranked)


if __name__ == "__main__":
    unittest.main()
