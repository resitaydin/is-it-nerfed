from __future__ import annotations

import unittest
from datetime import date, timedelta

import stats
from tests.synth import make_counts

WORSE = ("slightly_worse", "clearly_worse")
LEANING = ("leaning_worse", "leaning_better")


def days(n):
    start = date(2026, 1, 1)
    return [start + timedelta(days=i) for i in range(n)]


def result(lo, hi, diff=0.0, p_worse=0.5, sessions=10):
    return stats.BootResult(diff, lo, hi, p_worse, 10.0, 10.0 + diff, 100, 100, sessions, sessions)


class WindowsTest(unittest.TestCase):
    def test_windows_too_early(self):
        self.assertIsNone(stats.make_windows(days(2)))

    def test_windows_halves_odd(self):
        d = days(7)
        base, recent = stats.make_windows(d)
        self.assertEqual(base, (d[0], d[2]))
        self.assertEqual(recent, (d[4], d[6]))

    def test_windows_fixed_14(self):
        d = days(30)
        base, recent = stats.make_windows(d)
        self.assertEqual(base, (d[0], d[13]))
        self.assertEqual(recent, (d[-14], d[-1]))


class BootstrapTest(unittest.TestCase):
    def test_bootstrap_identical_windows(self):
        counts = make_counts(30, 8, 0.12, 1)
        r = stats.cluster_bootstrap(counts, counts, n=500)
        self.assertEqual(r.diff, 0)
        self.assertLessEqual(r.lo, 0)
        self.assertGreaterEqual(r.hi, 0)

    def test_empty_side_does_not_crash(self):
        r = stats.cluster_bootstrap([("a", 0, 0)], [("b", 1, 2)], n=50)
        self.assertEqual(r.base_rate, 0)
        self.assertEqual(r.recent_rate, 50.0)

    def test_counts_labeled_sessions_per_side(self):
        r = stats.cluster_bootstrap([("a", 0, 0), ("b", 1, 4)], [("c", 1, 2), ("d", 0, 3)], n=50)
        self.assertEqual((r.s_base, r.s_recent), (1, 2))

    def test_one_session_per_side_resamples_prompts(self):
        r = stats.cluster_bootstrap([("a", 1, 10)], [("b", 3, 10)], n=5000)
        self.assertEqual(r.diff, 20.0)
        self.assertLess(r.lo, r.hi)
        self.assertIn(stats.verdict(r), LEANING)


class VerdictTest(unittest.TestCase):
    def test_verdict_table(self):
        rows = [
            (result(lo=1, hi=4), "no_change"),
            (result(lo=-5, hi=5), "no_change"),
            (result(lo=6, hi=20, diff=12), "clearly_worse"),
            (result(lo=2, hi=20, diff=8), "slightly_worse"),
            (result(lo=-20, hi=-6, diff=-12), "better"),
            (result(lo=-8, hi=12, diff=2, p_worse=0.6), "leaning_worse"),
            (result(lo=-12, hi=8, diff=-2, p_worse=0.4), "leaning_better"),
        ]
        for r, expected in rows:
            self.assertEqual(stats.verdict(r), expected, r)

    def test_few_sessions_give_only_leaning(self):
        few = stats.MIN_SESSIONS - 1
        rows = [
            (result(lo=1, hi=4, p_worse=0.7, sessions=few), "leaning_worse"),
            (result(lo=6, hi=20, diff=12, p_worse=1.0, sessions=few), "leaning_worse"),
            (result(lo=-20, hi=-6, diff=-12, p_worse=0.0, sessions=few), "leaning_better"),
        ]
        for r, expected in rows:
            self.assertEqual(stats.verdict(r), expected, r)


class CalibrationTest(unittest.TestCase):
    def verdicts(self, base_rate, recent_rate, n_sessions=40, prompts_per=8):
        out = []
        for seed in range(200):
            base = make_counts(n_sessions, prompts_per, base_rate, seed * 2)
            recent = make_counts(n_sessions, prompts_per, recent_rate, seed * 2 + 1)
            out.append(stats.verdict(stats.cluster_bootstrap(base, recent, n=1000, seed=seed)))
        return out

    def assert_false_alarms(self, n_sessions, prompts_per):
        v = self.verdicts(0.12, 0.12, n_sessions, prompts_per)
        self.assertLessEqual(sum(x in WORSE for x in v) / 200, 0.08)
        self.assertLessEqual(sum(x == "better" for x in v) / 200, 0.08)

    def test_aa_false_alarm_rate(self):
        self.assert_false_alarms(40, 8)

    def test_aa_false_alarm_rate_3_sessions(self):
        self.assert_false_alarms(3, 30)

    def test_aa_false_alarm_rate_5_sessions(self):
        self.assert_false_alarms(5, 20)

    def test_planted_nerf_power(self):
        v = self.verdicts(0.12, 0.22)
        self.assertGreaterEqual(sum(x in WORSE for x in v) / 200, 0.80)


if __name__ == "__main__":
    unittest.main()
