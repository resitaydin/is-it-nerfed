from __future__ import annotations

import json
import unittest
from collections import Counter

import labels
import sample
from tests import SCRIPTS

ANCHORS_PATH = SCRIPTS.parent / "anchors.jsonl"


def load_anchors():
    return [json.loads(line) for line in ANCHORS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def perfect_labels(anchors):
    return {sample.item_id("anchor-" + a["anchor_id"]): {"kind": a["gold_kind"], "cause": a["gold_cause"]}
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
        for key in list(flipped)[:7]:
            row = flipped[key]
            flipped[key] = {"kind": "other" if row["kind"] != "other" else "new_work", "cause": row["cause"]}
        self.assertLess(labels.anchor_agreement(flipped, anchors), 0.8)

    def test_anchor_agreement_rules(self):
        anchors = [{"anchor_id": "s", "gold_kind": "steering", "gold_cause": "model"},
                   {"anchor_id": "n", "gold_kind": "new_work", "gold_cause": "unclear"}]
        sid, nid = sample.item_id("anchor-s"), sample.item_id("anchor-n")
        # Cause matters only for steering; a missing label is a disagreement.
        self.assertEqual(labels.anchor_agreement({nid: {"kind": "new_work", "cause": "user"}}, anchors), 0.5)
        self.assertEqual(labels.anchor_agreement({sid: {"kind": "steering", "cause": "user"},
                                                  nid: {"kind": "new_work", "cause": "user"}}, anchors), 0.5)


if __name__ == "__main__":
    unittest.main()
