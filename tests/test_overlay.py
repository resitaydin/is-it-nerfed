from __future__ import annotations

import unittest
from datetime import date, datetime, timezone
from pathlib import Path

import overlay
import parse
import sample
from tests import make_prompt

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def make_session(*prompts):
    return parse.Session(session_id="s", project="p", prompts=list(prompts))


def version_prompt(day, version):
    return make_prompt("u%d%s" % (day, version), day=day, cli_version=version)


class ChangelogTest(unittest.TestCase):
    def setUp(self):
        self.changelog = overlay.parse_changelog((FIXTURES / "changelog_sample.md").read_text())

    def test_parse_changelog(self):
        self.assertEqual(list(self.changelog), ["2.1.3", "2.1.2", "2.1.1"])
        self.assertEqual(sum(len(v) for v in self.changelog.values()), 6)
        self.assertEqual(self.changelog["2.1.2"][1], "Improved startup speed")

    def test_relevant_lines_keyword_filter(self):
        found = overlay.relevant_lines(self.changelog, ["2.1.3", "2.1.2", "2.1.1"])
        self.assertEqual(len(found), 2)
        self.assertEqual({f["version"] for f in found}, {"2.1.3", "2.1.1"})
        first = found[0]
        self.assertEqual(first["id"], sample.item_id(first["version"] + first["line"]))

    def test_relevant_lines_limits_to_versions(self):
        found = overlay.relevant_lines(self.changelog, ["2.1.1"])
        self.assertEqual([f["version"] for f in found], ["2.1.1"])


class IncidentTest(unittest.TestCase):
    def test_parse_incidents(self):
        incidents = overlay.parse_incidents((FIXTURES / "incidents_sample.json").read_text())
        self.assertEqual(len(incidents), 2)
        self.assertEqual(incidents[0].start, datetime(2026, 10, 1, 16, 20, 40, 767000, tzinfo=timezone.utc))
        self.assertEqual(incidents[0].end, datetime(2026, 10, 1, 18, 5, 10, tzinfo=timezone.utc))
        self.assertEqual(incidents[0].components, ["Claude Code", "Claude API"])
        self.assertEqual(incidents[1].start, datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc))
        self.assertIsNone(incidents[1].end)
        self.assertEqual(incidents[1].components, [])

    def test_parse_incidents_bad_json(self):
        self.assertEqual(overlay.parse_incidents("<html>502 Bad Gateway</html>"), [])

    def test_parse_incidents_skips_rows_of_another_shape(self):
        self.assertEqual(overlay.parse_incidents("[1, 2]"), [])
        text = '{"incidents": [{"id": "no name"}, {"name": "Errors", "created_at": "2026-10-03T09:00:00Z"}]}'
        self.assertEqual([i.name for i in overlay.parse_incidents(text)], ["Errors"])


class FetchTest(unittest.TestCase):
    def test_fetch_returns_none_on_error(self):
        self.assertIsNone(overlay.fetch("http://127.0.0.1:9/", timeout=2))


class VersionFirstSeenTest(unittest.TestCase):
    def test_version_first_seen(self):
        sessions = [
            make_session(version_prompt(5, "2.1.2"), version_prompt(3, "2.1.1")),
            make_session(version_prompt(2, "2.1.1")),
        ]
        self.assertEqual(
            overlay.version_first_seen(sessions),
            {"2.1.1": date(2026, 9, 2), "2.1.2": date(2026, 9, 5)},
        )

    def test_version_first_seen_skips_empty_version(self):
        sessions = [make_session(version_prompt(2, ""), version_prompt(3, "2.1.1"))]
        self.assertEqual(overlay.version_first_seen(sessions), {"2.1.1": date(2026, 9, 3)})


if __name__ == "__main__":
    unittest.main()
