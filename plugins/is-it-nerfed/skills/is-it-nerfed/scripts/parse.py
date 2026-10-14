"""Read Claude Code session logs (JSONL) into prompts and per-session counts."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

INTERRUPT_PREFIX = "[Request interrupted by user"
SYSTEM_PREFIXES = (
    "<local-command-",
    "<task-notification>",
    "<bash-stdout>",
    "<bash-stderr>",
    "<bash-input>",
    "<system-reminder>",
)
COMMAND_TAGS = ("<command-name>", "<command-message>")
# Commands with arguments come in command tags; plain text holds only a lone "/compact" or the like.
SLASH_COMMAND = re.compile(r"/[\w:-]+\s*")
NOT_HUMAN_FLAGS = ("isMeta", "isCompactSummary", "isVisibleInTranscriptOnly")
# A log line that shows this tool ran: its command, a run of its script, or a read of its data.
OWN_RUN = re.compile(r"<command-name>/is-it-nerfed|skills/is-it-nerfed/scripts/cli\.py\W+(?:scan|report)"
                     r"|is-it-nerfed/work/")
SYNTHETIC_MODEL = "<synthetic>"
EDIT_TOOLS = ("Edit", "MultiEdit")
SELF_CORRECTION = re.compile(
    r"\b(?:oh wait|hmm,? actually|actually,? wait|let me reconsider|i was wrong|my mistake)\b",
    re.I)


@dataclass
class Prompt:
    uuid: str
    session_id: str
    project: str
    timestamp: datetime
    text: str
    model: Optional[str]
    cli_version: str
    is_first: bool
    is_command: bool
    after_interrupt: bool
    prev_agent_text: str
    history: List[str]
    # Activity in the turn that this prompt started, up to the next prompt.
    tool_results: int = 0
    tool_errors: int = 0
    user_edits: int = 0
    compactions: int = 0
    output_tokens: int = 0


@dataclass
class Event:
    """One agent-behavior event: "tool", "edit", "blind_edit", "self_correction" or "interrupt"."""
    timestamp: datetime
    model: Optional[str]
    kind: str


@dataclass
class Session:
    session_id: str
    project: str
    prompts: List[Prompt] = field(default_factory=list)
    claude_md_files: Dict[str, str] = field(default_factory=dict)
    events: List[Event] = field(default_factory=list)


def find_roots(home: Path, env: Mapping[str, str]) -> List[Path]:
    candidates = [home / ".claude"]
    if env.get("CLAUDE_CONFIG_DIR"):
        candidates.append(Path(env["CLAUDE_CONFIG_DIR"]))
    candidates += sorted(p for p in home.glob(".claude*") if (p / "projects").is_dir())
    roots: List[Path] = []
    for path in candidates:
        if path.is_dir() and path not in roots:
            roots.append(path)
    return roots


def load_sessions(roots: List[Path]) -> List[Session]:
    sessions = []
    for root in roots:
        for path in sorted(root.glob("projects/*/*.jsonl")):
            session = parse_session(path)
            if session.prompts:
                sessions.append(session)
    return sessions


def parse_session(path: Path) -> Session:
    """The session up to the request that ran this tool: that request and all later lines are left out."""
    session = Session(session_id=path.stem, project=path.parent.name)
    state = _State()
    with path.open(encoding="utf-8", errors="replace") as f:
        for raw in f:
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(line, dict) or line.get("isSidechain"):
                continue
            if OWN_RUN.search(raw):
                if _typed_text(line) is None and session.prompts:
                    session.prompts.pop()  # the request in plain words that made the agent run this tool
                break
            _read_line(line, session, state)
    return session


def _typed_text(line: dict) -> Optional[str]:
    """The text of a line that the user typed, else None."""
    if line.get("type") != "user" or any(line.get(flag) for flag in NOT_HUMAN_FLAGS):
        return None
    content = (line.get("message") or {}).get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return None
    return _user_text(content)


def _turn(session: Session) -> Optional[Prompt]:
    """The last prompt that is not a command: the work that tool calls, tokens and compactions belong to."""
    return next((p for p in reversed(session.prompts) if not p.is_command), None)


def _read_line(line: dict, session: Session, state: _State) -> None:
    state.cwd = line.get("cwd") or state.cwd
    kind = line.get("type")
    if kind == "user":
        _read_user(line, session, state)
    elif kind == "assistant":
        _read_assistant(line, session, state)
    elif kind == "system" and line.get("subtype") == "compact_boundary" and _turn(session):
        _turn(session).compactions += 1
    elif kind == "attachment":
        # A file in the context is not blind.
        state.tool_values.update(f["path"] for f in _instruction_files(line.get("attachment")))
        if not session.claude_md_files:
            session.claude_md_files = _claude_md_files(line.get("attachment"))


@dataclass
class _State:
    agent_id: Optional[str] = None
    agent_text: str = ""
    message_tokens: Dict[str, int] = field(default_factory=dict)  # largest output_tokens per message id
    seen_tool_ids: set = field(default_factory=set)
    tool_values: set = field(default_factory=set)  # every string input of earlier tool calls
    commands: List[Tuple[str, str]] = field(default_factory=list)  # earlier Bash commands with their folder
    cwd: str = ""
    model: Optional[str] = None
    interrupted: bool = False


def _read_user(line: dict, session: Session, state: _State) -> None:
    turn = _turn(session)
    result = line.get("toolUseResult")
    content = (line.get("message") or {}).get("content")
    blocks = content if isinstance(content, list) else []
    results = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
    if turn is not None:
        turn.user_edits += isinstance(result, dict) and result.get("userModified") is True
        turn.tool_results += len(results)
        turn.tool_errors += sum(1 for b in results if b.get("is_error") is True)
    text = _typed_text(line)
    if text is None:
        return
    if text.startswith(INTERRUPT_PREFIX):
        session.events.append(Event(parse_time(line.get("timestamp", "")), state.model, "interrupt"))
        state.interrupted = True
        return
    if text.startswith(SYSTEM_PREFIXES):
        return
    is_command = text.startswith(COMMAND_TAGS) or bool(SLASH_COMMAND.fullmatch(text))
    prompt = Prompt(
        uuid=line.get("uuid", ""),
        session_id=session.session_id,
        project=session.project,
        timestamp=parse_time(line.get("timestamp", "")),
        text=text,
        model=None,
        cli_version=line.get("version", ""),
        is_first=not is_command and state.agent_id is None,  # no agent reply yet: nothing to steer
        is_command=is_command,
        after_interrupt=state.interrupted,
        prev_agent_text=state.agent_text,
        history=[p.text for p in reversed(session.prompts)],
    )
    state.interrupted = False
    session.prompts.append(prompt)


def _read_assistant(line: dict, session: Session, state: _State) -> None:
    message = line.get("message") or {}
    model = message.get("model")
    if model == SYNTHETIC_MODEL:
        return
    message_id = message.get("id")
    # Each content block of a message has its own line, and the usage on later lines can be larger.
    tokens = (message.get("usage") or {}).get("output_tokens") or 0
    before = state.message_tokens.get(message_id, 0) if message_id else 0
    turn = _turn(session)
    if tokens > before:
        if message_id:
            state.message_tokens[message_id] = tokens
        if turn is not None:
            turn.output_tokens += tokens - before
    if message_id != state.agent_id:
        state.agent_id = message_id
        state.agent_text = ""
    content = message.get("content")
    if isinstance(content, list):
        text = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        state.agent_text += text
        _read_behavior(content, text, parse_time(line.get("timestamp", "")), model, session, state)
    state.model = model or state.model
    prompt = session.prompts[-1] if session.prompts else None
    if prompt is not None and prompt.model is None and model:
        prompt.model = model


def _read_behavior(content: list, text: str, when: datetime, model: Optional[str],
                   session: Session, state: _State) -> None:
    """An edit is blind when no earlier tool call in the session named its file.

    A tool call names a file when one of its inputs is the path, or a Bash command contains it."""
    kinds = ["self_correction"] * len(SELF_CORRECTION.findall(text))
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use" or block.get("id") in state.seen_tool_ids:
            continue
        state.seen_tool_ids.add(block.get("id"))
        tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
        kinds.append("tool")
        if block.get("name") in EDIT_TOOLS:
            kinds.append("edit")
            path = str(tool_input.get("file_path", ""))
            if path and path not in state.tool_values and not any(_names_file(c, cwd, path)
                                                                  for cwd, c in reversed(state.commands)):
                kinds.append("blind_edit")
        state.tool_values.update(v for v in tool_input.values() if isinstance(v, str))
        if block.get("name") == "Bash" and isinstance(tool_input.get("command"), str):
            state.commands.append((state.cwd, tool_input["command"]))
    session.events += [Event(when, model, kind) for kind in kinds]


def _names_file(command: str, cwd: str, path: str) -> bool:
    """A command names a file by its absolute path, or by its whole path relative to the folder it ran in."""
    if path in command:
        return True
    folder = cwd.rstrip("/") + "/"
    if not cwd or not path.startswith(folder):
        return False
    relative = re.escape(path[len(folder):])
    return re.search(r"(?:^|[\s'\"=])(?:\./)?%s(?=$|[\s'\";|)>])" % relative, command) is not None


def _user_text(content: Any) -> Optional[str]:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return None


def _instruction_files(attachment: Any) -> List[dict]:
    if not isinstance(attachment, dict) or attachment.get("type") != "instructions":
        return []
    return [f for f in attachment.get("files") or [] if isinstance(f, dict) and isinstance(f.get("path"), str)]


def _claude_md_files(attachment: Any) -> Dict[str, str]:
    return {
        f["path"]: hashlib.sha256(f.get("content", "").encode("utf-8")).hexdigest()[:12]
        for f in _instruction_files(attachment) if f["path"].lower().endswith("claude.md")
    }


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
