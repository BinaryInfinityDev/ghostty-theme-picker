"""Discovery and parsing of Ghostty theme files.

A Ghostty theme is a plain config file (named after the theme, no extension)
containing lines like::

    palette = 0=#21222c
    palette = 1=#ff5555
    background = 282a36
    foreground = f8f8f2
    cursor-color = f8f8f2
    selection-background = 44475a

Themes ship with Ghostty and are discoverable either via ``ghostty
+list-themes`` or by scanning the resource directories where Ghostty installs
them. We parse the files directly because we need the actual color values to
render previews.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .color import RGB, contrast_ratio, is_light, parse_color

# Keys we care about, mapped onto Theme attributes.
_SIMPLE_KEYS = {
    "background": "background",
    "foreground": "foreground",
    "cursor-color": "cursor",
    "cursor-text": "cursor_text",
    "selection-background": "selection_bg",
    "selection-foreground": "selection_fg",
}

# Reasonable fallbacks when a theme omits a value.
_DEFAULT_BG = RGB(0x1D, 0x1F, 0x21)
_DEFAULT_FG = RGB(0xC5, 0xC8, 0xC6)

# A neutral 16-color ramp used only to fill gaps in a sparse palette so the
# color bar always has something to show.
_FALLBACK_PALETTE = [
    RGB(0x00, 0x00, 0x00), RGB(0xCC, 0x00, 0x00), RGB(0x4E, 0x9A, 0x06),
    RGB(0xC4, 0xA0, 0x00), RGB(0x34, 0x65, 0xA4), RGB(0x75, 0x50, 0x7B),
    RGB(0x06, 0x98, 0x9A), RGB(0xD3, 0xD7, 0xCF), RGB(0x55, 0x57, 0x53),
    RGB(0xEF, 0x29, 0x29), RGB(0x8A, 0xE2, 0x34), RGB(0xFC, 0xE9, 0x4F),
    RGB(0x72, 0x9F, 0xCF), RGB(0xAD, 0x7F, 0xA8), RGB(0x34, 0xE2, 0xE2),
    RGB(0xEE, 0xEE, 0xEC),
]


@dataclass
class Theme:
    """A parsed Ghostty theme."""

    name: str
    path: str | None
    palette: dict[int, RGB] = field(default_factory=dict)
    background: RGB = _DEFAULT_BG
    foreground: RGB = _DEFAULT_FG
    cursor: RGB | None = None
    cursor_text: RGB | None = None
    selection_bg: RGB | None = None
    selection_fg: RGB | None = None

    def palette_color(self, index: int) -> RGB:
        """Color for ANSI index 0-15, using a sane fallback if unset."""
        if index in self.palette:
            return self.palette[index]
        if 0 <= index < len(_FALLBACK_PALETTE):
            return _FALLBACK_PALETTE[index]
        return self.foreground

    @property
    def cursor_color(self) -> RGB:
        return self.cursor or self.foreground

    @property
    def cursor_text_color(self) -> RGB:
        return self.cursor_text or self.background

    @property
    def selection_background(self) -> RGB:
        if self.selection_bg is not None:
            return self.selection_bg
        # Blend a bit toward foreground for a visible selection.
        return self.background.blend(self.foreground, 0.30)

    @property
    def selection_foreground(self) -> RGB:
        return self.selection_fg or self.foreground

    @property
    def is_light(self) -> bool:
        return is_light(self.background)

    @property
    def contrast(self) -> float:
        return contrast_ratio(self.background, self.foreground)


def parse_theme_text(text: str, name: str, path: str | None = None) -> Theme:
    """Parse the contents of a theme file into a :class:`Theme`."""
    theme = Theme(name=name, path=path)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key == "palette":
            idx_str, isep, color_str = value.partition("=")
            if not isep:
                continue
            try:
                idx = int(idx_str.strip())
            except ValueError:
                continue
            color = parse_color(color_str)
            if color is not None:
                theme.palette[idx] = color
        elif key in _SIMPLE_KEYS:
            color = parse_color(value)
            if color is not None:
                setattr(theme, _SIMPLE_KEYS[key], color)
    return theme


def parse_theme_file(path: Path) -> Theme:
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_theme_text(text, name=path.name, path=str(path))


def _candidate_theme_dirs() -> list[Path]:
    """Best-effort list of directories where Ghostty keeps its themes."""
    dirs: list[Path] = []

    env_dir = os.environ.get("GHOSTTY_THEMES_DIR")
    if env_dir:
        dirs.append(Path(env_dir))

    xdg = os.environ.get("XDG_CONFIG_HOME")
    config_home = Path(xdg) if xdg else Path.home() / ".config"
    dirs.append(config_home / "ghostty" / "themes")  # user-provided themes
    dirs.append(Path.home() / ".config" / "ghostty" / "themes")

    if sys.platform == "darwin":
        dirs.append(
            Path("/Applications/Ghostty.app/Contents/Resources/ghostty/themes")
        )
        dirs.append(
            Path.home()
            / "Applications/Ghostty.app/Contents/Resources/ghostty/themes"
        )
        dirs.append(
            Path("/opt/homebrew/Caskroom/ghostty")  # homebrew cask (versioned)
        )

    # Linux / BSD install prefixes.
    for prefix in (
        "/usr/share",
        "/usr/local/share",
        "/opt/ghostty/share",
        "/var/lib/flatpak/app/com.mitchellh.ghostty/current/active/files/share",
    ):
        dirs.append(Path(prefix) / "ghostty" / "themes")

    flatpak_user = (
        Path.home()
        / ".local/share/flatpak/app/com.mitchellh.ghostty/current/active/files/share/ghostty/themes"
    )
    dirs.append(flatpak_user)

    # De-duplicate while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


def find_themes_dir(override: str | None = None) -> Path | None:
    """Return the first directory that actually yields theme files, or ``None``.

    We require at least one parseable theme so that a directory which merely
    exists (e.g. an unrelated cask/version folder) doesn't shadow a real one.
    """
    if override:
        p = Path(override).expanduser()
        return p if p.is_dir() else None
    for d in _candidate_theme_dirs():
        try:
            if d.is_dir() and load_themes_from_dir(d):
                return d
        except OSError:
            continue
    return None


def _looks_like_theme_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name.startswith("."):
        return False
    if path.suffix in (".md", ".txt", ".json", ".toml", ".py", ".sh"):
        return False
    return True


def load_themes_from_dir(directory: Path) -> dict[str, Theme]:
    themes: dict[str, Theme] = {}
    try:
        entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return themes
    for entry in entries:
        if not _looks_like_theme_file(entry):
            continue
        try:
            theme = parse_theme_file(entry)
        except OSError:
            continue
        themes[theme.name] = theme
    return themes


def discover_themes(themes_dir: str | None = None) -> dict[str, Theme]:
    """Discover all available themes as a ``name -> Theme`` mapping."""
    directory = find_themes_dir(themes_dir)
    if directory is None:
        return {}
    return load_themes_from_dir(directory)
