"""Turn an Analysis into the 5-line terminal summary and one self-contained HTML report."""
from __future__ import annotations

import math
import re
from datetime import date
from html import escape
from pathlib import Path
from string import Template
from typing import Dict, List, Optional, Tuple

from analyze import Analysis
from stats import BootResult, Window

VERDICT_TEXT: Dict[str, str] = {
    "no_change": "no change",
    "slightly_worse": "slightly worse",
    "clearly_worse": "clearly worse",
    "better": "better",
    "leaning_worse": "probably worse",
    "leaning_better": "probably better",
}
WORSE = {"slightly_worse", "clearly_worse", "leaning_worse"}
STATUS_TEXT: Dict[str, str] = {
    "too_early": "too early: fewer than 3 active days, no verdict yet",
    "judge_drift": "no verdict: the judge matched only %s of the anchor labels (it needs 80%%)",
    "no_model": "no verdict: no model found in the last 7 days",
    "no_labels": "no verdict: one window has no labeled prompts",
}
Z90 = 1.645
ROLL_DAYS = 5
SHORT_TAIL = 30
TEMPLATE = Path(__file__).with_name("report_template.html")


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
        return "%s–%d" % (_day(start), end.day)
    return "%s–%s" % (_day(start), _day(end))


def _pct(x: float) -> str:
    return "%.0f%%" % x


def _pts(x: float) -> str:
    return "%+d pts" % int(round(x))


def probability(verdict: str, boot: BootResult) -> str:
    if verdict == "no_change":
        return "90% interval inside ±5 pts"
    p = boot.p_worse if verdict in WORSE else 1 - boot.p_worse
    return "%.0f%% probability" % (100 * p)


def short_projects(names: List[str]) -> Dict[str, str]:
    """Strip the dash-bounded prefix all names share; fall back to the last 30 characters."""
    unique = sorted(set(names))
    prefix = "" if len(unique) == 1 else _common_prefix(unique)
    prefix = prefix[:prefix.rfind("-") + 1]
    out = {}
    for name in unique:
        rest = name[len(prefix):]
        if not rest or len(rest) > SHORT_TAIL:
            rest = name if len(name) <= SHORT_TAIL else "…" + name[-SHORT_TAIL:]
        out[name] = rest
    return out


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


def _status_text(a: Analysis) -> str:
    text = STATUS_TEXT[a.status]
    return text % _pct(100 * a.judge_agreement) if a.status == "judge_drift" else text


# ---------- terminal ----------

def _side_line(side: Dict[str, dict]) -> str:
    base, recent = side["base"], side["recent"]
    parts = []
    if recent["claude_md_edits"] > 0:
        parts.append("CLAUDE.md changed %d×" % recent["claude_md_edits"])
    if base["cli_versions"] and recent["cli_versions"] and base["cli_versions"] != recent["cli_versions"]:
        parts.append("CLI %s → %s" % (base["cli_versions"][0], recent["cli_versions"][-1]))
    if base["top_projects"] and recent["top_projects"]:
        top_b, top_r = base["top_projects"][0][0], recent["top_projects"][0][0]
        if top_b != top_r:
            short = _side_names(side)
            parts.append("top project %s → %s" % (short[top_b], short[top_r]))
    return "Your side: " + (", ".join(parts) if parts else "no change found")


def _harness_line(a: Analysis) -> str:
    if not a.overlay_ok:
        return "Harness: changelog not available: offline"
    return "Harness: " + ("; ".join(a.attribution) if a.attribution else "no known change")


def _display_path(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home):] if text.startswith(home + "/") else text


def summary(a: Analysis, report_path: Path) -> List[str]:
    name = model_name(a.model)
    last = "Report: " + _display_path(report_path)
    if a.status != "ok":
        return ["%s — %s%s" % (name, _status_text(a), _counts(a)), last]
    b = a.boot
    return [
        "%s — %s (%s)" % (name, VERDICT_TEXT[a.verdict], probability(a.verdict, b)),
        "Model-caused steering: %s → %s (%s), %s vs %s" % (
            _pct(b.base_rate), _pct(b.recent_rate), _pts(b.diff), span(a.base), span(a.recent)),
        _side_line(a.side),
        _harness_line(a),
        last,
    ]


# ---------- chart ----------

def wilson(k: int, n: int, z: float = Z90) -> Tuple[float, float]:
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def rolling(daily: List[Tuple[date, int, int]]) -> List[Tuple[Optional[date], float, float, float]]:
    """Per entry: pooled rate and Wilson band over up to 5 labeled days within 5 calendar days."""
    out = []
    for i, (d, _, n) in enumerate(daily):
        if n == 0:
            out.append((None, 0.0, 0.0, 0.0))
            continue
        pool = [(k2, n2) for d2, k2, n2 in daily[:i + 1]
                if n2 > 0 and (d - d2).days < ROLL_DAYS][-ROLL_DAYS:]
        k_sum, n_sum = sum(p[0] for p in pool), sum(p[1] for p in pool)
        lo, hi = wilson(k_sum, n_sum)
        out.append((d, k_sum / n_sum, lo, hi))
    return out


def _segments(points: list) -> List[list]:
    segs, cur = [], []
    for p in points:
        if p[0] is None:
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(p)
    if cur:
        segs.append(cur)
    return segs


def chart_svg(daily: List[Tuple[date, int, int]], markers: List[Tuple[date, str, str]],
              width: int = 720, height: int = 240) -> str:
    left, right, top, bottom = 40, 12, 12, 26
    plot_w, plot_h = width - left - right, height - top - bottom
    first = daily[0][0]
    days = max(1, (daily[-1][0] - first).days)
    roll = rolling(daily)
    peak = max([k / n for _, k, n in daily if n] + [p[3] for p in roll] + [0.1])
    y_max = min(1.0, math.ceil(peak * 10) / 10)

    def x(d: date) -> float:
        return left + plot_w * (d - first).days / days

    def y(rate: float) -> float:
        return top + plot_h * (1 - rate / y_max)

    parts = ['<svg class="chart" viewBox="0 0 %d %d" role="img" '
             'aria-label="Daily share of model-caused steering with a 5-day rolling line">' % (width, height)]
    for i in range(int(round(y_max * 10)) + 1):
        tick = i / 10
        if y_max > 0.5 and i % 2:
            continue
        parts.append('<line class="grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>'
                     '<text class="tick" x="%d" y="%.1f" text-anchor="end">%s</text>'
                     % (left, width - right, y(tick), y(tick), left - 6, y(tick) + 4, _pct(100 * tick)))
    for offset in range(0, days + 1, 7):
        d = date.fromordinal(first.toordinal() + offset)
        parts.append('<text class="tick" x="%.1f" y="%d" text-anchor="middle">%s</text>'
                     % (x(d), height - 8, _day(d)))
    for d, kind, label in markers:
        parts.append('<line class="mark %s" x1="%.1f" x2="%.1f" y1="%d" y2="%d"><title>%s, %s</title></line>'
                     % (kind, x(d), x(d), top, top + plot_h, _day(d), escape(_marker_label(kind, label))))
    segs = _segments(roll)
    band = " ".join(
        "M" + " L".join("%.1f %.1f" % (x(p[0]), y(p[3])) for p in seg)
        + " L" + " L".join("%.1f %.1f" % (x(p[0]), y(p[2])) for p in reversed(seg)) + " Z"
        for seg in segs)
    line = " ".join("M" + " L".join("%.1f %.1f" % (x(p[0]), y(p[1])) for p in seg) for seg in segs)
    parts.append('<path class="band" d="%s"/>' % band)
    parts.append('<path class="roll" d="%s"/>' % line)
    for d, k, n in daily:
        if n:
            parts.append('<circle class="dot" cx="%.1f" cy="%.1f" r="3.5"><title>%s: %d of %d (%s)</title></circle>'
                         % (x(d), y(k / n), _day(d), k, n, _pct(100 * k / n)))
    parts.append("</svg>")
    return "".join(parts)


# ---------- HTML sections ----------

def _hero(a: Analysis) -> str:
    name = escape(model_name(a.model))
    if a.status != "ok":
        text = _status_text(a) + _counts(a)
        return '<h1>%s</h1><p class="banner" role="status">%s.</p>' % (name, escape(text[:1].upper() + text[1:]))
    b = a.boot
    head = "%s shows no change" % name if a.verdict == "no_change" else "%s is %s" % (
        name, VERDICT_TEXT[a.verdict])
    out = ['<h1>%s</h1>' % head,
           '<p class="lead">Model-caused steering went from %s to %s of your labeled prompts (%s): '
           '%s, 90%% interval %+.0f to %+.0f pts.</p>'
           % (_pct(b.base_rate), _pct(b.recent_rate), _pts(b.diff),
              probability(a.verdict, b), b.lo, b.hi),
           '<p class="meta">First days %s, %d prompts. Recent %s, %d prompts.</p>'
           % (span(a.base), b.n_base, span(a.recent), b.n_recent)]
    if a.shared_verdict:
        out.append('<p class="note">Your project mix changed. On projects that appear in both windows, '
                   'the verdict is %s; on all projects, it is %s.</p>'
                   % (VERDICT_TEXT[a.shared_verdict], VERDICT_TEXT[a.verdict]))
    if a.judge_agreement is not None:
        out.append('<p class="meta">The judge matched %s of the anchor labels.</p>'
                   % _pct(100 * a.judge_agreement))
    return "".join(out)


def _chart_section(a: Analysis) -> str:
    if not a.daily:
        return ""
    marks = "".join('<li><span class="key %s"></span>%s, %s</li>'
                    % (kind, _day(d), escape(_marker_label(kind, label)))
                    for d, kind, label in a.markers)
    rows = "".join("<tr><td>%s</td><td>%d</td><td>%d</td><td>%s</td></tr>"
                   % (_day(d), k, n, _pct(100 * k / n) if n else "no labels")
                   for d, k, n in a.daily)
    return (
        '<section><h2>Model-caused steering by day</h2>'
        '<p class="meta">A prompt counts when you corrected the agent for a mistake the model made.</p>'
        '<figure>%s<figcaption><ul class="legend">'
        '<li><span class="key dot"></span>one day</li>'
        '<li><span class="key roll"></span>5-day pooled rate, band is the 90%% interval</li>'
        '%s</ul></figcaption></figure>'
        '<details><summary>Daily counts</summary><table><thead><tr><th>Day</th><th>Steering</th>'
        '<th>Labeled</th><th>Share</th></tr></thead><tbody>%s</tbody></table></details></section>'
        % (chart_svg(a.daily, a.markers), marks, rows))


def _compare_section(a: Analysis) -> str:
    if a.compare is None:
        return ""
    c = a.compare
    return ('<section><h2>Model against model</h2>'
            '<p>Against %s, less controlled: different weeks. Verdict: %s.</p>'
            '<p class="meta">%s in its last window: %s of %d prompts. %s recent: %s of %d prompts.</p>'
            '</section>'
            % (escape(model_name(a.prev_model)), VERDICT_TEXT[a.compare_verdict],
               escape(model_name(a.prev_model)), _pct(c.base_rate), c.n_base,
               escape(model_name(a.model)), _pct(c.recent_rate), c.n_recent))


def _projects(top: List[Tuple[str, float]], short: Dict[str, str]) -> str:
    return "<br>".join("%s %s" % (escape(short[n]), _pct(100 * s)) for n, s in top) or "none"


SIDE_ROWS = [
    ("CLAUDE.md edits", lambda s, short: str(s["claude_md_edits"])),
    ("CLI versions", lambda s, short: escape(", ".join(s["cli_versions"])) or "none"),
    ("Median prompt length", lambda s, short: "%d characters" % s["median_prompt_chars"]),
    ("Project mix", lambda s, short: _projects(s["top_projects"], short)),
    ("Compactions per session", lambda s, short: "%.1f" % s["compactions_per_session"]),
    ("Interrupts per 100 prompts", lambda s, short: "%.1f" % (100 * s["interrupts_per_prompt"])),
    ("Tool error rate", lambda s, short: "%.1f%%" % (100 * s["tool_error_rate"])),
    ("Your edits to agent edits", lambda s, short: str(s["user_edits"])),
    ("Output tokens per prompt", lambda s, short: "{:,.0f}".format(s["output_tokens_per_prompt"])),
]


def _side_section(a: Analysis) -> str:
    if not a.side:
        return ""
    short = _side_names(a.side)
    rows = "".join('<tr><th scope="row">%s</th><td>%s</td><td>%s</td></tr>'
                   % (label, cell(a.side["base"], short), cell(a.side["recent"], short))
                   for label, cell in SIDE_ROWS)
    return ('<section><h2>Is it you?</h2>'
            '<p class="meta">Changes on your side can move the rate too.</p>'
            '<table class="side"><thead><tr><th></th><th>First days<br><span>%s</span></th>'
            '<th>Recent<br><span>%s</span></th></tr></thead><tbody>%s</tbody></table></section>'
            % (span(a.base), span(a.recent), rows))


def _harness_section(a: Analysis) -> str:
    if a.base is None:
        return ""
    if not a.overlay_ok:
        return '<section><h2>Harness changes</h2><p>changelog not available: offline</p></section>'
    out = ['<section><h2>Harness changes</h2>']
    if a.attribution:
        out.append('<p>Possible causes in the recent window:</p><ul class="causes">%s</ul>'
                   % "".join("<li>%s</li>" % escape(line) for line in a.attribution))
    changes = [h for h in a.harness if h.get("affects_behavior") == "yes"]
    if changes:
        out.append('<p class="meta">CLI changes in both windows that can change model behavior:</p><dl>%s</dl>'
                   % "".join("<dt>%s</dt><dd>%s<span>%s</span></dd>"
                             % (escape(h["version"]), escape(h["line"]), escape(h["reason"]))
                             for h in changes))
    else:
        out.append("<p>No CLI change in these windows can change model behavior.</p>")
    out.append("</section>")
    return "".join(out)


def _receipts(title: str, items: List[dict]) -> str:
    body = "".join('<figure class="receipt"><blockquote>%s</blockquote><figcaption>%s. %s</figcaption></figure>'
                   % (escape(r["quote"]), _day(date.fromisoformat(r["date"])), escape(r["reason"]))
                   for r in items) or '<p class="meta">No model-caused steering in this window.</p>'
    return "<div><h3>%s</h3>%s</div>" % (title, body)


def _evidence_section(a: Analysis) -> str:
    if not a.receipts:
        return ""
    return ('<section><h2>Evidence</h2><p class="meta">The worst model-caused moments, in your words.</p>'
            '<div class="receipts">%s%s</div></section>'
            % (_receipts("First days, " + span(a.base), a.receipts.get("base", [])),
               _receipts("Recent, " + span(a.recent), a.receipts.get("recent", []))))


def render(a: Analysis) -> str:
    return Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        title=escape("Is it nerfed? " + model_name(a.model)),
        hero=_hero(a),
        chart=_chart_section(a),
        compare=_compare_section(a),
        side=_side_section(a),
        harness=_harness_section(a),
        evidence=_evidence_section(a),
    )
