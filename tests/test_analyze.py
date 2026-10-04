from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

import analyze
import parse
from overlay import Incident

TODAY = date(2026, 10, 4)
OPUS5 = "claude-opus-5-5"
OPUS4 = "claude-opus-4-1"


def day_n(i: int, start: date = date(2026, 8, 1)) -> date:
    return start + timedelta(days=i)


def make_session(sid, day, model, project="p1", n=2, version="2.1.0", **kw):
    when = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    prompts = [
        parse.Prompt(uuid="%s-%d" % (sid, i), session_id=sid, project=project, timestamp=when,
                     text="text %d" % i, model=model, cli_version=version, is_first=i == 0,
                     is_command=False, after_interrupt=False, prev_agent_text="", history=[])
        for i in range(n)
    ]
    return parse.Session(session_id=sid, project=project, prompts=prompts, cli_versions=[version], **kw)


def label(steer: bool) -> dict:
    return {"kind": "steering" if steer else "other", "steering_type": "x",
            "cause": "model" if steer else "none", "evidence": "quote", "reasoning": "why"}


def labels_for(sessions, rate_by_day):
    """Label every prompt; the first prompt of a day steers when rate_by_day(day) is true."""
    out = {}
    for s in sessions:
        for i, p in enumerate(s.prompts):
            out[p.uuid] = label(i == 0 and rate_by_day(p.timestamp.date()))
    return out


def days_sessions(count, model=OPUS5, start=date(2026, 8, 1), **kw):
    return [make_session("%s-s%d" % (model, i), day_n(i, start), model, **kw) for i in range(count)]


def run(sessions, labels, **kw):
    args = dict(interp={}, incidents=[], version_dates={}, baselines={}, judge_agreement=None,
                overlay_ok=True, today=TODAY, model=OPUS5)
    args.update(kw)
    return analyze.run(sessions, labels, **args)


class HelperTests(unittest.TestCase):
    def test_family(self):
        self.assertEqual(analyze.family("claude-opus-5-5"), "claude-opus")
        self.assertEqual(analyze.family("claude-sonnet-4-20250514"), "claude-sonnet")
        self.assertEqual(analyze.family("claude-opus"), "claude-opus")

    def test_current_model_uses_last_seven_days(self):
        old = make_session("a", TODAY - timedelta(days=20), OPUS4, n=9)
        new = make_session("b", TODAY - timedelta(days=1), OPUS5, n=2)
        self.assertEqual(analyze.current_model([old, new], TODAY), OPUS5)
        self.assertIsNone(analyze.current_model([old], TODAY))

    def test_previous_model_same_family(self):
        prev = days_sessions(4, OPUS4, start=date(2026, 6, 1))
        other_family = days_sessions(4, "claude-sonnet-4-5", start=date(2026, 7, 20))
        short = days_sessions(2, "claude-opus-3-0", start=date(2026, 7, 25))
        cur = days_sessions(4, OPUS5, start=date(2026, 8, 1))
        self.assertEqual(analyze.previous_model(prev + other_family + short + cur, OPUS5), OPUS4)
        self.assertIsNone(analyze.previous_model(cur, OPUS5))

    def test_daily_keeps_zero_label_days(self):
        sessions = days_sessions(3)
        labels = labels_for(sessions[:2], lambda d: True)
        rows = analyze.daily(sessions, OPUS5, labels)
        self.assertEqual(rows, [(day_n(0), 1, 2), (day_n(1), 1, 2), (day_n(2), 0, 0)])

    def test_attribution_sentences(self):
        recent = (date(2026, 9, 1), date(2026, 9, 14))
        harness = [
            {"id": "a", "version": "2.2.0", "line": "Changed default effort", "affects_behavior": "yes", "reason": ""},
            {"id": "b", "version": "2.2.1", "line": "Fix typo", "affects_behavior": "no", "reason": ""},
            {"id": "c", "version": "2.0.0", "line": "Old", "affects_behavior": "yes", "reason": ""},
        ]
        vd = {"2.2.0": date(2026, 9, 3), "2.2.1": date(2026, 9, 4), "2.0.0": date(2026, 8, 1)}
        at = lambda d: datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        incidents = [
            Incident("Degraded performance on Opus", "minor", at(date(2026, 9, 10)), None, ["Claude Code"]),
            Incident("Degraded performance", "minor", at(date(2026, 9, 10)), at(date(2026, 9, 11)), ["API"]),
            Incident("Login errors", "minor", at(date(2026, 9, 10)), at(date(2026, 9, 11)), ["Claude Code"]),
            Incident("Degraded performance", "minor", at(date(2026, 8, 1)), at(date(2026, 8, 2)), ["Claude Code"]),
        ]
        lines = analyze.attribution(recent, harness, vd, incidents)
        self.assertEqual(len(lines), 2)
        self.assertIn("2.2.0", lines[0])
        self.assertIn("Changed default effort", lines[0])
        self.assertIn("Degraded performance on Opus", lines[1])


class SideChangeTests(unittest.TestCase):
    def edits(self, files_per_session):
        sessions = []
        for i, files in enumerate(files_per_session):
            s = make_session("e%d" % i, day_n(i), OPUS5)
            s.claude_md_files = files
            sessions.append(s)
        return analyze.side_changes(sessions, OPUS5, (day_n(0), day_n(9)))["claude_md_edits"]

    def test_separate_projects_are_not_edits(self):
        self.assertEqual(self.edits([{"/a/CLAUDE.md": "h1"}, {"/b/CLAUDE.md": "h2"}]), 0)

    def test_three_versions_of_one_path_are_two_edits(self):
        self.assertEqual(self.edits([{"/a/CLAUDE.md": "h1"}, {"/a/CLAUDE.md": "h2"},
                                     {"/a/CLAUDE.md": "h3"}, {"/a/CLAUDE.md": "h3"}]), 2)


class VersionOrderTests(unittest.TestCase):
    def test_cli_versions_sort_numerically(self):
        sessions = [make_session("v1", day_n(0), OPUS5, version="2.1.100"),
                    make_session("v2", day_n(1), OPUS5, version="2.1.99"),
                    make_session("v3", day_n(2), OPUS5, version="2.1.x")]
        side = analyze.side_changes(sessions, OPUS5, (day_n(0), day_n(9)))
        self.assertEqual(side["cli_versions"], ["2.1.99", "2.1.100", "2.1.x"])


class RunTests(unittest.TestCase):
    def test_no_model(self):
        old = days_sessions(5, start=date(2026, 6, 1))
        analysis, _ = run(old, {}, model=None)
        self.assertEqual(analysis.status, "no_model")
        self.assertIsNone(analysis.model)

    def test_no_labels_status(self):
        sessions = days_sessions(30)
        analysis, saved = run(sessions, {})
        self.assertEqual(analysis.status, "no_labels")
        self.assertEqual(analysis.verdict, "")
        self.assertEqual(analysis.boot.n_recent, 0)
        self.assertEqual(saved, {})

    def test_too_early_status(self):
        sessions = days_sessions(2, start=date(2026, 10, 1))
        analysis, _ = run(sessions, {})
        self.assertEqual(analysis.status, "too_early")
        self.assertEqual(analysis.model, OPUS5)
        self.assertIsNone(analysis.boot)
        self.assertEqual(analysis.daily, [(date(2026, 10, 1), 0, 0), (date(2026, 10, 2), 0, 0)])
        self.assertIsNone(analysis.base)

    def test_judge_drift_status(self):
        sessions = days_sessions(10)
        analysis, _ = run(sessions, labels_for(sessions, lambda d: False), judge_agreement=0.7, model=OPUS5)
        self.assertEqual(analysis.status, "judge_drift")
        self.assertEqual(analysis.verdict, "")
        self.assertIsNotNone(analysis.boot)

    def test_ok_worse_with_receipts_and_compare(self):
        prev = days_sessions(6, OPUS4, start=date(2026, 6, 1))
        cur = days_sessions(10, OPUS5, start=date(2026, 9, 20))
        sessions = prev + cur
        labels = labels_for(sessions, lambda d: d >= date(2026, 9, 25))
        analysis, _ = run(sessions, labels, interp={}, model=OPUS5)
        self.assertEqual(analysis.status, "ok")
        self.assertEqual(analysis.prev_model, OPUS4)
        self.assertGreater(analysis.boot.diff, 0)
        self.assertEqual(len(analysis.receipts["recent"]), 3)
        self.assertEqual(analysis.receipts["recent"][0]["quote"], "quote")
        self.assertEqual(analysis.receipts["base"], [])
        self.assertIsNotNone(analysis.compare)
        self.assertIn("recent", analysis.side)

    def test_baseline_frozen_at_28_days(self):
        sessions = days_sessions(28)
        labels = labels_for(sessions, lambda d: d < day_n(14))
        analysis, saved = run(sessions, labels)
        self.assertEqual(analysis.status, "ok")
        entry = saved[OPUS5]
        self.assertEqual(entry["start"], day_n(0).isoformat())
        self.assertEqual(entry["end"], day_n(13).isoformat())
        self.assertEqual(len(entry["sessions"]), 14)
        self.assertEqual(entry["sessions"][0], ["%s-s0" % OPUS5, 1, 2])
        # More days, old labels gone: the saved base is reused.
        more = days_sessions(35)
        new_labels = labels_for(more[14:], lambda d: False)
        again, saved2 = run(more, new_labels, baselines=saved)
        self.assertEqual(again.base, (day_n(0), day_n(13)))
        self.assertEqual(again.boot.n_base, 28)
        self.assertEqual(again.boot.base_rate, 50.0)
        self.assertEqual(again.recent, (day_n(21), day_n(34)))
        self.assertEqual(saved2, saved)

    def test_shared_projects_verdict_set_only_when_different(self):
        # Base has an extra project that steers on every prompt; the recent window lacks it.
        base = [make_session("b%d" % i, day_n(i % 5), OPUS5, project="old") for i in range(5)]
        base += [make_session("c%d" % i, day_n(i % 5), OPUS5, project="shared") for i in range(5)]
        recent = [make_session("r%d" % i, day_n(5 + i % 5), OPUS5, project="shared") for i in range(10)]
        sessions = base + recent
        labels = {p.uuid: label(s.project == "old") for s in sessions for p in s.prompts}
        analysis, _ = run(sessions, labels)
        self.assertNotEqual(analysis.verdict, "")
        self.assertIsNotNone(analysis.shared_verdict)
        self.assertNotEqual(analysis.shared_verdict, analysis.verdict)

        same = days_sessions(10, project="only")
        analysis, _ = run(same, labels_for(same, lambda d: False))
        self.assertIsNone(analysis.shared_verdict)

    def test_harness_and_markers(self):
        sessions = days_sessions(10, version="2.1.0")
        sessions[8].prompts[0].cli_version = "2.2.0"
        labels = labels_for(sessions, lambda d: False)
        vd = {"2.1.0": day_n(0), "2.2.0": day_n(8), "1.0.0": day_n(-50)}
        interp = {
            "x": {"id": "x", "version": "2.2.0", "line": "effort", "affects_behavior": "yes", "reason": "r"},
            "y": {"id": "y", "version": "1.0.0", "line": "old", "affects_behavior": "yes", "reason": "r"},
        }
        at = datetime(2026, 8, 5, tzinfo=timezone.utc)
        incidents = [Incident("Outage", "major", at, at, ["Claude Code"]),
                     Incident("API blip", "major", at, at, ["API"])]
        analysis, _ = run(sessions, labels, interp=interp, version_dates=vd, incidents=incidents)
        self.assertEqual([h["id"] for h in analysis.harness], ["x"])
        kinds = [(m[1], m[2]) for m in analysis.markers]
        self.assertIn(("version", "2.2.0"), kinds)
        self.assertIn(("incident", "Outage"), kinds)
        self.assertNotIn(("incident", "API blip"), kinds)
        self.assertEqual(len(analysis.attribution), 1)


if __name__ == "__main__":
    unittest.main()
