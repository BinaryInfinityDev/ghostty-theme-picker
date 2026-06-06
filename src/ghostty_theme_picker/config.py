"""Persistent state for a comparison session, stored as TOML.

The state file is both the durable record of a session (so it can be resumed)
and the deliverable the user asked for: a ranked list plus the themes they
excluded. Its schema::

    version  = 1
    selected = "Theme Name"        # chosen theme (optional)
    pool      = ["A", "B", ...]    # universe for this session (optional)
    excluded  = ["Bad", ...]       # vetoed themes
    favorites = ["Great", ...]     # finalists
    ranking   = ["A", "C", "B"]    # cached ranking, best first

    [filters]
    exclude_light = false
    exclude_dark  = false
    min_contrast  = 1.0

    [[comparison]]
    winner = "A"
    loser  = "B"

``pool`` lets a user start from a subset: list the themes you want to consider
and the tool restricts the tournament to them. ``excluded`` removes themes
entirely. Active themes for a session are ``pool`` (or all discovered themes)
minus ``excluded`` minus anything cut by the property filters.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import ranking
from .themes import Theme
from .toml_writer import format_keyval


@dataclass
class Filters:
    exclude_light: bool = False
    exclude_dark: bool = False
    min_contrast: float = 1.0  # WCAG ratio; 1.0 means "no filter"

    def is_active(self) -> bool:
        return self.exclude_light or self.exclude_dark or self.min_contrast > 1.0

    def rejects(self, theme: Theme) -> bool:
        if self.exclude_light and theme.is_light:
            return True
        if self.exclude_dark and not theme.is_light:
            return True
        if theme.contrast < self.min_contrast:
            return True
        return False


@dataclass
class State:
    version: int = 1
    selected: str | None = None
    pool: list[str] | None = None
    excluded: list[str] = field(default_factory=list)
    favorites: list[str] = field(default_factory=list)
    ranking: list[str] = field(default_factory=list)
    filters: Filters = field(default_factory=Filters)
    comparisons: list[tuple[str, str]] = field(default_factory=list)

    # ---- derived sets -----------------------------------------------------

    def active_themes(self, available: dict[str, Theme]) -> list[str]:
        """Themes still in play: pool (or all) minus excluded minus filtered.

        ``available`` is the discovered ``name -> Theme`` map; only themes we
        actually have are returned, in a stable order.
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

    def record(self, winner: str, loser: str) -> None:
        key = ranking.pair_key(winner, loser)
        # Replace any prior verdict for this matchup.
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

    def recompute_ranking(self, available: dict[str, Theme]) -> list[str]:
        self.ranking = ranking.ranking_names(
            self.active_themes(available), self.comparisons
        )
        return self.ranking

    # ---- serialization ----------------------------------------------------

    def to_toml(self) -> str:
        lines: list[str] = []
        lines.append(format_keyval("version", self.version))
        if self.selected:
            lines.append(format_keyval("selected", self.selected))
        if self.pool is not None:
            lines.append(format_keyval("pool", list(self.pool)))
        lines.append(format_keyval("excluded", list(self.excluded)))
        lines.append(format_keyval("favorites", list(self.favorites)))
        lines.append(format_keyval("ranking", list(self.ranking)))

        lines.append("")
        lines.append("[filters]")
        lines.append(format_keyval("exclude_light", self.filters.exclude_light))
        lines.append(format_keyval("exclude_dark", self.filters.exclude_dark))
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
        filters = Filters(
            exclude_light=bool(filters_data.get("exclude_light", False)),
            exclude_dark=bool(filters_data.get("exclude_dark", False)),
            min_contrast=float(filters_data.get("min_contrast", 1.0)),
        )
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
            pool=pool,
            excluded=[str(x) for x in data.get("excluded", []) or []],
            favorites=[str(x) for x in data.get("favorites", []) or []],
            ranking=[str(x) for x in data.get("ranking", []) or []],
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
