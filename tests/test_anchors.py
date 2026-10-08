from __future__ import annotations

import unittest
from collections import Counter

import jsonl
import labels
import sample
from tests import SCRIPTS

ANCHORS_PATH = SCRIPTS.parent / "anchors.jsonl"


def load_anchors():
    return jsonl.read(ANCHORS_PATH)


def perfect_labels(anchors):
    return {sample.anchor_item_id(a): {"kind": a["gold_kind"], "cause": a["gold_cause"]}
            for a in anchors}


class AnchorSetTest(unittest.TestCase):
    def test_anchor_count_and_mix(self):
        anchors = load_anchors()
        self.assertEqual(len(anchors), 30)
        self.assertEqual(len({a["anchor_id"] for a in anchors}), 30)
        mix = Counter((a["gold_kind"], a["gold_cause"]) for a in anchors)
        self.assertEqual(mix, Counter({("new_work", "unclear"): 8, ("steering", "model"): 10,
                                       ("steering", "user"): 6, ("steering", "unclear"): 2,
                                       ("other", "unclear"): 4}))
        for a in anchors:
            self.assertIn(a["gold_steering_type"], labels.STEERING_TYPES)
            self.assertEqual(a["gold_steering_type"] is None, a["gold_kind"] != "steering")

    def test_anchor_evidence_possible(self):
        for a in load_anchors():
            self.assertTrue(a["prompt"].strip(), a["anchor_id"])
            self.assertIsInstance(a["previous_agent_reply"], str)
            self.assertIsInstance(a["earlier_prompts"], list)

    def test_anchors_survive_blinding(self):
        # Real items are blinded; an anchor that blinding would change is easy to spot.
        for a in load_anchors():
            for text in [a["prompt"], a["previous_agent_reply"]] + a["earlier_prompts"]:
                self.assertEqual(sample.blind(text), text, a["anchor_id"])

    def test_anchor_agreement(self):
        anchors = load_anchors()
        good = perfect_labels(anchors)
        self.assertEqual(labels.anchor_agreement(good, anchors), 1.0)
        flipped = dict(good)
        model_ids = [sample.anchor_item_id(a) for a in anchors
                     if a["gold_kind"] == "steering" and a["gold_cause"] == "model"]
        for key in model_ids[:7]:
            flipped[key] = dict(flipped[key], cause="unclear")
        self.assertLess(labels.anchor_agreement(flipped, anchors), 0.8)

    def test_anchor_agreement_ignores_missing_anchors(self):
        anchors = load_anchors()
        good = perfect_labels(anchors)
        for key in list(good)[:7]:
            del good[key]
        self.assertEqual(labels.anchor_agreement(good, anchors), 1.0)

    def test_anchor_agreement_not_measured_below_min_anchors(self):
        anchors = load_anchors()
        good = perfect_labels(anchors)
        few = {k: good[k] for k in list(good)[:labels.MIN_ANCHORS - 1]}
        self.assertIsNone(labels.anchor_agreement(few, anchors))
        self.assertIsNone(labels.anchor_agreement({}, anchors))

    def test_anchor_agreement_rules(self):
        anchors = ([{"anchor_id": "s%d" % i, "gold_kind": "steering", "gold_cause": "model"} for i in range(10)]
                   + [{"anchor_id": "u%d" % i, "gold_kind": "steering", "gold_cause": "user"} for i in range(5)]
                   + [{"anchor_id": "n%d" % i, "gold_kind": "new_work", "gold_cause": "unclear"} for i in range(5)])
        # Only the model-caused label counts: a user/unclear swap or a new_work/other swap agrees.
        labels_by_id = {}
        for a in anchors:
            model = a["gold_cause"] == "model"
            labels_by_id[sample.anchor_item_id(a)] = (
                {"kind": "steering", "cause": "user"} if model
                else {"kind": "other" if a["gold_kind"] == "new_work" else "steering", "cause": "unclear"})
        self.assertEqual(labels.anchor_agreement(labels_by_id, anchors), 0.5)

if __name__ == "__main__":
    unittest.main()
