import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from ghostty_theme_picker.cli import main
from ghostty_theme_picker.config import State, load_state, save_state

from . import SAMPLE_THEMES_DIR


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class ListThemesTests(unittest.TestCase):
    def test_plain(self):
        code, out, err = run(["list-themes", "--themes-dir", SAMPLE_THEMES_DIR])
        self.assertEqual(code, 0)
        self.assertIn("Dracula", out)
        self.assertIn("Solarized Light", out)

    def test_details(self):
        code, out, _ = run(
            ["list-themes", "--themes-dir", SAMPLE_THEMES_DIR, "--details"]
        )
        self.assertEqual(code, 0)
        self.assertIn("light", out)
        self.assertIn("dark", out)
        self.assertIn("contrast", out)

    def test_missing_themes_dir_errors(self):
        with TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty"
            empty.mkdir()
            code, _, err = run(["list-themes", "--themes-dir", str(empty)])
            self.assertEqual(code, 2)
            self.assertIn("No Ghostty themes found", err)


class PreviewTests(unittest.TestCase):
    def test_preview_outputs_ansi(self):
        code, out, _ = run(
            [
                "preview",
                "Dracula",
                "--themes-dir",
                SAMPLE_THEMES_DIR,
                "--color",
                "truecolor",
            ]
        )
        self.assertEqual(code, 0)
        self.assertIn("Dracula", out)
        self.assertIn("\x1b[", out)

    def test_preview_unknown_theme(self):
        code, _, err = run(
            ["preview", "Nope", "--themes-dir", SAMPLE_THEMES_DIR]
        )
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    def test_preview_case_insensitive(self):
        code, out, _ = run(
            ["preview", "dracula", "--themes-dir", SAMPLE_THEMES_DIR]
        )
        self.assertEqual(code, 0)
        self.assertIn("Dracula", out)


class RankTests(unittest.TestCase):
    def test_rank_outputs_order(self):
        with TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "picker.toml"
            state = State(
                comparisons=[("Dracula", "Nord"), ("Dracula", "Gruvbox Dark"), ("Nord", "Gruvbox Dark")]
            )
            save_state(cfg, state)
            code, out, _ = run(
                ["rank", "--themes-dir", SAMPLE_THEMES_DIR, "--config", str(cfg)]
            )
            self.assertEqual(code, 0)
            # Dracula should be ranked first.
            lines = [l for l in out.splitlines() if l.strip()]
            self.assertIn("Dracula", lines[0])


class ApplyTests(unittest.TestCase):
    def test_apply_named_theme(self):
        with TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "picker.toml"
            ghostty = Path(tmp) / "ghostty.config"
            ghostty.write_text("font-size = 13\n")
            code, out, _ = run(
                [
                    "apply",
                    "Nord",
                    "--themes-dir",
                    SAMPLE_THEMES_DIR,
                    "--config",
                    str(cfg),
                    "--ghostty-config",
                    str(ghostty),
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn("theme = Nord", ghostty.read_text())
            self.assertEqual(load_state(cfg).selected, "Nord")

    def test_apply_default_to_top_ranked(self):
        with TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "picker.toml"
            ghostty = Path(tmp) / "ghostty.config"
            save_state(cfg, State(comparisons=[("Dracula", "Nord")]))
            code, _, _ = run(
                [
                    "apply",
                    "--themes-dir",
                    SAMPLE_THEMES_DIR,
                    "--config",
                    str(cfg),
                    "--ghostty-config",
                    str(ghostty),
                    "--create",
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn("theme = Dracula", ghostty.read_text())

    def test_apply_missing_config_without_create(self):
        with TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "picker.toml"
            ghostty = Path(tmp) / "does-not-exist"
            code, _, err = run(
                [
                    "apply",
                    "Nord",
                    "--themes-dir",
                    SAMPLE_THEMES_DIR,
                    "--config",
                    str(cfg),
                    "--ghostty-config",
                    str(ghostty),
                ]
            )
            self.assertEqual(code, 2)
            self.assertIn("not found", err)


class InfoTests(unittest.TestCase):
    def test_info_runs(self):
        with TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "picker.toml"
            code, out, _ = run(
                ["info", "--themes-dir", SAMPLE_THEMES_DIR, "--config", str(cfg)]
            )
            self.assertEqual(code, 0)
            self.assertIn("Themes found:", out)
            self.assertIn("Color mode:", out)


if __name__ == "__main__":
    unittest.main()
