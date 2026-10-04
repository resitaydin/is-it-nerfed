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
SESOI_RATIO = 1.5  # smallest rate ratio that matters
FLOOR = 1.5  # smallest absolute change that matters, in percentage points
CLEAR_RATIO = 2.0
LEAN = 0.8  # bootstrap share on one side needed for a leaning verdict


def in_window(day: date, window: Window) -> bool:
    return window[0] <= day <= window[1]


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
    ratio: float
    ratio_lo: float
    ratio_hi: float


def rate(counts: List[SessionCount]) -> float:
    total = sum(c[2] for c in counts)
    return 100.0 * sum(c[1] for c in counts) / total if total else 0.0


def _ratio(hits_base: int, n_base: int, hits_recent: int, n_recent: int) -> float:
    """Recent rate over base rate, with half a hit added to each side so zero counts stay finite."""
    return ((hits_recent + 0.5) / (n_recent + 1)) / ((hits_base + 0.5) / (n_base + 1))


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
    diffs, ratios = [], []
    for _ in range(n):
        drawn = []
        for side in sides:
            pick = rng.choices(side, k=len(side))
            total = sum(m for m, _ in pick)
            hits = sum(min(m, bisect.bisect_right(cdf, rng.random())) for m, cdf in pick)
            drawn.append((hits, total))
        (hb, nb), (hr, nr) = drawn
        diffs.append((100.0 * hr / nr if nr else 0.0) - (100.0 * hb / nb if nb else 0.0))
        ratios.append(_ratio(hb, nb, hr, nr))
    diffs.sort()
    ratios.sort()
    totals = [(sum(c[1] for c in side), sum(c[2] for c in side)) for side in (base, recent)]
    return BootResult(
        diff=rate(recent) - rate(base),
        lo=diffs[int(0.05 * n)],
        hi=diffs[min(n - 1, int(0.95 * n))],
        p_worse=sum(d > 0 for d in diffs) / n,
        base_rate=rate(base),
        recent_rate=rate(recent),
        n_base=sum(c[2] for c in base),
        n_recent=sum(c[2] for c in recent),
        s_base=len(sides[0]),
        s_recent=len(sides[1]),
        ratio=_ratio(*totals[0], *totals[1]),
        ratio_lo=ratios[int(0.05 * n)],
        ratio_hi=ratios[min(n - 1, int(0.95 * n))],
    )


def ratio_bootstrap(base: List[SessionCount], recent: List[SessionCount],
                    n: int = 2000, seed: int = 0) -> Tuple[float, float, float]:
    """Rate ratio with a 90% interval from resampling sessions only, for counts with no upper bound."""
    rng = random.Random(seed)

    def totals(side: List[SessionCount]) -> Tuple[int, int]:
        return sum(c[1] for c in side), sum(c[2] for c in side)

    ratios = sorted(_ratio(*totals(rng.choices(base, k=len(base))), *totals(rng.choices(recent, k=len(recent))))
                    for _ in range(n))
    return _ratio(*totals(base), *totals(recent)), ratios[int(0.05 * n)], ratios[min(n - 1, int(0.95 * n))]


def verdict(r: BootResult) -> str:
    """Rate-ratio verdict: a rare event that doubles is a real change, whatever its size in points."""
    if min(r.s_base, r.s_recent) < MIN_SESSIONS:
        return _leaning(r)
    if (r.ratio_lo >= 1 / SESOI_RATIO and r.ratio_hi <= SESOI_RATIO) or (r.lo >= -FLOOR and r.hi <= FLOOR):
        return "no_change"
    if r.ratio_lo > 1 and r.diff >= FLOOR:
        return "clearly_worse" if r.ratio >= CLEAR_RATIO else "slightly_worse"
    if r.ratio_hi < 1 and r.diff <= -FLOOR:
        return "better"
    return _leaning(r)


def _leaning(r: BootResult) -> str:
    if r.p_worse >= LEAN:
        return "leaning_worse"
    if r.p_worse <= 1 - LEAN:
        return "leaning_better"
    return "unclear"
