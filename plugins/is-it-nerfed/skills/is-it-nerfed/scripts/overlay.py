from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional

import parse
import sample

KEYWORDS = re.compile(r"effort|thinking|system prompt|compact|default model|context|reasoning", re.I)


@dataclass
class Incident:
    name: str
    start: datetime
    end: Optional[datetime]
    components: List[str]


def fetch(url: str, timeout: int = 10) -> Optional[str]:
    request = urllib.request.Request(url, headers={"User-Agent": "is-it-nerfed"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except Exception:
        return None


def parse_changelog(md: str) -> Dict[str, List[str]]:
    changelog: Dict[str, List[str]] = {}
    current: Optional[List[str]] = None
    for line in md.splitlines():
        if line.startswith("## "):
            current = changelog.setdefault(line[3:].strip(), [])
        elif line.startswith("- ") and current is not None:
            current.append(line[2:].strip())
    return changelog


def relevant_lines(changelog: Dict[str, List[str]], versions: Iterable[str]) -> List[dict]:
    found = []
    for version in versions:
        for line in changelog.get(version, []):
            if KEYWORDS.search(line):
                found.append({"id": sample.item_id(version + line), "version": version, "line": line})
    return found


def version_first_seen(sessions: List[parse.Session]) -> Dict[str, date]:
    first: Dict[str, date] = {}
    for session in sessions:
        for prompt in session.prompts:
            if not prompt.cli_version:
                continue
            day = prompt.timestamp.date()
            if prompt.cli_version not in first or day < first[prompt.cli_version]:
                first[prompt.cli_version] = day
    return first


def parse_incidents(text: str) -> List[Incident]:
    try:
        data = json.loads(text)
    except ValueError:
        return []
    incidents = []
    # The feed is not ours: skip a row of another shape instead of failing after the labels are paid for.
    for raw in data.get("incidents", []) if isinstance(data, dict) else []:
        try:
            resolved = raw.get("resolved_at")
            incidents.append(Incident(
                name=raw["name"],
                start=parse.parse_time(raw.get("started_at") or raw["created_at"]),
                end=parse.parse_time(resolved) if resolved else None,
                components=[c["name"] for c in raw.get("components") or []],
            ))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return incidents
