"""Turn an Analysis into the terminal summary and one self-contained HTML report."""
from __future__ import annotations

import base64
import json
import re
from datetime import date, timedelta
from html import escape
from pathlib import Path
from string import Template
from typing import Dict, List, Optional, Tuple

from analyze import Analysis
from signals import SignalResult
from stats import MIN_EVENTS, Window

# Per verdict: the status icon, the word (the HTML badge and the first terminal sentence),
# the short text, and the detail sentence.
VERDICTS: Dict[str, Tuple[str, str, str, str]] = {
    "no_change": ("good", "Not nerfed", "no change", "%(name)s works as well for you as before."),
    "better": ("good", "Not nerfed", "better", "%(name)s is better for you (%(p)s probability)."),
    "leaning_better": ("good", "Not nerfed", "probably better",
                       "%(name)s is probably better for you (%(p)s probability)."),
    "unclear": ("neutral", "No clear change", "no clear change", "The data does not show a change either way."),
    "too_few_events": ("neutral", "Not enough data", "too few model mistakes to measure",
                       "The judge found only %(events)d model mistakes in both windows; a verdict needs %(min)d."),
    "slightly_worse": ("critical", "Nerfed for you", "slightly worse",
                       "%(name)s is slightly worse for you (%(p)s probability)."),
    "clearly_worse": ("critical", "Nerfed for you", "clearly worse",
                      "%(name)s is clearly worse for you (%(p)s probability)."),
    "leaning_worse": ("warning", "Possibly nerfed", "probably worse",
                      "%(name)s is probably worse for you (%(p)s probability)."),
    "unconfirmed_worse": ("warning", "Possibly nerfed", "probably worse, but agent behavior did not change",
                          "You corrected %(name)s more often, but the agent behavior did not change "
                          "(%(p)s probability)."),
}
WORSE = {v for v, (kind, _, _, _) in VERDICTS.items() if kind in ("critical", "warning")}
BETTER = {"better", "leaning_better"}
STATUS_TEXT: Dict[str, str] = {
    "too_early": "too early: fewer than 3 active days, no verdict yet",
    "judge_drift": "no verdict: the judge got only %s of the test prompts right (it needs 80%%)",
    "no_labels": "no verdict: one window has no labeled prompts",
}
ROLL_DAYS = 5
SHORT_TAIL = 30
TITLE_WIDTH = 16
LOW_DAYS, LOW_PROMPTS = 5, 50
HIGH_DAYS, HIGH_PROMPTS = 7, 150
TEMPLATE = Path(__file__).with_name("report_template.html")
CHARTJS = Path(__file__).with_name("vendor") / "chart.umd.min.js"
FONT = Path(__file__).with_name("vendor") / "Geist-Variable.woff2"


# ---------- small formatters ----------

def model_name(model: Optional[str]) -> str:
    if not model:
        return "No model"
    m = re.fullmatch(r"claude-([a-z]+)-(\d+(?:-\d+)*?)(?:-\d{8})?", model)
    if not m:
        return model
    return "%s %s" % (m.group(1).capitalize(), m.group(2).replace("-", "."))


def _day(d: date) -> str:
    return "%s %d" % (d.strftime("%b"), d.day)


def span(w: Window) -> str:
    start, end = w
    if start == end:
        return _day(start)
    if (start.year, start.month) == (end.year, end.month):
        return "%s-%d" % (_day(start), end.day)
    return "%s-%s" % (_day(start), _day(end))


def _pct(x: float) -> str:
    return "%.0f%%" % x


def _pts(x: float) -> str:
    return "%+d pts" % int(round(x))


def _times(ratio: float) -> str:
    return "×%.1f" % ratio


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def short_projects(names: List[str]) -> Dict[str, str]:
    """Strip the dash-bounded prefix all names share and cut long rests at a dash.

    With no shared prefix, keep the tail of the name from a dash on."""
    unique = sorted(set(names))
    prefix = "" if len(unique) == 1 else _common_prefix(unique)
    prefix = prefix[:prefix.rfind("-") + 1]
    out = {}
    for name in unique:
        rest = name[len(prefix):]
        if not prefix or not rest:
            out[name] = _tail(name)
        elif len(rest) > SHORT_TAIL:
            head = rest[:SHORT_TAIL]
            out[name] = head[:head.rfind("-")] + "…" if head.rfind("-") > 0 else head + "…"
        else:
            out[name] = rest
    return out


def _tail(name: str) -> str:
    if len(name) <= SHORT_TAIL:
        return name
    tail = name[-SHORT_TAIL:]
    dash = tail.find("-")
    return "…" + (tail[dash + 1:] if 0 <= dash < len(tail) - 1 else tail)


def _common_prefix(names: List[str]) -> str:
    first, last = names[0], names[-1]
    i = 0
    while i < min(len(first), len(last)) and first[i] == last[i]:
        i += 1
    return first[:i]


def _side_names(side: Dict[str, dict]) -> Dict[str, str]:
    return short_projects([name for s in side.values() for name, _ in s["top_projects"]])


def _marker_label(kind: str, label: str) -> str:
    return ("CLI " if kind == "version" else "") + label


def _counts(a: Analysis) -> str:
    if not a.daily:
        return ""
    return " (%d labeled prompts on %d days)" % (sum(n for _, _, n in a.daily), len(a.daily))


def _no_verdict_text(a: Analysis) -> str:
    text = STATUS_TEXT[a.status]
    if a.status == "judge_drift":
        text %= _pct(100 * a.judge_agreement)
    return _cap(text + _counts(a)) + "."


# ---------- terminal ----------

def _titled(title: str, text: str) -> str:
    return "%-*s%s" % (TITLE_WIDTH, title + ":", text)


def _verdict_detail(a: Analysis) -> str:
    p = a.boot.p_worse if a.verdict in WORSE else 1 - a.boot.p_worse
    return VERDICTS[a.verdict][3] % {"name": model_name(a.model), "p": _pct(100 * p),
                                     "events": a.boot.k_base + a.boot.k_recent, "min": MIN_EVENTS}


def _verdict_text(a: Analysis) -> str:
    return "%s. %s" % (VERDICTS[a.verdict][1], _verdict_detail(a))


def _mistakes_text(a: Analysis) -> str:
    b = a.boot
    return "%d of %d prompts before (%s, %s), %d of %d now (%s, %s)." % (
        b.k_base, b.n_base, _pct(b.base_rate), span(a.base),
        b.k_recent, b.n_recent, _pct(b.recent_rate), span(a.recent))


def _moved(results: List[SignalResult]) -> List[SignalResult]:
    return [r for r in results if r.direction]


def _behavior_text(a: Analysis) -> str:
    moved = _moved(a.signals)
    if moved:
        text = "; ".join("%s %.1f× as often as before" % (r.signal.name, r.ratio) for r in moved)
        return _cap(text) + "."
    names = [r.signal.name for r in a.signals]
    if not names:
        return "Too few events to measure."
    if len(names) == 1:
        return "No change in %s." % names[0]
    return "No change in %s%s or %s." % (", ".join(names[:-1]), "," if len(names) > 2 else "", names[-1])


def _setup_parts(a: Analysis) -> List[Tuple[str, str]]:
    """An icon name and a sentence for each setup change that can affect the result."""
    parts = []
    if a.side["recent"]["claude_md_edits"] > 0:
        parts.append(("file-text", "CLAUDE.md changed %d×." % a.side["recent"]["claude_md_edits"]))
    if a.shared_verdict:
        parts.append(("folder", "Your project mix changed. On the same projects only, it is %s."
                      % VERDICTS[a.shared_verdict][2]))
    return parts


def _setup_text(a: Analysis) -> str:
    return " ".join(text for _, text in _setup_parts(a)) or "No change that can affect the result."


def _claude_code_text(a: Analysis) -> str:
    if a.attribution and a.verdict in WORSE:
        return "; ".join(a.attribution) + ". This can explain the drift."
    new = [v for v in a.side["recent"]["cli_versions"] if v not in a.side["base"]["cli_versions"]]
    if not new:
        return "No update in the recent window."
    count = "%d update%s in the recent window." % (len(new), "" if len(new) == 1 else "s")
    if not a.overlay_ok:
        return count + " The changelog was not checked (offline)."
    return count if a.attribution else count + " None can change model quality."


def _confidence(a: Analysis) -> Tuple[str, str]:
    """The confidence level (Low, Medium or High) and its reason."""
    b = a.boot
    labeled = [d for d, _, n in a.daily if n]
    recent_days = len([d for d in labeled if d >= a.recent[0]])
    if recent_days < LOW_DAYS:
        return "Low", "Only %d recent day%s. Run again after %s." % (
            recent_days, "" if recent_days == 1 else "s", _day(a.recent[1] + timedelta(days=LOW_DAYS - recent_days)))
    fewest = min(b.n_base, b.n_recent)
    if fewest < LOW_PROMPTS:
        return "Low", "Only %d prompts in one window." % fewest
    level = "High" if recent_days >= HIGH_DAYS and fewest >= HIGH_PROMPTS else "Medium"
    return level, "%d prompts over %d days." % (b.n_base + b.n_recent, len(labeled))


def _confidence_text(a: Analysis) -> str:
    return "%s. %s" % _confidence(a)


def _display_path(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home):] if text.startswith(home + "/") else text


def summary(a: Analysis, report_path: Path) -> List[str]:
    last = _titled("Report", _display_path(report_path))
    if a.status != "ok":
        return [_titled("Verdict", _no_verdict_text(a)), last]
    return [
        _titled("Verdict", _verdict_text(a)),
        _titled("Model mistakes", _mistakes_text(a)),
        _titled("Agent behavior", _behavior_text(a)),
        _titled("Your setup", _setup_text(a)),
        _titled("Claude Code", _claude_code_text(a)),
        _titled("Confidence", _confidence_text(a)),
        last,
    ]


# ---------- chart ----------

def rolling(daily: List[Tuple[date, int, int]]) -> List[Tuple[date, Optional[float]]]:
    """Per calendar day: the pooled rate over the last 5 calendar days, or None with no prompts in them."""
    first, last = daily[0][0], daily[-1][0]
    out = []
    for o in range(first.toordinal(), last.toordinal() + 1):
        d = date.fromordinal(o)
        pool = [(k, n) for d2, k, n in daily if 0 <= (d - d2).days < ROLL_DAYS]
        n = sum(p[1] for p in pool)
        out.append((d, sum(p[0] for p in pool) / n if n else None))
    return out


def chart_windows(a: Analysis) -> List[Tuple[str, Window, float]]:
    """The Before and Now windows with the same rates the cards show."""
    if a.boot is None:
        return []
    return [("Before", a.base, a.boot.base_rate), ("Now", a.recent, a.boot.recent_rate)]


def trend_data(daily: List[Tuple[date, int, int]], markers: List[Tuple[date, str, str]],
               windows: List[Tuple[str, Window, float]]) -> dict:
    """One entry per calendar day for the Chart.js trend: 5-day rate, counts, window averages, markers."""
    points = rolling(daily)
    first, last = points[0][0], points[-1][0]
    index = dict((d, i) for i, (d, _) in enumerate(points))
    counts = dict((d, [k, n]) for d, k, n in daily if n)
    return {
        "labels": [_day(d) for d, _ in points],
        "rate": [round(100 * r, 1) if r is not None else None for _, r in points],
        "counts": [counts.get(d) for d, _ in points],
        "windows": [{"label": label, "start": index[max(w[0], first)], "end": index[min(w[1], last)],
                     "avg": round(rate, 1)} for label, w, rate in windows if w[0] <= last and w[1] >= first],
        "markers": [{"i": index[d], "kind": kind, "label": "%s, %s" % (_day(d), _marker_label(kind, label))}
                    for d, kind, label in markers if d in index],
    }


# ---------- HTML sections ----------

# Icon paths from Tabler Icons 3.19 outline (MIT), inlined so the report loads nothing from the web.
ICONS: Dict[str, str] = {
    "good": '<path d="M5 12l5 5l10 -10"/>',
    "warning": '<path d="M12 9v4"/><path d="M10.363 3.591l-8.106 13.534a1.914 1.914 0 0 0 1.636 2.871h16.214'
               'a1.914 1.914 0 0 0 1.636 -2.87l-8.106 -13.536a1.914 1.914 0 0 0 -3.274 0z"/><path d="M12 16h.01"/>',
    "critical": '<path d="M18 6l-12 12"/><path d="M6 6l12 12"/>',
    "neutral": '<path d="M5 12l14 0"/>',
    "calendar": '<path d="M4 7a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2v-12z"/>'
                '<path d="M16 3v4"/><path d="M8 3v4"/><path d="M4 11h16"/><path d="M11 15h1"/><path d="M12 15v3"/>',
    "message-report": '<path d="M18 4a3 3 0 0 1 3 3v8a3 3 0 0 1 -3 3h-5l-5 3v-3h-2a3 3 0 0 1 -3 -3v-8a3 3 0 0 1 3 -3h12z"/>'
                      '<path d="M12 8v3"/><path d="M12 14v.01"/>',
    "robot": '<path d="M6 4m0 2a2 2 0 0 1 2 -2h8a2 2 0 0 1 2 2v4a2 2 0 0 1 -2 2h-8a2 2 0 0 1 -2 -2z"/><path d="M12 2v2"/>'
             '<path d="M9 12v9"/><path d="M15 12v9"/><path d="M5 16l4 -2"/><path d="M15 14l4 2"/><path d="M9 18h6"/>'
             '<path d="M10 8v.01"/><path d="M14 8v.01"/>',
    "adjustments-horizontal": '<path d="M14 6m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M4 6l8 0"/><path d="M16 6l4 0"/>'
                              '<path d="M8 12m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M4 12l2 0"/>'
                              '<path d="M10 12l10 0"/><path d="M17 18m-2 0a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/>'
                              '<path d="M4 18l11 0"/><path d="M19 18l1 0"/>',
    "terminal-2": '<path d="M8 9l3 3l-3 3"/><path d="M13 15l3 0"/>'
                  '<path d="M3 4m0 2a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2z"/>',
    "chart-line": '<path d="M4 19l16 0"/><path d="M4 15l4 -6l4 2l4 -5l4 4"/>',
    "quote": '<path d="M10 11h-4a1 1 0 0 1 -1 -1v-3a1 1 0 0 1 1 -1h3a1 1 0 0 1 1 1v6c0 2.667 -1.333 4.333 -4 5"/>'
             '<path d="M19 11h-4a1 1 0 0 1 -1 -1v-3a1 1 0 0 1 1 -1h3a1 1 0 0 1 1 1v6c0 2.667 -1.333 4.333 -4 5"/>',
    "table": '<path d="M3 5a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2v14a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2v-14z"/>'
             '<path d="M3 10h18"/><path d="M10 3v18"/>',
    "info-circle": '<path d="M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0"/><path d="M12 9h.01"/><path d="M11 12h1v4h1"/>',
    "eye": '<path d="M10 12a2 2 0 1 0 4 0a2 2 0 0 0 -4 0"/>'
           '<path d="M21 12c-2.4 4 -5.4 6 -9 6c-3.6 0 -6.6 -2 -9 -6c2.4 -4 5.4 -6 9 -6c3.6 0 6.6 2 9 6"/>',
    "checks": '<path d="M7 12l5 5l10 -10"/><path d="M2 12l5 5m5 -5l5 -5"/>',
    "arrows-diff": '<path d="M11 16h10"/><path d="M11 16l4 4"/><path d="M11 16l4 -4"/><path d="M13 8h-10"/>'
                   '<path d="M13 8l-4 4"/><path d="M13 8l-4 -4"/>',
    "activity": '<path d="M3 12h4l3 8l4 -16l3 8h4"/>',
    "target": '<path d="M12 12m-1 0a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"/><path d="M12 12m-5 0a5 5 0 1 0 10 0a5 5 0 1 0 -10 0"/>'
              '<path d="M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0 -18 0"/>',
    "file-text": '<path d="M14 3v4a1 1 0 0 0 1 1h4"/>'
                 '<path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2z"/>'
                 '<path d="M9 9l1 0"/><path d="M9 13l6 0"/><path d="M9 17l6 0"/>',
    "folder": '<path d="M5 4h4l3 3h7a2 2 0 0 1 2 2v8a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2v-11a2 2 0 0 1 2 -2"/>',
}
CONFIDENCE_BARS = {"Low": 1, "Medium": 2, "High": 3}


def _icon(name: str) -> str:
    return '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">%s</svg>' % ICONS[name]


def _tile(name: str) -> str:
    return '<span class="tile">%s</span>' % _icon(name)


def _status(kind: str, word: str) -> str:
    return '<span class="status %s">%s%s</span>' % (kind, _icon(kind), word)


def _question(a: Analysis) -> str:
    return "Is %s nerfed?" % (model_name(a.model) if a.model else "your model")


def _window_chip(label: str, w: Window) -> str:
    return '<span class="chip">%s<strong>%s</strong> %s</span>' % (_icon("calendar"), label, span(w))


def _header(a: Analysis) -> str:
    when = ""
    if a.base and a.recent:
        when = '<div class="windows">%s%s</div>' % (_window_chip("Before", a.base), _window_chip("Now", a.recent))
    return '<header><h1>%s</h1>%s</header>' % (escape(_question(a)), when)


def _meter(level: str) -> str:
    on = CONFIDENCE_BARS[level]
    return '<span class="meter" aria-hidden="true">%s</span>' % "".join(
        '<i class="%s"></i>' % ("on" if i < on else "") for i in range(3))


def _verdict_panel(a: Analysis) -> str:
    if a.status != "ok":
        return ('<section class="verdict neutral"><span class="verdict-icon">%s</span><div>'
                '<p class="verdict-word">No verdict yet</p><p class="verdict-text">%s</p></div></section>'
                % (_icon("neutral"), escape(_no_verdict_text(a))))
    kind, word = VERDICTS[a.verdict][:2]
    level, reason = _confidence(a)
    cause = ""
    if a.verdict in WORSE and a.attribution:
        cause = '<p class="cause">%s<span><strong>Probable cause:</strong> Claude Code %s.</span></p>' % (
            _icon("terminal-2"), escape("; ".join(a.attribution)))
    return ('<section class="verdict %s"><span class="verdict-icon">%s</span><div>'
            '<p class="verdict-word">%s</p><p class="verdict-text">%s</p>%s'
            '<p class="confidence">%s<strong>%s confidence</strong> %s</p></div></section>'
            % (kind, _icon(kind), word, escape(_verdict_detail(a)), cause, _meter(level), level, escape(reason)))


def _category(area: str, icon: str, title: str, status: str, body: str) -> str:
    return ('<article class="category %s"><div class="category-head">%s<h2>%s</h2>%s</div>%s</article>'
            % (area, _tile(icon), title, status, body))


def _mistakes_status(a: Analysis) -> str:
    if a.verdict in WORSE:
        return _status(VERDICTS[a.verdict][0], "Higher")
    if a.verdict in BETTER:
        return _status("good", "Lower")
    if a.verdict == "too_few_events":
        return _status("neutral", "Too few events")
    return _status("good", "Same")


def _delta(a: Analysis) -> str:
    """The change in points, colored by the verdict and not by the sign, so noise never looks alarming."""
    kind = VERDICTS[a.verdict][0] if a.verdict in WORSE or a.verdict in BETTER else "neutral"
    return '<span class="delta %s">%s</span>' % (kind, _pts(a.boot.diff))


def _mistakes_figures(a: Analysis) -> str:
    """The two rates as large figures with their counts; no change chip when no prompt has a mistake."""
    b = a.boot
    figure = ('<div><span class="figure%s">%s</span><span class="caption"><strong>%s</strong><br>%d of %d prompts'
              '</span>%s</div>')
    return ('<div class="figures">%s<span class="arrow" aria-hidden="true">→</span>%s</div>'
            % (figure % ("", _pct(b.base_rate), "Before", b.k_base, b.n_base, ""),
               figure % (" now", _pct(b.recent_rate), "Now", b.k_recent, b.n_recent,
                         _delta(a) if b.k_base or b.k_recent else "")))


def _behavior_status(a: Analysis) -> str:
    if not a.signals:
        return _status("neutral", "Too few events")
    directions = {r.direction for r in a.signals}
    if "up" in directions:
        return _status("warning", "Higher")
    if "down" in directions:
        return _status("good", "Lower")
    return _status("good", "Same")


def _signal_values(r: SignalResult) -> str:
    if r.signal.scale == 100:
        return "%.1f%% → %.1f%% of %ss" % (r.base_rate, r.recent_rate, r.signal.per)
    return "%.1f → %.1f per 1,000 %s calls" % (r.base_rate, r.recent_rate, r.signal.per)


def _signal_tag(r: SignalResult) -> str:
    if r.direction == "up":
        return '<span class="tag warning">↑ %.1f×</span>' % r.ratio
    return '<span class="tag good">↓ %.1f×</span>' % r.ratio


def _behavior_body(a: Analysis) -> str:
    """A row per signal that moved, and one line that names the signals that did not."""
    moved = _moved(a.signals)
    if not moved:
        return "<p>%s</p>" % escape(_behavior_text(a))
    rows = '<ul class="signals">%s</ul>' % "".join(
        '<li class="signal-row"><span><strong>%s</strong><span class="caption">%s</span></span>%s</li>'
        % (escape(_cap(r.signal.name)), escape(_signal_values(r)), _signal_tag(r)) for r in moved)
    same = [r.signal.name for r in a.signals if not r.direction]
    return rows + ("<p>No change in %s.</p>" % escape(", ".join(same)) if same else "")


def _setup_status(a: Analysis) -> str:
    return _status("warning", "Changed") if _setup_parts(a) else _status("good", "Same")


def _facts(items: List[Tuple[str, str]]) -> str:
    """A list of icon names and HTML lines."""
    return '<ul class="facts">%s</ul>' % "".join("<li>%s<span>%s</span></li>" % (_icon(i), html) for i, html in items)


def _setup_body(a: Analysis) -> str:
    parts = _setup_parts(a)
    if not parts:
        return "<p>%s</p>" % escape(_setup_text(a))
    return _facts([(icon, escape(text)) for icon, text in parts])


def _claude_code_status(a: Analysis) -> str:
    if a.attribution and a.verdict in WORSE:
        return _status("warning", "Check")
    if not a.overlay_ok:
        return _status("neutral", "Not checked")
    if a.harness:
        return _status("neutral", "Updated")
    return _status("good", "Same")


def _claude_code_body(a: Analysis) -> str:
    if not a.harness:
        return "<p>%s</p>" % escape(_claude_code_text(a))
    return _facts([("terminal-2", "<strong>%s</strong> %s.<br>%s" % (
        escape(h["version"]), escape(h["line"]), escape(h["reason"]))) for h in a.harness])


def _categories(a: Analysis) -> str:
    """The possible causes first (your setup, Claude Code), then the evidence (mistakes, behavior)."""
    if a.status != "ok":
        return ""
    return '<section class="categories">%s%s%s%s</section>' % (
        _category("setup", "adjustments-horizontal", "Your setup", _setup_status(a), _setup_body(a)),
        _category("code", "terminal-2", "Claude Code", _claude_code_status(a), _claude_code_body(a)),
        _category("mistakes", "message-report", "Model mistakes", _mistakes_status(a), _mistakes_figures(a)),
        _category("behavior", "robot", "Agent behavior", _behavior_status(a), _behavior_body(a)))


def _section_head(icon: str, title: str, meta: str = "") -> str:
    return ('<div class="section-head">%s<div><h2>%s</h2>%s</div></div>'
            % (_tile(icon), title, '<p class="meta">%s</p>' % meta if meta else ""))


def _trend(a: Analysis) -> str:
    if not a.daily:
        return ""
    # Versions share one legend entry (the chart tooltip names each one); incidents keep their own.
    marks = "".join('<li><span class="key incident"></span>%s, %s</li>' % (_day(d), escape(label))
                    for d, kind, label in a.markers if kind == "incident")
    if any(kind == "version" for _, kind, _ in a.markers):
        marks = '<li><span class="key version"></span>Claude Code update</li>' + marks
    return ('<section class="trend">%s'
            '<figure><div class="chart-box"><canvas id="trend" role="img" aria-label="Share of prompts with a '
            'model mistake, as a 5-day rate"></canvas></div><figcaption><ul class="legend">'
            '<li><span class="key roll"></span>5-day rate</li><li><span class="key avg"></span>Window average</li>'
            '%s</ul></figcaption></figure></section>'
            % (_section_head("chart-line", "Model mistakes by day",
                             "Prompts where you corrected the model, as a 5-day rate."), marks))


def _details(icon: str, title: str, body: str) -> str:
    return ('<details><summary>%s<span class="summary-title">%s</span></summary>'
            '<div class="details-body">%s</div></details>' % (
        _tile(icon), title, body))


def _receipts(label: str, w: Window, items: List[dict]) -> str:
    body = "".join('<figure class="receipt">%s<blockquote>%s</blockquote><figcaption><strong>%s.</strong> %s'
                   '</figcaption></figure>'
                   % (_icon("quote"), escape(r["quote"]), _day(date.fromisoformat(r["date"])), escape(r["reason"]))
                   for r in items) or '<p>No model mistakes in this window.</p>'
    return '<div><h3><span class="chip"><strong>%s</strong> %s</span></h3>%s</div>' % (label, span(w), body)


def _examples(a: Analysis) -> str:
    if not a.receipts:
        return ""
    return _details("quote", "Examples where you corrected the model",
                    '<p class="note">These quotes are your own prompts. This file stays on your computer.</p>'
                    '<div class="receipts">%s%s</div>'
                    % (_receipts("Before", a.base, a.receipts.get("base", [])),
                       _receipts("Now", a.recent, a.receipts.get("recent", []))))


def _projects(top: List[Tuple[str, float]], short: Dict[str, str]) -> str:
    return "<br>".join("%s %s" % (escape(short[n]), _pct(100 * s)) for n, s in top) or "none"


# The setup numbers the cards do not show; the table keeps only the rows that changed.
SIDE_ROWS = [
    ("Median prompt length", lambda s, short: "%d characters" % s["median_prompt_chars"]),
    ("Project mix", lambda s, short: _projects(s["top_projects"], short)),
    ("Compactions per session", lambda s, short: "%.1f" % s["compactions_per_session"]),
    ("Tool error rate", lambda s, short: "%.1f%%" % (100 * s["tool_error_rate"])),
    ("Your edits to agent edits", lambda s, short: str(s["user_edits"])),
    ("Output tokens per prompt", lambda s, short: "{:,.0f}".format(s["output_tokens_per_prompt"])),
]


def _stat(label: str, value: str) -> str:
    return '<div class="stat"><span class="caption">%s</span><strong>%s</strong></div>' % (label, value)


def _numbers(a: Analysis) -> str:
    if a.status != "ok":
        return ""
    out = []
    b = a.boot
    if b.k_base or b.k_recent:
        out.append('<div class="stats">%s%s</div>'
                   % (_stat("Mistakes now vs before", _times(b.ratio)),
                      _stat("90% interval", "%s to %s" % (_times(b.ratio_lo), _times(b.ratio_hi)))))
    if a.side:
        short = _side_names(a.side)
        rows = [(label, cell(a.side["base"], short), cell(a.side["recent"], short)) for label, cell in SIDE_ROWS]
        rows = [r for r in rows if r[1] != r[2]]
        if rows:
            out.append('<h3>Other setup changes</h3><table><thead><tr><th></th><th>Before</th><th>Now</th></tr>'
                       '</thead><tbody>%s</tbody></table>'
                       % "".join('<tr><th scope="row">%s</th><td>%s</td><td>%s</td></tr>' % r for r in rows))
    if a.compare is not None:
        c = a.compare
        out.append('<h3>Against %s</h3><p>Less controlled: different weeks. Verdict: %s. %s: %s of %d prompts. '
                   '%s: %s of %d prompts.</p>'
                   % (escape(model_name(a.prev_model)), VERDICTS[a.compare_verdict][2],
                      escape(model_name(a.prev_model)), _pct(c.base_rate), c.n_base,
                      escape(model_name(a.model)), _pct(c.recent_rate), c.n_recent))
    return _details("table", "All numbers", "".join(out)) if out else ""


METHOD_STEPS = [
    ("eye", "A Sonnet judge reads a sample of your prompts."),
    ("checks", "It marks each prompt where you corrected a model mistake."),
    ("arrows-diff", "The report compares that share now with the share before."),
    ("activity", 'Agent behavior comes from your logs, with no judge. A firm "worse" verdict needs it to rise too.'),
]


def _method(a: Analysis) -> str:
    steps = list(METHOD_STEPS)
    if a.judge_agreement is not None:
        steps.append(("target", "The judge got %s of the test prompts right." % _pct(100 * a.judge_agreement)))
    return _details("info-circle", "How this works", '<ol class="steps">%s</ol>' % "".join(
        "<li>%s<span>%s</span></li>" % (_tile(icon), escape(text)) for icon, text in steps))


def _script_json(data: dict) -> str:
    return json.dumps(data).replace("</", "<\\/")


def render(a: Analysis) -> str:
    trend = trend_data(a.daily, a.markers, chart_windows(a)) if a.daily else None
    return Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        font=base64.b64encode(FONT.read_bytes()).decode("ascii"),
        chartjs=CHARTJS.read_text(encoding="utf-8") if trend else "",
        trend_data=_script_json(trend) if trend else "null",
        title=escape(_question(a)),
        header=_header(a),
        verdict=_verdict_panel(a),
        categories=_categories(a),
        trend=_trend(a),
        details=_examples(a) + _numbers(a) + _method(a),
    )
