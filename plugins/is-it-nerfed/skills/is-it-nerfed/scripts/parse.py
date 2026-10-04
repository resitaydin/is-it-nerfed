"""Read Claude Code session logs (JSONL) into prompts and per-session counts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

INTERRUPT_PREFIX = "[Request interrupted by user"
SYSTEM_PREFIXES = (
    "<local-command-",
    "<task-notification>",
    "<bash-stdout>",
    "<bash-stderr>",
    "<bash-input>",
    "<system-reminder>",
)
COMMAND_PREFIXES = ("<command-name>", "<command-message>", "/")
NOT_HUMAN_FLAGS = ("isMeta", "isCompactSummary", "isVisibleInTranscriptOnly")
OWN_COMMAND = "<command-name>/is-it-nerfed"
OWN_DATA_DIR = "is-it-nerfed/work/"
SYNTHETIC_MODEL = "<synthetic>"


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


@dataclass
class Session:
    session_id: str
    project: str
    prompts: List[Prompt] = field(default_factory=list)
    claude_md_files: Dict[str, str] = field(default_factory=dict)
    cli_versions: List[str] = field(default_factory=list)
    tool_results: int = 0
    tool_errors: int = 0
    interrupts: int = 0
    user_modified_edits: int = 0
    compactions: int = 0
    output_tokens: int = 0
    is_own: bool = False


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
            if session.prompts and not session.is_own:
                sessions.append(session)
    return sessions


def parse_session(path: Path) -> Session:
    session = Session(session_id=path.stem, project=path.parent.name)
    state = _State()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if OWN_DATA_DIR in raw:
            session.is_own = True
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(line, dict) or line.get("isSidechain"):
            continue
        version = line.get("version")
        if version and version not in session.cli_versions:
            session.cli_versions.append(version)
        kind = line.get("type")
        if kind == "user":
            _read_user(line, session, state)
        elif kind == "assistant":
            _read_assistant(line, session, state)
        elif kind == "system" and line.get("subtype") == "compact_boundary":
            session.compactions += 1
        elif kind == "attachment" and not session.claude_md_files:
            session.claude_md_files = _claude_md_files(line.get("attachment"))
    if any(OWN_COMMAND in p.text for p in session.prompts):
        session.is_own = True
    return session


@dataclass
class _State:
    last_prompt: Optional[Prompt] = None
    agent_id: Optional[str] = None
    agent_text: str = ""
    seen_message_ids: set = field(default_factory=set)
    interrupted: bool = False


def _read_user(line: dict, session: Session, state: _State) -> None:
    result = line.get("toolUseResult")
    if isinstance(result, dict) and result.get("userModified") is True:
        session.user_modified_edits += 1
    content = (line.get("message") or {}).get("content")
    blocks = content if isinstance(content, list) else []
    results = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
    session.tool_results += len(results)
    session.tool_errors += sum(1 for b in results if b.get("is_error") is True)
    if results or any(line.get(flag) for flag in NOT_HUMAN_FLAGS):
        return
    text = _user_text(content)
    if text is None:
        return
    if text.startswith(INTERRUPT_PREFIX):
        session.interrupts += 1
        state.interrupted = True
        return
    if text.startswith(SYSTEM_PREFIXES):
        return
    prompt = Prompt(
        uuid=line.get("uuid", ""),
        session_id=session.session_id,
        project=session.project,
        timestamp=_parse_time(line.get("timestamp", "")),
        text=text,
        model=None,
        cli_version=line.get("version", ""),
        is_first=not session.prompts,
        is_command=text.startswith(COMMAND_PREFIXES),
        after_interrupt=state.interrupted,
        prev_agent_text=state.agent_text,
        history=[p.text for p in reversed(session.prompts)],
    )
    state.interrupted = False
    state.last_prompt = prompt
    session.prompts.append(prompt)


def _read_assistant(line: dict, session: Session, state: _State) -> None:
    message = line.get("message") or {}
    model = message.get("model")
    if model == SYNTHETIC_MODEL:
        return
    message_id = message.get("id")
    if message_id not in state.seen_message_ids:
        state.seen_message_ids.add(message_id)
        usage = message.get("usage") or {}
        session.output_tokens += usage.get("output_tokens") or 0
    if message_id != state.agent_id:
        state.agent_id = message_id
        state.agent_text = ""
    content = message.get("content")
    if isinstance(content, list):
        state.agent_text += "".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    prompt = state.last_prompt
    if prompt is not None and prompt.model is None and model:
        prompt.model = model


def _user_text(content: Any) -> Optional[str]:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return None


def _claude_md_files(attachment: Any) -> Dict[str, str]:
    if not isinstance(attachment, dict) or attachment.get("type") != "instructions":
        return {}
    files = [f for f in attachment.get("files") or [] if isinstance(f, dict)]
    return {
        f["path"]: hashlib.sha256(f.get("content", "").encode("utf-8")).hexdigest()[:12]
        for f in files if str(f.get("path", "")).lower().endswith("claude.md")
    }


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
