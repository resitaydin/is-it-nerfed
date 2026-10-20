from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

import sample
from tests import make_prompt


class SelectTest(unittest.TestCase):
    def test_select_cap_round_robin(self):
        prompts = [make_prompt("d%d-%d" % (d, i), day=d) for d in range(1, 11) for i in range(50)]
        window = (date(2026, 9, 1), date(2026, 9, 10))
        picked = sample.select(prompts, window, cap=200)
        self.assertEqual(len(picked), 200)
        for d in range(1, 11):
            self.assertEqual(sum(1 for p in picked if p.timestamp.day == d), 20)
        again = sample.select(prompts, window, cap=200)
        self.assertEqual([p.uuid for p in picked], [p.uuid for p in again])

    def test_select_skips_ineligible(self):
        prompts = [
            make_prompt("ok"),
            make_prompt("first", is_first=True), make_prompt("cmd", is_command=True),
            make_prompt("late", day=20),
        ]
        picked = sample.select(prompts, (date(2026, 9, 1), date(2026, 9, 10)))
        self.assertEqual([p.uuid for p in picked], ["ok"])


class BlindTest(unittest.TestCase):
    def test_blind(self):
        out = sample.blind("Opus 5.5 on 2026-09-24 got nerfed, v2.1.285, claude-opus-5-5")
        for word in ("Opus", "2026", "nerfed", "2.1.285", "claude-"):
            self.assertNotIn(word, out)

    def test_blind_dates_times_and_words(self):
        out = sample.blind("On Sep 24 and 24 September 2026 at 10:15:30 it got DUMBER, Degraded")
        for word in ("Sep", "September", "2026", "10:15", "DUMBER", "Degraded"):
            self.assertNotIn(word, out)

    def test_blind_model_names_any_case_and_separator(self):
        cases = {
            "opus 4.7 is slow": "[x] is slow",
            "try sonnet-4-5 now": "try [x] now",
            "Opus4.7 broke it": "[x] broke it",
            "HAIKU 5 and Fable": "[x] and [x]",
        }
        for text, expected in cases.items():
            self.assertEqual(sample.blind(text), expected)

    def test_blind_other_date_and_version_forms(self):
        out = sample.blind("see 20261021_add_index.py from 10/21/2026, v2.1 and Claude 4 too")
        for word in ("20261021", "10/21", "v2.1", "Claude 4"):
            self.assertNotIn(word, out)

    def test_blind_every_nerf_word(self):
        self.assertEqual(sample.blind("Nerfs, nerfing and nerf"), "[x], [x] and [x]")

    def test_blind_keeps_words_that_only_start_with_a_month(self):
        for text in ("Market 5 items", "Use 2 Markdown files", "Decode 3 times", "Mayor 9"):
            self.assertEqual(sample.blind(text), text)


class BuildItemTest(unittest.TestCase):
    def test_build_item_truncation(self):
        history = ["h%d " % i + "x" * 600 for i in range(10)]
        p = make_prompt("u1", prev_agent_text="a" * 3500 + "END" * 500, history=history)
        item = sample.build_item(p)
        self.assertEqual(item["id"], sample.item_id("u1"))
        self.assertEqual(len(item["previous_agent_reply"]), 1500)
        self.assertTrue(item["previous_agent_reply"].endswith("END"))
        self.assertLessEqual(sum(len(e) for e in item["earlier_prompts"]), 2000)
        self.assertEqual(len(item["earlier_prompts"]), 3)
        self.assertTrue(item["earlier_prompts"][0].startswith("h0"))

    def test_build_item_cuts_long_newest_earlier_prompt(self):
        p = make_prompt("u1", history=["y" * 2500 + "TAIL", "older"])
        earlier = sample.build_item(p)["earlier_prompts"]
        self.assertEqual(len(earlier), 1)
        self.assertEqual(len(earlier[0]), 2000)
        self.assertTrue(earlier[0].endswith("TAIL"))

    def test_build_item_blinds_all_fields(self):
        p = make_prompt(text="it got nerfed", prev_agent_text="Opus 5", history=["on 2026-09-01"])
        item = sample.build_item(p)
        self.assertEqual(item["prompt"], "it got [x]")
        self.assertEqual(item["previous_agent_reply"], "[x]")
        self.assertEqual(item["earlier_prompts"], ["on [x]"])


class WriteBatchesTest(unittest.TestCase):
    def test_write_batches_hides_anchor_gold(self):
        items = [{"id": "i%d" % n, "prompt": "p", "previous_agent_reply": "", "earlier_prompts": []}
                 for n in range(45)]
        anchors = [{"anchor_id": "a%d" % n, "prompt": "p", "previous_agent_reply": "",
                    "earlier_prompts": [], "gold_kind": "steering", "gold_cause": "model"}
                   for n in range(30)]
        with tempfile.TemporaryDirectory() as tmp:
            paths = sample.write_batches(items, anchors, Path(tmp))
            self.assertEqual([p.name for p in paths], ["batch-001.jsonl", "batch-002.jsonl"])
            lines = [json.loads(l) for p in paths for l in p.read_text().splitlines()]
        self.assertEqual(len(lines), 75)
        for line in lines:
            self.assertEqual(set(line), {"id", "prompt", "previous_agent_reply", "earlier_prompts"})
        self.assertIn(sample.item_id("anchor-a0"), {l["id"] for l in lines})

    def test_estimate_tokens(self):
        items = [{"id": "x"}]
        self.assertEqual(sample.estimate_tokens(items, 2), len(json.dumps(items[0])) // 4 + 40000 + 400)


if __name__ == "__main__":
    unittest.main()
