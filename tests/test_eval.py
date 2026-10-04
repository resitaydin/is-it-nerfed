from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import parse

EVAL = Path(__file__).resolve().parent.parent / "eval"
sys.path.insert(0, str(EVAL))

import make_set  # noqa: E402
import score  # noqa: E402


def prompt(uuid, text, after_interrupt=False):
    return parse.Prompt(uuid, "s", "p", datetime(2026, 1, 1, tzinfo=timezone.utc), text, "m", "1.0.0",
                        False, False, after_interrupt, "", [])


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

    def test_precision_recall(self):
        gold = ["m", "m", "u", "u"]
        pred = ["m", "u", "m", "u"]
        self.assertEqual(score.precision_recall(gold, pred, "m"), (0.5, 0.5))

    def test_precision_recall_no_positive(self):
        self.assertEqual(score.precision_recall(["u"], ["u"], "m"), (0.0, 0.0))


class ScoreLabelsTest(unittest.TestCase):
    def label(self, i, kind, cause="unclear"):
        return {"id": i, "kind": kind, "cause": cause}

    def test_score_counts_common_ids_only(self):
        gold = [self.label("1", "steering", "model"), self.label("2", "other"), self.label("3", "other")]
        pred = [self.label("1", "steering", "model"), self.label("2", "other"), self.label("9", "other")]
        result = score.score(gold, pred)
        self.assertEqual(result["common"], 2)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(result["kappa_steering"], 1.0)
        self.assertEqual(result["kappa_cause"], 1.0)
        self.assertEqual(result["precision"], 1.0)
        self.assertEqual(result["recall"], 1.0)


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


if __name__ == "__main__":
    unittest.main()
