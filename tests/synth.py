from __future__ import annotations

import random
from typing import List

from stats import SessionCount
CONCENTRATION = 20


def make_counts(n_sessions: int, prompts_per: int, rate: float, seed: int) -> List[SessionCount]:
    """Synthetic sessions whose steering rate varies per session (clustering)."""
    rng = random.Random(seed)
    counts = []
    for i in range(n_sessions):
        session_rate = rng.betavariate(rate * CONCENTRATION, (1 - rate) * CONCENTRATION)
        k = sum(1 for _ in range(prompts_per) if rng.random() < session_rate)
        counts.append(("s%d" % i, k, prompts_per))
    return counts
