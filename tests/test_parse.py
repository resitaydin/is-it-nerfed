from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import parse

ROOT = Path(__file__).parent / "fixtures" / "root"
PROJ = ROOT / "projects" / "-proj-a"


class ParseSessionTest(unittest.TestCase):
    def setUp(self):
        self.basic = parse.parse_session(PROJ / "basic.jsonl")

    def test_prompts_exclude_interrupt_and_system_lines(self):
        prompts = self.basic.prompts
        self.assertEqual(len(prompts), 3)
        self.assertEqual(prompts[0].text, "Fix the login bug")
        self.assertTrue(prompts[1].after_interrupt)
        self.assertFalse(prompts[0].after_interrupt)
        self.assertFalse(prompts[2].after_interrupt)
        self.assertEqual(self.basic.interrupts, 1)

    def test_command_and_first_flags(self):
        prompts = self.basic.prompts
        self.assertTrue(prompts[0].is_first)
        self.assertFalse(prompts[1].is_first)
        self.assertTrue(prompts[2].is_command)
        self.assertFalse(prompts[0].is_command)

    def test_usage_deduplicated_by_message_id(self):
        self.assertEqual(self.basic.output_tokens, 50)

    def test_synthetic_skipped(self):
        self.assertNotIn("<synthetic>", [p.model for p in self.basic.prompts])

    def test_counts(self):
        self.assertEqual(self.basic.tool_errors, 1)
        self.assertEqual(self.basic.tool_results, 2)
        self.assertEqual(self.basic.user_modified_edits, 1)
        self.assertEqual(self.basic.compactions, 1)
        self.assertEqual(sorted(self.basic.claude_md_files), ["/x/CLAUDE.md", "/y/CLAUDE.md"])
        self.assertRegex(self.basic.claude_md_files["/x/CLAUDE.md"], r"^[0-9a-f]{12}$")

    def test_context_fields(self):
        first, second, third = self.basic.prompts
        self.assertEqual(self.basic.project, "-proj-a")
        self.assertEqual(self.basic.session_id, "basic")
        self.assertEqual(first.model, "claude-opus-5-5")
        self.assertIsNone(second.model)
        self.assertEqual(first.prev_agent_text, "")
        self.assertEqual(second.prev_agent_text, "I will look at it.")
        self.assertEqual(second.history, ["Fix the login bug"])
        self.assertEqual(third.history[0], "No, use the other file")
        self.assertEqual(second.cli_version, "2.1.281")
        self.assertEqual(self.basic.cli_versions, ["2.1.280", "2.1.281"])
        self.assertEqual(first.timestamp.isoformat(), "2026-09-01T10:00:01+00:00")

    def test_model_per_prompt(self):
        session = parse.parse_session(PROJ / "two_models.jsonl")
        models = [p.model for p in session.prompts]
        self.assertEqual(models, ["claude-opus-5-5", "claude-sonnet-5-5"])

    def test_truncated_line_skipped(self):
        session = parse.parse_session(PROJ / "truncated.jsonl")
        self.assertEqual([p.text for p in session.prompts], ["First prompt", "Second prompt"])

    def test_non_human_lines_skipped(self):
        session = parse.parse_session(PROJ / "non_human.jsonl")
        texts = [p.text for p in session.prompts]
        self.assertEqual(texts[:2], ["Real prompt", "Second real prompt"])
        self.assertEqual(len(texts), 3)
        self.assertEqual(session.prompts[1].history, ["Real prompt"])

    def test_command_message_is_command(self):
        session = parse.parse_session(PROJ / "non_human.jsonl")
        self.assertEqual([p.is_command for p in session.prompts], [False, False, True])

    def test_is_own_by_command_and_by_data_dir(self):
        self.assertTrue(parse.parse_session(PROJ / "own_run.jsonl").is_own)
        self.assertTrue(parse.parse_session(PROJ / "own_run_tool.jsonl").is_own)
        self.assertFalse(self.basic.is_own)


class LoadSessionsTest(unittest.TestCase):
    def test_own_runs_excluded(self):
        ids = {s.session_id for s in parse.load_sessions([ROOT])}
        self.assertNotIn("own_run", ids)
        self.assertNotIn("own_run_tool", ids)
        self.assertEqual(ids, {"basic", "two_models", "truncated", "non_human"})

    def test_subagents_and_empty_sessions_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "projects" / "-p"
            (proj / "subagents").mkdir(parents=True)
            line = '{"type":"user","timestamp":"2026-09-01T10:00:00.000Z","message":{"role":"user","content":"hi"}}\n'
            (proj / "subagents" / "sub.jsonl").write_text(line)
            (proj / "empty.jsonl").write_text('{"type":"mystery"}\n')
            self.assertEqual(parse.load_sessions([Path(tmp)]), [])


class FindRootsTest(unittest.TestCase):
    def test_find_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude" / "projects").mkdir(parents=True)
            (home / ".claude-second" / "projects").mkdir(parents=True)
            (home / ".claude-empty").mkdir()
            roots = parse.find_roots(home, {})
            self.assertEqual(set(roots), {home / ".claude", home / ".claude-second"})

    def test_env_dir_added_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude" / "projects").mkdir(parents=True)
            roots = parse.find_roots(home, {"CLAUDE_CONFIG_DIR": str(home / ".claude")})
            self.assertEqual(roots, [home / ".claude"])
            self.assertEqual(parse.find_roots(home, {"CLAUDE_CONFIG_DIR": str(home / "nope")}), roots)


if __name__ == "__main__":
    unittest.main()
