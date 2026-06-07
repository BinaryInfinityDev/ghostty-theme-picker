import unittest

from ghostty_theme_picker.ranking import (
    all_pairs,
    compute_ranking,
    completed_pairs,
    pair_key,
    ranking_names,
    remaining_pairs,
    total_pairs,
)


class PairTests(unittest.TestCase):
    def test_pair_key_is_order_independent(self):
        self.assertEqual(pair_key("a", "b"), pair_key("b", "a"))

    def test_all_pairs_complete_round_robin(self):
        themes = ["a", "b", "c", "d", "e"]
        pairs = all_pairs(themes)
        self.assertEqual(len(pairs), total_pairs(themes))
        keys = {pair_key(a, b) for a, b in pairs}
        self.assertEqual(len(keys), len(pairs))  # no duplicates
        # Every unordered pair present.
        import itertools

        expected = {pair_key(a, b) for a, b in itertools.combinations(themes, 2)}
        self.assertEqual(keys, expected)

    def test_all_pairs_even_count(self):
        themes = ["a", "b", "c", "d"]
        self.assertEqual(len(all_pairs(themes)), 6)

    def test_all_pairs_trivial(self):
        self.assertEqual(all_pairs([]), [])
        self.assertEqual(all_pairs(["a"]), [])

    def test_dedupes_input(self):
        self.assertEqual(len(all_pairs(["a", "a", "b"])), 1)


class RemainingTests(unittest.TestCase):
    def test_remaining_excludes_done(self):
        themes = ["a", "b", "c"]
        done = [("a", "b")]
        remaining = remaining_pairs(themes, done)
        keys = {pair_key(*p) for p in remaining}
        self.assertNotIn(pair_key("a", "b"), keys)
        self.assertEqual(len(remaining), 2)

    def test_completed_pairs_counts_only_active(self):
        comparisons = [("a", "b"), ("a", "x")]  # x not active
        self.assertEqual(completed_pairs(["a", "b", "c"], comparisons), 1)

    def test_reverse_order_counts_as_done(self):
        remaining = remaining_pairs(["a", "b"], [("b", "a")])
        self.assertEqual(remaining, [])


class RankingTests(unittest.TestCase):
    def test_simple_ordering(self):
        themes = ["a", "b", "c"]
        # a beats b and c; b beats c.
        comparisons = [("a", "b"), ("a", "c"), ("b", "c")]
        self.assertEqual(ranking_names(themes, comparisons), ["a", "b", "c"])

    def test_win_rate_orders_partial(self):
        themes = ["a", "b", "c"]
        # a: 1-0, b: 1-1, c: 0-1
        comparisons = [("a", "b"), ("b", "c")]
        names = ranking_names(themes, comparisons)
        self.assertEqual(names[0], "a")
        self.assertEqual(names[-1], "c")

    def test_excluded_theme_not_counted(self):
        themes = ["a", "b"]  # c excluded from the set
        comparisons = [("c", "a"), ("c", "b"), ("a", "b")]
        rows = {r.name: r for r in compute_ranking(themes, comparisons)}
        self.assertNotIn("c", rows)
        # a's loss to c is ignored since c is not in the active set.
        self.assertEqual(rows["a"].losses, 0)
        self.assertEqual(rows["a"].wins, 1)

    def test_rank_row_metrics(self):
        rows = {r.name: r for r in compute_ranking(["a", "b"], [("a", "b")])}
        self.assertEqual(rows["a"].wins, 1)
        self.assertEqual(rows["a"].win_rate, 1.0)
        self.assertEqual(rows["a"].score, 1)
        self.assertEqual(rows["b"].score, -1)


if __name__ == "__main__":
    unittest.main()
