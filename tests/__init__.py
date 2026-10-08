from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins/is-it-nerfed/skills/is-it-nerfed/scripts"
sys.path.insert(0, str(SCRIPTS))

import parse  # noqa: E402


def make_prompt(uuid: str = "u", day: int = 1, **fields) -> parse.Prompt:
    """A prompt on a day of September 2026; any Prompt field can be set."""
    values = dict(uuid=uuid, session_id="s", project="p",
                  timestamp=datetime(2026, 9, day, 10, 0, tzinfo=timezone.utc),
                  text="hello", model=None, cli_version="2.1.0", is_first=False, is_command=False,
                  after_interrupt=False, prev_agent_text="", history=[])
    values.update(fields)
    return parse.Prompt(**values)
