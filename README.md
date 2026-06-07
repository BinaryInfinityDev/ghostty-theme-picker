# ghostty-theme-picker

Ghostty ships with hundreds of color themes, but its built-in picker only shows
you **one at a time**. Choosing a favorite by scrolling through a long list is
slow and you can never really compare two side by side.

`ghostty-theme-picker` turns theme selection into a **side-by-side tournament**.
It shows you two themes at once — rendered as faithful mini-terminals in their
real 24-bit colors — and you pick the better one. Repeat across the matchups and
it produces a **ranked list**. Then it can write your chosen theme straight into
your Ghostty config.

![Two themes compared side by side](docs/preview-dark.png)

It also works with light themes:

![A light and a dark theme compared](docs/preview-mixed.png)

## Highlights

- **True side-by-side previews.** Each theme is drawn as a realistic terminal
  window (shell prompt, syntax-highlighted code, the full 16-color ANSI bar, a
  text selection sample and a block cursor) using the theme's exact colors —
  24-bit when your terminal supports it, with an automatic 256-color fallback.
- **Separate light & dark leaderboards.** Themes are classified light/dark with
  Ghostty's own logic, and only ever compared within their group (light vs
  light, dark vs dark). You get two independent ranked lists — exactly what you
  need for Ghostty's combined `light:…,dark:…` theme assignment.
- **Pick a scheme.** Compare both groups, or restrict a session to just light or
  just dark with `--scheme` (or from the in-app menu).
- **Full round-robin.** Every within-group pair of non-excluded themes is
  presented exactly once. Progress is saved continuously — stop and resume
  anytime.
- **Veto bad themes fast.** Press `x` to remove a theme you'd never use; it
  drops out of *all* its remaining matchups, shrinking the tournament.
- **Minimum-contrast filter.** Prune unreadable themes by requiring a minimum
  text/background contrast ratio.
- **Favorites & finals.** Star themes as you go, then run a decisive **finals**
  round-robin among just your favorites (still within each group).
- **Ranked results.** Standings are computed with a Copeland-style win count
  (ordered by win rate so partial progress still makes sense).
- **Apply to Ghostty.** Write a combined `light:…,dark:…` assignment by default,
  or just one group — the previous config is backed up first.
- **Start from a subset.** Begin from all installed themes, or from a curated
  list in a config file.
- **Zero dependencies.** Pure Python standard library, Python 3.11+.

## Install

```bash
# from a clone of this repo
pip install .

# or run without installing
python -m ghostty_theme_picker --help
```

This installs a `ghostty-theme-picker` command.

## Quick start

```bash
# Compare every installed Ghostty theme, two at a time:
ghostty-theme-picker compare

# Try it against the bundled sample themes (no Ghostty needed):
ghostty-theme-picker compare --themes-dir ./sample-themes
```

### Keys while comparing

| Key | Action |
| --- | --- |
| `←` / `h` | Left theme is better |
| `→` / `l` | Right theme is better |
| `s` / `space` | Skip this pair for now |
| `x` | Veto a theme (then pick a side) — drops all its remaining matchups |
| `f` | Favorite a theme (then pick a side) — candidate for the finals |
| `u` | Undo the last action |
| `m` / `Esc` | Open the menu (leaderboards, finals, scheme & filters, apply, save, quit) |
| `?` | Help |
| `Ctrl-C` | Quit (everything is saved as you go) |

From the menu you can view the live **leaderboards** (light and dark), run the
**finals** among your favorites, change the **scheme & filters**, or **apply**
theme(s) to your Ghostty config.

## Light vs dark

Themes are classified using **Ghostty's own logic** — the relative luminance of
the background (`0.2126·R + 0.7152·G + 0.0722·B`, normalized) is below `0.5` for
dark themes — the same rule Ghostty's `+list-themes` uses. The tool keeps two
independent leaderboards and only ever compares **light against light** and
**dark against dark**, so a "dark" theme never has to compete with a "light"
one. Use `--scheme` (or the in-app **Scheme & filters** menu) to compare both
groups or restrict to one:

```bash
ghostty-theme-picker compare --scheme dark    # only dark themes
ghostty-theme-picker compare --scheme light   # only light themes
ghostty-theme-picker compare --scheme all     # both (the default)
```

## Other commands

```bash
# Print the leaderboards (light and dark; non-interactive):
ghostty-theme-picker rank
ghostty-theme-picker rank --scheme dark        # just the dark leaderboard

# List discovered themes, optionally with light/dark + contrast:
ghostty-theme-picker list-themes --details

# Print a single theme preview to stdout:
ghostty-theme-picker preview "Tokyo Night"

# Show resolved paths and counts:
ghostty-theme-picker info
```

### Applying theme(s) to Ghostty

By default `apply` writes Ghostty's **combined** assignment using the top theme
from each leaderboard, so Ghostty can switch automatically with your OS
appearance:

```bash
# theme = light:<top light>,dark:<top dark>
ghostty-theme-picker apply

# Apply just one group:
ghostty-theme-picker apply --only-dark
ghostty-theme-picker apply --only-light

# Override either side (anything omitted uses the auto pick):
ghostty-theme-picker apply --light "Solarized Light" --dark "Tokyo Night"

# Or apply one exact theme as a single value:
ghostty-theme-picker apply "Tokyo Night"
```

### Starting from a subset

```bash
# Restrict the tournament to a comma-separated list:
ghostty-theme-picker compare --pool "Dracula,Nord,Tokyo Night,Gruvbox Dark"

# ...or from a file with one theme name per line:
ghostty-theme-picker compare --pool-file my-shortlist.txt
```

You can also point `--config` at any saved session file; its `pool` and
`excluded` lists define the starting set, and its `scheme` the light/dark
restriction.

## Where things live

- **Picker state / results:** `$XDG_CONFIG_HOME/ghostty-theme-picker/picker.toml`
  (override with `--config`). This is the deliverable: it stores the two ranked
  lists (`ranking_light`, `ranking_dark`), the themes you excluded, your
  favorites, the scheme and filters, the recorded comparisons (so sessions
  resume), and your selected assignment.
- **Ghostty config:** auto-detected at `$XDG_CONFIG_HOME/ghostty/config`
  (and the macOS Application Support location). Override with
  `--ghostty-config`.
- **Theme files:** auto-detected from the usual Ghostty resource directories.
  If yours live somewhere unusual, set `--themes-dir DIR` or the
  `GHOSTTY_THEMES_DIR` environment variable.

### Example `picker.toml`

```toml
version = 1
selected = "light:GitHub Light,dark:Tokyo Night"
scheme = "all"
excluded = ["Faded Mono"]
favorites = ["Dracula", "Tokyo Night"]
ranking_light = ["GitHub Light", "Solarized Light"]
ranking_dark = ["Tokyo Night", "Dracula", "Nord", "Gruvbox Dark"]

[filters]
min_contrast = 4.5

[[comparison]]
winner = "Tokyo Night"
loser = "Nord"
```

## How ranking works

Each decision is recorded as a `(winner, loser)` pair. Within each group
(light, dark) themes are ordered by **win rate**, then total wins, then fewest
losses. For a *completed* round-robin (where every theme plays the same number
of games) this is exactly a Copeland win count; mid-tournament, win rate keeps
partial standings sensible. Because comparisons never cross groups, the two
leaderboards are fully independent. Vetoing a theme removes it — and all
comparisons involving it — from its leaderboard entirely.

The number of matchups in a group of `n` themes is `n·(n−1)/2`, which grows
quickly. Restricting to one scheme, vetoing themes you'd never use, and the
minimum-contrast filter are the fastest ways to get to a finishable size; the
progress bar shows how many matchups remain and how many each veto would remove.

## Development

```bash
# Run the test suite (standard library unittest, no extra deps):
python -m unittest discover -s tests -t .
```

## License

MIT — see [LICENSE](LICENSE).
