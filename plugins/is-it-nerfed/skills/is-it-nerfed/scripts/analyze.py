"""Join parser, stats, labels and overlay into one Analysis for the report."""
from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import labels as labels_mod
import overlay
import parse
import stats
from stats import BootResult, SessionCount, Window

RECENT_DAYS = 7
MIN_ACTIVE_DAYS = 3
FREEZE_DAYS = 28
PREV_WINDOW_DAYS = 14
DRIFT_THRESHOLD = 0.8
CLAUDE_CODE = "Claude Code"
CAUSE_WORDS = re.compile(r"degraded|performance", re.I)
BOOT_RESAMPLES = 5000


@dataclass
class Analysis:
    status: str  # "ok" | "too_early" | "judge_drift" | "no_model"
    model: Optional[str] = None
    prev_model: Optional[str] = None
    base: Optional[Window] = None
    recent: Optional[Window] = None
    boot: Optional[BootResult] = None
    verdict: Optional[str] = None
    shared_verdict: Optional[str] = None
    compare: Optional[BootResult] = None
    compare_verdict: Optional[str] = None
    daily: List[Tuple[date, int, int]] = field(default_factory=list)
    markers: List[Tuple[date, str, str]] = field(default_factory=list)
    side: Dict[str, dict] = field(default_factory=dict)
    harness: List[dict] = field(default_factory=list)
    receipts: Dict[str, List[dict]] = field(default_factory=dict)
    attribution: List[str] = field(default_factory=list)
    judge_agreement: Optional[float] = None
    overlay_ok: bool = True


def family(model: str) -> str:
    return re.sub(r"(-\d+)+$", "", model)


def _model_prompts(sessions: List[parse.Session], model: str) -> List[parse.Prompt]:
    return [p for s in sessions for p in s.prompts if p.model == model]


def _in(day: date, window: Window) -> bool:
    return window[0] <= day <= window[1]


def current_model(sessions: List[parse.Session], today: date) -> Optional[str]:
    counts = Counter(p.model for s in sessions for p in s.prompts
                     if p.model and 0 <= (today - p.timestamp.date()).days < RECENT_DAYS)
    return counts.most_common(1)[0][0] if counts else None


def model_days(sessions: List[parse.Session], model: str) -> List[date]:
    return sorted({p.timestamp.date() for p in _model_prompts(sessions, model)})


def previous_model(sessions: List[parse.Session], model: str) -> Optional[str]:
    first = model_days(sessions, model)[0]
    best: Optional[Tuple[date, str]] = None
    for other in {p.model for s in sessions for p in s.prompts if p.model}:
        if other == model or family(other) != family(model):
            continue
        days = model_days(sessions, other)
        if len(days) >= MIN_ACTIVE_DAYS and days[-1] < first and (best is None or days[-1] > best[0]):
            best = (days[-1], other)
    return best[1] if best else None


def windows_for(sessions: List[parse.Session], model: str,
                baselines: dict) -> Optional[Tuple[Window, Window]]:
    windows = stats.make_windows(model_days(sessions, model))
    saved = baselines.get(model)
    if windows is None or saved is None:
        return windows
    return (date.fromisoformat(saved["start"]), date.fromisoformat(saved["end"])), windows[1]


def prev_window(sessions: List[parse.Session], prev_model_id: str) -> Window:
    days = model_days(sessions, prev_model_id)[-PREV_WINDOW_DAYS:]
    return days[0], days[-1]


def session_counts(sessions: List[parse.Session], model: str, window: Window,
                   labels: Dict[str, dict]) -> List[SessionCount]:
    counts = []
    for s in sessions:
        mine = [labels[p.uuid] for p in s.prompts
                if p.model == model and _in(p.timestamp.date(), window) and p.uuid in labels]
        if mine:
            counts.append((s.session_id, sum(labels_mod.is_model_steering(l) for l in mine), len(mine)))
    return counts


def side_changes(sessions: List[parse.Session], model: str, window: Window) -> dict:
    prompts = [p for p in _model_prompts(sessions, model) if _in(p.timestamp.date(), window)]
    ids = {p.session_id for p in prompts}
    chosen = [s for s in sessions if s.session_id in ids]
    n_prompts = len(prompts) or 1
    results = sum(s.tool_results for s in chosen)
    shares = Counter(p.project for p in prompts).most_common(3)
    return {
        "claude_md_hashes": len({s.claude_md_hash for s in chosen if s.claude_md_hash}),
        "cli_versions": sorted({p.cli_version for p in prompts if p.cli_version}),
        "median_prompt_chars": int(statistics.median(len(p.text) for p in prompts)) if prompts else 0,
        "top_projects": [(name, n / n_prompts) for name, n in shares],
        "compactions_per_session": sum(s.compactions for s in chosen) / (len(chosen) or 1),
        "interrupts_per_prompt": sum(s.interrupts for s in chosen) / n_prompts,
        "tool_error_rate": sum(s.tool_errors for s in chosen) / results if results else 0.0,
        "user_edits": sum(s.user_modified_edits for s in chosen),
        "output_tokens_per_prompt": sum(s.output_tokens for s in chosen) / n_prompts,
    }


def daily(sessions: List[parse.Session], model: str,
          labels: Dict[str, dict]) -> List[Tuple[date, int, int]]:
    rows: Dict[date, List[int]] = {d: [0, 0] for d in model_days(sessions, model)}
    for p in _model_prompts(sessions, model):
        label = labels.get(p.uuid)
        if label is not None:
            row = rows[p.timestamp.date()]
            row[0] += labels_mod.is_model_steering(label)
            row[1] += 1
    return [(d, k, n) for d, (k, n) in sorted(rows.items())]


def receipts(sessions: List[parse.Session], model: str, window: Window,
             labels: Dict[str, dict], k: int = 3) -> List[dict]:
    by_session = []
    for s in sessions:
        hits = [(p, labels[p.uuid]) for p in s.prompts
                if p.model == model and _in(p.timestamp.date(), window)
                and p.uuid in labels and labels_mod.is_model_steering(labels[p.uuid])]
        if hits:
            by_session.append((-len(hits), s.session_id, hits))
    found = [hit for _, _, hits in sorted(by_session, key=lambda t: t[:2]) for hit in hits]
    return [{"date": p.timestamp.date().isoformat(), "quote": l.get("evidence", ""),
             "reason": l.get("reasoning", "")} for p, l in found[:k]]


def _overlaps(incident: overlay.Incident, window: Window) -> bool:
    return (incident.start.date() <= window[1]
            and (incident.end is None or incident.end.date() >= window[0]))


def _claude_code(incident: overlay.Incident) -> bool:
    return CLAUDE_CODE in incident.components


def attribution(recent: Window, harness: List[dict], version_dates: Dict[str, date],
                incidents: List[overlay.Incident]) -> List[str]:
    lines = ["CLI %s started in the recent window: %s" % (h["version"], h["line"])
             for h in harness
             if h.get("affects_behavior") == "yes"
             and h["version"] in version_dates and _in(version_dates[h["version"]], recent)]
    lines += ["Incident in the recent window: %s" % i.name for i in incidents
              if _claude_code(i) and CAUSE_WORDS.search(i.name) and _overlaps(i, recent)]
    return lines


def _harness(interp: Dict[str, dict], version_dates: Dict[str, date],
             windows: Tuple[Window, Window]) -> List[dict]:
    found = [r for r in interp.values() if r["version"] in version_dates
             and any(_in(version_dates[r["version"]], w) for w in windows)]
    return sorted(found, key=lambda r: (version_dates[r["version"]], r["id"]))


def _markers(days: List[date], version_dates: Dict[str, date],
             incidents: List[overlay.Incident]) -> List[Tuple[date, str, str]]:
    span = (days[0], days[-1])
    marks = [(d, "version", v) for v, d in version_dates.items() if _in(d, span)]
    marks += [(i.start.date(), "incident", i.name) for i in incidents
              if _claude_code(i) and _in(i.start.date(), span)]
    return sorted(marks)


def _boot(base: List[SessionCount], recent: List[SessionCount]) -> BootResult:
    return stats.cluster_bootstrap(base, recent, n=BOOT_RESAMPLES, seed=0)


def _shared_verdict(sessions: List[parse.Session], base: List[SessionCount],
                    recent: List[SessionCount], main: str) -> Optional[str]:
    project = {s.session_id: s.project for s in sessions}
    shared = {project.get(c[0]) for c in base} & {project.get(c[0]) for c in recent}
    shared.discard(None)
    keep = lambda counts: [c for c in counts if project.get(c[0]) in shared]
    if not shared:
        return None
    other = stats.verdict(_boot(keep(base), keep(recent)))
    return other if other != main else None


def _base_counts(sessions: List[parse.Session], model: str, base: Window,
                 labels: Dict[str, dict], baselines: dict) -> Tuple[List[SessionCount], dict]:
    saved = baselines.get(model)
    if saved is not None:
        return [tuple(s) for s in saved["sessions"]], baselines
    counts = session_counts(sessions, model, base, labels)
    frozen = {"start": base[0].isoformat(), "end": base[1].isoformat(),
              "sessions": [list(c) for c in counts]}
    return counts, {**baselines, model: frozen}


def run(sessions: List[parse.Session], labels: Dict[str, dict], interp: Dict[str, dict],
        incidents: List[overlay.Incident], version_dates: Dict[str, date], baselines: dict,
        judge_agreement: Optional[float], overlay_ok: bool, today: date,
        model: Optional[str] = None) -> Tuple[Analysis, dict]:
    model = model or current_model(sessions, today)
    out = Analysis(status="no_model", model=model, judge_agreement=judge_agreement,
                   overlay_ok=overlay_ok)
    if model is None:
        return out, baselines
    days = model_days(sessions, model)
    windows = windows_for(sessions, model, baselines)
    if windows is None:
        out.status = "too_early"
        return out, baselines
    base, recent = windows
    drift = judge_agreement is not None and judge_agreement < DRIFT_THRESHOLD
    out.status = "judge_drift" if drift else "ok"
    base_counts, saved = _base_counts(sessions, model, base, labels, baselines)
    recent_counts = session_counts(sessions, model, recent, labels)
    if drift or len(days) < FREEZE_DAYS:
        saved = baselines
    out.base, out.recent = base, recent
    out.boot = _boot(base_counts, recent_counts)
    out.verdict = "" if drift else stats.verdict(out.boot)
    if not drift:
        out.shared_verdict = _shared_verdict(sessions, base_counts, recent_counts, out.verdict)
    out.prev_model = previous_model(sessions, model)
    if out.prev_model:
        prev = session_counts(sessions, out.prev_model, prev_window(sessions, out.prev_model), labels)
        out.compare = _boot(prev, recent_counts)
        out.compare_verdict = stats.verdict(out.compare)
    out.daily = daily(sessions, model, labels)
    out.markers = _markers(days, version_dates, incidents)
    out.side = {"base": side_changes(sessions, model, base),
                "recent": side_changes(sessions, model, recent)}
    out.harness = _harness(interp, version_dates, windows)
    out.receipts = {"base": receipts(sessions, model, base, labels),
                    "recent": receipts(sessions, model, recent, labels)}
    out.attribution = attribution(recent, out.harness, version_dates, incidents)
    return out, saved
