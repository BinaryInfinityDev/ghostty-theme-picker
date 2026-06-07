"""Persistent state for a comparison session, stored as TOML.

The state file is both the durable record of a session (so it can be resumed)
and the deliverable: separate ranked lists for light and dark themes, plus the
themes the user excluded. Its schema::

    version  = 1
    selected = "light:Foo,dark:Bar"   # what was last applied (optional)
    scheme    = "all"                 # all | light | dark -- which group(s) to compare
    pool      = ["A", "B", ...]       # universe for this session (optional)
    excluded  = ["Bad", ...]          # vetoed themes
    favorites = ["Great", ...]        # finalists
    ranking_light = ["A", "C", ...]   # cached light leaderboard, best first
    ranking_dark  = ["X", "Y", ...]   # cached dark leaderboard, best first

    [filters]
    min_contrast = 1.0

    [[comparison]]
    winner = "A"
    loser  = "B"

Themes are classified light/dark with Ghostty's own logic (see
``color.ghostty_luminance``). Comparisons only ever happen *within* a group, so
the two leaderboards are fully independent. ``scheme`` lets the user restrict a
session to just light or just dark themes.

Sets:
* **considered** = ``pool`` (or all discovered) minus ``excluded`` minus the
  contrast filter. Both leaderboards are computed over this set.
* **active**     = considered, further restricted to the chosen ``scheme``.
  This is what gets compared.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import ranking
from .themes import Theme
from .toml_writer import format_keyval

SCHEMES = ("all", "light", "dark")


@dataclass
class Filters:
    min_contrast: float = 1.0  # WCAG ratio; 1.0 means "no filter"

    def is_active(self) -> bool:
        return self.min_contrast > 1.0

    def rejects(self, theme: Theme) -> bool:
        return theme.contrast < self.min_contrast


@dataclass
class State:
    version: int = 1
    selected: str | None = None
    scheme: str = "all"
    pool: list[str] | None = None
    excluded: list[str] = field(default_factory=list)
    favorites: list[str] = field(default_factory=list)
    ranking_light: list[str] = field(default_factory=list)
    ranking_dark: list[str] = field(default_factory=list)
    filters: Filters = field(default_factory=Filters)
    comparisons: list[tuple[str, str]] = field(default_factory=list)

    # ---- derived sets -----------------------------------------------------

    def considered_themes(self, available: dict[str, Theme]) -> list[str]:
        """Pool (or all) minus excluded minus the contrast filter.

        Independent of ``scheme`` -- both leaderboards are built from this.
        """
        if self.pool is not None:
            base = [n for n in self.pool if n in available]
        else:
            base = list(available.keys())
        excluded = set(self.excluded)
        result = []
        for name in base:
            if name in excluded:
                continue
            if self.filters.rejects(available[name]):
                continue
            result.append(name)
        return result

    def considered_groups(self, available: dict[str, Theme]) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {"light": [], "dark": []}
        for name in self.considered_themes(available):
            groups[available[name].scheme].append(name)
        return groups

    def active_themes(self, available: dict[str, Theme]) -> list[str]:
        """Considered themes restricted to the chosen scheme."""
        result = []
        for name in self.considered_themes(available):
            if self.scheme == "all" or self.scheme == available[name].scheme:
                result.append(name)
        return result

    def active_groups(self, available: dict[str, Theme]) -> dict[str, list[str]]:
        """Active themes partitioned by scheme (the group(s) being compared)."""
        groups: dict[str, list[str]] = {"light": [], "dark": []}
        for name in self.active_themes(available):
            groups[available[name].scheme].append(name)
        return groups

    # ---- mutations --------------------------------------------------------

    def record(self, winner: str, loser: str) -> None:
        key = ranking.pair_key(winner, loser)
        self.comparisons = [
            (w, l) for (w, l) in self.comparisons if ranking.pair_key(w, l) != key
        ]
        self.comparisons.append((winner, loser))

    def exclude(self, name: str) -> None:
        if name not in self.excluded:
            self.excluded.append(name)
        if name in self.favorites:
            self.favorites.remove(name)

    def toggle_favorite(self, name: str) -> bool:
        if name in self.favorites:
            self.favorites.remove(name)
            return False
        self.favorites.append(name)
        return True

    # ---- leaderboards -----------------------------------------------------

    def recompute_rankings(
        self, available: dict[str, Theme]
    ) -> tuple[list[str], list[str]]:
        groups = self.considered_groups(available)
        self.ranking_light = ranking.ranking_names(groups["light"], self.comparisons)
        self.ranking_dark = ranking.ranking_names(groups["dark"], self.comparisons)
        return self.ranking_light, self.ranking_dark

    def top_light(self) -> str | None:
        return self.ranking_light[0] if self.ranking_light else None

    def top_dark(self) -> str | None:
        return self.ranking_dark[0] if self.ranking_dark else None

    # ---- serialization ----------------------------------------------------

    def to_toml(self) -> str:
        lines: list[str] = []
        lines.append(format_keyval("version", self.version))
        if self.selected:
            lines.append(format_keyval("selected", self.selected))
        lines.append(format_keyval("scheme", self.scheme))
        if self.pool is not None:
            lines.append(format_keyval("pool", list(self.pool)))
        lines.append(format_keyval("excluded", list(self.excluded)))
        lines.append(format_keyval("favorites", list(self.favorites)))
        lines.append(format_keyval("ranking_light", list(self.ranking_light)))
        lines.append(format_keyval("ranking_dark", list(self.ranking_dark)))

        lines.append("")
        lines.append("[filters]")
        lines.append(format_keyval("min_contrast", float(self.filters.min_contrast)))

        for winner, loser in self.comparisons:
            lines.append("")
            lines.append("[[comparison]]")
            lines.append(format_keyval("winner", winner))
            lines.append(format_keyval("loser", loser))

        return "\n".join(lines) + "\n"

    @classmethod
    def from_dict(cls, data: dict) -> "State":
        filters_data = data.get("filters", {}) or {}
        filters = Filters(min_contrast=float(filters_data.get("min_contrast", 1.0)))

        scheme = data.get("scheme")
        if scheme not in SCHEMES:
            # Back-compat with the old exclude_light/exclude_dark filters.
            el = bool(filters_data.get("exclude_light", False))
            ed = bool(filters_data.get("exclude_dark", False))
            if el and not ed:
                scheme = "dark"
            elif ed and not el:
                scheme = "light"
            else:
                scheme = "all"

        comparisons: list[tuple[str, str]] = []
        for entry in data.get("comparison", []) or []:
            winner = entry.get("winner")
            loser = entry.get("loser")
            if isinstance(winner, str) and isinstance(loser, str):
                comparisons.append((winner, loser))

        pool = data.get("pool")
        if pool is not None:
            pool = [str(x) for x in pool]

        return cls(
            version=int(data.get("version", 1)),
            selected=data.get("selected"),
            scheme=scheme,
            pool=pool,
            excluded=[str(x) for x in data.get("excluded", []) or []],
            favorites=[str(x) for x in data.get("favorites", []) or []],
            ranking_light=[str(x) for x in data.get("ranking_light", []) or []],
            ranking_dark=[str(x) for x in data.get("ranking_dark", []) or []],
            filters=filters,
            comparisons=comparisons,
        )


def default_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "ghostty-theme-picker" / "picker.toml"


def load_state(path: Path) -> State:
    """Load state, returning a fresh :class:`State` if the file is absent."""
    if not path.exists():
        return State()
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    return State.from_dict(data)


def save_state(path: Path, state: State) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(state.to_toml(), encoding="utf-8")
    tmp.replace(path)
