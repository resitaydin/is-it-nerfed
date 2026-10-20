from __future__ import annotations

import unittest
from unittest import mock
from datetime import date, datetime, timedelta, timezone

import analyze
import parse
from overlay import Incident
from tests import make_prompt

TODAY = date(2026, 10, 4)
OPUS5 = "claude-opus-5-5"
OPUS4 = "claude-opus-4-1"


def day_n(i: int, start: date = date(2026, 8, 1)) -> date:
    return start + timedelta(days=i)


def make_session(sid, day, model, project="p1", n=2, version="2.1.0", **kw):
    when = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    prompts = [make_prompt("%s-%d" % (sid, i), session_id=sid, project=project, timestamp=when,
                           text="text %d" % i, model=model, cli_version=version, is_first=i == 0)
               for i in range(n)]
    return parse.Session(session_id=sid, project=project, prompts=prompts, **kw)


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
    args = dict(interp={}, incidents=[], version_dates={}, judge_agreement=None,
                overlay_ok=True, model=OPUS5)
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

    def test_attribution_groups_by_version(self):
        recent = (date(2026, 9, 1), date(2026, 9, 14))
        harness = [
            {"id": "a", "version": "2.2.0", "line": "Changed default effort to low", "short": "default effort lowered",
             "affects_behavior": "yes", "reason": ""},
            {"id": "d", "version": "2.2.0", "line": "Changed compaction", "short": "compaction changed",
             "affects_behavior": "yes", "reason": ""},
            {"id": "c", "version": "2.0.0", "line": "Old", "short": "old", "affects_behavior": "yes", "reason": ""},
        ]
        vd = {"2.2.0": date(2026, 9, 3), "2.2.1": date(2026, 9, 4), "2.0.0": date(2026, 8, 1)}
        at = lambda d: datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        incidents = [
            Incident("Degraded performance on Opus", at(date(2026, 9, 10)), None, ["Claude Code"]),
            Incident("Degraded performance", at(date(2026, 9, 10)), at(date(2026, 9, 11)), ["API"]),
            Incident("Login errors", at(date(2026, 9, 10)), at(date(2026, 9, 11)), ["Claude Code"]),
            Incident("Degraded performance", at(date(2026, 8, 1)), at(date(2026, 8, 2)), ["Claude Code"]),
        ]
        lines = analyze.attribution(recent, harness, vd, incidents)
        self.assertEqual(lines, ["2.2.0: default effort lowered; compaction changed",
                                 "incident: Degraded performance on Opus"])


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


class SideChangesTest(unittest.TestCase):
    def test_counts_only_the_turns_in_the_window(self):
        s = make_session("s", day_n(0), OPUS5, n=2)
        s.prompts[0].tool_results, s.prompts[0].tool_errors, s.prompts[0].output_tokens = 10, 5, 900
        s.prompts[1].timestamp += timedelta(days=5)
        s.prompts[1].tool_results, s.prompts[1].output_tokens = 10, 100
        side = analyze.side_changes([s], OPUS5, (day_n(0), day_n(1)))
        self.assertEqual(side["tool_error_rate"], 0.5)
        self.assertEqual(side["output_tokens_per_prompt"], 900)


class RunTests(unittest.TestCase):
    def test_no_labels_status(self):
        sessions = days_sessions(30)
        analysis = run(sessions, {})
        self.assertEqual(analysis.status, "no_labels")
        self.assertIsNone(analysis.verdict)
        self.assertIsNone(analysis.boot)

    def test_too_early_status(self):
        sessions = days_sessions(2, start=date(2026, 10, 1))
        analysis = run(sessions, {})
        self.assertEqual(analysis.status, "too_early")
        self.assertEqual(analysis.model, OPUS5)
        self.assertIsNone(analysis.boot)
        self.assertEqual(analysis.daily, [(date(2026, 10, 1), 0, 0), (date(2026, 10, 2), 0, 0)])
        self.assertIsNone(analysis.base)

    def test_judge_drift_status(self):
        sessions = days_sessions(10)
        analysis = run(sessions, labels_for(sessions, lambda d: False), judge_agreement=0.7, model=OPUS5)
        self.assertEqual(analysis.status, "judge_drift")
        self.assertIsNone(analysis.verdict)
        self.assertIsNone(analysis.boot)
        self.assertEqual(analysis.receipts, {})

    def test_ok_worse_with_receipts_and_compare(self):
        prev = days_sessions(6, OPUS4, start=date(2026, 6, 1))
        cur = days_sessions(10, OPUS5, start=date(2026, 9, 20))
        sessions = prev + cur
        labels = labels_for(sessions, lambda d: d >= date(2026, 9, 25))
        analysis = run(sessions, labels, interp={}, model=OPUS5)
        self.assertEqual(analysis.status, "ok")
        self.assertEqual(analysis.prev_model, OPUS4)
        self.assertGreater(analysis.boot.diff, 0)
        self.assertEqual(len(analysis.receipts["recent"]), 3)
        self.assertEqual(analysis.receipts["recent"][0]["quote"], "quote")
        self.assertEqual(analysis.receipts["base"], [])
        self.assertIsNotNone(analysis.compare)
        self.assertIn("recent", analysis.side)

    def test_firm_worse_needs_a_behavior_signal(self):
        sessions = days_sessions(20, n=8)
        labels = labels_for(sessions, lambda d: d >= day_n(10))
        alone = run(sessions, labels)
        self.assertEqual(alone.signals, [])
        self.assertEqual(alone.verdict, "unconfirmed_worse")
        for s in sessions:
            when = s.prompts[0].timestamp
            late = when.date() >= day_n(10)
            s.events = [parse.Event(when, OPUS5, k) for k in ["tool"] * 100 + ["interrupt"] * (6 if late else 1)]
        confirmed = run(sessions, labels)
        self.assertIn(confirmed.verdict, analyze.FIRM_WORSE)
        self.assertEqual(confirmed.signals[0].direction, "up")

    def test_shared_verdict_compares_the_verdict_before_the_downgrade(self):
        sessions = days_sessions(20, n=8)
        analysis = run(sessions, labels_for(sessions, lambda d: d >= day_n(10)))
        self.assertEqual(analysis.verdict, "unconfirmed_worse")
        self.assertIsNone(analysis.shared_verdict)

    def test_shared_verdict_hidden_when_it_shows_the_same_as_the_main_one(self):
        sessions = days_sessions(20, n=8)
        labels = labels_for(sessions, lambda d: d >= day_n(10))
        with mock.patch.object(analyze, "_shared_verdict", return_value="slightly_worse"):
            analysis = run(sessions, labels)
        self.assertEqual(analysis.verdict, "unconfirmed_worse")
        self.assertIsNone(analysis.shared_verdict)

    def test_compare_needs_ok_status_and_labels_on_both_sides(self):
        prev = days_sessions(6, OPUS4, start=date(2026, 6, 1))
        cur = days_sessions(10, OPUS5, start=date(2026, 9, 20))
        labels = labels_for(prev + cur, lambda d: d >= date(2026, 9, 25))
        drift = run(prev + cur, labels, judge_agreement=0.7)
        self.assertEqual(drift.status, "judge_drift")
        self.assertIsNone(drift.compare)
        self.assertIsNone(drift.compare_verdict)
        cur_only = {p.uuid: labels[p.uuid] for s in cur for p in s.prompts}
        unlabeled_prev = run(prev + cur, cur_only)
        self.assertEqual(unlabeled_prev.status, "ok")
        self.assertEqual(unlabeled_prev.prev_model, OPUS4)
        self.assertIsNone(unlabeled_prev.compare)
        self.assertIsNone(unlabeled_prev.compare_verdict)

    def test_shared_projects_verdict_set_only_when_different(self):
        # Base has an extra project that steers on every prompt; the recent window lacks it.
        base = [make_session("b%d" % i, day_n(i % 5), OPUS5, project="old") for i in range(5)]
        base += [make_session("c%d" % i, day_n(i % 5), OPUS5, project="shared") for i in range(5)]
        recent = [make_session("r%d" % i, day_n(5 + i % 5), OPUS5, project="shared") for i in range(10)]
        sessions = base + recent
        labels = {p.uuid: label(s.project == "old") for s in sessions for p in s.prompts}
        analysis = run(sessions, labels)
        self.assertIsNotNone(analysis.shared_verdict)
        self.assertNotEqual(analysis.shared_verdict, analysis.verdict)

        same = days_sessions(10, project="only")
        analysis = run(same, labels_for(same, lambda d: False))
        self.assertIsNone(analysis.shared_verdict)

    def test_harness_and_markers(self):
        sessions = days_sessions(10, version="2.1.0")
        sessions[8].prompts[0].cli_version = "2.2.0"
        labels = labels_for(sessions, lambda d: False)
        vd = {"2.1.0": day_n(0), "2.2.0": day_n(8), "1.0.0": day_n(-50)}
        interp = {
            "x": {"id": "x", "version": "2.2.0", "line": "effort", "short": "e", "affects_behavior": "yes", "reason": "r"},
            "y": {"id": "y", "version": "1.0.0", "line": "old", "short": "o", "affects_behavior": "yes", "reason": "r"},
            "z": {"id": "z", "version": "2.2.0", "line": "typo", "short": "t", "affects_behavior": "no", "reason": "r"},
        }
        at = datetime(2026, 8, 5, tzinfo=timezone.utc)
        incidents = [Incident("Outage", at, at, ["Claude Code"]),
                     Incident("API blip", at, at, ["API"])]
        analysis = run(sessions, labels, interp=interp, version_dates=vd, incidents=incidents)
        self.assertEqual([h["id"] for h in analysis.harness], ["x"])
        kinds = [(m[1], m[2]) for m in analysis.markers]
        self.assertIn(("version", "2.2.0"), kinds)
        self.assertIn(("incident", "Outage"), kinds)
        self.assertNotIn(("incident", "API blip"), kinds)
        self.assertEqual(len(analysis.attribution), 1)


if __name__ == "__main__":
    unittest.main()
