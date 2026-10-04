from __future__ import annotations

import bisect
import math
import random
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

Window = Tuple[date, date]
SessionCount = Tuple[str, int, int]  # session_id, model-caused steering count, labeled count
MIN_SESSIONS = 5  # labeled sessions per side below which only a leaning verdict is given


def make_windows(days: List[date]) -> Optional[Tuple[Window, Window]]:
    """Split sorted distinct active days into a base window and a recent window."""
    n = len(days)
    if n < 3:
        return None
    if n < 28:
        half = n // 2
        base, recent = days[:half], days[n - half:]
    else:
        base, recent = days[:14], days[-14:]
    return (base[0], base[-1]), (recent[0], recent[-1])


@dataclass
class BootResult:
    diff: float
    lo: float
    hi: float
    p_worse: float
    base_rate: float
    recent_rate: float
    n_base: int
    n_recent: int
    s_base: int
    s_recent: int


def _rate(counts: List[SessionCount]) -> float:
    total = sum(c[2] for c in counts)
    return 100.0 * sum(c[1] for c in counts) / total if total else 0.0


def _binomial_cdf(k: int, n: int) -> List[float]:
    """Cumulative Binomial(n, k/n) probabilities for 0..n."""
    p = k / n
    total, cdf = 0.0, []
    for j in range(n + 1):
        total += math.comb(n, j) * p ** j * (1 - p) ** (n - j)
        cdf.append(total)
    return cdf


def cluster_bootstrap(base: List[SessionCount], recent: List[SessionCount],
                      n: int = 5000, seed: int = 0) -> BootResult:
    """Two-stage bootstrap: resample sessions, then prompts inside each picked session.

    Rates are in percentage points. Sessions without labeled prompts are left out.
    """
    rng = random.Random(seed)
    sides = [[(c[2], _binomial_cdf(c[1], c[2])) for c in side if c[2] > 0] for side in (base, recent)]
    diffs = []
    for _ in range(n):
        rates = []
        for side in sides:
            pick = rng.choices(side, k=len(side))
            total = sum(m for m, _ in pick)
            hits = sum(min(m, bisect.bisect_right(cdf, rng.random())) for m, cdf in pick)
            rates.append(100.0 * hits / total if total else 0.0)
        diffs.append(rates[1] - rates[0])
    diffs.sort()
    return BootResult(
        diff=_rate(recent) - _rate(base),
        lo=diffs[int(0.05 * n)],
        hi=diffs[min(n - 1, int(0.95 * n))],
        p_worse=sum(d > 0 for d in diffs) / n,
        base_rate=_rate(base),
        recent_rate=_rate(recent),
        n_base=sum(c[2] for c in base),
        n_recent=sum(c[2] for c in recent),
        s_base=len(sides[0]),
        s_recent=len(sides[1]),
    )


def verdict(r: BootResult, sesoi: float = 5.0) -> str:
    if min(r.s_base, r.s_recent) < MIN_SESSIONS:
        return _leaning(r)
    if r.lo >= -sesoi and r.hi <= sesoi:
        return "no_change"
    if r.lo > 0 and r.diff >= 2 * sesoi:
        return "clearly_worse"
    if r.lo > 0:
        return "slightly_worse"
    if r.hi < 0:
        return "better"
    return _leaning(r)


def _leaning(r: BootResult) -> str:
    return "leaning_worse" if r.p_worse >= 0.5 else "leaning_better"
