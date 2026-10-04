from __future__ import annotations

import unittest
from datetime import date, timedelta

import stats
from tests.synth import make_counts

WORSE = ("slightly_worse", "clearly_worse")


def days(n):
    start = date(2026, 1, 1)
    return [start + timedelta(days=i) for i in range(n)]


def result(lo, hi, diff=0.0, p_worse=0.5):
    return stats.BootResult(diff, lo, hi, p_worse, 10.0, 10.0 + diff, 100, 100)


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


class CalibrationTest(unittest.TestCase):
    def verdicts(self, base_rate, recent_rate):
        out = []
        for seed in range(200):
            base = make_counts(40, 8, base_rate, seed * 2)
            recent = make_counts(40, 8, recent_rate, seed * 2 + 1)
            out.append(stats.verdict(stats.cluster_bootstrap(base, recent, n=1000, seed=seed)))
        return out

    def test_aa_false_alarm_rate(self):
        v = self.verdicts(0.12, 0.12)
        self.assertLessEqual(sum(x in WORSE for x in v) / 200, 0.08)
        self.assertLessEqual(sum(x == "better" for x in v) / 200, 0.08)

    def test_planted_nerf_power(self):
        v = self.verdicts(0.12, 0.22)
        self.assertGreaterEqual(sum(x in WORSE for x in v) / 200, 0.80)


if __name__ == "__main__":
    unittest.main()
