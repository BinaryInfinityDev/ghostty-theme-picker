"""Rendering a faithful mini-terminal preview of a theme.

Each preview is a bordered "window" filled with the theme's own background and
painted with its real colors: a shell prompt, a syntax-highlighted code
snippet, the full 16-color ANSI bar, a selection sample and a block cursor.
Because we emit the theme's exact colors (24-bit when the terminal supports
it), what you see is what Ghostty would actually render.

``build_preview`` returns a list of strings, one per row, each exactly
``width`` visible columns wide so two previews tile cleanly side by side.
"""

from __future__ import annotations

from dataclasses import dataclass

from .color import BOLD, DIM, ITALIC, RESET, RGB, Painter, best_text_on
from .themes import Theme


@dataclass
class Span:
    text: str
    fg: RGB | None = None
    bg: RGB | None = None
    bold: bool = False
    dim: bool = False
    italic: bool = False


def _pad_spans(spans: list[Span], width: int, bg: RGB) -> list[Span]:
    """Truncate or pad ``spans`` to exactly ``width`` visible columns."""
    out: list[Span] = []
    used = 0
    for span in spans:
        if used >= width:
            break
        room = width - used
        text = span.text if len(span.text) <= room else span.text[:room]
        if text:
            out.append(
                Span(text, span.fg, span.bg, span.bold, span.dim, span.italic)
            )
            used += len(text)
    if used < width:
        out.append(Span(" " * (width - used), bg=bg))
    return out


def render_line(spans: list[Span], width: int, theme: Theme, painter: Painter) -> str:
    """Render a row of spans to an ANSI string of exactly ``width`` columns."""
    default_bg = theme.background
    default_fg = theme.foreground
    fixed = _pad_spans(spans, width, default_bg)
    parts: list[str] = []
    for span in fixed:
        bg = span.bg or default_bg
        fg = span.fg or default_fg
        attrs = ""
        if span.bold:
            attrs += BOLD
        if span.dim:
            attrs += DIM
        if span.italic:
            attrs += ITALIC
        parts.append(painter.bg(bg) + painter.fg(fg) + attrs + span.text + RESET)
    return "".join(parts)


def _content_sections(theme: Theme, inner_w: int) -> list[list[Span]]:
    """Logical content lines, most informative first (so truncation is kind)."""
    fg = theme.foreground
    p = theme.palette_color
    comment = p(8)
    green, yellow, blue, magenta, cyan = p(10), p(11), p(12), p(13), p(14)
    red = p(9)

    sections: list[list[Span]] = []

    # Meta line.
    kind = "light" if theme.is_light else "dark"
    sections.append(
        [Span(f"{kind} theme · contrast {theme.contrast:.1f}:1", fg=comment, italic=True)]
    )

    # Shell prompt.
    sections.append(
        [
            Span("user", fg=green, bold=True),
            Span("@", fg=fg),
            Span("ghostty", fg=green, bold=True),
            Span(":", fg=fg),
            Span("~/projects", fg=blue, bold=True),
            Span("$ ", fg=fg),
            Span("git status", fg=fg),
        ]
    )
    sections.append(
        [
            Span("On branch ", fg=fg),
            Span("main", fg=cyan),
            Span("  ", fg=fg),
            Span("modified:", fg=red),
            Span(" theme.zig", fg=fg),
        ]
    )

    sections.append([])  # blank

    # 16-color ANSI bar, two rows of eight uniform cells.
    for base in (0, 8):
        row: list[Span] = []
        for i in range(base, base + 8):
            cell = p(i)
            row.append(Span(f"{i:^4}", bg=cell, fg=best_text_on(cell)))
        sections.append(row)

    sections.append([])  # blank

    # Syntax-highlighted code snippet.
    sections.append(
        [
            Span("def ", fg=magenta, bold=True),
            Span("greet", fg=blue),
            Span("(", fg=fg),
            Span("name", fg=yellow),
            Span("):", fg=fg),
        ]
    )
    sections.append(
        [
            Span("    return ", fg=magenta),
            Span('f"Hello, ', fg=green),
            Span("{name}", fg=cyan),
            Span('!"', fg=green),
        ]
    )
    sections.append([Span("    # wave to the world", fg=comment, italic=True)])

    sections.append([])  # blank

    # Selection sample.
    sections.append(
        [
            Span("Drag to ", fg=fg),
            Span(" select text ", bg=theme.selection_background, fg=theme.selection_foreground),
            Span(" here.", fg=fg),
        ]
    )

    # Block cursor.
    sections.append(
        [
            Span("$ ", fg=fg),
            Span("ghostty ", fg=fg),
            Span(" ", bg=theme.cursor_color, fg=theme.cursor_text_color),
        ]
    )

    return sections


def build_preview(
    theme: Theme, width: int, height: int, painter: Painter
) -> list[str]:
    """Render a full bordered preview window, ``height`` rows of ``width`` cols."""
    width = max(width, 8)
    height = max(height, 3)

    border = theme.palette_color(8)
    bg = theme.background

    inner_w = width - 4  # left border + space ... space + right border
    inner_h = height - 2

    rows: list[str] = []

    # Top border with embedded title.
    title = f" {theme.name} "
    if len(title) > width - 4:
        title = title[: width - 5] + "… "
    dash_count = (width - 2) - len(title)
    left_dashes = 1
    right_dashes = max(0, dash_count - left_dashes)
    top = (
        [Span("╭", fg=border)]
        + [Span("─" * left_dashes, fg=border)]
        + [Span(title, fg=theme.foreground, bold=True)]
        + [Span("─" * right_dashes, fg=border)]
        + [Span("╮", fg=border)]
    )
    rows.append(render_line(top, width, theme, painter))

    # Content rows.
    sections = _content_sections(theme, inner_w)
    if len(sections) > inner_h:
        sections = sections[:inner_h]
    while len(sections) < inner_h:
        sections.append([])

    for content in sections:
        inner = _pad_spans(content, inner_w, bg)
        row = (
            [Span("│", fg=border), Span(" ", bg=bg)]
            + inner
            + [Span(" ", bg=bg), Span("│", fg=border)]
        )
        rows.append(render_line(row, width, theme, painter))

    # Bottom border.
    bottom = (
        [Span("╰", fg=border)]
        + [Span("─" * (width - 2), fg=border)]
        + [Span("╯", fg=border)]
    )
    rows.append(render_line(bottom, width, theme, painter))

    return rows
