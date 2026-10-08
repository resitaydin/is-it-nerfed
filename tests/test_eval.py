from __future__ import annotations

import sys
import unittest
from pathlib import Path

from tests import make_prompt

EVAL = Path(__file__).resolve().parent.parent / "eval"
sys.path.insert(0, str(EVAL))

import make_set  # noqa: E402
import score  # noqa: E402


def prompt(uuid, text, after_interrupt=False, history=()):
    return make_prompt(uuid, text=text, after_interrupt=after_interrupt, history=list(history))


class KappaTest(unittest.TestCase):
    def test_kappa_perfect(self):
        self.assertEqual(score.cohen_kappa(["a", "b", "a"], ["a", "b", "a"]), 1.0)

    def test_kappa_chance(self):
        # 2x2 table: both yes 20, a yes/b no 5, a no/b yes 10, both no 15 -> kappa 0.4
        a = ["y"] * 25 + ["n"] * 25
        b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
        self.assertAlmostEqual(score.cohen_kappa(a, b), 0.4, places=3)

    def test_kappa_one_class(self):
        self.assertEqual(score.cohen_kappa(["a", "a"], ["a", "a"]), 1.0)
        self.assertEqual(score.cohen_kappa(["a", "a"], ["b", "b"]), 0.0)


class AgreementTest(unittest.TestCase):
    def test_ac1_perfect_and_skewed(self):
        self.assertEqual(score.gwet_ac1([True, False], [True, False]), 1.0)
        # 1 disagreement in 100 rare-class items: kappa is low, AC1 stays high.
        a = [True] + [False] * 99
        b = [False] * 100
        self.assertLess(score.cohen_kappa(a, b), 0.1)
        self.assertGreater(score.gwet_ac1(a, b), 0.98)

    def test_kappa_interval_contains_estimate(self):
        a = [True] * 10 + [False] * 90
        b = [True] * 8 + [False] * 2 + [False] * 89 + [True]
        lo, hi = score.kappa_interval(a, b)
        self.assertLessEqual(lo, score.cohen_kappa(a, b))
        self.assertGreaterEqual(hi, score.cohen_kappa(a, b))
        self.assertLess(lo, hi)


class ScoreLabelsTest(unittest.TestCase):
    def label(self, i, kind, cause="unclear"):
        return {"id": i, "kind": kind, "cause": cause}

    def test_score_counts_common_ids_only(self):
        gold = [self.label("1", "steering", "model"), self.label("2", "other"), self.label("3", "other")]
        pred = [self.label("1", "steering", "model"), self.label("2", "other"), self.label("9", "other")]
        result = score.score(gold, pred)
        self.assertEqual(result["common"], 2)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(result["kappa_model"], 1.0)
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 1.0)

    def test_score_model_caused_counts(self):
        gold = ([self.label("m%d" % i, "steering", "model") for i in range(4)]
                + [self.label("u%d" % i, "steering", "user") for i in range(4)]
                + [self.label("o%d" % i, "other") for i in range(12)])
        pred = ([self.label("m0", "steering", "model"), self.label("m1", "steering", "model"),
                 self.label("m2", "steering", "unclear"), self.label("m3", "new_work")]
                # A user/unclear swap does not change the model-caused label.
                + [self.label("u%d" % i, "steering", "unclear") for i in range(4)]
                + [self.label("o0", "steering", "model")]
                + [self.label("o%d" % i, "other") for i in range(1, 12)])
        result = score.score(gold, pred)
        self.assertEqual((result["tp"], result["fp"], result["fn"]), (2, 1, 2))
        self.assertEqual(result["positives"], 4)
        self.assertAlmostEqual(result["false_alarm_rate"], 1 / 16)
        self.assertAlmostEqual(result["recall"], 0.5)

    def test_gate(self):
        ok = {"positives": 30, "kappa_model": 0.75, "false_alarm_rate": 0.01}
        self.assertTrue(score.passes(ok))
        self.assertFalse(score.passes(dict(ok, positives=29)))
        self.assertFalse(score.passes(dict(ok, kappa_model=0.69)))
        self.assertFalse(score.passes(dict(ok, false_alarm_rate=0.011)))


class MakeSetTest(unittest.TestCase):
    def test_pool_split(self):
        prompts = [prompt("n%d" % i, "No, that is wrong") for i in range(5)]
        prompts += [prompt("i1", "carry on", after_interrupt=True)]
        prompts += [prompt("o%d" % i, "add a test") for i in range(10)]
        picked, pool = make_set.pick(prompts, 8, seed=1)
        self.assertEqual(len(picked), 8)
        self.assertEqual(pool, 4)
        self.assertEqual(len({p.uuid for p in picked}), 8)

    def test_short_pool_filled_from_other(self):
        prompts = [prompt("n1", "stop"), prompt("o1", "a"), prompt("o2", "b"), prompt("o3", "c")]
        picked, pool = make_set.pick(prompts, 4, seed=1)
        self.assertEqual(len(picked), 4)
        self.assertEqual(pool, 1)

    def test_negation_start(self):
        self.assertTrue(make_set.is_candidate(prompt("a", "  Don't do that")))
        self.assertFalse(make_set.is_candidate(prompt("a", "nothing here")))

    def test_model_hint_phrases(self):
        for text in ["I asked for snake_case", "it still fails", "you didn't run the tests",
                     "same error as before", "that does not work"]:
            self.assertTrue(make_set.is_model_hint(prompt("a", text)), text)
        self.assertFalse(make_set.is_model_hint(prompt("a", "add a logout button")))

    def test_model_hint_repeated_instruction(self):
        earlier = "push your changes then merge it gracefully."
        self.assertTrue(make_set.is_model_hint(prompt("a", "push your changes then merge it gracefully",
                                                      history=["other", earlier])))
        self.assertFalse(make_set.is_model_hint(prompt("a", "ok", history=["ok"])))

    def test_pick_hints_skips_known_ids(self):
        prompts = [prompt("h%d" % i, "it still fails") for i in range(5)] + [prompt("o", "add a test")]
        picked = make_set.pick_hints(prompts, 10, seed=1, skip={"h0"})
        self.assertEqual(sorted(p.uuid for p in picked), ["h1", "h2", "h3", "h4"])


if __name__ == "__main__":
    unittest.main()
