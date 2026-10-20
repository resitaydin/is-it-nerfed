from __future__ import annotations

import dataclasses
import random
import unittest
from datetime import date, timedelta

import stats
from analyze import FIRM_WORSE as WORSE
from tests.synth import make_counts



def days(n):
    start = date(2026, 1, 1)
    return [start + timedelta(days=i) for i in range(n)]


def result(diff=0.0, p_worse=0.5, sessions=10, ratio=1.0, ratio_lo=0.5, ratio_hi=2.0):
    return stats.BootResult(diff, p_worse, 10.0, 10.0 + diff, 10, 10, 100, 100, sessions, sessions,
                            ratio, ratio_lo, ratio_hi)


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
        self.assertLessEqual(r.ratio_lo, 1)
        self.assertGreaterEqual(r.ratio_hi, 1)

    def test_empty_side_does_not_crash(self):
        r = stats.cluster_bootstrap([("a", 0, 0)], [("b", 1, 2)], n=50)
        self.assertEqual(r.base_rate, 0)
        self.assertEqual(r.recent_rate, 50.0)

    def test_counts_labeled_sessions_per_side(self):
        r = stats.cluster_bootstrap([("a", 0, 0), ("b", 1, 4)], [("c", 1, 2), ("d", 0, 3)], n=50)
        self.assertEqual((r.s_base, r.s_recent), (1, 2))

    def test_rate_ratio(self):
        r = stats.cluster_bootstrap(make_counts(40, 8, 0.05, 1), make_counts(40, 8, 0.15, 2), n=1000)
        self.assertAlmostEqual(r.ratio, r.recent_rate / r.base_rate, delta=0.1)
        self.assertLess(r.ratio_lo, r.ratio)
        self.assertGreater(r.ratio_hi, r.ratio)

    def test_rate_ratio_with_zero_base(self):
        r = stats.cluster_bootstrap([("a", 0, 10)], [("b", 2, 10)], n=200)
        self.assertGreater(r.ratio, 1)
        self.assertLess(r.ratio, float("inf"))

    def test_one_session_per_side_resamples_prompts(self):
        r = stats.cluster_bootstrap([("a", 1, 10)], [("b", 3, 10)], n=5000)
        self.assertEqual(r.diff, 20.0)
        self.assertLess(r.ratio_lo, r.ratio_hi)
        self.assertEqual(stats.verdict(r), "too_few_events")


class RatioBootstrapTest(unittest.TestCase):
    def test_same_rate_interval_holds_one(self):
        side = [("s%d" % i, 3, 100) for i in range(10)]
        ratio, lo, hi = stats.ratio_bootstrap(side, side, n=500)
        self.assertAlmostEqual(ratio, 1.0)
        self.assertLessEqual(lo, 1)
        self.assertGreaterEqual(hi, 1)

    def test_higher_recent_rate(self):
        base = [("b%d" % i, 1 + i % 2, 100) for i in range(10)]
        recent = [("r%d" % i, 6 + i % 3, 100) for i in range(10)]
        ratio, lo, hi = stats.ratio_bootstrap(base, recent, n=500)
        self.assertGreater(lo, 1)
        self.assertLess(lo, ratio)
        self.assertGreater(hi, ratio)


    def test_aa_false_rise_rate(self):
        # Behavior signals: event counts per session vary a lot, and a "rise" is a ratio interval above 1.
        def side(rng, n):
            out = []
            for i in range(n):
                tools, rate = rng.randint(20, 400), 0.01 * rng.lognormvariate(-0.5, 1)
                out.append(("s%d" % i, sum(rng.random() < rate for _ in range(tools)), tools))
            return out
        rng = random.Random(7)
        runs = 300
        rises = sum(stats.ratio_bootstrap(side(rng, 30), side(rng, 30), n=1000, seed=i)[1] > 1 for i in range(runs))
        self.assertLessEqual(rises / runs, 0.05)


class VerdictTest(unittest.TestCase):
    def test_verdict_table(self):
        rows = [
            (result(ratio_lo=0.8, ratio_hi=1.4), "no_change"),
            (result(ratio_lo=0.3, ratio_hi=3.0), "unclear"),
            (result(diff=4, ratio=2.2, ratio_lo=1.2, ratio_hi=4), "clearly_worse"),
            (result(diff=2, ratio=1.6, ratio_lo=1.1, ratio_hi=2.5), "slightly_worse"),
            (result(diff=-3, ratio=0.4, ratio_lo=0.2, ratio_hi=0.8), "better"),
            (result(diff=2, p_worse=0.85, ratio=1.4, ratio_lo=0.7, ratio_hi=2.8), "leaning_worse"),
            (result(diff=-2, p_worse=0.15, ratio=0.7, ratio_lo=0.3, ratio_hi=1.4), "leaning_better"),
            (result(p_worse=0.6, ratio_lo=0.6, ratio_hi=1.7), "unclear"),
        ]
        for r, expected in rows:
            self.assertEqual(stats.verdict(r), expected, r)

    def test_small_difference_alone_is_not_no_change(self):
        # A rare event can double and still move less than 1.5 points: that is not "no change".
        r = result(diff=0.4, p_worse=0.7, ratio=2.0, ratio_lo=0.4, ratio_hi=9)
        self.assertEqual(stats.verdict(r), "unclear")

    def test_too_few_events_gives_no_verdict(self):
        r = dataclasses.replace(result(ratio_lo=0.9, ratio_hi=1.1), k_base=3, k_recent=6)
        self.assertEqual(stats.verdict(r), "too_few_events")
        r = dataclasses.replace(r, k_recent=7)
        self.assertEqual(stats.verdict(r), "no_change")

    def test_worse_needs_the_absolute_floor(self):
        r = result(diff=1, p_worse=0.97, ratio=3.0, ratio_lo=1.2, ratio_hi=8)
        self.assertEqual(stats.verdict(r), "leaning_worse")

    def test_few_sessions_give_only_leaning(self):
        few = stats.MIN_SESSIONS - 1
        rows = [
            (result(p_worse=0.85, sessions=few, ratio_lo=0.9, ratio_hi=1.1), "leaning_worse"),
            (result(p_worse=0.6, sessions=few, ratio_lo=0.9, ratio_hi=1.1), "unclear"),
            (result(diff=12, p_worse=1.0, sessions=few, ratio=3, ratio_lo=2, ratio_hi=5),
             "leaning_worse"),
            (result(diff=-12, p_worse=0.0, sessions=few, ratio=0.3, ratio_lo=0.1,
                    ratio_hi=0.6), "leaning_better"),
        ]
        for r, expected in rows:
            self.assertEqual(stats.verdict(r), expected, r)


class CalibrationTest(unittest.TestCase):
    """Model-caused steering is rare: about 3.5% of prompts in the judge eval set."""

    def verdicts(self, base_rate, recent_rate, n_sessions=50, prompts_per=8):
        out = []
        for seed in range(200):
            base = make_counts(n_sessions, prompts_per, base_rate, seed * 2)
            recent = make_counts(n_sessions, prompts_per, recent_rate, seed * 2 + 1)
            out.append(stats.verdict(stats.cluster_bootstrap(base, recent, n=1000, seed=seed)))
        return out

    def share(self, verdicts, names):
        return sum(v in names for v in verdicts) / len(verdicts)

    def assert_false_alarms(self, rate, n_sessions, prompts_per):
        v = self.verdicts(rate, rate, n_sessions, prompts_per)
        self.assertLessEqual(self.share(v, WORSE), 0.08)
        self.assertLessEqual(self.share(v, ("better",)), 0.08)

    def test_aa_false_alarm_rate(self):
        self.assert_false_alarms(0.035, 50, 8)

    def test_aa_false_alarm_rate_common_event(self):
        self.assert_false_alarms(0.12, 40, 8)

    def test_aa_false_alarm_rate_3_sessions(self):
        self.assert_false_alarms(0.035, 3, 30)

    def test_aa_false_alarm_rate_5_sessions(self):
        self.assert_false_alarms(0.035, 5, 20)

    def test_aa_rarely_leans(self):
        v = self.verdicts(0.035, 0.035, n_sessions=100)
        self.assertLessEqual(self.share(v, ("leaning_worse", "leaning_better")), 0.45)

    def test_rare_event_at_real_size_never_claims_no_change(self):
        # Real logs: model-caused steering near 0.5% and at most 200 labeled prompts per window.
        v = self.verdicts(0.005, 0.005, n_sessions=25)
        self.assertLessEqual(self.share(v, ("no_change",)), 0.05)
        self.assertGreaterEqual(self.share(v, ("too_few_events",)), 0.5)

    def test_planted_doubling(self):
        v = self.verdicts(0.035, 0.07, n_sessions=100)
        self.assertGreaterEqual(self.share(v, WORSE), 0.70)
        self.assertLessEqual(self.share(v, ("no_change",)), 0.05)


if __name__ == "__main__":
    unittest.main()
