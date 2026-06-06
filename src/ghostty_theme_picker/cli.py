"""Command-line interface for ghostty-theme-picker.

Subcommands:

* ``compare``     -- interactive side-by-side tournament (the default).
* ``rank``        -- print the current ranking (non-interactive).
* ``list-themes`` -- list discovered themes.
* ``preview``     -- print a single theme preview to stdout.
* ``apply``       -- write a theme into the Ghostty config.
* ``info``        -- show resolved paths and counts.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import ghostty_config
from .color import Painter, detect_color_mode
from .config import State, default_config_path, load_state, save_state
from .preview import build_preview
from .ranking import compute_ranking
from .themes import Theme, discover_themes, find_themes_dir


def _resolve_color_mode(choice: str) -> str:
    if choice == "auto":
        return detect_color_mode()
    return choice


def _load_themes(args) -> dict[str, Theme]:
    return discover_themes(getattr(args, "themes_dir", None))


def _require_themes(themes: dict[str, Theme]) -> None:
    if not themes:
        sys.stderr.write(
            "No Ghostty themes found.\n"
            "  • Make sure Ghostty is installed, or\n"
            "  • point me at the themes directory with --themes-dir DIR\n"
            "    or the GHOSTTY_THEMES_DIR environment variable.\n"
        )
        raise SystemExit(2)


def _apply_pool_options(state: State, args, available: dict[str, Theme]) -> None:
    names: list[str] | None = None
    if getattr(args, "pool", None):
        names = [n.strip() for n in args.pool.split(",") if n.strip()]
    elif getattr(args, "pool_file", None):
        text = Path(args.pool_file).expanduser().read_text(encoding="utf-8")
        names = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    if names is not None:
        unknown = [n for n in names if n not in available]
        if unknown:
            sys.stderr.write(
                "Warning: these pool entries are not among discovered themes:\n  "
                + ", ".join(unknown)
                + "\n"
            )
        state.pool = names


# --- subcommands -----------------------------------------------------------


def cmd_compare(args) -> int:
    from .tui import App  # imported lazily; pulls in termios

    config_path = Path(args.config).expanduser() if args.config else default_config_path()
    state = State() if args.reset_all else load_state(config_path)
    if args.reset:
        state.comparisons = []
        state.ranking = []

    available = _load_themes(args)
    _require_themes(available)
    _apply_pool_options(state, args, available)

    active = state.active_themes(available)
    if len(active) < 2:
        sys.stderr.write(
            f"Need at least two themes to compare (have {len(active)} active).\n"
            "Check your pool/excluded/filters settings.\n"
        )
        return 2

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        sys.stderr.write(
            "The 'compare' command needs an interactive terminal (TTY).\n"
            "Run it directly in Ghostty, or use 'rank'/'preview' for non-interactive use.\n"
        )
        return 2

    painter = Painter(_resolve_color_mode(args.color))
    gpath = ghostty_config.find_config_path(args.ghostty_config)
    save_state(config_path, state)  # persist any pool/reset changes up front

    app = App(state, available, config_path, painter, gpath)
    app.run()

    ranked = state.ranking
    if ranked:
        print(f"Top theme: {ranked[0]}")
    print(f"Saved progress to {config_path}")
    return 0


def cmd_rank(args) -> int:
    config_path = Path(args.config).expanduser() if args.config else default_config_path()
    state = load_state(config_path)
    available = _load_themes(args)
    active = state.active_themes(available) if available else (
        state.pool or sorted({n for c in state.comparisons for n in c})
    )
    rows = compute_ranking(active, state.comparisons)
    if not rows:
        print("No ranking yet. Run 'compare' first.")
        return 0
    favs = set(state.favorites)
    width = max((len(r.name) for r in rows), default=4)
    for i, row in enumerate(rows, start=1):
        star = "*" if row.name in favs else " "
        print(
            f"{i:>3}. {star} {row.name:<{width}}  "
            f"{row.wins:>3}-{row.losses:<3}  {row.win_rate * 100:>5.1f}%"
        )
    if state.excluded:
        print("\nExcluded: " + ", ".join(state.excluded))
    return 0


def cmd_list_themes(args) -> int:
    available = _load_themes(args)
    _require_themes(available)
    if args.details:
        width = max((len(n) for n in available), default=4)
        for name, theme in sorted(available.items(), key=lambda kv: kv[0].lower()):
            kind = "light" if theme.is_light else "dark"
            print(f"{name:<{width}}  {kind:<5}  contrast {theme.contrast:>4.1f}:1")
    else:
        for name in sorted(available, key=str.lower):
            print(name)
    where = find_themes_dir(args.themes_dir)
    sys.stderr.write(f"\n{len(available)} themes from {where}\n")
    return 0


def cmd_preview(args) -> int:
    available = _load_themes(args)
    _require_themes(available)
    theme = available.get(args.theme)
    if theme is None:
        match = [n for n in available if n.lower() == args.theme.lower()]
        if match:
            theme = available[match[0]]
    if theme is None:
        sys.stderr.write(f"Theme not found: {args.theme}\n")
        return 2
    painter = Painter(_resolve_color_mode(args.color))
    for line in build_preview(theme, args.width, args.height, painter):
        sys.stdout.write(line + "\n")
    return 0


def cmd_apply(args) -> int:
    config_path = Path(args.config).expanduser() if args.config else default_config_path()
    state = load_state(config_path)
    available = _load_themes(args)

    target = args.theme
    if target is None:
        target = state.selected
    if target is None:
        active = state.active_themes(available) if available else None
        ranked = compute_ranking(active, state.comparisons) if active else []
        if ranked:
            target = ranked[0].name
    if target is None:
        sys.stderr.write(
            "No theme specified and no ranking/selection available.\n"
            "Pass a theme name: ghostty-theme-picker apply 'Theme Name'\n"
        )
        return 2

    if available and target not in available:
        sys.stderr.write(
            f"Warning: '{target}' is not among discovered themes; applying anyway.\n"
        )

    gpath = ghostty_config.find_config_path(args.ghostty_config)
    if not gpath.exists() and not args.create:
        sys.stderr.write(
            f"Ghostty config not found at {gpath}.\n"
            "Pass --create to create it, or --ghostty-config PATH.\n"
        )
        return 2

    result = ghostty_config.apply_theme(
        target, gpath, create=args.create, backup=not args.no_backup
    )
    state.selected = target
    save_state(config_path, state)

    verb = "Created" if result.created else ("Updated" if result.replaced else "Added")
    print(f"{verb} theme = {result.theme}")
    print(f"  in {result.path}")
    if result.previous and result.previous != target:
        print(f"  (was: {result.previous})")
    if result.backup:
        print(f"  backup: {result.backup}")
    print("Restart Ghostty or reload its config to apply.")
    return 0


def cmd_info(args) -> int:
    config_path = Path(args.config).expanduser() if args.config else default_config_path()
    state = load_state(config_path)
    available = _load_themes(args)
    print(f"Picker config:   {config_path}  ({'exists' if config_path.exists() else 'new'})")
    print(f"Themes dir:      {find_themes_dir(args.themes_dir)}")
    print(f"Ghostty config:  {ghostty_config.find_config_path(args.ghostty_config)}")
    print(f"Color mode:      {_resolve_color_mode(args.color)}")
    print(f"Themes found:    {len(available)}")
    if available:
        print(f"Active (in play):{len(state.active_themes(available)):>4}")
    print(f"Comparisons:     {len(state.comparisons)}")
    print(f"Excluded:        {len(state.excluded)}")
    print(f"Favorites:       {len(state.favorites)}")
    if state.selected:
        print(f"Selected:        {state.selected}")
    return 0


# --- argument parsing ------------------------------------------------------


def _add_common(parser: argparse.ArgumentParser, *, color=True, ghostty=False) -> None:
    parser.add_argument(
        "--config", help="Path to the picker state file (TOML)."
    )
    parser.add_argument(
        "--themes-dir", help="Directory containing Ghostty theme files."
    )
    if color:
        parser.add_argument(
            "--color",
            choices=("auto", "truecolor", "256"),
            default="auto",
            help="Color output mode (default: auto-detect).",
        )
    if ghostty:
        parser.add_argument(
            "--ghostty-config", help="Path to the Ghostty config file."
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ghostty-theme-picker",
        description="Rank Ghostty themes by comparing them two at a time.",
    )
    sub = parser.add_subparsers(dest="command")

    p_cmp = sub.add_parser("compare", help="Interactive side-by-side comparison.")
    _add_common(p_cmp, color=True, ghostty=True)
    p_cmp.add_argument("--pool", help="Comma-separated subset of themes to consider.")
    p_cmp.add_argument("--pool-file", help="File with one theme name per line.")
    p_cmp.add_argument("--reset", action="store_true", help="Clear comparison progress.")
    p_cmp.add_argument(
        "--reset-all", action="store_true", help="Start completely fresh."
    )
    p_cmp.set_defaults(func=cmd_compare)

    p_rank = sub.add_parser("rank", help="Print the current ranking.")
    _add_common(p_rank, color=False)
    p_rank.set_defaults(func=cmd_rank)

    p_list = sub.add_parser("list-themes", help="List discovered themes.")
    _add_common(p_list, color=False)
    p_list.add_argument(
        "--details", action="store_true", help="Show light/dark and contrast."
    )
    p_list.set_defaults(func=cmd_list_themes)

    p_prev = sub.add_parser("preview", help="Print a single theme preview.")
    _add_common(p_prev, color=True)
    p_prev.add_argument("theme", help="Theme name to preview.")
    p_prev.add_argument("--width", type=int, default=46, help="Preview width.")
    p_prev.add_argument("--height", type=int, default=18, help="Preview height.")
    p_prev.set_defaults(func=cmd_preview)

    p_apply = sub.add_parser("apply", help="Set the theme in the Ghostty config.")
    _add_common(p_apply, color=False, ghostty=True)
    p_apply.add_argument(
        "theme", nargs="?", help="Theme to apply (default: top-ranked/selected)."
    )
    p_apply.add_argument(
        "--create", action="store_true", help="Create the config file if missing."
    )
    p_apply.add_argument(
        "--no-backup", action="store_true", help="Do not write a backup file."
    )
    p_apply.set_defaults(func=cmd_apply)

    p_info = sub.add_parser("info", help="Show resolved paths and counts.")
    _add_common(p_info, color=True, ghostty=True)
    p_info.set_defaults(func=cmd_info)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(raw)
    if not getattr(args, "command", None):
        # No subcommand given: default to interactive comparison.
        args = parser.parse_args(["compare", *raw])
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1


if __name__ == "__main__":
    raise SystemExit(main())
