"""Build a blind item set from the real logs for hand-labeling the judge."""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "plugins/is-it-nerfed/skills/is-it-nerfed/scripts"))

import parse  # noqa: E402
import sample  # noqa: E402

NEGATION_WORDS = ("no", "not", "don't", "dont", "stop", "wrong", "why did", "that's not", "revert", "undo")
NEGATION_START = re.compile(r"(?:%s)\b" % "|".join(re.escape(w) for w in NEGATION_WORDS))


def is_candidate(p: parse.Prompt) -> bool:
    return p.after_interrupt or bool(NEGATION_START.match(p.text.strip().lower()))


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
    args = parser.parse_args(argv)
    sessions = parse.load_sessions(parse.find_roots(Path.home(), os.environ))
    picked, pool = pick([p for s in sessions for p in s.prompts], args.n, args.seed)
    random.Random(args.seed).shuffle(picked)
    args.out.mkdir(parents=True, exist_ok=True)
    items = [sample.build_item(p) for p in picked]
    keys = [{"id": i["id"], "uuid": p.uuid, "model": p.model, "date": p.timestamp.date().isoformat()}
            for i, p in zip(items, picked)]
    for name, rows in (("items.jsonl", items), ("key.jsonl", keys)):
        (args.out / name).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    print("wrote %d items (%d from the steering-candidate pool) to %s" % (len(items), pool, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
