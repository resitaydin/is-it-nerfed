from __future__ import annotations

import hashlib
import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

import parse
from stats import Window

REPLY_MAX = 1500
EARLIER_MAX = 2000
ANCHOR_KEYS = ("prompt", "previous_agent_reply", "earlier_prompts")

MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
BLIND_PATTERNS = [re.compile(p) for p in (
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z?)?",
    r"\b\d{1,2}:\d{2}(?::\d{2})?\b",
    MONTH + r" \d{1,2}(?:st|nd|rd|th)?(?:,? \d{4})?",
    r"\b\d{1,2}(?:st|nd|rd|th)? " + MONTH + r"(?: \d{4})?",
    r"claude-[\w.-]+",
    r"\b(?:Opus|Sonnet|Haiku|Fable)(?: \d+(?:\.\d+)*)?",
    r"\bv?\d+\.\d+\.\d+\b",
    r"(?i:\b(?:nerf|nerfed|dumber|degraded)\b)",
)]


def eligible(p: parse.Prompt) -> bool:
    return not p.is_first and not p.is_command


def select(prompts: List[parse.Prompt], window: Window, cap: int = 200,
           seed: int = 0, skip: Set[str] = frozenset()) -> List[parse.Prompt]:
    """Pick up to cap eligible prompts in the window, one per day in turn."""
    start, end = window
    by_day: Dict[object, List[parse.Prompt]] = defaultdict(list)
    for p in prompts:
        if eligible(p) and p.uuid not in skip and start <= p.timestamp.date() <= end:
            by_day[p.timestamp.date()].append(p)
    rng = random.Random(seed)
    queues = []
    for day in sorted(by_day):
        day_prompts = sorted(by_day[day], key=lambda p: p.uuid)
        rng.shuffle(day_prompts)
        queues.append(day_prompts)
    picked: List[parse.Prompt] = []
    depth = 0
    while len(picked) < cap and any(len(q) > depth for q in queues):
        for q in queues:
            if len(q) > depth and len(picked) < cap:
                picked.append(q[depth])
        depth += 1
    return picked


def blind(text: str) -> str:
    for pattern in BLIND_PATTERNS:
        text = pattern.sub("[x]", text)
    return text


def item_id(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def build_item(p: parse.Prompt) -> dict:
    earlier: List[str] = []
    total = 0
    for entry in p.history:
        entry = blind(entry)
        if total + len(entry) > EARLIER_MAX:
            break
        earlier.append(entry)
        total += len(entry)
    return {
        "id": item_id(p.uuid),
        "prompt": blind(p.text),
        "previous_agent_reply": blind(p.prev_agent_text)[-REPLY_MAX:],
        "earlier_prompts": earlier,
    }


def write_batches(items: List[dict], anchors: List[dict], out_dir: Path,
                  batch_size: int = 40, seed: int = 0) -> List[Path]:
    """Shuffle items and anchors together and write batch-NNN.jsonl files."""
    hidden = [dict({k: a[k] for k in ANCHOR_KEYS}, id=item_id("anchor-" + a["anchor_id"]))
              for a in anchors]
    rows = list(items) + hidden
    random.Random(seed).shuffle(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for n, start in enumerate(range(0, len(rows), batch_size), 1):
        path = out_dir / ("batch-%03d.jsonl" % n)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows[start:start + batch_size]),
                        encoding="utf-8")
        paths.append(path)
    return paths


def estimate_tokens(items: List[dict], n_batches: int) -> int:
    return (sum(len(json.dumps(i)) // 4 for i in items)
            + 3000 * n_batches + 120 * len(items))
