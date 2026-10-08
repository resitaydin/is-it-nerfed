"""Build a blind item set from the real logs for hand-labeling the judge."""
from __future__ import annotations

import argparse
import difflib
import os
import random
import re
import sys
from pathlib import Path
from typing import List, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "plugins/is-it-nerfed/skills/is-it-nerfed/scripts"))

import jsonl  # noqa: E402
import parse  # noqa: E402
import sample  # noqa: E402

NEGATION_WORDS = ("no", "not", "don't", "dont", "stop", "wrong", "why did", "that's not", "revert", "undo")
NEGATION_START = re.compile(r"(?:%s)\b" % "|".join(re.escape(w) for w in NEGATION_WORDS))


def is_candidate(p: parse.Prompt) -> bool:
    return p.after_interrupt or bool(NEGATION_START.match(p.text.strip().lower()))

# Phrases that often mean the agent missed an instruction: the rare model-caused positives.
MODEL_HINT = re.compile(r"\b(?:i (?:asked|said|told)|again|still|you (?:didn't|did not|forgot|missed|ignored)"
                        r"|(?:doesn't|does not|didn't|did not|not) work|same (?:error|issue|problem))\b")
REPEAT_MIN_CHARS = 15
REPEAT_RATIO = 0.8


def is_model_hint(p: parse.Prompt) -> bool:
    """A hint phrase, or a prompt that repeats one of the last 3 prompts (the agent did not do it)."""
    text = p.text.strip().lower()
    if MODEL_HINT.search(text):
        return True
    return len(text) >= REPEAT_MIN_CHARS and any(_similar(text, h.strip().lower()) for h in p.history[:3])


def _similar(a: str, b: str) -> bool:
    """The quick ratios are upper bounds of the full ratio, so they skip most pairs cheaply."""
    m = difflib.SequenceMatcher(None, a, b)
    return m.real_quick_ratio() >= REPEAT_RATIO and m.quick_ratio() >= REPEAT_RATIO and m.ratio() >= REPEAT_RATIO


def pick_hints(prompts: List[parse.Prompt], n: int, seed: int, skip: Set[str]) -> List[parse.Prompt]:
    """Take up to n eligible model-hint or steering-candidate prompts that are not in skip."""
    pool = sorted((p for p in prompts if sample.eligible(p) and p.uuid not in skip
                   and (is_model_hint(p) or is_candidate(p))),
                  key=lambda p: p.uuid)
    random.Random(seed).shuffle(pool)
    return pool[:n]


def pick(prompts: List[parse.Prompt], n: int, seed: int) -> Tuple[List[parse.Prompt], int]:
    """Take half from the steering-candidate pool, the rest from the others. Return (picked, pool taken)."""
    rng = random.Random(seed)
    eligible = sorted((p for p in prompts if sample.eligible(p)), key=lambda p: p.uuid)
    pool = [p for p in eligible if is_candidate(p)]
    other = [p for p in eligible if not is_candidate(p)]
    rng.shuffle(pool)
    rng.shuffle(other)
    take_pool = min(n // 2, len(pool))
    take_other = min(n - take_pool, len(other))
    take_pool = min(n - take_other, len(pool))
    return pool[:take_pool] + other[:take_other], take_pool


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "data")
    parser.add_argument("--hints-only", type=Path, metavar="KEY",
                        help="take only model-hint or steering-candidate prompts that are not in this key file")
    args = parser.parse_args(argv)
    sessions = parse.load_sessions(parse.find_roots(Path.home(), os.environ))
    prompts = [p for s in sessions for p in s.prompts]
    if args.hints_only:
        skip = {r["uuid"] for r in jsonl.read(args.hints_only)}
        picked = pick_hints(prompts, args.n, args.seed, skip)
        pool = len(picked)
    else:
        picked, pool = pick(prompts, args.n, args.seed)
        random.Random(args.seed).shuffle(picked)
    items = [sample.build_item(p) for p in picked]
    keys = [{"id": i["id"], "uuid": p.uuid, "model": p.model, "date": p.timestamp.date().isoformat()}
            for i, p in zip(items, picked)]
    for name, rows in (("items.jsonl", items), ("key.jsonl", keys)):
        jsonl.write(args.out / name, rows)
    print("wrote %d items (%d from the steering-candidate pool) to %s" % (len(items), pool, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
