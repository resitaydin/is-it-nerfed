from __future__ import annotations

import re
import unittest

from tests import SCRIPTS

JUDGE_PROMPT = (SCRIPTS.parent / "judge-prompt.md").read_text(encoding="utf-8")


class JudgePromptTest(unittest.TestCase):
    def test_no_words_that_unblind_the_judge(self):
        for word in ["nerf", "degrad", "dumber", "anchor", "window", "opus", "sonnet", "haiku",
                     "fable", "version"]:
            self.assertNotIn(word, JUDGE_PROMPT.lower(), word)
        self.assertIsNone(re.search(r"\b20\d\d-\d\d-\d\d\b", JUDGE_PROMPT))

    def test_answer_to_agent_question_is_checked_first(self):
        procedure = JUDGE_PROMPT.split("## Decision procedure", 1)[1]
        first_step = procedure.split("\n1. ", 1)[1].split("\n2. ", 1)[0]
        self.assertIn("question", first_step)
        self.assertIn("never `steering`", first_step)

    def test_reasoning_names_the_step_and_the_broken_instruction(self):
        output = JUDGE_PROMPT.split("## Output", 1)[1]
        self.assertIn("step", output)
        self.assertIn("broke", output)


if __name__ == "__main__":
    unittest.main()
