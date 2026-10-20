from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

import parse
import signals

OPUS5 = "claude-opus-5-5"
BASE = (date(2026, 9, 1), date(2026, 9, 14))
RECENT = (date(2026, 9, 15), date(2026, 9, 28))


def session(sid, day, kinds, model=OPUS5):
    when = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    return parse.Session(session_id=sid, project="p",
                         events=[parse.Event(when, model, k) for k in kinds])


def calls(tools, interrupts, fixes=0):
    return ["tool"] * tools + ["interrupt"] * interrupts + ["self_correction"] * fixes


class SessionCountsTest(unittest.TestCase):
    def test_counts_only_the_model_in_the_window(self):
        sessions = [session("a", date(2026, 9, 2), ["tool", "tool", "interrupt"]),
                    session("b", date(2026, 9, 3), ["tool", "interrupt"], model="claude-sonnet-5"),
                    session("c", date(2026, 9, 20), ["tool"]),
                    session("d", date(2026, 9, 4), ["interrupt"])]
        interrupts = signals.SIGNALS[1]
        self.assertEqual(interrupts.kind, "interrupt")
        self.assertEqual(signals.session_counts(sessions, OPUS5, BASE, interrupts), [("a", 1, 2)])


class CompareTest(unittest.TestCase):
    def test_interrupts_up_alone_do_not_confirm_worse(self):
        base = [session("b%d" % i, date(2026, 9, 1 + i), calls(100, 1)) for i in range(10)]
        recent = [session("r%d" % i, date(2026, 9, 15 + i), calls(100, 6)) for i in range(10)]
        both = base + recent
        results = signals.compare(*(signals.window_counts(both, OPUS5, w) for w in (BASE, RECENT)))
        self.assertEqual([r.signal.name for r in results], ["interrupts"])  # no self-corrections: too few
        r = results[0]
        self.assertAlmostEqual(r.base_rate, 10.0)
        self.assertAlmostEqual(r.recent_rate, 60.0)
        self.assertGreater(r.lo, 1)
        # Interrupts are the user's behavior: they rise in a bad stretch of hard tasks too.
        self.assertFalse(signals.confirms_worse(results))

    def test_self_corrections_up_confirm_worse(self):
        base = [session("b%d" % i, date(2026, 9, 1 + i), calls(100, 0, fixes=1)) for i in range(10)]
        recent = [session("r%d" % i, date(2026, 9, 15 + i), calls(100, 0, fixes=6)) for i in range(10)]
        results = signals.compare(*(signals.window_counts(base + recent, OPUS5, w) for w in (BASE, RECENT)))
        self.assertEqual([r.signal.name for r in results], ["self-corrections"])
        self.assertTrue(signals.confirms_worse(results))

    def test_signal_with_too_few_events_gives_no_result(self):
        # With no events, the half hit added to each side makes the ratio compare only the tool calls.
        base = [session("b%d" % i, date(2026, 9, 1 + i), calls(1000, 0)) for i in range(10)]
        recent = [session("r%d" % i, date(2026, 9, 15 + i), calls(50, 0)) for i in range(10)]
        both = base + recent
        self.assertEqual(signals.compare(*(signals.window_counts(both, OPUS5, w) for w in (BASE, RECENT))), [])

    def test_no_change_does_not_confirm(self):
        sessions = [session("b%d" % i, date(2026, 9, 1 + i), calls(100, 2)) for i in range(10)]
        sessions += [session("r%d" % i, date(2026, 9, 15 + i), calls(100, 2)) for i in range(10)]
        counts = [signals.window_counts(sessions, OPUS5, w) for w in (BASE, RECENT)]
        self.assertFalse(signals.confirms_worse(signals.compare(*counts)))
        self.assertFalse(signals.confirms_worse([]))


if __name__ == "__main__":
    unittest.main()
