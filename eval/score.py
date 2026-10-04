"""Score judge labels (pred) against hand-corrected labels (gold)."""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "plugins/is-it-nerfed/skills/is-it-nerfed/scripts"))

import labels  # noqa: E402

GATE = 0.7


def cohen_kappa(a: list, b: list) -> float:
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(count_a[c] * count_b[c] for c in count_a) / (n * n)
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def precision_recall(gold: List[str], pred: List[str], positive: str) -> Tuple[float, float]:
    hits = sum(g == positive and p == positive for g, p in zip(gold, pred))
    predicted = sum(p == positive for p in pred)
    actual = sum(g == positive for g in gold)
    return (hits / predicted if predicted else 0.0, hits / actual if actual else 0.0)


def _model_steering(label: dict) -> str:
    return "model_steering" if labels.is_model_steering(label) else "other"


def score(gold_rows: List[dict], pred_rows: List[dict]) -> Dict[str, float]:
    gold = {r["id"]: r for r in gold_rows}
    pred = {r["id"]: r for r in pred_rows}
    common = [i for i in gold if i in pred]
    steering = [i for i in common if gold[i]["kind"] == "steering"]
    p, r = precision_recall([_model_steering(gold[i]) for i in common],
                            [_model_steering(pred[i]) for i in common], "model_steering")
    return {
        "common": len(common),
        "skipped": len(set(gold) | set(pred)) - len(common),
        "kappa_steering": cohen_kappa([gold[i]["kind"] == "steering" for i in common],
                                      [pred[i]["kind"] == "steering" for i in common]),
        "kappa_cause": cohen_kappa([gold[i]["cause"] for i in steering],
                                   [pred[i]["cause"] for i in steering]) if steering else 0.0,
        "steering_items": len(steering),
        "precision": p,
        "recall": r,
    }


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("gold", type=Path)
    parser.add_argument("pred", type=Path)
    args = parser.parse_args(argv)
    result = score(labels.read_jsonl(args.gold), labels.read_jsonl(args.pred))
    print("scored %d items, skipped %d (id in only one file)" % (result["common"], result["skipped"]))
    print("kappa steering (binary):  %.3f" % result["kappa_steering"])
    print("kappa cause (%d steering): %.3f" % (result["steering_items"], result["kappa_cause"]))
    print("model-caused steering: precision %.3f, recall %.3f" % (result["precision"], result["recall"]))
    passed = min(result["kappa_steering"], result["kappa_cause"]) >= GATE
    print("gate (both kappa >= %.1f): %s" % (GATE, "PASS" if passed else "FAIL"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
