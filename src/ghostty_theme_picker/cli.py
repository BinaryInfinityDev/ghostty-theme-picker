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
        state.ranking_light = []
        state.ranking_dark = []
    if args.scheme:
        state.scheme = args.scheme

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

    state.recompute_rankings(available)
    if state.top_light():
        print(f"Top light: {state.top_light()}")
    if state.top_dark():
        print(f"Top dark:  {state.top_dark()}")
    print(f"Saved progress to {config_path}")
    return 0


def _print_board(rows, favorites) -> None:
    favs = set(favorites)
    width = max((len(r.name) for r in rows), default=4)
    for i, row in enumerate(rows, start=1):
        star = "*" if row.name in favs else " "
        print(
            f"{i:>3}. {star} {row.name:<{width}}  "
            f"{row.wins:>3}-{row.losses:<3}  {row.win_rate * 100:>5.1f}%"
        )


def cmd_rank(args) -> int:
    config_path = Path(args.config).expanduser() if args.config else default_config_path()
    state = load_state(config_path)
    available = _load_themes(args)
    scheme = getattr(args, "scheme", None) or "all"

    if not available:
        # Offline fallback: we can't classify light/dark without theme files,
        # so print a single ungrouped board from the recorded comparisons.
        names = state.pool or sorted({n for c in state.comparisons for n in c})
        rows = compute_ranking(names, state.comparisons)
        if not rows:
            print("No ranking yet. Run 'compare' first.")
            return 0
        sys.stderr.write(
            "(theme files not found; cannot separate light/dark leaderboards)\n"
        )
        _print_board(rows, state.favorites)
        return 0

    considered = state.considered_groups(available)
    groups = ["light", "dark"] if scheme == "all" else [scheme]
    printed = False
    for group in groups:
        rows = compute_ranking(considered[group], state.comparisons)
        if not rows:
            continue
        if printed:
            print()
        print(f"== {group.capitalize()} themes ==")
        _print_board(rows, state.favorites)
        printed = True
    if not printed:
        print("No ranking yet. Run 'compare' first.")
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


def _warn_unknown(available: dict, name: str) -> None:
    if available and name not in available:
        sys.stderr.write(
            f"Warning: '{name}' is not among discovered themes; applying anyway.\n"
        )


def _warn_scheme(available: dict, name: str, expected: str) -> None:
    if available and name in available and available[name].scheme != expected:
        sys.stderr.write(
            f"Warning: '{name}' is a {available[name].scheme} theme but is being "
            f"used as the {expected} theme.\n"
        )


def cmd_apply(args) -> int:
    config_path = Path(args.config).expanduser() if args.config else default_config_path()
    state = load_state(config_path)
    available = _load_themes(args)
    if available:
        state.recompute_rankings(available)

    if args.only_light and args.only_dark:
        sys.stderr.write("Use only one of --only-light / --only-dark.\n")
        return 2

    value: str | None = None

    if args.theme:
        # An explicit positional theme overrides everything else.
        if args.light or args.dark or args.only_light or args.only_dark:
            sys.stderr.write(
                "Note: positional theme given; ignoring --light/--dark/--only-*.\n"
            )
        value = args.theme
        _warn_unknown(available, value)
    else:
        light = args.light or state.top_light()
        dark = args.dark or state.top_dark()
        if args.light:
            _warn_unknown(available, args.light)
            _warn_scheme(available, args.light, "light")
        if args.dark:
            _warn_unknown(available, args.dark)
            _warn_scheme(available, args.dark, "dark")

        if args.only_light:
            value = light
            if value is None:
                sys.stderr.write("No light theme available to apply.\n")
                return 2
        elif args.only_dark:
            value = dark
            if value is None:
                sys.stderr.write("No dark theme available to apply.\n")
                return 2
        elif light and dark:
            value = f"light:{light},dark:{dark}"  # Ghostty combined assignment
        elif light or dark:
            value = light or dark
        else:
            value = state.selected

    if value is None:
        sys.stderr.write(
            "Nothing to apply: no theme specified and no ranking/selection yet.\n"
            "Pass a theme name, or run 'compare' first.\n"
        )
        return 2

    gpath = ghostty_config.find_config_path(args.ghostty_config)
    if not gpath.exists() and not args.create:
        sys.stderr.write(
            f"Ghostty config not found at {gpath}.\n"
            "Pass --create to create it, or --ghostty-config PATH.\n"
        )
        return 2

    result = ghostty_config.apply_theme(
        value, gpath, create=args.create, backup=not args.no_backup
    )
    state.selected = value
    save_state(config_path, state)

    verb = "Created" if result.created else ("Updated" if result.replaced else "Added")
    print(f"{verb} theme = {result.theme}")
    print(f"  in {result.path}")
    if result.previous and result.previous != value:
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
    print(f"Scheme:          {state.scheme}")
    print(f"Themes found:    {len(available)}")
    if available:
        considered = state.considered_groups(available)
        print(f"Light themes:    {len(considered['light'])}")
        print(f"Dark themes:     {len(considered['dark'])}")
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
    p_cmp.add_argument(
        "--scheme",
        choices=("all", "light", "dark"),
        default=None,
        help="Limit comparisons to light themes, dark themes, or all (default: keep saved).",
    )
    p_cmp.add_argument("--reset", action="store_true", help="Clear comparison progress.")
    p_cmp.add_argument(
        "--reset-all", action="store_true", help="Start completely fresh."
    )
    p_cmp.set_defaults(func=cmd_compare)

    p_rank = sub.add_parser("rank", help="Print the light and dark leaderboards.")
    _add_common(p_rank, color=False)
    p_rank.add_argument(
        "--scheme",
        choices=("all", "light", "dark"),
        default="all",
        help="Which leaderboard(s) to print (default: all).",
    )
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

    p_apply = sub.add_parser(
        "apply",
        help="Set the theme in the Ghostty config (combined light/dark by default).",
    )
    _add_common(p_apply, color=False, ghostty=True)
    p_apply.add_argument(
        "theme",
        nargs="?",
        help="Apply this exact theme as a single value (overrides the options below).",
    )
    p_apply.add_argument(
        "--light", help="Light theme for the combined assignment (default: top light)."
    )
    p_apply.add_argument(
        "--dark", help="Dark theme for the combined assignment (default: top dark)."
    )
    p_apply.add_argument(
        "--only-light",
        "--onlyLight",
        dest="only_light",
        action="store_true",
        help="Apply only the light theme (single value).",
    )
    p_apply.add_argument(
        "--only-dark",
        "--onlyDark",
        dest="only_dark",
        action="store_true",
        help="Apply only the dark theme (single value).",
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
