from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

KINDS = {"new_work", "steering", "other"}
CAUSES = {"model", "user", "unclear"}
STEERING_TYPES = {"correction", "rejection", "failure_report", "redirect", None}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def item_text(item: dict) -> str:
    parts = [item["prompt"], item["previous_agent_reply"]] + list(item["earlier_prompts"])
    return _norm(" ".join(parts))


def valid(label: dict, item: dict) -> bool:
    evidence = label.get("evidence")
    if not isinstance(evidence, str) or not _norm(evidence):
        return False
    return (label.get("kind") in KINDS
            and label.get("cause") in CAUSES
            and label.get("steering_type") in STEERING_TYPES
            and _norm(evidence) in item_text(item))


def _read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def read_labels(paths: List[Path], items_by_id: Dict[str, dict]) -> Tuple[Dict[str, dict], List[str]]:
    found: Dict[str, dict] = {}
    for path in paths:
        for label in _read_jsonl(path):
            item = items_by_id.get(label.get("id"))
            if item is not None and label["id"] not in found and valid(label, item):
                found[label["id"]] = label
    return found, [i for i in items_by_id if i not in found]


def load_cache(path: Path) -> Dict[str, dict]:
    return {r["uuid"]: r for r in _read_jsonl(path) if "uuid" in r}


def append_cache(path: Path, records: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def is_model_steering(label: dict) -> bool:
    return label.get("kind") == "steering" and label.get("cause") == "model"
