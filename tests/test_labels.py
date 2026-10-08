from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import jsonl
import labels

ITEM = {"id": "a", "prompt": "No, use the  other file", "previous_agent_reply": "I edited x.py",
        "earlier_prompts": ["fix login"]}


def label(**kw):
    base = {"id": "a", "kind": "steering", "cause": "model", "steering_type": "correction",
            "evidence": "use the other file", "reasoning": "r"}
    base.update(kw)
    return base


class ValidTest(unittest.TestCase):
    def test_valid_accepts_whitespace_variant(self):
        self.assertTrue(labels.valid(label(evidence="use  the\nother   file"), ITEM))

    def test_valid_rejects_fake_evidence(self):
        self.assertFalse(labels.valid(label(evidence="never said this"), ITEM))
        self.assertFalse(labels.valid(label(evidence="  "), ITEM))

    def test_valid_checks_enums_and_null_steering_type(self):
        self.assertFalse(labels.valid(label(kind="bogus"), ITEM))
        self.assertFalse(labels.valid(label(cause="bogus"), ITEM))
        self.assertFalse(labels.valid(label(steering_type="bogus"), ITEM))
        self.assertTrue(labels.valid(label(kind="other", steering_type=None), ITEM))

    def test_valid_requires_text_reasoning(self):
        self.assertFalse(labels.valid(label(reasoning=None), ITEM))
        self.assertFalse(labels.valid(label(reasoning=["r"]), ITEM))
        no_reasoning = label()
        del no_reasoning["reasoning"]
        self.assertFalse(labels.valid(no_reasoning, ITEM))

    def test_is_model_steering(self):
        self.assertTrue(labels.is_model_steering(label()))
        self.assertFalse(labels.is_model_steering(label(cause="user")))
        self.assertFalse(labels.is_model_steering(label(kind="other")))


class ReadLabelsTest(unittest.TestCase):
    def test_read_labels_unknown_and_duplicate_ids(self):
        items = {"a": ITEM, "b": dict(ITEM, id="b"), "c": dict(ITEM, id="c")}
        lines = [
            json.dumps(label(id="zzz")),
            json.dumps(label(id="a", evidence="fake")),
            json.dumps(label(id="a", cause="user")),
            json.dumps(label(id="a", cause="model")),
            "{broken",
            json.dumps(label(id="b")),
            json.dumps(label(id=["a"])),
            json.dumps(label(id="c", kind=["steering"])),
            json.dumps(label(id="c", cause={"x": 1})),
            json.dumps(label(id="c", steering_type=["correction"])),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.jsonl"
            path.write_text("\n".join(lines) + "\n")
            found, missing = labels.read_labels([path, Path(tmp) / "none.jsonl"], items)
        self.assertEqual(set(found), {"a", "b"})
        self.assertEqual(found["a"]["cause"], "user")
        self.assertEqual(missing, ["c"])


class CacheTest(unittest.TestCase):
    def test_cache_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache" / "labels.jsonl"
            self.assertEqual(labels.load_cache(path), {})
            jsonl.append(path, [{"uuid": "u1", "kind": "other"}])
            jsonl.append(path, [{"uuid": "u2", "kind": "steering"}])
            path.write_text(path.read_text() + "{truncated")
            self.assertEqual(set(labels.load_cache(path)), {"u1", "u2"})


if __name__ == "__main__":
    unittest.main()
