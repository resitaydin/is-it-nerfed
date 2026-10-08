"""Join parser, stats, labels and overlay into one Analysis for the report."""
from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

import labels as labels_mod
import overlay
import parse
import signals as signals_mod
import stats
from stats import BootResult, SessionCount, Window

RECENT_DAYS = 7
MIN_ACTIVE_DAYS = 3
FREEZE_DAYS = 28
PREV_WINDOW_DAYS = 14
DRIFT_THRESHOLD = 0.8
CLAUDE_CODE = "Claude Code"
CAUSE_WORDS = re.compile(r"degraded|performance", re.I)
FIRM_WORSE = ("slightly_worse", "clearly_worse")


@dataclass
class Analysis:
    status: str  # "ok" | "too_early" | "judge_drift" | "no_labels"
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
    signals: List[signals_mod.SignalResult] = field(default_factory=list)


def judge_drifted(agreement: Optional[float]) -> bool:
    return agreement is not None and agreement < DRIFT_THRESHOLD


def family(model: str) -> str:
    return re.sub(r"(-\d+)+$", "", model)


def model_prompts(sessions: List[parse.Session], model: str) -> List[parse.Prompt]:
    return [p for s in sessions for p in s.prompts if p.model == model]


def _in(p: parse.Prompt, model: str, window: Window) -> bool:
    return p.model == model and stats.in_window(p.timestamp.date(), window)


def current_model(sessions: List[parse.Session], today: date) -> Optional[str]:
    counts = Counter(p.model for s in sessions for p in s.prompts
                     if p.model and 0 <= (today - p.timestamp.date()).days < RECENT_DAYS)
    return counts.most_common(1)[0][0] if counts else None


def model_days(sessions: List[parse.Session], model: str) -> List[date]:
    return sorted({p.timestamp.date() for p in model_prompts(sessions, model)})


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
        mine = [labels[p.uuid] for p in s.prompts if _in(p, model, window) and p.uuid in labels]
        if mine:
            counts.append((s.session_id, sum(labels_mod.is_model_steering(l) for l in mine), len(mine)))
    return counts


def _version_key(version: str) -> Tuple[Tuple[int, int, str], ...]:
    """Numeric parts sort by value; non-numeric parts sort after them, as text."""
    return tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in version.split("."))


def _claude_md_edits(chosen: List[parse.Session]) -> int:
    versions: Dict[str, set] = {}
    for s in chosen:
        for path, digest in s.claude_md_files.items():
            versions.setdefault(path, set()).add(digest)
    return sum(len(v) - 1 for v in versions.values())


def side_changes(sessions: List[parse.Session], model: str, window: Window) -> dict:
    prompts = [p for s in sessions for p in s.prompts if _in(p, model, window)]
    ids = {p.session_id for p in prompts}
    chosen = [s for s in sessions if s.session_id in ids]
    n_prompts = len(prompts) or 1
    results = sum(p.tool_results for p in prompts)
    shares = Counter(p.project for p in prompts).most_common(3)
    return {
        "claude_md_edits": _claude_md_edits(chosen),
        "cli_versions": sorted({p.cli_version for p in prompts if p.cli_version}, key=_version_key),
        "median_prompt_chars": int(statistics.median(len(p.text) for p in prompts)) if prompts else 0,
        "top_projects": [(name, n / n_prompts) for name, n in shares],
        "compactions_per_session": sum(p.compactions for p in prompts) / (len(chosen) or 1),
        "tool_error_rate": sum(p.tool_errors for p in prompts) / results if results else 0.0,
        "user_edits": sum(p.user_edits for p in prompts),
        "output_tokens_per_prompt": sum(p.output_tokens for p in prompts) / n_prompts,
    }


def daily(sessions: List[parse.Session], model: str,
          labels: Dict[str, dict]) -> List[Tuple[date, int, int]]:
    rows: Dict[date, List[int]] = {d: [0, 0] for d in model_days(sessions, model)}
    for p in model_prompts(sessions, model):
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
                if _in(p, model, window) and labels_mod.is_model_steering(labels.get(p.uuid, {}))]
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
    by_version: Dict[str, List[str]] = {}
    for h in harness:
        if stats.in_window(version_dates[h["version"]], recent):
            by_version.setdefault(h["version"], []).append(h["short"])
    lines = ["%s: %s" % (v, "; ".join(texts)) for v, texts in by_version.items()]
    lines += ["incident: %s" % i.name for i in incidents
              if _claude_code(i) and CAUSE_WORDS.search(i.name) and _overlaps(i, recent)]
    return lines


def _harness(interp: Dict[str, dict], version_dates: Dict[str, date],
             windows: Tuple[Window, Window]) -> List[dict]:
    """Changelog lines that can change model behavior, from versions first seen in a window."""
    found = [r for r in interp.values() if r["affects_behavior"] == "yes" and r["version"] in version_dates
             and any(stats.in_window(version_dates[r["version"]], w) for w in windows)]
    return sorted(found, key=lambda r: (version_dates[r["version"]], r["id"]))


def _markers(days: List[date], version_dates: Dict[str, date],
             incidents: List[overlay.Incident]) -> List[Tuple[date, str, str]]:
    span = (days[0], days[-1])
    marks = [(d, "version", v) for v, d in version_dates.items() if stats.in_window(d, span)]
    marks += [(i.start.date(), "incident", i.name) for i in incidents
              if _claude_code(i) and stats.in_window(i.start.date(), span)]
    return sorted(marks)


def _shared_verdict(sessions: List[parse.Session], base: List[SessionCount],
                    recent: List[SessionCount], main: str) -> Optional[str]:
    project = {s.session_id: s.project for s in sessions}
    shared = {project.get(c[0]) for c in base} & {project.get(c[0]) for c in recent}
    shared.discard(None)
    keep = lambda counts: [c for c in counts if project.get(c[0]) in shared]
    if not shared:
        return None
    other = stats.verdict(stats.cluster_bootstrap(keep(base), keep(recent)))
    return other if other != main else None


def _base_counts(sessions: List[parse.Session], model: str, base: Window, labels: Dict[str, dict],
                 baselines: dict) -> Tuple[List[SessionCount], Dict[str, List[SessionCount]]]:
    """The base counts of steering and of each signal: the saved ones, or new ones from the logs.

    The saved counts outlive the logs, which Claude Code deletes after 30 days by default."""
    saved = baselines.get(model, {})
    counts = ([tuple(c) for c in saved["sessions"]] if "sessions" in saved
              else session_counts(sessions, model, base, labels))
    signals = ({name: [tuple(c) for c in rows] for name, rows in saved["signals"].items()} if "signals" in saved
               else signals_mod.window_counts(sessions, model, base))
    return counts, signals


def _shown(verdict: Optional[str], confirmed: bool) -> Optional[str]:
    """A firm "worse" needs a behavior signal that rose too."""
    return "unconfirmed_worse" if verdict in FIRM_WORSE and not confirmed else verdict


def run(sessions: List[parse.Session], labels: Dict[str, dict], interp: Dict[str, dict],
        incidents: List[overlay.Incident], version_dates: Dict[str, date], baselines: dict,
        judge_agreement: Optional[float], overlay_ok: bool, model: str) -> Tuple[Analysis, dict]:
    """The analysis, and the baselines to save: a base window is frozen once the model has FREEZE_DAYS days."""
    out = Analysis(status="too_early", model=model, judge_agreement=judge_agreement, overlay_ok=overlay_ok)
    days = model_days(sessions, model)
    windows = windows_for(sessions, model, baselines)
    out.daily = daily(sessions, model, labels)
    out.markers = _markers(days, version_dates, incidents)
    if windows is None:
        return out, baselines
    base, recent = windows
    out.base, out.recent = base, recent
    base_counts, base_signals = _base_counts(sessions, model, base, labels, baselines)
    recent_counts = session_counts(sessions, model, recent, labels)
    if not stats.totals(base_counts)[1] or not stats.totals(recent_counts)[1]:
        out.status = "no_labels"
    elif judge_drifted(judge_agreement):
        out.status = "judge_drift"
    else:
        out.status = "ok"
    if out.status != "ok":
        return out, baselines
    out.boot = stats.cluster_bootstrap(base_counts, recent_counts)
    out.signals = signals_mod.compare(base_signals, signals_mod.window_counts(sessions, model, recent))
    confirmed = signals_mod.confirms_worse(out.signals)
    verdict = stats.verdict(out.boot)
    out.verdict = _shown(verdict, confirmed)
    shared = _shown(_shared_verdict(sessions, base_counts, recent_counts, verdict), confirmed)
    out.shared_verdict = shared if shared != out.verdict else None
    out.prev_model = previous_model(sessions, model)
    if out.prev_model:
        prev = session_counts(sessions, out.prev_model, prev_window(sessions, out.prev_model), labels)
        if prev:
            out.compare = stats.cluster_bootstrap(prev, recent_counts)
            out.compare_verdict = stats.verdict(out.compare)
    out.side = {"base": side_changes(sessions, model, base),
                "recent": side_changes(sessions, model, recent)}
    out.harness = _harness(interp, version_dates, windows)
    out.receipts = {"base": receipts(sessions, model, base, labels),
                    "recent": receipts(sessions, model, recent, labels)}
    out.attribution = attribution(recent, out.harness, version_dates, incidents)
    signals = {name: [list(c) for c in counts] for name, counts in base_signals.items()}
    saved = baselines.get(model)
    if saved is None:
        if len(days) < FREEZE_DAYS:
            return out, baselines
        frozen = {"start": base[0].isoformat(), "end": base[1].isoformat(),
                  "sessions": [list(c) for c in base_counts], "signals": signals}
        return out, {**baselines, model: frozen}
    if "signals" not in saved and any(signals.values()):
        # A baseline saved before the signals were frozen gets them while its logs remain.
        return out, {**baselines, model: {**saved, "signals": signals}}
    return out, baselines
