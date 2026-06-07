"""Pairwise comparison bookkeeping and ranking.

The user compares themes two at a time. Each decision is recorded as a
``(winner, loser)`` pair. From the full set of recorded comparisons we derive:

* a round-robin schedule of every unordered pair that still needs a verdict,
* a ranking using a Copeland-style win count, ordered primarily by win rate so
  that partial progress still yields a sensible ranking.

Pairs are identified by an unordered key so that comparing (A, B) and (B, A)
are treated as the same matchup.
"""

from __future__ import annotations

from dataclasses import dataclass


def pair_key(a: str, b: str) -> tuple[str, str]:
    """Order-independent identity for a matchup."""
    return (a, b) if a <= b else (b, a)


def all_pairs(themes: list[str]) -> list[tuple[str, str]]:
    """Every unordered pair, scheduled so themes are spread out.

    Uses the circle method for round-robin scheduling: in each round every
    theme is paired at most once, which keeps the same theme from appearing in
    several consecutive matchups.
    """
    players = list(dict.fromkeys(themes))  # de-dupe, preserve order
    n = len(players)
    if n < 2:
        return []

    bye = None
    if n % 2 == 1:
        bye = object()  # sentinel; pairings with the bye are dropped
        players = players + [bye]
        n += 1

    half = n // 2
    rotating = players[1:]
    fixed = players[0]
    schedule: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _ in range(n - 1):
        round_players = [fixed] + rotating
        for i in range(half):
            a = round_players[i]
            b = round_players[n - 1 - i]
            if a is bye or b is bye:
                continue
            key = pair_key(a, b)  # type: ignore[arg-type]
            if key not in seen:
                seen.add(key)
                schedule.append((a, b))  # type: ignore[arg-type]
        # Rotate all but the fixed element.
        rotating = [rotating[-1]] + rotating[:-1]
    return schedule


def completed_keys(comparisons: list[tuple[str, str]]) -> set[tuple[str, str]]:
    return {pair_key(w, l) for w, l in comparisons}


def remaining_pairs(
    active: list[str], comparisons: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Scheduled pairs among ``active`` themes that have no verdict yet."""
    done = completed_keys(comparisons)
    result = []
    for a, b in all_pairs(active):
        if pair_key(a, b) not in done:
            result.append((a, b))
    return result


def total_pairs(active: list[str]) -> int:
    n = len(set(active))
    return n * (n - 1) // 2


def remaining_pairs_in_groups(
    groups: dict[str, list[str]], comparisons: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Remaining matchups within each group, interleaved across groups.

    Each group is paired only against itself (never cross-group), and the
    groups' remaining pairs are interleaved round-robin so a mixed session
    alternates between, say, dark and light matchups rather than finishing one
    group before starting the other.
    """
    per_group = [remaining_pairs(members, comparisons) for members in groups.values()]
    out: list[tuple[str, str]] = []
    longest = max((len(p) for p in per_group), default=0)
    for i in range(longest):
        for pairs in per_group:
            if i < len(pairs):
                out.append(pairs[i])
    return out


def total_pairs_in_groups(groups: dict[str, list[str]]) -> int:
    return sum(total_pairs(members) for members in groups.values())


def completed_pairs_in_groups(
    groups: dict[str, list[str]], comparisons: list[tuple[str, str]]
) -> int:
    return sum(completed_pairs(members, comparisons) for members in groups.values())


def completed_pairs(active: list[str], comparisons: list[tuple[str, str]]) -> int:
    """How many of the active matchups already have a verdict."""
    active_set = set(active)
    done = completed_keys(comparisons)
    count = 0
    for a, b in done:
        if a in active_set and b in active_set:
            count += 1
    return count


@dataclass
class RankRow:
    name: str
    wins: int
    losses: int

    @property
    def games(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0

    @property
    def score(self) -> int:
        """Copeland score: wins minus losses."""
        return self.wins - self.losses


def compute_ranking(
    themes: list[str], comparisons: list[tuple[str, str]]
) -> list[RankRow]:
    """Rank ``themes`` from recorded comparisons.

    Only comparisons whose participants are both in ``themes`` are counted, so
    excluding a theme cleanly removes its influence. Ordering is by win rate,
    then total wins, then fewest losses, then name -- which is equivalent to a
    pure win count for a completed round-robin (where everyone plays the same
    number of games) but stays sensible mid-tournament.
    """
    theme_set = set(themes)
    rows = {name: RankRow(name=name, wins=0, losses=0) for name in theme_set}
    for winner, loser in comparisons:
        if winner in theme_set and loser in theme_set and winner != loser:
            rows[winner].wins += 1
            rows[loser].losses += 1

    return sorted(
        rows.values(),
        key=lambda r: (-r.win_rate, -r.wins, r.losses, r.name.lower()),
    )


def ranking_names(themes: list[str], comparisons: list[tuple[str, str]]) -> list[str]:
    return [row.name for row in compute_ranking(themes, comparisons)]
