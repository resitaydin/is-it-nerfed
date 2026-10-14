from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import parse

ROOT = Path(__file__).parent / "fixtures" / "root"
PROJ = ROOT / "projects" / "-proj-a"


def user(text, second=0, **extra):
    return dict({"type": "user", "uuid": "u%d" % second, "timestamp": "2026-09-01T10:00:%02d.000Z" % second,
                 "message": {"role": "user", "content": text}}, **extra)


def assistant(blocks, second=0, msg="m", tokens=1):
    return {"type": "assistant", "timestamp": "2026-09-01T10:00:%02d.000Z" % second,
            "message": {"id": msg, "model": "claude-opus-5-5", "role": "assistant", "content": blocks,
                        "usage": {"output_tokens": tokens}}}


def tool(name, **inputs):
    return {"type": "tool_use", "id": name + json.dumps(inputs), "name": name, "input": inputs}


def parse_lines(*lines):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "s.jsonl"
        path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
        return parse.parse_session(path)


class ParseLinesTest(unittest.TestCase):
    def test_own_run_cuts_the_session_before_the_request(self):
        session = parse_lines(
            user("Fix the build", 1), assistant([{"type": "text", "text": "Done."}], 2),
            user("did claude get dumber?", 3),
            assistant([tool("Bash", command='python3 "/h/skills/is-it-nerfed/scripts/cli.py" scan')], 4),
            user("Fix the tests", 6))
        self.assertEqual([p.text for p in session.prompts], ["Fix the build"])

    def test_only_a_lone_slash_word_is_a_plain_text_command(self):
        session = parse_lines(user("/compact", 1), user("/Users/me/app.py still throws", 2),
                              user("/tmp is full again", 3))
        self.assertEqual([p.is_command for p in session.prompts], [True, False, False])

    def test_first_prompt_is_the_one_before_any_agent_reply(self):
        session = parse_lines(user("/compact", 1), user("hi", 2), assistant([{"type": "text", "text": "ok"}], 3),
                              user("wrong loop", 4))
        self.assertEqual([p.is_first for p in session.prompts], [False, True, False])
        after_command = parse_lines(user("<command-name>/review</command-name>", 1),
                                    assistant([{"type": "text", "text": "Review."}], 2), user("finding 3 is wrong", 3))
        self.assertFalse(after_command.prompts[1].is_first)

    def test_reading_the_tool_source_does_not_cut_the_session(self):
        session = parse_lines(
            user("fix the parser", 1),
            assistant([tool("Read", file_path="/r/plugins/is-it-nerfed/skills/is-it-nerfed/scripts/parse.py")], 2),
            user("now the tests", 3))
        self.assertEqual(len(session.prompts), 2)

    def test_typed_request_with_the_marker_is_left_out_and_nothing_else(self):
        session = parse_lines(user("Fix the build", 1),
                              user("python3 /h/skills/is-it-nerfed/scripts/cli.py scan", 2))
        self.assertEqual([p.text for p in session.prompts], ["Fix the build"])

    def test_compaction_after_a_command_belongs_to_the_last_real_prompt(self):
        session = parse_lines(user("work", 1), assistant([{"type": "text", "text": "ok"}], 2),
                              user("/compact", 3), {"type": "system", "subtype": "compact_boundary"})
        self.assertEqual(session.prompts[0].compactions, 1)

    def test_messages_without_id_each_count(self):
        session = parse_lines(user("go", 1),
                              {"type": "assistant", "message": {"model": "m", "content": [], "usage": {"output_tokens": 500}}},
                              {"type": "assistant", "message": {"model": "m", "content": [], "usage": {"output_tokens": 300}}})
        self.assertEqual(session.prompts[0].output_tokens, 800)

    def test_bash_command_with_non_ascii_path_names_the_file(self):
        session = parse_lines(
            user("edit it", 1),
            assistant([tool("Bash", command="cat /Users/ü/a.py")], 2, msg="m1"),
            assistant([tool("Edit", file_path="/Users/ü/a.py", old_string="a", new_string="b")], 3, msg="m2"),
            assistant([tool("Edit", file_path="C:\\x\\b.py", old_string="a", new_string="b")], 4, msg="m3"))
        self.assertEqual([e.kind for e in session.events].count("blind_edit"), 1)

    def test_bash_command_with_a_path_relative_to_the_session_folder_names_the_file(self):
        session = parse_lines(
            user("edit it", 1),
            dict(assistant([tool("Bash", command="sed -n '1,50p' src/app/route.ts")], 2, msg="m1"), cwd="/repo"),
            dict(assistant([tool("Edit", file_path="/repo/src/app/route.ts", old_string="a", new_string="b")],
                           3, msg="m2"), cwd="/repo"))
        self.assertEqual([e.kind for e in session.events].count("blind_edit"), 0)

    def test_file_loaded_as_instructions_is_not_a_blind_edit(self):
        session = parse_lines(
            {"type": "attachment", "attachment": {"type": "instructions",
                                                  "files": [{"path": "/h/memory/MEMORY.md", "content": "x"}]}},
            user("remember this", 1),
            assistant([tool("Edit", file_path="/h/memory/MEMORY.md", old_string="a", new_string="b")], 2))
        self.assertEqual([e.kind for e in session.events].count("blind_edit"), 0)

    def test_relative_path_must_match_the_whole_name(self):
        session = parse_lines(
            user("edit it", 1),
            dict(assistant([tool("Bash", command="cat tests/test_check.py")], 2, msg="m1"), cwd="/repo"),
            dict(assistant([tool("Edit", file_path="/repo/check.py", old_string="a", new_string="b")],
                           3, msg="m2"), cwd="/repo"))
        self.assertEqual([e.kind for e in session.events].count("blind_edit"), 1)

    def test_self_correction_needs_the_whole_phrase(self):
        texts = ["Anyone can sign up, no waitlist.", "The page shows nothing while you wait, so it feels slow.",
                 "Do you want me to wait, or retry?", "There is no waiting on the review.",
                 "With two attempts and no wait between them, each run fails."]
        for text in texts:
            session = parse_lines(user("go", 1), assistant([{"type": "text", "text": text}], 2))
            self.assertEqual([e.kind for e in session.events].count("self_correction"), 0, text)

    def test_output_tokens_use_the_largest_value_per_message(self):
        session = parse_lines(
            user("go", 1),
            assistant([{"type": "text", "text": "a"}], 2, msg="m1", tokens=4),
            assistant([tool("Bash", command="ls")], 3, msg="m1", tokens=812))
        self.assertEqual(session.prompts[0].output_tokens, 812)

    def test_turn_counts_belong_to_the_prompt_before_them(self):
        session = parse_lines(
            user("one", 1), assistant([tool("Bash", command="ls")], 2, msg="m1", tokens=10),
            user([{"type": "tool_result", "tool_use_id": "t", "is_error": True, "content": "x"}], 3),
            user("two", 4), assistant([{"type": "text", "text": "ok"}], 5, msg="m2", tokens=7))
        one, two = session.prompts
        self.assertEqual((one.tool_results, one.tool_errors, one.output_tokens), (1, 1, 10))
        self.assertEqual((two.tool_results, two.tool_errors, two.output_tokens), (0, 0, 7))


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
        self.assertEqual([e.kind for e in self.basic.events].count("interrupt"), 1)

    def test_behavior_events(self):
        events = parse.parse_session(PROJ / "signals.jsonl").events
        kinds = sorted(e.kind for e in events)
        self.assertEqual(kinds, ["blind_edit", "edit", "edit", "edit", "interrupt",
                                 "self_correction", "self_correction", "tool", "tool", "tool", "tool", "tool"])
        self.assertEqual({e.model for e in events}, {"claude-opus-5-5"})
        blind = [e for e in events if e.kind == "blind_edit"]
        self.assertEqual(blind[0].timestamp.second, 3)

    def test_command_and_first_flags(self):
        prompts = self.basic.prompts
        self.assertTrue(prompts[0].is_first)
        self.assertFalse(prompts[1].is_first)
        self.assertTrue(prompts[2].is_command)
        self.assertFalse(prompts[0].is_command)

    def test_usage_deduplicated_by_message_id(self):
        self.assertEqual(sum(p.output_tokens for p in self.basic.prompts), 50)

    def test_synthetic_skipped(self):
        self.assertNotIn("<synthetic>", [p.model for p in self.basic.prompts])

    def test_counts(self):
        first, second, _ = self.basic.prompts
        self.assertEqual((first.tool_results, first.tool_errors), (1, 1))
        self.assertEqual((second.tool_results, second.user_edits, second.compactions), (1, 1, 1))
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

    def test_own_run_by_command_and_by_data_dir_leaves_no_prompts(self):
        self.assertEqual(parse.parse_session(PROJ / "own_run.jsonl").prompts, [])
        self.assertEqual(parse.parse_session(PROJ / "own_run_tool.jsonl").prompts, [])


class LoadSessionsTest(unittest.TestCase):
    def test_own_runs_excluded(self):
        ids = {s.session_id for s in parse.load_sessions([ROOT])}
        self.assertNotIn("own_run", ids)
        self.assertNotIn("own_run_tool", ids)
        self.assertEqual(ids, {"basic", "two_models", "truncated", "non_human", "signals"})

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
