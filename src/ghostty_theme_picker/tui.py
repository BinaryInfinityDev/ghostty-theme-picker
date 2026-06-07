"""The interactive terminal UI for comparing and ranking themes.

Screens:

* **Compare** -- two previews side by side; pick a winner, skip, veto a theme
  (drops all its remaining matchups), or favorite a theme for the finals.
* **Ranking** -- scrollable standings; select a theme to apply, or veto one.
* **Finals** -- a fresh round-robin restricted to your favorites.
* **Filters** -- prune the pool by light/dark and minimum contrast.
* **Apply** -- write the chosen theme into your Ghostty config.

Chrome (headers, footers, menus) is drawn in the terminal's own default colors
so it stays legible regardless of the themes being previewed; only the preview
windows use theme colors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import ghostty_config, ranking
from .color import Painter
from .config import State, save_state
from .preview import build_preview
from .terminal import (
    KEY_CTRL_C,
    KEY_DOWN,
    KEY_END,
    KEY_ENTER,
    KEY_ESC,
    KEY_HOME,
    KEY_LEFT,
    KEY_PGDN,
    KEY_PGUP,
    KEY_RIGHT,
    KEY_UP,
    Terminal,
    get_size,
)
from .themes import Theme

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
REVERSE = "\x1b[7m"

MIN_COLS = 54
MIN_ROWS = 16


def _bar(done: int, total: int, width: int) -> str:
    width = max(1, width)
    ratio = 1.0 if total <= 0 else max(0.0, min(1.0, done / total))
    filled = round(ratio * width)
    return "█" * filled + "░" * (width - filled)


class QuitApp(Exception):
    """Raised to unwind out of every screen and exit cleanly."""


class App:
    def __init__(
        self,
        state: State,
        available: dict[str, Theme],
        config_path: Path,
        painter: Painter,
        ghostty_config_path: Path,
    ):
        self.state = state
        self.available = available
        self.config_path = config_path
        self.painter = painter
        self.ghostty_config_path = ghostty_config_path
        self.term: Terminal | None = None
        self.undo_stack: list[tuple[str, Callable[[], None]]] = []
        self.message: str | None = None

    # -- persistence --------------------------------------------------------

    def save(self) -> None:
        self.state.recompute_rankings(self.available)
        save_state(self.config_path, self.state)

    # -- undoable operations ------------------------------------------------

    def do_vote(self, winner: str, loser: str) -> None:
        key = ranking.pair_key(winner, loser)
        prev = [c for c in self.state.comparisons if ranking.pair_key(*c) == key]
        self.state.record(winner, loser)

        def undo() -> None:
            self.state.comparisons = [
                c for c in self.state.comparisons if ranking.pair_key(*c) != key
            ]
            self.state.comparisons.extend(prev)

        self.undo_stack.append((f"vote {winner} ▸ {loser}", undo))
        self.save()

    def do_exclude(self, name: str) -> None:
        if name in self.state.excluded:
            return
        was_fav = name in self.state.favorites
        self.state.exclude(name)

        def undo() -> None:
            if name in self.state.excluded:
                self.state.excluded.remove(name)
            if was_fav and name not in self.state.favorites:
                self.state.favorites.append(name)

        self.undo_stack.append((f"veto {name}", undo))
        self.save()

    def do_favorite(self, name: str) -> bool:
        added = self.state.toggle_favorite(name)

        def undo() -> None:
            self.state.toggle_favorite(name)

        self.undo_stack.append((f"favorite {name}", undo))
        self.save()
        return added

    def undo(self) -> None:
        if not self.undo_stack:
            self.message = "Nothing to undo."
            return
        label, fn = self.undo_stack.pop()
        fn()
        self.save()
        self.message = f"Undid: {label}"

    # -- main entry ---------------------------------------------------------

    def run(self) -> None:
        with Terminal() as term:
            self.term = term
            try:
                self.compare_loop(finals=False)
            except QuitApp:
                pass
        self.save()

    # -- comparison loop ----------------------------------------------------

    def _groups_for(self, finals: bool) -> dict[str, list[str]]:
        """Return ``{"light": [...], "dark": [...]}`` for the current context.

        Comparisons only ever happen within a group. ``scheme`` restricts which
        group(s) are in play; finals are scoped to the favorites (still split by
        group and restricted to the active scheme).
        """
        if finals:
            groups: dict[str, list[str]] = {"light": [], "dark": []}
            for name in self.state.favorites:
                if name not in self.available:
                    continue
                scheme = self.available[name].scheme
                if self.state.scheme in ("all", scheme):
                    groups[scheme].append(name)
            return groups
        return self.state.active_groups(self.available)

    def compare_loop(self, finals: bool) -> None:
        while True:
            groups = self._groups_for(finals)
            if finals and all(len(m) < 2 for m in groups.values()):
                self.notice(
                    "Finals need at least two favorites in a scheme group.",
                    "Mark favorites with 'f' during comparison, then try again.",
                )
                return
            # Finals is the same within-group round-robin, scoped to favorites:
            # it asks the favorite matchups not yet decided, then ends.
            queue = ranking.remaining_pairs_in_groups(groups, self.state.comparisons)

            if not queue:
                if self.show_done_screen(finals) == "quit":
                    return
                action = self.menu(finals)
                if action == "quit":
                    raise QuitApp()
                if action == "finals":
                    self.compare_loop(finals=True)
                    continue
                # "compare"/"rebuild": loop again (recomputes the queue).
                continue

            rebuild = self.run_queue(queue, finals)
            if rebuild == "quit":
                raise QuitApp()
            # Any other return falls through and rebuilds the queue.

    def run_queue(self, queue: list[tuple[str, str]], finals: bool) -> str:
        idx = 0
        while idx < len(queue):
            a, b = queue[idx]
            # Skip pairs that became invalid (e.g. just vetoed).
            if a not in self.available or b not in self.available:
                idx += 1
                continue
            if not finals and (
                a in self.state.excluded or b in self.state.excluded
            ):
                idx += 1
                continue

            self.draw_compare(a, b, queue, idx, finals)
            key = self.term.read_key()

            if key in (KEY_LEFT, "h"):
                self.do_vote(a, b)
                idx += 1
            elif key in (KEY_RIGHT, "l"):
                self.do_vote(b, a)
                idx += 1
            elif key in ("s", " "):
                idx += 1  # leave undecided; reappears on next rebuild
            elif key == "u":
                self.undo()
                return "rebuild"
            elif key == "x":
                side = self.choose_side("Veto which theme?")
                if side == "left":
                    self.do_exclude(a)
                    self.message = f"Vetoed {a}."
                    return "rebuild"
                if side == "right":
                    self.do_exclude(b)
                    self.message = f"Vetoed {b}."
                    return "rebuild"
            elif key == "f":
                side = self.choose_side("Favorite which theme?")
                if side == "left":
                    added = self.do_favorite(a)
                    self.message = f"{'Favorited' if added else 'Unfavorited'} {a}."
                elif side == "right":
                    added = self.do_favorite(b)
                    self.message = f"{'Favorited' if added else 'Unfavorited'} {b}."
            elif key in (KEY_ESC, "m"):
                action = self.menu(finals)
                if action == "quit":
                    return "quit"
                if action == "finals":
                    self.compare_loop(finals=True)
                    return "rebuild"
                if action == "rebuild":
                    return "rebuild"
                # "compare": stay in this loop, redraw current pair.
            elif key == "?":
                self.help_screen()
            elif key == KEY_CTRL_C:
                return "quit"
        return "rebuild"

    # -- drawing: comparison ------------------------------------------------

    def draw_compare(
        self,
        a: str,
        b: str,
        queue: list[tuple[str, str]],
        idx: int,
        finals: bool,
    ) -> None:
        size = get_size()
        if size.cols < MIN_COLS or size.rows < MIN_ROWS:
            self.term.render(
                f"\n  Terminal too small ({size.cols}x{size.rows}).\n"
                f"  Please resize to at least {MIN_COLS}x{MIN_ROWS}.\n"
            )
            return

        groups = self._groups_for(finals)
        total = ranking.total_pairs_in_groups(groups)
        done = ranking.completed_pairs_in_groups(groups, self.state.comparisons)
        remaining = max(0, total - done)
        group = self.available[a].scheme  # both sides share a scheme

        gutter = 2
        margin = 1
        panel_w = (size.cols - 2 * margin - gutter) // 2
        header_rows = 2
        footer_rows = 4
        panel_h = size.rows - header_rows - footer_rows
        panel_h = max(5, panel_h)

        theme_a = self.available[a]
        theme_b = self.available[b]
        left = build_preview(theme_a, panel_w, panel_h, self.painter)
        right = build_preview(theme_b, panel_w, panel_h, self.painter)

        lines: list[str] = []

        # Header.
        if finals:
            mode = f"FINALS — your {group} favorites"
        else:
            mode = f"Which {group} theme do you prefer?"
        lines.append(self._center(f"{BOLD}{mode}{RESET}", size.cols))
        a_lbl = f"{BOLD}◀ A{RESET}  press ← or h"
        b_lbl = f"press → or l  {BOLD}B ▶{RESET}"
        left_seg = (" " * margin) + self._ljust(a_lbl, panel_w)
        right_seg = self._rjust(b_lbl, panel_w)
        lines.append(left_seg + (" " * gutter) + right_seg)

        # Panels.
        for i in range(panel_h):
            lrow = left[i] if i < len(left) else " " * panel_w
            rrow = right[i] if i < len(right) else " " * panel_w
            lines.append((" " * margin) + lrow + (" " * gutter) + rrow)

        # Footer.
        bar_w = max(10, size.cols - 28)
        lines.append(
            self._clip(
                f"{_bar(done, total, bar_w)} {done}/{total}  "
                f"{DIM}({remaining} left){RESET}",
                size.cols,
            )
        )
        rem_a = sum(1 for x, y in queue if a in (x, y))
        rem_b = sum(1 for x, y in queue if b in (x, y))
        tip = (
            f"{DIM}veto A drops {rem_a} matchups · veto B drops {rem_b} · "
            f"scheme: {self.state.scheme} · favorites: {len(self.state.favorites)} · "
            f"vetoed: {len(self.state.excluded)}{RESET}"
        )
        lines.append(self._clip(tip, size.cols))
        legend = (
            f"{DIM}←/→ pick · s skip · x veto · f favorite · "
            f"u undo · m menu · ? help · ^C quit{RESET}"
        )
        lines.append(self._clip(legend, size.cols))
        msg = self.message or ""
        self.message = None
        lines.append(self._clip(f"{BOLD}{msg}{RESET}" if msg else "", size.cols))

        self.term.render("\n".join(lines))

    # -- choose-side prompt -------------------------------------------------

    def choose_side(self, prompt: str) -> str | None:
        size = get_size()
        hint = (
            f"{BOLD}{prompt}{RESET}  "
            f"←/h = left   →/l = right   (Esc to cancel)"
        )
        # Overwrite the last footer line in place.
        self.term.write("\x1b[%d;1H\x1b[2K" % size.rows)
        self.term.write(self._clip(hint, size.cols))
        self.term.flush()
        while True:
            key = self.term.read_key()
            if key in (KEY_LEFT, "h"):
                return "left"
            if key in (KEY_RIGHT, "l"):
                return "right"
            if key in (KEY_ESC, "m", "q"):
                return None
            if key == KEY_CTRL_C:
                raise QuitApp()

    # -- menu ---------------------------------------------------------------

    def menu(self, finals: bool) -> str:
        options = [
            ("r", "Resume comparisons"),
            ("v", "View ranking"),
            ("F", f"Run finals among favorites ({len(self.state.favorites)})"),
            ("t", "Scheme & filters (light/dark/contrast)"),
            ("a", "Apply theme(s) to Ghostty config"),
            ("s", "Save now"),
            ("q", "Quit (saves automatically)"),
        ]
        while True:
            self._draw_box("Menu", [f"[{k}]  {label}" for k, label in options],
                            footer="Press a key, or Esc to resume.")
            key = self.term.read_key()
            if key in (KEY_ESC, "r", "m"):
                return "compare"
            if key == "v":
                self.ranking_screen()
                return "compare"
            if key in ("F", "f"):
                return "finals"
            if key == "t":
                changed = self.filters_screen()
                return "rebuild" if changed else "compare"
            if key == "a":
                self.apply_screen()
                return "compare"
            if key == "s":
                self.save()
                self.message = "Saved."
                return "compare"
            if key in ("q", KEY_CTRL_C):
                return "quit"

    # -- ranking screen -----------------------------------------------------

    def ranking_screen(self) -> None:
        cursor = 0  # index into the selectable rows
        top = 0  # first display item shown
        while True:
            self.state.recompute_rankings(self.available)
            considered = self.state.considered_groups(self.available)
            show = (
                ["light", "dark"]
                if self.state.scheme == "all"
                else [self.state.scheme]
            )
            # Build a flat display list of headers and rows.
            items: list[tuple[str, object]] = []
            selectable: list[int] = []
            for group in show:
                rows = ranking.compute_ranking(
                    considered[group], self.state.comparisons
                )
                if not rows:
                    continue
                items.append(("header", group))
                for i, row in enumerate(rows):
                    selectable.append(len(items))
                    items.append(("row", (i + 1, row)))
            if not selectable:
                self.notice("No themes to rank yet.", "Compare some themes first.")
                return

            cursor = max(0, min(cursor, len(selectable) - 1))
            size = get_size()
            view_h = max(3, size.rows - 4)
            cur_item = selectable[cursor]
            if cur_item < top:
                top = cur_item
            elif cur_item >= top + view_h:
                top = cur_item - view_h + 1
            top = max(0, min(top, max(0, len(items) - view_h)))

            lines = [self._center(f"{BOLD}Leaderboards{RESET}", size.cols)]
            for idx in range(top, min(top + view_h, len(items))):
                kind, payload = items[idx]
                if kind == "header":
                    label = "Light themes" if payload == "light" else "Dark themes"
                    lines.append(f"{BOLD}── {label} ──{RESET}")
                    continue
                rank_no, row = payload  # type: ignore[misc]
                star = "★" if row.name in self.state.favorites else " "
                swatch = self._swatch(self.available[row.name])
                text = (
                    f"{rank_no:>3}. {star} {row.name:<24.24}  "
                    f"{row.wins}-{row.losses}  {row.win_rate * 100:>4.0f}%  {swatch}"
                )
                text = self._clip(text, size.cols - 1)
                if idx == cur_item:
                    lines.append(f"{REVERSE}{self._ljust(text, size.cols - 1)}{RESET}")
                else:
                    lines.append(text)
            while len(lines) < size.rows - 2:
                lines.append("")
            lines.append(
                f"{DIM}↑/↓ move · Enter apply · x veto · Home/End · Esc back{RESET}"
            )
            self.term.render("\n".join(lines))

            def row_at(c: int):
                return items[selectable[c]][1]

            key = self.term.read_key()
            if key in (KEY_ESC, "m", "q"):
                return
            if key in (KEY_UP, "k"):
                cursor -= 1
            elif key in (KEY_DOWN, "j"):
                cursor += 1
            elif key == KEY_PGUP:
                cursor -= view_h
            elif key == KEY_PGDN:
                cursor += view_h
            elif key == KEY_HOME:
                cursor = 0
            elif key == KEY_END:
                cursor = len(selectable) - 1
            elif key == "x":
                _, row = row_at(cursor)
                self.do_exclude(row.name)  # list refreshes next iteration
            elif key in (KEY_ENTER, "a"):
                _, row = row_at(cursor)
                self.apply_screen(preselect=row.name)
            elif key == KEY_CTRL_C:
                raise QuitApp()

    def _swatch(self, theme: Theme) -> str:
        p = self.painter
        cells = [theme.background, theme.foreground] + [
            theme.palette_color(i) for i in (1, 2, 4, 5, 6)
        ]
        return "".join(p.bg(c) + " " + RESET for c in cells)

    # -- filters screen -----------------------------------------------------

    def filters_screen(self) -> bool:
        f = self.state.filters
        before = (self.state.scheme, f.min_contrast)
        while True:
            considered = self.state.considered_groups(self.available)
            active = len(self.state.active_themes(self.available))
            body = [
                "Scheme — which themes to compare:",
                f"   [a] all   [l] light   [d] dark      (now: {self.state.scheme})",
                "",
                f"[+/-] Minimum contrast ratio   {f.min_contrast:.1f}:1",
                "[0]  Reset minimum contrast",
                "",
                f"Light: {len(considered['light'])}   Dark: {len(considered['dark'])}"
                f"   In play now: {active}",
            ]
            self._draw_box("Scheme & filters", body, footer="Esc when done.")
            key = self.term.read_key()
            if key in (KEY_ESC, "m", "q"):
                break
            if key == "a":
                self.state.scheme = "all"
            elif key == "l":
                self.state.scheme = "light"
            elif key == "d":
                self.state.scheme = "dark"
            elif key in ("+", "=", KEY_RIGHT):
                f.min_contrast = min(21.0, round(f.min_contrast + 0.5, 1))
            elif key in ("-", "_", KEY_LEFT):
                f.min_contrast = max(1.0, round(f.min_contrast - 0.5, 1))
            elif key == "0":
                f.min_contrast = 1.0
            elif key == KEY_CTRL_C:
                raise QuitApp()
        self.save()
        return (self.state.scheme, f.min_contrast) != before

    # -- apply screen -------------------------------------------------------

    def _apply_value(self, value: str) -> None:
        """Write a theme value (single name or ``light:..,dark:..``) and report."""
        try:
            result = ghostty_config.apply_theme(value, self.ghostty_config_path)
        except OSError as exc:
            self.notice("Could not write config.", str(exc))
            return
        self.state.selected = value
        self.save()
        detail = [f"Set theme = {result.theme}", f"in {result.path}"]
        if result.created:
            detail.append("(created a new config file)")
        if result.backup:
            detail.append(f"Backup: {result.backup.name}")
        detail += ["", "Restart Ghostty or reload config to see it."]
        self.notice("Applied!", "\n".join(detail))

    def apply_screen(self, preselect: str | None = None) -> None:
        # From the leaderboard: apply a single chosen theme.
        if preselect is not None:
            body = [
                f"Apply theme:  {BOLD}{preselect}{RESET}",
                "",
                f"Ghostty config: {self.ghostty_config_path}",
                "",
                "Updates (or adds) the 'theme =' line and keeps a backup.",
                "",
                f"{BOLD}[y]{RESET} apply    {BOLD}[Esc]{RESET} cancel",
            ]
            self._draw_box("Apply to Ghostty", body)
            while True:
                key = self.term.read_key()
                if key in ("y", "Y", KEY_ENTER):
                    self._apply_value(preselect)
                    return
                if key in (KEY_ESC, "n", "N", "m", "q"):
                    return
                if key == KEY_CTRL_C:
                    raise QuitApp()

        # From the menu: offer Ghostty's combined light/dark assignment.
        self.state.recompute_rankings(self.available)
        light = self.state.top_light()
        dark = self.state.top_dark()
        combined = f"light:{light},dark:{dark}" if (light and dark) else None
        default_value = combined or light or dark
        if default_value is None:
            self.notice("Nothing to apply yet.", "Compare some themes first.")
            return

        body = [
            f"Light winner: {BOLD}{light or '(none)'}{RESET}",
            f"Dark winner:  {BOLD}{dark or '(none)'}{RESET}",
            "",
            f"Ghostty config: {self.ghostty_config_path}",
            "",
        ]
        if combined:
            body.append(f"{BOLD}[y]{RESET} apply combined  →  theme = {combined}")
        else:
            body.append(f"{BOLD}[y]{RESET} apply  →  theme = {default_value}")
        if light:
            body.append(f"{BOLD}[l]{RESET} apply only light  ({light})")
        if dark:
            body.append(f"{BOLD}[d]{RESET} apply only dark   ({dark})")
        body.append(f"{BOLD}[Esc]{RESET} cancel")
        self._draw_box("Apply to Ghostty", body)
        while True:
            key = self.term.read_key()
            if key in ("y", "Y", KEY_ENTER):
                self._apply_value(default_value)
                return
            if key == "l" and light:
                self._apply_value(light)
                return
            if key == "d" and dark:
                self._apply_value(dark)
                return
            if key in (KEY_ESC, "n", "N", "m", "q"):
                return
            if key == KEY_CTRL_C:
                raise QuitApp()

    # -- simple screens -----------------------------------------------------

    def show_done_screen(self, finals: bool) -> str:
        self.save()
        groups = self._groups_for(finals)
        title = "Finals complete!" if finals else "All comparisons done!"
        shown = [g for g in ("light", "dark") if groups.get(g)] or ["dark"]
        body = []
        for group in shown:
            ranked = ranking.ranking_names(groups[group], self.state.comparisons)
            body.append(f"Top {group}: {BOLD}{ranked[0] if ranked else '(none)'}{RESET}")
        body += [
            "",
            "Open the menu to view leaderboards, run a finals round,",
            "or apply theme(s) to your Ghostty config.",
            "",
            f"{BOLD}[m]{RESET} menu    {BOLD}[Esc]{RESET} quit",
        ]
        self._draw_box(title, body)
        while True:
            key = self.term.read_key()
            if key in ("m", KEY_ENTER):
                return "menu"
            if key in (KEY_ESC, "q", KEY_CTRL_C):
                return "quit"

    def help_screen(self) -> None:
        body = [
            f"{BOLD}Comparing{RESET}",
            "  ← / h        left theme is better",
            "  → / l        right theme is better",
            "  s / space    skip this pair for now",
            "  x            veto a theme (drops all its remaining matchups)",
            "  f            favorite a theme (candidate for the finals)",
            "  u            undo the last action",
            "",
            f"{BOLD}Navigation{RESET}",
            "  m / Esc      open the menu",
            "  ? help · ^C quit (everything is saved as you go)",
            "",
            "Tip: vetoing themes you'd never use is the fastest way to",
            "shrink a 300-theme tournament down to something finishable.",
        ]
        self._draw_box("Help", body, footer="Press any key to continue.")
        self.term.read_key()

    def notice(self, title: str, body: str) -> None:
        lines = body.split("\n") if body else [""]
        self._draw_box(title, lines, footer="Press any key to continue.")
        self.term.read_key()

    # -- layout helpers -----------------------------------------------------

    def _draw_box(self, title: str, body_lines: list[str], footer: str = "") -> None:
        size = get_size()
        width = min(size.cols - 4, 72)
        width = max(20, width)
        inner = width - 4
        out: list[str] = []
        pad_top = max(0, (size.rows - (len(body_lines) + 6)) // 2)
        out.extend([""] * pad_top)
        out.append(self._center("╭" + "─" * (width - 2) + "╮", size.cols))
        out.append(self._center("│ " + self._ljust(f"{BOLD}{title}{RESET}", inner) + " │", size.cols))
        out.append(self._center("│ " + " " * inner + " │", size.cols))
        for line in body_lines:
            out.append(self._center("│ " + self._ljust(line, inner) + " │", size.cols))
        out.append(self._center("│ " + " " * inner + " │", size.cols))
        if footer:
            out.append(self._center("│ " + self._ljust(f"{DIM}{footer}{RESET}", inner) + " │", size.cols))
            out.append(self._center("│ " + " " * inner + " │", size.cols))
        out.append(self._center("╰" + "─" * (width - 2) + "╯", size.cols))
        self.term.render("\n".join(out))

    @staticmethod
    def _visible_len(text: str) -> int:
        from .color import visible_width

        return visible_width(text)

    def _ljust(self, text: str, width: int) -> str:
        pad = width - self._visible_len(text)
        return text + " " * pad if pad > 0 else self._clip(text, width)

    def _rjust(self, text: str, width: int) -> str:
        pad = width - self._visible_len(text)
        return " " * pad + text if pad > 0 else self._clip(text, width)

    def _center(self, text: str, width: int) -> str:
        pad = width - self._visible_len(text)
        if pad <= 0:
            return self._clip(text, width)
        left = pad // 2
        return " " * left + text + " " * (pad - left)

    def _clip(self, text: str, width: int) -> str:
        """Clip to ``width`` visible columns, preserving escape sequences."""
        if self._visible_len(text) <= width:
            return text
        out = []
        count = 0
        i = 0
        while i < len(text) and count < width:
            if text[i] == "\x1b":
                j = i + 1
                if j < len(text) and text[j] == "[":
                    j += 1
                    # Consume params/intermediates up to the final byte (@-~).
                    while j < len(text) and not (0x40 <= ord(text[j]) <= 0x7E):
                        j += 1
                    if j < len(text):
                        j += 1  # include the final byte
                out.append(text[i:j])
                i = j
            else:
                out.append(text[i])
                count += 1
                i += 1
        out.append(RESET)
        return "".join(out)
