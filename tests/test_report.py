from __future__ import annotations

import re
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

import report
from analyze import Analysis
from signals import SIGNALS, SignalResult
from stats import BootResult

START = date(2026, 9, 7)
DIR = "-Users-resit-orca-workspaces-"


def _daily():
    """28 active days; base rate near 9%, recent near 15%; day 20 has prompts but no labels."""
    rows = []
    for i in range(28):
        n = 0 if i == 20 else 8 + (i * 5) % 9
        rate = 0.09 if i < 14 else 0.15
        rows.append((START + timedelta(days=i), int(round(n * rate + (i % 3 - 1) * 0.6)) if n else 0, n))
    return rows


def _side(edits, versions, top, chars):
    return {"claude_md_edits": edits, "cli_versions": versions, "median_prompt_chars": chars,
            "top_projects": top, "compactions_per_session": 0.4,
            "tool_error_rate": 0.031, "user_edits": 6, "output_tokens_per_prompt": 1840.0}


def fixture(status: str = "ok") -> Analysis:
    """One plausible Analysis with every section filled; the preview uses the same data."""
    base, recent = (START, START + timedelta(days=13)), (START + timedelta(days=14), START + timedelta(days=27))
    return Analysis(
        status=status, model="claude-opus-5-5", prev_model="claude-opus-5-4",
        base=base, recent=recent,
        boot=BootResult(diff=6.2, p_worse=0.78, base_rate=9.1, recent_rate=15.3, k_base=15, k_recent=26,
                        n_base=160, n_recent=170, s_base=24, s_recent=26,
                        ratio=1.7, ratio_lo=1.1, ratio_hi=2.6),
        verdict="slightly_worse", shared_verdict="leaning_worse",
        compare=BootResult(diff=-1.0, p_worse=0.35, base_rate=16.3, recent_rate=15.3, k_base=23, k_recent=26,
                           n_base=140, n_recent=170, s_base=22, s_recent=26,
                           ratio=0.94, ratio_lo=0.6, ratio_hi=1.3),
        compare_verdict="leaning_better",
        daily=_daily(),
        markers=[(START + timedelta(days=9), "version", "2.1.280"),
                 (START + timedelta(days=17), "version", "2.1.285"),
                 (START + timedelta(days=22), "incident", "Elevated errors on Claude Code")],
        side={"base": _side(0, ["2.1.271", "2.1.280"],
                            [(DIR + "ai-team-journey-analyzer", 0.62), (DIR + "is-it-nerfed", 0.38)], 212),
              "recent": _side(2, ["2.1.285", "2.1.289"],
                              [(DIR + "is-it-nerfed", 0.55), (DIR + "ai-team-journey-analyzer", 0.45)], 240)},
        harness=[{"id": "h1", "version": "2.1.285", "line": "Changed the default effort to medium",
                  "affects_behavior": "yes", "reason": "Lower effort can mean shorter reasoning."}],
        receipts={"base": [{"date": "2026-09-12", "quote": "no, use the existing helper",
                            "reason": "The agent wrote a new helper."}],
                  "recent": [{"date": "2026-09-30", "quote": "you ignored the test I asked for",
                              "reason": "The agent skipped a stated step."},
                             {"date": "2026-10-02", "quote": "stop, that file is not in scope",
                              "reason": "The agent edited an unrelated file."}]},
        attribution=["2.1.285: default effort lowered to medium"],
        judge_agreement=0.93, overlay_ok=True,
        signals=[SignalResult(SIGNALS[0], 8.0, 9.1, 1.1, 0.7, 1.6),
                 SignalResult(SIGNALS[1], 1.2, 3.9, 3.2, 1.8, 5.5)],
    )


def too_early() -> Analysis:
    return Analysis(status="too_early", model="claude-opus-5-5",
                    daily=[(START, 1, 9), (START + timedelta(days=1), 0, 7)])


REPORT = Path("/data/report-2026-10-04.html")


class SummaryTest(unittest.TestCase):
    def test_summary_lines_worse(self):
        lines = report.summary(fixture(), REPORT)
        self.assertEqual(lines, [
            "Verdict:        Nerfed for you. Opus 5.5 is slightly worse for you (more mistakes in 78% of resamples).",
            "Model mistakes: 15 of 160 work prompts before (9%, Sep 7-20), 26 of 170 now (15%, Sep 21-Oct 4).",
            "Agent behavior: Interrupts 3.2× as often as before.",
            "Your setup:     CLAUDE.md changed 2×. Your project mix changed. On the same projects only, it is probably worse.",
            "Claude Code:    2.1.285: default effort lowered to medium. Same period; not tested as the cause.",
            "Confidence:     High. 330 work prompts over 27 days.",
            "Report:         /data/report-2026-10-04.html",
        ])

    def test_summary_no_change_keeps_every_title(self):
        a = fixture()
        a.verdict = "no_change"
        a.signals = [SignalResult(SIGNALS[0], 8.0, 9.1, 1.1, 0.7, 1.6)]
        a.side["recent"] = dict(a.side["base"], cli_versions=["2.1.280", "2.1.285", "2.1.289"])
        a.attribution, a.shared_verdict = [], None
        lines = report.summary(a, REPORT)
        self.assertEqual(lines[:5], [
            "Verdict:        Not nerfed. Opus 5.5 works as well for you as before.",
            "Model mistakes: 15 of 160 work prompts before (9%, Sep 7-20), 26 of 170 now (15%, Sep 21-Oct 4).",
            "Agent behavior: No change in blind edits.",
            "Your setup:     No CLAUDE.md or project mix change.",
            "Claude Code:    2 updates in the recent window. None can change model quality.",
        ])
        a.overlay_ok = False
        self.assertEqual(report.summary(a, REPORT)[4],
                         "Claude Code:    2 updates in the recent window. The changelog was not checked (offline).")
        a.side["recent"]["cli_versions"] = ["2.1.280"]
        self.assertEqual(report.summary(a, REPORT)[4], "Claude Code:    No update in the recent window.")

    def test_summary_behavior_without_enough_events(self):
        a = fixture()
        a.signals = []
        self.assertEqual(report.summary(a, REPORT)[2], "Agent behavior: Too few events to measure.")
        a.signals = [SignalResult(SIGNALS[0], 8.0, 9.1, 1.1, 0.7, 1.6), SignalResult(SIGNALS[2], 1.0, 1.1, 1.1, 0.5, 2)]
        self.assertEqual(report.summary(a, REPORT)[2], "Agent behavior: No change in blind edits or self-corrections.")

    def test_summary_verdict_words(self):
        a = fixture()
        cases = {
            "unclear": "No clear change. The data does not show a change either way.",
            "clearly_worse": "Nerfed for you. Opus 5.5 is clearly worse for you (more mistakes in 78% of resamples).",
            "leaning_worse": "Possibly nerfed. Opus 5.5 is probably worse for you (more mistakes in 78% of resamples). "
                             "A bad stretch of hard tasks looks the same.",
            "unconfirmed_worse": "Possibly nerfed. You corrected Opus 5.5 more often (in 78% of resamples), "
                                 "but its own behavior did not change. A bad stretch of hard tasks looks the same.",
            "better": "Not nerfed. Opus 5.5 is better for you (fewer mistakes in 22% of resamples).",
            "leaning_better": "Possibly better. Opus 5.5 is probably better for you (fewer mistakes in 22% of resamples).",
        }
        for verdict, text in cases.items():
            a.verdict = verdict
            self.assertEqual(report.summary(a, REPORT)[0], "Verdict:        " + text)

    def test_summary_too_few_events(self):
        a = fixture()
        a.verdict = "too_few_events"
        a.boot.k_base, a.boot.k_recent = 3, 6
        self.assertEqual(report.summary(a, REPORT)[0], "Verdict:        Not enough data. "
                         "The judge found only 9 model mistakes in both windows; a verdict needs 10.")

    def test_summary_names_a_cause_only_for_a_worse_verdict(self):
        a = fixture()
        a.verdict = "no_change"
        self.assertEqual(report.summary(a, REPORT)[4], "Claude Code:    2 updates in the recent window.")

    def test_summary_confidence_levels(self):
        a = fixture()
        a.daily = [(d, k, n) for d, k, n in a.daily if d <= a.recent[0] + timedelta(days=2)]
        self.assertEqual(report.summary(a, REPORT)[5],
                         "Confidence:     Low. Only 3 recent days. Run again after Oct 6.")

    def test_summary_setup_names_the_project_mix_only_when_it_changes_the_verdict(self):
        a = fixture()
        a.shared_verdict = None
        self.assertEqual(report.summary(a, REPORT)[3], "Your setup:     CLAUDE.md changed 2×.")

    def test_summary_confidence_low_and_medium(self):
        a = fixture()
        a.boot.n_base = 40
        self.assertEqual(report.summary(a, REPORT)[5], "Confidence:     Low. Only 40 work prompts in one window.")
        a.boot.n_base = 100
        self.assertEqual(report.summary(a, REPORT)[5], "Confidence:     Medium. 270 work prompts over 27 days.")

    def test_summary_too_early(self):
        lines = report.summary(too_early(), REPORT)
        self.assertEqual(lines, [
            "Verdict:        Too early: fewer than 3 active days, no verdict yet (16 labeled work prompts on 2 days).",
            "Report:         /data/report-2026-10-04.html",
        ])


class NamesTest(unittest.TestCase):
    def test_model_name(self):
        self.assertEqual(report.model_name("claude-opus-5-5"), "Opus 5.5")
        self.assertEqual(report.model_name("claude-sonnet-5"), "Sonnet 5")
        self.assertEqual(report.model_name("claude-haiku-4-5-20251001"), "Haiku 4.5")
        self.assertEqual(report.model_name("gpt-x"), "gpt-x")

    def test_short_projects_strip_common_prefix_at_dash(self):
        names = [DIR + "ai-team-x", DIR + "ai-tools"]
        self.assertEqual(report.short_projects(names), {names[0]: "team-x", names[1]: "tools"})

    def test_short_projects_cut_long_names_at_a_dash(self):
        names = [DIR + "ai-610-make-audience-creation-work-outside-the-u", DIR + "launch-ready"]
        self.assertEqual(report.short_projects(names),
                         {names[0]: "ai-610-make-audience-creation…", names[1]: "launch-ready"})

    def test_short_projects_single_name_falls_back_to_tail(self):
        name = DIR + "ai-team-journey-analyzer-launch-ready"
        self.assertEqual(report.short_projects([name]), {name: "…journey-analyzer-launch-ready"})
        self.assertEqual(report.short_projects(["-tmp-x"]), {"-tmp-x": "-tmp-x"})


class ChartTest(unittest.TestCase):
    def test_trend_data_spans_empty_days_and_uses_card_averages(self):
        a = fixture()
        data = report.trend_data(a.daily, a.markers, report.chart_windows(a))
        self.assertEqual(len(data["labels"]), 28)
        self.assertEqual(data["labels"][0], "Sep 7")
        self.assertIsNotNone(data["rate"][20])
        self.assertIsNone(data["counts"][20])
        self.assertEqual(data["counts"][17], [2, 12])
        self.assertEqual([(w["label"], w["avg"]) for w in data["windows"]], [("Before", 9.1), ("Now", 15.3)])
        self.assertEqual((data["windows"][1]["start"], data["windows"][1]["end"]), (14, 27))
        self.assertEqual([(m["i"], m["kind"]) for m in data["markers"]],
                         [(9, "version"), (17, "version"), (22, "incident")])

    def test_trend_data_skips_a_window_before_the_logs(self):
        a = fixture()
        old = (a.daily[0][0] - timedelta(days=30), a.daily[0][0] - timedelta(days=16))
        data = report.trend_data(a.daily, a.markers, [("Before", old, 5.0), ("Now", a.recent, 15.3)])
        self.assertEqual([w["label"] for w in data["windows"]], ["Now"])

    def test_chart_windows_empty_without_result(self):
        self.assertEqual(report.chart_windows(Analysis(status="too_early")), [])

    def test_rolling_gives_every_calendar_day_its_five_day_rate(self):
        d = START
        rows = [(d, 1, 10), (d + timedelta(days=1), 0, 0), (d + timedelta(days=2), 3, 10),
                (d + timedelta(days=9), 5, 10)]
        points = report.rolling(rows)
        self.assertEqual([p[0] for p in points], [d + timedelta(days=i) for i in range(10)])
        rates = [p[1] for p in points]
        self.assertAlmostEqual(rates[1], 0.1)
        self.assertAlmostEqual(rates[2], 0.2)
        self.assertAlmostEqual(rates[6], 0.3)
        self.assertEqual(rates[7:9], [None, None])
        self.assertAlmostEqual(rates[9], 0.5)


class RenderTest(unittest.TestCase):
    def test_render_sections_in_order(self):
        out = report.render(fixture())
        heads = ["Nerfed for you", "In the same period", "Your setup</h2>", "Claude Code</h2>", "Model mistakes</h2>",
                 "Agent behavior</h2>", "Model mistakes by day", "Examples where you corrected the model", "All numbers", "How this works"]
        positions = [out.index(h) for h in heads]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('<p class="verdict-text">Opus 5.5 is slightly worse for you (more mistakes in 78% of resamples).</p>', out)

    def test_render_verdict_names_the_probable_cause_only_when_worse(self):
        out = report.render(fixture())
        self.assertIn("<strong>In the same period:</strong> Claude Code 2.1.285: default effort lowered to medium. Not tested as the cause.", out)
        a = fixture()
        a.verdict = "no_change"
        self.assertNotIn("In the same period", report.render(a))

    def test_render_shows_each_fact_once(self):
        out = report.render(fixture())
        for text in ("+6 pts", "Changed the default effort to medium", "3.2×", "CLAUDE.md changed 2×",
                     "On the same projects only"):
            self.assertEqual(out.count(text), 1, text)
        self.assertNotIn("Compactions per session", out)
        self.assertIn("Median prompt length", out)

    def test_render_header_names_model_and_dates(self):
        out = report.render(fixture())
        self.assertIn("<title>Is Opus 5.5 nerfed?</title>", out)
        self.assertIn('<header><h1>Is Opus 5.5 nerfed?</h1>', out)
        self.assertIn('<strong>Before</strong> Sep 7-20</span>', out)
        self.assertIn('<strong>Now</strong> Sep 21-Oct 4</span>', out)

    def test_render_verdict_shows_confidence_level(self):
        out = report.render(fixture())
        self.assertIn('<strong>High confidence</strong> 330 work prompts over 27 days.', out)
        self.assertEqual(out.count('<i class="on">'), 3)

    def test_render_header_without_model_asks_generic_question(self):
        out = report.render(Analysis(status="too_early"))
        self.assertIn("<title>Is your model nerfed?</title>", out)
        self.assertIn("<h1>Is your model nerfed?</h1>", out)

    def test_render_status_words_per_category(self):
        out = report.render(fixture())
        for word in ("Higher", "Changed", "Check"):
            self.assertIn('class="status', out)
            self.assertIn(">%s<" % word, out)
        a = fixture()
        a.verdict, a.signals, a.attribution, a.shared_verdict = "no_change", a.signals[:1], [], None
        a.side["recent"] = dict(a.side["base"])
        out = report.render(a)
        self.assertIn("Not nerfed", out)
        self.assertNotIn(">Higher<", out)
        self.assertNotIn(">Changed<", out)

    def test_render_behavior_without_enough_events_is_not_same(self):
        a = fixture()
        a.signals = []
        out = report.render(a)
        self.assertIn(">Too few events<", out)

    def test_unclear_is_low_confidence_and_not_same(self):
        a = fixture()
        a.verdict = "unclear"
        self.assertEqual(report._confidence(a)[0], "Low")
        self.assertIn(">Unclear<", report._mistakes_status(a))

    def test_render_mistakes_with_too_few_events_is_not_same(self):
        a = fixture()
        a.verdict = "too_few_events"
        self.assertIn(">Too few events<", report._mistakes_status(a))

    def test_render_claude_code_with_behavior_updates_is_not_same(self):
        a = fixture()
        a.verdict = "no_change"
        out = report.render(a)
        self.assertIn(">Updated<", out)
        self.assertNotIn(">Check<", out)

    def test_render_behavior_has_rows_only_for_signals_that_moved(self):
        out = report.render(fixture())
        self.assertEqual(out.count('class="signal-row"'), 1)
        self.assertIn("1.2 → 3.9 per 1,000 tool calls", out)
        self.assertIn(">↑ 3.2×<", out)
        self.assertIn("<p>No change in blind edits.</p>", out)
        self.assertNotIn("8.0% → 9.1%", out)

    def test_render_mistakes_as_figures_with_counts(self):
        out = report.render(fixture())
        self.assertIn('class="verdict critical"', out)
        self.assertIn('<span class="figure">9%</span><span class="caption"><strong>Before</strong><br>15 of 160 work prompts', out)
        self.assertIn('<span class="figure now">15%</span><span class="caption"><strong>Now</strong><br>26 of 170 work prompts', out)

    def test_render_no_change_chip_when_no_prompt_has_a_mistake(self):
        a = fixture()
        a.boot.k_base = a.boot.k_recent = 0
        a.boot.base_rate = a.boot.recent_rate = 0.0
        out = report.render(a)
        self.assertIn('<span class="figure now">0%</span>', out)
        self.assertNotIn('class="delta', out)

    def test_render_legend_groups_versions_and_names_incidents(self):
        out = report.render(fixture())
        self.assertEqual(out.count('class="key version"'), 1)
        self.assertIn('<span class="key version"></span>Claude Code update</li>', out)
        self.assertIn('<span class="key incident"></span>Sep 29, Elevated errors on Claude Code</li>', out)
        self.assertNotIn("CLI 2.1.280</li>", out)

    def test_render_embeds_the_font(self):
        out = report.render(fixture())
        self.assertIn('src: url("data:font/woff2;base64,', out)

    def test_render_details_are_closed_and_hold_the_extras(self):
        out = report.render(fixture())
        self.assertNotIn("<details open", out)
        self.assertIn("Less controlled: different weeks", out)
        self.assertIn("Changed the default effort to medium", out)

    def test_render_is_light_only(self):
        out = report.render(fixture())
        self.assertNotIn("prefers-color-scheme", out)
        self.assertIn('<meta name="color-scheme" content="light">', out)

    def test_render_has_no_long_dashes(self):
        out = report.render(fixture())
        self.assertNotIn("\u2014", out)
        self.assertNotIn("\u2013", out)

    def test_render_hides_the_ratio_when_no_prompt_has_a_mistake(self):
        a = fixture()
        a.verdict = "no_change"
        a.boot.k_base = a.boot.k_recent = 0
        out = report.render(a)
        self.assertNotIn('class="stats"', out)
        self.assertIn('class="stats"', report.render(fixture()))

    def test_render_escapes_html(self):
        a = fixture()
        a.receipts["recent"][0]["quote"] = "<script>alert(1)</script>"
        out = report.render(a)
        self.assertNotIn("<script>alert", out)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", out)

    def test_render_no_external_urls(self):
        out = report.render(fixture())
        self.assertIsNone(re.search(r'(src|href)\s*=\s*["\']?\s*(https?:)?//', out))
        self.assertNotIn("<script src", out)
        self.assertIn("Chart.js v4.5.1", out)
        self.assertIn("<canvas", out)

    def test_render_escapes_script_end_in_chart_data(self):
        a = fixture()
        a.markers.append((START, "incident", "</script><b>x"))
        out = report.render(a)
        self.assertNotIn("</script><b>x", out)

    def test_render_offline_and_no_compare(self):
        a = fixture()
        a.overlay_ok, a.compare, a.attribution, a.harness = False, None, [], []
        out = report.render(a)
        self.assertIn("The changelog was not checked (offline).", out)
        self.assertNotIn("less controlled", out)

    def test_render_non_ok_has_no_verdict(self):
        out = report.render(too_early())
        self.assertIn("No verdict yet", out)
        self.assertIn("too early", out.lower())
        self.assertNotIn("Nerfed for you", out)
        self.assertNotIn("Your setup", out)
        self.assertIn("<canvas", out)


if __name__ == "__main__" and len(sys.argv) == 2:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    (out / "report-fixture.html").write_text(report.render(fixture()), encoding="utf-8")
    (out / "report-too-early.html").write_text(report.render(too_early()), encoding="utf-8")
    print("\n".join(report.summary(fixture(), out / "report-fixture.html")))
