"""Locating and updating the user's Ghostty configuration file.

Applying a theme means ensuring the config has a ``theme = <name>`` line. We
update the last uncommented ``theme =`` line in place (preserving everything
else and any commented-out lines) or append one if none exists, and we keep a
timestamped backup before writing.
"""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_THEME_LINE_RE = re.compile(r"^(\s*)theme(\s*)=(.*)$")


def candidate_config_paths() -> list[Path]:
    paths: list[Path] = []
    xdg = os.environ.get("XDG_CONFIG_HOME")
    config_home = Path(xdg) if xdg else Path.home() / ".config"
    paths.append(config_home / "ghostty" / "config")
    paths.append(Path.home() / ".config" / "ghostty" / "config")
    if sys.platform == "darwin":
        paths.append(
            Path.home()
            / "Library/Application Support/com.mitchellh.ghostty/config"
        )
    # De-duplicate preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def find_config_path(override: str | None = None) -> Path:
    """Return the config path to use.

    With no override, prefer an existing config; otherwise fall back to the
    platform default (which may not exist yet -- callers decide whether to
    create it).
    """
    if override:
        return Path(override).expanduser()
    candidates = candidate_config_paths()
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


@dataclass
class ApplyResult:
    path: Path
    theme: str
    created: bool
    replaced: bool
    backup: Path | None
    previous: str | None


def set_theme_in_text(text: str, theme: str) -> tuple[str, bool, str | None]:
    """Return ``(new_text, replaced, previous_value)``.

    Replaces the last uncommented ``theme =`` line, or appends one.
    """
    lines = text.splitlines()
    last_idx = -1
    previous: str | None = None
    for i, line in enumerate(lines):
        m = _THEME_LINE_RE.match(line)
        if m:
            last_idx = i
            previous = m.group(3).strip()
    if last_idx >= 0:
        indent = _THEME_LINE_RE.match(lines[last_idx]).group(1)  # type: ignore[union-attr]
        lines[last_idx] = f"{indent}theme = {theme}"
        new_text = "\n".join(lines)
        if text.endswith("\n"):
            new_text += "\n"
        return new_text, True, previous

    # Append.
    if text and not text.endswith("\n"):
        text += "\n"
    addition = f"theme = {theme}\n"
    return text + addition, False, None


def apply_theme(
    theme: str,
    config_path: Path,
    *,
    create: bool = True,
    backup: bool = True,
) -> ApplyResult:
    """Write ``theme`` into the Ghostty config at ``config_path``."""
    existed = config_path.exists()
    if not existed and not create:
        raise FileNotFoundError(f"Ghostty config not found: {config_path}")

    original = config_path.read_text(encoding="utf-8") if existed else ""
    new_text, replaced, previous = set_theme_in_text(original, theme)

    backup_path: Path | None = None
    if existed and backup and original != new_text:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup_path = config_path.with_name(f"{config_path.name}.bak-{stamp}")
        # Second-granularity stamps can collide on rapid re-applies; never
        # clobber an existing backup -- add a counter suffix instead.
        counter = 1
        while backup_path.exists():
            backup_path = config_path.with_name(f"{config_path.name}.bak-{stamp}-{counter}")
            counter += 1
        backup_path.write_text(original, encoding="utf-8")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(new_text, encoding="utf-8")

    return ApplyResult(
        path=config_path,
        theme=theme,
        created=not existed,
        replaced=replaced,
        backup=backup_path,
        previous=previous,
    )
