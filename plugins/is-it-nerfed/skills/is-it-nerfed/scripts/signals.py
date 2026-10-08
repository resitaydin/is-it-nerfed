"""Agent-behavior signals that need no judge, counted on every session in a window."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import parse
import stats
from stats import SessionCount, Window


@dataclass(frozen=True)
class Signal:
    name: str
    label: str
    kind: str  # the event counted
    per: str  # the event it is counted against
    scale: int  # 100 for a percentage, 1000 for "per 1,000"


# Pre-declared from the March 2026 regression (anthropics/claude-code#42796), where each moved 3-6x.
SIGNALS = (
    Signal("blind edits", "Edits of a file no earlier tool call named (%)", "blind_edit", "edit", 100),
    Signal("interrupts", "Interrupts per 1,000 tool calls", "interrupt", "tool", 1000),
    Signal("self-corrections", "Self-corrections per 1,000 tool calls", "self_correction", "tool", 1000),
)


@dataclass
class SignalResult:
    signal: Signal
    base_rate: float
    recent_rate: float
    ratio: float
    lo: float
    hi: float

    @property
    def direction(self) -> Optional[str]:
        """"up" or "down" when the 90% interval of the ratio excludes 1, else None."""
        if self.lo > 1:
            return "up"
        if self.hi < 1:
            return "down"
        return None


def session_counts(sessions: List[parse.Session], model: str, window: Window,
                   signal: Signal) -> List[SessionCount]:
    counts = []
    for s in sessions:
        kinds = [e.kind for e in s.events if e.model == model and stats.in_window(e.timestamp.date(), window)]
        if signal.per in kinds:
            counts.append((s.session_id, kinds.count(signal.kind), kinds.count(signal.per)))
    return counts


def compare(sessions: List[parse.Session], model: str, base: Window, recent: Window) -> List[SignalResult]:
    """One result per signal that has events on both sides."""
    out = []
    for signal in SIGNALS:
        b, r = (session_counts(sessions, model, w, signal) for w in (base, recent))
        if b and r:
            ratio, lo, hi = stats.ratio_bootstrap(b, r)
            scale = signal.scale / 100
            out.append(SignalResult(signal, scale * stats.rate(b), scale * stats.rate(r), ratio, lo, hi))
    return out


def confirms_worse(results: List[SignalResult]) -> bool:
    return any(r.direction == "up" for r in results)
