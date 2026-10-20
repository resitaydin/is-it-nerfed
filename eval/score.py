"""Score judge labels (pred) against reference labels (gold)."""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "plugins/is-it-nerfed/skills/is-it-nerfed/scripts"))

import jsonl  # noqa: E402
import labels  # noqa: E402

# The verdict counts only model-caused steering, so the gate scores only that label.
GATE_KAPPA = 0.7
GATE_FALSE_ALARM = 0.01  # false alarms pull the rate ratio toward 1 and hide a real change
GATE_POSITIVES = 30  # fewer reference positives give a kappa interval too wide to judge


def cohen_kappa(a: list, b: list) -> float:
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(count_a[c] * count_b[c] for c in count_a) / (n * n)
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def gwet_ac1(a: List[bool], b: List[bool]) -> float:
    """Binary agreement that stays stable when one class is rare, unlike kappa."""
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    share = (sum(a) + sum(b)) / (2 * n)
    expected = 2 * share * (1 - share)
    return (observed - expected) / (1 - expected)


def kappa_interval(a: list, b: list, runs: int = 2000, seed: int = 1) -> Tuple[float, float]:
    """95% bootstrap interval of Cohen's kappa over items."""
    rng = random.Random(seed)
    n = len(a)
    kappas = []
    for _ in range(runs):
        idx = [rng.randrange(n) for _ in range(n)]
        kappas.append(cohen_kappa([a[i] for i in idx], [b[i] for i in idx]))
    kappas.sort()
    return kappas[int(0.025 * runs)], kappas[int(0.975 * runs) - 1]


def score(gold_rows: List[dict], pred_rows: List[dict]) -> Dict[str, float]:
    gold = {r["id"]: r for r in gold_rows}
    pred = {r["id"]: r for r in pred_rows}
    common = [i for i in gold if i in pred]
    g = [labels.is_model_steering(gold[i]) for i in common]
    p = [labels.is_model_steering(pred[i]) for i in common]
    tp = sum(x and y for x, y in zip(g, p))
    fp = sum(y and not x for x, y in zip(g, p))
    fn = sum(x and not y for x, y in zip(g, p))
    negatives = len(g) - sum(g)
    steering = [i for i in common if gold[i]["kind"] == "steering"]
    return {
        "common": len(common),
        "skipped": len(set(gold) | set(pred)) - len(common),
        "positives": sum(g),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "false_alarm_rate": fp / negatives if negatives else 0.0,
        "kappa_model": cohen_kappa(g, p),
        "kappa_model_ci": kappa_interval(g, p),
        "ac1_model": gwet_ac1(g, p),
        # Diagnostics only: the verdict does not use these labels.
        "kappa_steering": cohen_kappa([gold[i]["kind"] == "steering" for i in common],
                                      [pred[i]["kind"] == "steering" for i in common]),
        "kappa_cause": cohen_kappa([gold[i]["cause"] for i in steering],
                                   [pred[i]["cause"] for i in steering]) if steering else 0.0,
        "steering_items": len(steering),
    }


def passes(result: Dict[str, float]) -> bool:
    return (result["positives"] >= GATE_POSITIVES and result["kappa_model"] >= GATE_KAPPA
            and result["false_alarm_rate"] <= GATE_FALSE_ALARM)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("gold", type=Path)
    parser.add_argument("pred", type=Path)
    args = parser.parse_args(argv)
    result = score(jsonl.read(args.gold), jsonl.read(args.pred))
    print("scored %d items, skipped %d (id in only one file)" % (result["common"], result["skipped"]))
    print("model-caused steering: %d reference positives, tp %d, fp %d, fn %d"
          % (result["positives"], result["tp"], result["fp"], result["fn"]))
    print("  kappa %.3f (95%% CI %.2f to %.2f), AC1 %.3f" % ((result["kappa_model"],) + result["kappa_model_ci"]
                                                          + (result["ac1_model"],)))
    print("  precision %.3f, recall %.3f, false-alarm rate %.4f"
          % (result["precision"], result["recall"], result["false_alarm_rate"]))
    print("diagnostics: kappa steering %.3f, kappa cause %.3f (%d steering items)"
          % (result["kappa_steering"], result["kappa_cause"], result["steering_items"]))
    print("gate (>= %d positives, kappa >= %.1f, false alarms <= %.0f%%): %s"
          % (GATE_POSITIVES, GATE_KAPPA, 100 * GATE_FALSE_ALARM, "PASS" if passes(result) else "FAIL"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
