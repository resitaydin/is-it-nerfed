from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import jsonl
import sample

KINDS = {"new_work", "steering", "other"}
CAUSES = {"model", "user", "unclear"}
STEERING_TYPES = {"correction", "rejection", "failure_report", "redirect", None}
MIN_ANCHORS = 20  # labeled anchors below which agreement is not measured


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def item_text(item: dict) -> str:
    parts = [item["prompt"], item["previous_agent_reply"]] + list(item["earlier_prompts"])
    return _norm(" ".join(parts))


def valid(label: dict, item: dict) -> bool:
    fields = [label.get(k) for k in ("kind", "cause", "evidence", "reasoning")]
    steering_type = label.get("steering_type")
    if not all(isinstance(f, str) for f in fields):
        return False
    if steering_type is not None and not isinstance(steering_type, str):
        return False
    kind, cause, evidence, _ = fields
    return (kind in KINDS and cause in CAUSES and steering_type in STEERING_TYPES
            and bool(_norm(evidence)) and _norm(evidence) in item_text(item))


SHORT_MAX = 80


def valid_interp(row: dict) -> bool:
    """An interpret label: whether a changelog line can change model behavior, with a short text for it.

    The short text goes into the summary that Claude shows as printed, so it must be one plain line.
    """
    short = row.get("short")
    return (row.get("affects_behavior") in ("yes", "no") and isinstance(short, str)
            and 0 < len(short) <= SHORT_MAX and not any(c in short for c in "\n\r`"))


def read_labels(paths: List[Path], items_by_id: Dict[str, dict]) -> Tuple[Dict[str, dict], List[str]]:
    found: Dict[str, dict] = {}
    for path in paths:
        for label in jsonl.read(path):
            label_id = label.get("id")
            if not isinstance(label_id, str) or label_id in found:
                continue
            item = items_by_id.get(label_id)
            if item is not None and valid(label, item):
                found[label_id] = label
    return found, [i for i in items_by_id if i not in found]


def is_model_steering(label: dict) -> bool:
    return label.get("kind") == "steering" and label.get("cause") == "model"


def anchor_agreement(labels_by_id: Dict[str, dict], anchors: List[dict]) -> Optional[float]:
    """Share of labeled anchors whose model-caused label matches the gold one.

    The verdict counts only model-caused steering, so other label differences do not count.

    None when fewer than MIN_ANCHORS anchors have a label.
    """
    ids = [(a, sample.anchor_item_id(a)) for a in anchors]
    labeled = [(a, labels_by_id[i]) for a, i in ids if i in labels_by_id]
    if len(labeled) < MIN_ANCHORS:
        return None
    agreed = sum(1 for a, label in labeled
                 if is_model_steering(label) == is_model_steering({"kind": a["gold_kind"], "cause": a["gold_cause"]}))
    return agreed / len(labeled)
