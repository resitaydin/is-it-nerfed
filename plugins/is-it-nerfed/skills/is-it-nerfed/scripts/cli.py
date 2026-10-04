"""Command line entry: `scan` writes label batches, `report` reads labels and writes the report."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import analyze
import labels as labels_mod
import overlay
import parse
import report
import sample

SKILL_DIR = Path(__file__).resolve().parent.parent
CHANGELOG_URL = "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md"
INCIDENTS_URL = "https://status.claude.com/api/v2/incidents.json"
DEFAULT_DATA_DIR = "~/.claude/is-it-nerfed"
EXIT_NO_LOGS = 2
EXIT_RETRY = 3


class Paths:
    def __init__(self, data_dir: str):
        self.data = Path(data_dir).expanduser()
        self.work = self.data / "work"
        self.to_label = self.work / "to_label"
        self.labels_dir = self.work / "labels"
        self.plan = self.work / "plan.json"
        self.incidents = self.work / "incidents.json"
        self.to_interpret = self.work / "to_interpret.jsonl"
        self.interp_labels = self.work / "interp-labels.jsonl"
        self.labels_cache = self.data / "cache" / "labels.jsonl"
        self.interp_cache = self.data / "cache" / "interp.jsonl"
        self.baselines = self.data / "cache" / "baselines.json"
        self.judge = self.data / "cache" / "judge.json"


def _read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_jsonl(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _emit(data: dict) -> None:
    print(json.dumps(data))


def _anchors() -> List[dict]:
    text = (SKILL_DIR / "anchors.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def _iso(window) -> Optional[List[str]]:
    return [d.isoformat() for d in window] if window else None


def _batch_items(paths: Paths) -> Dict[str, dict]:
    items: Dict[str, dict] = {}
    for path in sorted(paths.to_label.glob("*.jsonl")):
        for row in labels_mod.read_jsonl(path):
            items.setdefault(row["id"], row)
    return items


def _interp_cache(paths: Paths) -> Dict[str, dict]:
    cache: Dict[str, dict] = {}
    for row in labels_mod.read_jsonl(paths.interp_cache):
        cache.setdefault(row["id"], row)
    return cache


def _fetch_overlay(paths: Paths, sessions: List[parse.Session], windows: list) -> Optional[List[dict]]:
    """Save the incidents, and return the uncached changelog lines; None when a fetch fails."""
    changelog, incidents = overlay.fetch(CHANGELOG_URL), overlay.fetch(INCIDENTS_URL)
    if changelog is None or incidents is None:
        return None
    paths.incidents.write_text(incidents, encoding="utf-8")
    first_seen = overlay.version_first_seen(sessions)
    versions = [v for v, day in first_seen.items() if any(w[0] <= day <= w[1] for w in windows)]
    lines = overlay.relevant_lines(overlay.parse_changelog(changelog), versions)
    cached = _interp_cache(paths)
    return [line for line in lines if line["id"] not in cached]


def scan(args: argparse.Namespace) -> int:
    paths = Paths(args.data_dir)
    today = date.fromisoformat(args.today) if args.today else date.today()
    roots = parse.find_roots(Path.home(), os.environ)
    sessions = parse.load_sessions(roots)
    if not sessions:
        _emit({"status": "no_logs", "message": "No session logs found in: %s"
               % (", ".join(str(r) for r in roots) or str(Path.home() / ".claude"))})
        return EXIT_NO_LOGS
    shutil.rmtree(paths.work, ignore_errors=True)
    paths.work.mkdir(parents=True)
    baselines = _read_json(paths.baselines, {})
    model = args.model or analyze.current_model(sessions, today)
    windows = analyze.windows_for(sessions, model, baselines) if model else None
    result = {"status": "ok", "model": model, "prompts_to_label": 0, "batches": [],
              "interpret_batch": None, "interpret_items": 0, "interpret_labels": str(paths.interp_labels),
              "estimated_tokens": 0, "labels_dir": str(paths.labels_dir)}
    if model is None or windows is None:
        result["status"] = "no_model" if model is None else "too_early"
        return _emit(result) or 0
    prev = analyze.previous_model(sessions, model)
    prev_win = analyze.prev_window(sessions, prev) if prev else None
    cached = set(labels_mod.load_cache(paths.labels_cache))
    prompts = {m: [p for s in sessions for p in s.prompts if p.model == m] for m in (model, prev)}
    picked = {p.uuid: p for window, m in zip((*windows, prev_win), (model, model, prev)) if window
              for p in sample.select(prompts[m], window, skip=cached)}
    items = [sample.build_item(p) for p in picked.values()]
    anchors = _anchors() if items else []
    batches = sample.write_batches(items, anchors, paths.to_label)
    interpret = None if args.offline else _fetch_overlay(paths, sessions, list(windows))
    if interpret:
        _write_jsonl(paths.to_interpret, interpret)
    _write_json(paths.plan, {
        "model": model, "today": today.isoformat(), "overlay_ok": interpret is not None,
        "windows": {"base": _iso(windows[0]), "recent": _iso(windows[1]), "prev": _iso(prev_win)},
        "items": {sample.item_id(u): u for u in picked}})
    result.update(prompts_to_label=len(items), batches=[str(b) for b in batches],
                  interpret_batch=str(paths.to_interpret) if interpret else None,
                  interpret_items=len(interpret or []),
                  estimated_tokens=sample.estimate_tokens(items, len(batches)))
    _emit(result)
    return 0


def _merge_interp(paths: Paths) -> Dict[str, dict]:
    asked = {r["id"]: r for r in labels_mod.read_jsonl(paths.to_interpret)}
    new = []
    cache = _interp_cache(paths)
    for row in labels_mod.read_jsonl(paths.interp_labels):
        item = asked.get(row.get("id"))
        if item is None or item["id"] in cache or row.get("affects_behavior") not in ("yes", "no"):
            continue
        cache[item["id"]] = {"id": item["id"], "version": item["version"], "line": item["line"],
                             "affects_behavior": row["affects_behavior"], "reason": row.get("reason", "")}
        new.append(cache[item["id"]])
    labels_mod.append_cache(paths.interp_cache, new)
    return cache


def report_cmd(args: argparse.Namespace) -> int:
    paths = Paths(args.data_dir)
    if not paths.plan.exists():
        print("No scan found. Run scan first.", file=sys.stderr)
        return 1
    plan = _read_json(paths.plan, {})
    today = date.fromisoformat(args.today) if args.today else date.fromisoformat(plan["today"])
    items = _batch_items(paths)
    found, missing = labels_mod.read_labels(sorted(paths.labels_dir.glob("*.jsonl")), items)
    if missing and not args.final:
        retry = paths.to_label / "retry-001.jsonl"
        _write_jsonl(retry, [items[i] for i in missing])
        _emit({"status": "retry", "batches": [str(retry)]})
        return EXIT_RETRY
    if missing:
        print("%d items left without a label" % len(missing), file=sys.stderr)
    judge = _read_json(paths.judge, {})
    agreement = labels_mod.anchor_agreement(found, _anchors())
    if agreement is not None:
        judge = {"agreement": agreement, "date": today.isoformat()}
        _write_json(paths.judge, judge)
    cache = labels_mod.load_cache(paths.labels_cache)
    new = [{"uuid": plan["items"][i], **label} for i, label in found.items()
           if i in plan["items"] and plan["items"][i] not in cache]
    labels_mod.append_cache(paths.labels_cache, new)
    cache.update({r["uuid"]: r for r in new})
    sessions = parse.load_sessions(parse.find_roots(Path.home(), os.environ))
    incidents = overlay.parse_incidents(paths.incidents.read_text(encoding="utf-8")) if paths.incidents.exists() else []
    analysis, baselines = analyze.run(
        sessions, cache, _merge_interp(paths), incidents, overlay.version_first_seen(sessions),
        _read_json(paths.baselines, {}), judge.get("agreement"), plan["overlay_ok"], today,
        model=plan["model"])
    _write_json(paths.baselines, baselines)
    out = paths.data / ("report-%s.html" % today.isoformat())
    out.write_text(report.render(analysis), encoding="utf-8")
    print("\n".join(report.summary(analysis, out)))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="cli.py")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("scan", "report"):
        p = sub.add_parser(name)
        p.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
        p.add_argument("--today")
    sub.choices["scan"].add_argument("--model")
    sub.choices["scan"].add_argument("--offline", action="store_true")
    sub.choices["report"].add_argument("--final", action="store_true")
    args = parser.parse_args(argv)
    return (scan if args.command == "scan" else report_cmd)(args)


if __name__ == "__main__":
    sys.exit(main())
