"""Turn an Analysis into the terminal summary and one self-contained HTML report."""
from __future__ import annotations

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
    "judge_drift": "no verdict: the judge matched only %s of the anchor labels (it needs 80%%)",
    "no_labels": "no verdict: one window has no labeled prompts",
}
ROLL_DAYS = 5
SHORT_TAIL = 30
TITLE_WIDTH = 16
LOW_DAYS, LOW_PROMPTS = 5, 50
HIGH_DAYS, HIGH_PROMPTS = 7, 150
TEMPLATE = Path(__file__).with_name("report_template.html")
CHARTJS = Path(__file__).with_name("vendor") / "chart.umd.min.js"


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


def _times_interval(ratio: float, lo: float, hi: float) -> str:
    return "%s (%s to %s)" % (_times(ratio), _times(lo), _times(hi))


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


def _setup_parts(side: Dict[str, dict]) -> List[str]:
    """Sentences for each setup change that can affect the result."""
    base, recent = side["base"], side["recent"]
    parts = []
    if recent["claude_md_edits"] > 0:
        parts.append("CLAUDE.md changed %d×." % recent["claude_md_edits"])
    if base["top_projects"] and recent["top_projects"]:
        top_b, top_r = base["top_projects"][0][0], recent["top_projects"][0][0]
        if top_b != top_r:
            short = short_projects([top_b, top_r])
            parts.append("Main project changed: %s → %s." % (short[top_b], short[top_r]))
    return parts


def _setup_text(side: Dict[str, dict]) -> str:
    return " ".join(_setup_parts(side)) or "No change that can affect the result."


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


def _confidence_text(a: Analysis) -> str:
    b = a.boot
    labeled = [d for d, _, n in a.daily if n]
    recent_days = len([d for d in labeled if d >= a.recent[0]])
    if recent_days < LOW_DAYS:
        return "Low. Only %d recent day%s. Run again after %s." % (
            recent_days, "" if recent_days == 1 else "s", _day(a.recent[1] + timedelta(days=LOW_DAYS - recent_days)))
    fewest = min(b.n_base, b.n_recent)
    if fewest < LOW_PROMPTS:
        return "Low. Only %d prompts in one window." % fewest
    level = "High" if recent_days >= HIGH_DAYS and fewest >= HIGH_PROMPTS else "Medium"
    return "%s. %d prompts over %d days." % (level, b.n_base + b.n_recent, len(labeled))


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
        _titled("Your setup", _setup_text(a.side)),
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

# Icon paths from Tabler Icons (MIT), inlined so the report loads nothing from the web.
ICONS: Dict[str, str] = {
    "good": '<path d="M5 12l5 5l10 -10"/>',
    "warning": '<path d="M12 9v4"/><path d="M10.363 3.591l-8.106 13.534a1.914 1.914 0 0 0 1.636 2.871h16.214'
               'a1.914 1.914 0 0 0 1.636 -2.87l-8.106 -13.536a1.914 1.914 0 0 0 -3.274 0z"/><path d="M12 16h.01"/>',
    "critical": '<path d="M18 6l-12 12"/><path d="M6 6l12 12"/>',
    "neutral": '<path d="M5 12l14 0"/>',
}


def _status(kind: str, word: str) -> str:
    return ('<span class="status %s"><svg viewBox="0 0 24 24" aria-hidden="true">%s</svg>%s</span>'
            % (kind, ICONS[kind], word))


def _question(a: Analysis) -> str:
    return "Is %s nerfed?" % (model_name(a.model) if a.model else "your model")


def _header(a: Analysis) -> str:
    when = ""
    if a.base and a.recent:
        when = ('<p class="meta">Compares your %s prompts before (%s) with now (%s). Other models do not count.</p>'
                % (escape(model_name(a.model)), span(a.base), span(a.recent)))
    return '<header><p class="product">Model drift report</p><h1>%s</h1>%s</header>' % (escape(_question(a)), when)


def _verdict_panel(a: Analysis) -> str:
    if a.status != "ok":
        return ('<section class="verdict">%s<p class="verdict-text">%s</p></section>'
                % (_status("neutral", "No verdict yet"), escape(_no_verdict_text(a))))
    kind, word = VERDICTS[a.verdict][:2]
    detail = _verdict_detail(a)
    return ('<section class="verdict %s">%s<p class="verdict-text">%s</p>'
            '<p class="confidence"><strong>Confidence</strong> %s</p></section>'
            % (kind, _status(kind, word), escape(detail), escape(_confidence_text(a))))


def _category(title: str, status: str, text: str, visual: str = "") -> str:
    return ('<article class="category"><div class="category-head"><h2>%s</h2>%s</div><p>%s</p>%s</article>'
            % (title, status, escape(text), visual))


def _mistakes_status(a: Analysis) -> str:
    if a.verdict in WORSE:
        return _status(VERDICTS[a.verdict][0], "Higher")
    if a.verdict in BETTER:
        return _status("good", "Lower")
    return _status("good", "Same")


def _mistakes_visual(a: Analysis) -> str:
    """Two large figures and two plain bars on one shared scale."""
    b = a.boot
    widest = max(b.base_rate, b.recent_rate, 1.0)
    rows = (("before", "Before", b.base_rate, b.k_base, b.n_base),
            ("now", "Now", b.recent_rate, b.k_recent, b.n_recent))
    figures = ('<div class="figures"><div><span class="figure">%s</span><span class="caption">Before</span></div>'
               '<span class="arrow" aria-hidden="true">→</span>'
               '<div><span class="figure now">%s</span><span class="caption">Now</span></div></div>'
               % (_pct(b.base_rate), _pct(b.recent_rate)))
    bars = "".join('<div class="bar-row"><span class="caption">%s</span><span class="bar-track">'
                   '<span class="bar %s" style="width:%.1f%%" data-tip="%s: %d of %d prompts"></span>'
                   '</span></div>'
                   % (label, kind, max(100 * rate / widest, 1.5), label, k, n)
                   for kind, label, rate, k, n in rows)
    return figures + '<div class="bars">%s</div>' % bars


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
    if r.direction == "down":
        return '<span class="tag good">↓ %.1f×</span>' % r.ratio
    return '<span class="tag neutral">Same</span>'


def _signal_rows(results: List[SignalResult]) -> str:
    return '<ul class="signals">%s</ul>' % "".join(
        '<li class="signal-row"><span><strong>%s</strong><span class="caption">%s</span></span>%s</li>'
        % (escape(_cap(r.signal.name)), escape(_signal_values(r)), _signal_tag(r))
        for r in results) if results else ""


def _setup_status(a: Analysis) -> str:
    return _status("warning", "Changed") if _setup_parts(a.side) else _status("good", "Same")


def _claude_code_status(a: Analysis) -> str:
    if a.attribution and a.verdict in WORSE:
        return _status("warning", "Check")
    if not a.overlay_ok:
        return _status("neutral", "Not checked")
    return _status("good", "Same")


def _categories(a: Analysis) -> str:
    if a.status != "ok":
        return ""
    b = a.boot
    counts = "%d of %d prompts before, %d of %d now." % (b.k_base, b.n_base, b.k_recent, b.n_recent)
    return '<section class="categories">%s%s%s%s</section>' % (
        _category("Model mistakes", _mistakes_status(a), counts, _mistakes_visual(a)),
        _category("Agent behavior", _behavior_status(a), _behavior_text(a), _signal_rows(a.signals)),
        _category("Your setup", _setup_status(a), _setup_text(a.side)),
        _category("Claude Code", _claude_code_status(a), _claude_code_text(a)))


def _trend(a: Analysis) -> str:
    if not a.daily:
        return ""
    marks = "".join('<li><span class="key %s"></span>%s, %s</li>'
                    % (kind, _day(d), escape(_marker_label(kind, label)))
                    for d, kind, label in a.markers)
    return ('<section class="trend"><h2>Model mistakes by day</h2>'
            '<p class="meta">Share of your prompts where you corrected a mistake the model made, '
            'over 5 days. Point at a day to see its numbers.</p>'
            '<figure><div class="chart-box"><canvas id="trend" role="img" aria-label="Share of prompts with a '
            'model mistake, as a 5-day rate"></canvas></div><figcaption><ul class="legend">'
            '<li><span class="key roll"></span>5-day rate</li><li><span class="key avg"></span>Window average</li>'
            '%s</ul></figcaption></figure></section>'
            % marks)


def _receipts(title: str, items: List[dict]) -> str:
    body = "".join('<figure class="receipt"><blockquote>%s</blockquote><figcaption>%s. %s</figcaption></figure>'
                   % (escape(r["quote"]), _day(date.fromisoformat(r["date"])), escape(r["reason"]))
                   for r in items) or '<p class="meta">No model mistakes in this window.</p>'
    return "<div><h3>%s</h3>%s</div>" % (title, body)


def _examples(a: Analysis) -> str:
    if not a.receipts:
        return ""
    return ('<details><summary>Examples where you corrected the model</summary>'
            '<p class="meta">These quotes are your own prompts. This file stays on your computer.</p>'
            '<div class="receipts">%s%s</div></details>'
            % (_receipts("Before, " + span(a.base), a.receipts.get("base", [])),
               _receipts("Now, " + span(a.recent), a.receipts.get("recent", []))))


def _projects(top: List[Tuple[str, float]], short: Dict[str, str]) -> str:
    return "<br>".join("%s %s" % (escape(short[n]), _pct(100 * s)) for n, s in top) or "none"


SIDE_ROWS = [
    ("CLAUDE.md edits", lambda s, short: str(s["claude_md_edits"])),
    ("CLI versions", lambda s, short: escape(", ".join(s["cli_versions"])) or "none"),
    ("Median prompt length", lambda s, short: "%d characters" % s["median_prompt_chars"]),
    ("Project mix", lambda s, short: _projects(s["top_projects"], short)),
    ("Compactions per session", lambda s, short: "%.1f" % s["compactions_per_session"]),
    ("Tool error rate", lambda s, short: "%.1f%%" % (100 * s["tool_error_rate"])),
    ("Your edits to agent edits", lambda s, short: str(s["user_edits"])),
    ("Output tokens per prompt", lambda s, short: "{:,.0f}".format(s["output_tokens_per_prompt"])),
]


def _numbers(a: Analysis) -> str:
    if a.status != "ok":
        return ""
    out = ['<details><summary>All numbers</summary>']
    b = a.boot
    if b.k_base or b.k_recent:
        out.append('<p>Model mistakes: %s, 90%% interval %s to %s (%s).</p>'
                   % (_times(b.ratio), _times(b.ratio_lo), _times(b.ratio_hi), _pts(b.diff)))
    if a.shared_verdict:
        out.append('<p>Your project mix changed. On projects that appear in both windows, the verdict is %s; '
                   'on all projects, it is %s.</p>' % (VERDICTS[a.shared_verdict][2], VERDICTS[a.verdict][2]))
    if a.signals:
        out.append('<h3>Agent behavior</h3><table><thead><tr><th></th><th>Before</th><th>Now</th>'
                   '<th>Change, 95%% range</th></tr></thead><tbody>%s</tbody></table>'
                   % "".join('<tr><th scope="row">%s</th><td>%.1f</td><td>%.1f</td><td>%s</td></tr>'
                             % (escape(r.signal.label), r.base_rate, r.recent_rate,
                                _times_interval(r.ratio, r.lo, r.hi)) for r in a.signals))
    if a.side:
        short = _side_names(a.side)
        out.append('<h3>Your setup</h3><table><thead><tr><th></th><th>Before</th><th>Now</th></tr></thead>'
                   '<tbody>%s</tbody></table>'
                   % "".join('<tr><th scope="row">%s</th><td>%s</td><td>%s</td></tr>'
                             % (label, cell(a.side["base"], short), cell(a.side["recent"], short))
                             for label, cell in SIDE_ROWS))
    if a.harness:
        out.append('<h3>Claude Code changes that can change model quality</h3><dl>%s</dl>'
                   % "".join("<dt>%s</dt><dd>%s<span>%s</span></dd>"
                             % (escape(h["version"]), escape(h["line"]), escape(h["reason"])) for h in a.harness))
    if a.compare is not None:
        c = a.compare
        out.append('<h3>Against %s</h3><p>Less controlled: different weeks. Verdict: %s. %s: %s of %d prompts. '
                   '%s: %s of %d prompts.</p>'
                   % (escape(model_name(a.prev_model)), VERDICTS[a.compare_verdict][2],
                      escape(model_name(a.prev_model)), _pct(c.base_rate), c.n_base,
                      escape(model_name(a.model)), _pct(c.recent_rate), c.n_recent))
    out.append("</details>")
    return "".join(out)


def _method(a: Analysis) -> str:
    judge = ""
    if a.judge_agreement is not None:
        judge = " The judge matched %s of the anchor labels." % _pct(100 * a.judge_agreement)
    return ('<details><summary>How this works</summary>'
            '<p>A Sonnet judge reads a sample of your prompts. For each one, it decides if you corrected a '
            'mistake that the model made. The report compares the share of those prompts in the recent days '
            'with the share in the days before. Agent behavior counts come from your logs and use no judge. '
            'A firm "worse" verdict needs one of them to rise too.%s</p></details>' % judge)


def _script_json(data: dict) -> str:
    return json.dumps(data).replace("</", "<\\/")


def render(a: Analysis) -> str:
    trend = trend_data(a.daily, a.markers, chart_windows(a)) if a.daily else None
    return Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        chartjs=CHARTJS.read_text(encoding="utf-8") if trend else "",
        trend_data=_script_json(trend) if trend else "null",
        title=escape(_question(a)),
        header=_header(a),
        verdict=_verdict_panel(a),
        categories=_categories(a),
        trend=_trend(a),
        details=_examples(a) + _numbers(a) + _method(a),
    )
