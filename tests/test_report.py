from __future__ import annotations

import re
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

import report
from analyze import Analysis
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
            "top_projects": top, "compactions_per_session": 0.4, "interrupts_per_prompt": 0.05,
            "tool_error_rate": 0.031, "user_edits": 6, "output_tokens_per_prompt": 1840.0}


def fixture(status: str = "ok") -> Analysis:
    """One plausible Analysis with every section filled; the preview uses the same data."""
    base, recent = (START, START + timedelta(days=13)), (START + timedelta(days=14), START + timedelta(days=27))
    return Analysis(
        status=status, model="claude-opus-5-5", prev_model="claude-opus-5-4",
        base=base, recent=recent,
        boot=BootResult(diff=6.2, lo=1.1, hi=11.0, p_worse=0.78, base_rate=9.1, recent_rate=15.3,
                        n_base=160, n_recent=170),
        verdict="slightly_worse", shared_verdict="leaning_worse",
        compare=BootResult(diff=-1.0, lo=-6.0, hi=4.0, p_worse=0.35, base_rate=16.3, recent_rate=15.3,
                           n_base=140, n_recent=170),
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
                  "affects_behavior": "yes", "reason": "Lower effort can mean shorter reasoning."},
                 {"id": "h2", "version": "2.1.280", "line": "Fixed a typo in /help",
                  "affects_behavior": "no", "reason": "Text only."}],
        receipts={"base": [{"date": "2026-09-12", "quote": "no, use the existing helper",
                            "reason": "The agent wrote a new helper."}],
                  "recent": [{"date": "2026-09-30", "quote": "you ignored the test I asked for",
                              "reason": "The agent skipped a stated step."},
                             {"date": "2026-10-02", "quote": "stop, that file is not in scope",
                              "reason": "The agent edited an unrelated file."}]},
        attribution=["CLI 2.1.285 started in the recent window: Changed the default effort to medium"],
        judge_agreement=0.93, overlay_ok=True,
    )


def too_early() -> Analysis:
    return Analysis(status="too_early", model="claude-opus-5-5",
                    daily=[(START, 1, 9), (START + timedelta(days=1), 0, 7)])


REPORT = Path("/data/report-2026-10-04.html")


class SummaryTest(unittest.TestCase):
    def test_summary_five_lines_ok(self):
        lines = report.summary(fixture(), REPORT)
        self.assertEqual(lines, [
            "Opus 5.5 — slightly worse (78% probability)",
            "Model-caused steering: 9% → 15% (+6 pts), Sep 7–20 vs Sep 21–Oct 4",
            "Your side: CLAUDE.md changed 2×, CLI 2.1.271 → 2.1.289, "
            "top project ai-team-journey-analyzer → is-it-nerfed",
            "Harness: CLI 2.1.285 started in the recent window: Changed the default effort to medium",
            "Report: /data/report-2026-10-04.html",
        ])

    def test_summary_better_and_no_change(self):
        a = fixture()
        a.verdict = "leaning_better"
        self.assertEqual(report.summary(a, REPORT)[0], "Opus 5.5 — probably better (22% probability)")
        a.verdict = "no_change"
        self.assertEqual(report.summary(a, REPORT)[0],
                         "Opus 5.5 — no change (90% interval inside ±5 pts)")

    def test_summary_no_side_change_and_offline(self):
        a = fixture()
        a.side["recent"] = dict(a.side["base"])
        a.overlay_ok = False
        lines = report.summary(a, REPORT)
        self.assertEqual(lines[2], "Your side: no change found")
        self.assertEqual(lines[3], "Harness: changelog not available: offline")
        a.overlay_ok, a.attribution = True, []
        self.assertEqual(report.summary(a, REPORT)[3], "Harness: no known change")

    def test_summary_too_early(self):
        lines = report.summary(too_early(), REPORT)
        self.assertEqual(len(lines), 2)
        self.assertIn("too early", lines[0])
        self.assertIn("16 labeled prompts", lines[0])
        self.assertEqual(lines[1], "Report: /data/report-2026-10-04.html")


class NamesTest(unittest.TestCase):
    def test_model_name(self):
        self.assertEqual(report.model_name("claude-opus-5-5"), "Opus 5.5")
        self.assertEqual(report.model_name("claude-sonnet-5"), "Sonnet 5")
        self.assertEqual(report.model_name("claude-haiku-4-5-20251001"), "Haiku 4.5")
        self.assertEqual(report.model_name("gpt-x"), "gpt-x")

    def test_short_projects_strip_common_prefix_at_dash(self):
        names = [DIR + "ai-team-x", DIR + "ai-tools"]
        self.assertEqual(report.short_projects(names), {names[0]: "team-x", names[1]: "tools"})

    def test_short_projects_single_name_falls_back_to_tail(self):
        name = DIR + "ai-team-journey-analyzer-launch-ready"
        self.assertEqual(report.short_projects([name]), {name: "…" + name[-30:]})
        self.assertEqual(report.short_projects(["-tmp-x"]), {"-tmp-x": "-tmp-x"})


class ChartTest(unittest.TestCase):
    def test_chart_gap_on_zero_label_day(self):
        svg = report.chart_svg(fixture().daily, fixture().markers)
        line = re.search(r'<path class="roll" d="([^"]*)"', svg).group(1)
        self.assertEqual(line.count("M"), 2)
        self.assertEqual(svg.count('class="dot"'), 27)
        self.assertIn("viewBox=", svg)

    def test_rolling_pools_last_five_labeled_days(self):
        d = START
        rows = [(d, 1, 10), (d + timedelta(days=1), 0, 0), (d + timedelta(days=2), 3, 10),
                (d + timedelta(days=9), 5, 10)]
        points = report.rolling(rows)
        self.assertEqual([p[0] for p in points], [rows[0][0], None, rows[2][0], rows[3][0]])
        self.assertAlmostEqual(points[2][1], 0.2)
        self.assertAlmostEqual(points[3][1], 0.5)
        lo, hi = points[3][2], points[3][3]
        self.assertTrue(0.25 < lo < 0.5 < hi < 0.75)


class RenderTest(unittest.TestCase):
    def test_render_escapes_html(self):
        a = fixture()
        a.receipts["recent"][0]["quote"] = "<script>alert(1)</script>"
        out = report.render(a)
        self.assertNotIn("<script>alert", out)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", out)

    def test_render_no_external_urls(self):
        out = report.render(fixture())
        self.assertIsNone(re.search(r'(src|href)\s*=\s*["\']?\s*(https?:)?//', out))
        self.assertNotIn("http", out)

    def test_render_sections_in_order(self):
        out = report.render(fixture())
        heads = ["Model-caused steering by day", "Model against model", "Is it you?",
                 "Harness changes", "Evidence"]
        positions = [out.index(h) for h in heads]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("your project mix changed", out.lower())
        self.assertIn("less controlled: different weeks", out)
        self.assertIn("Changed the default effort to medium", out)
        self.assertNotIn("Fixed a typo in /help", out)

    def test_render_offline_and_no_compare(self):
        a = fixture()
        a.overlay_ok, a.compare = False, None
        out = report.render(a)
        self.assertIn("changelog not available: offline", out)
        self.assertNotIn("Model against model", out)

    def test_render_non_ok_has_banner_and_no_verdict(self):
        out = report.render(too_early())
        self.assertIn("too early", out.lower())
        self.assertNotIn("slightly worse", out)
        self.assertIn("<svg", out)


if __name__ == "__main__" and len(sys.argv) == 2:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    (out / "report-fixture.html").write_text(report.render(fixture()), encoding="utf-8")
    (out / "report-too-early.html").write_text(report.render(too_early()), encoding="utf-8")
    print("\n".join(report.summary(fixture(), out / "report-fixture.html")))
