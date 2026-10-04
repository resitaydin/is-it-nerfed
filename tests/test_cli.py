from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from tests import SCRIPTS

CLI = SCRIPTS / "cli.py"
ANCHORS = SCRIPTS.parent / "anchors.jsonl"
TODAY = "2026-09-11"
PROMPTS_PER_DAY = 5


def _line(kind: str, uuid: str, stamp: str, message: dict) -> str:
    return json.dumps({"type": kind, "uuid": uuid, "sessionId": "s", "version": "2.1.280",
                       "timestamp": stamp, "message": message})


def write_logs(home: Path, per_day: int = PROMPTS_PER_DAY) -> None:
    """Ten active days: 5 on the older model, 5 on the newer model of the same family."""
    project = home / ".claude" / "projects" / "-proj"
    project.mkdir(parents=True)
    for day in range(10):
        model = "claude-opus-5-4" if day < 5 else "claude-opus-5-5"
        start = datetime(2026, 9, 1, 10) + timedelta(days=day)
        lines = []
        for n in range(per_day):
            uuid = "u-%d-%d" % (day, n)
            at = (start + timedelta(minutes=2 * n)).isoformat() + ".000Z"
            lines.append(_line("user", uuid, at, {"role": "user", "content": "change thing %d %d" % (day, n)}))
            lines.append(_line("assistant", "a-" + uuid, at, {
                "id": "m-" + uuid, "model": model, "role": "assistant",
                "content": [{"type": "text", "text": "Done with that step."}],
                "usage": {"output_tokens": 10}}))
        (project / ("day%d.jsonl" % day)).write_text("\n".join(lines) + "\n", encoding="utf-8")


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.data = self.home / "data"
        write_logs(self.home)

    def run_cli(self, *args: str, home: Path = None) -> subprocess.CompletedProcess:
        env = dict(os.environ, HOME=str(home or self.home))
        env.pop("CLAUDE_CONFIG_DIR", None)
        return subprocess.run([sys.executable, str(CLI), *args, "--data-dir", str(self.data)],
                              capture_output=True, text=True, env=env)

    def scan(self) -> dict:
        result = self.run_cli("scan", "--offline", "--today", TODAY)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def batch_items(self, scan: dict) -> list:
        return [json.loads(l) for p in scan["batches"] for l in Path(p).read_text().splitlines()]

    def write_labels(self, scan: dict, skip: int = 0) -> None:
        gold = {json.loads(l)["anchor_id"]: json.loads(l) for l in ANCHORS.read_text().splitlines()}
        import sample
        gold_by_id = {sample.item_id("anchor-" + k): v for k, v in gold.items()}
        labels = []
        for item in self.batch_items(scan):
            anchor = gold_by_id.get(item["id"])
            labels.append({"id": item["id"], "kind": anchor["gold_kind"] if anchor else "other",
                           "steering_type": anchor["gold_steering_type"] if anchor else None,
                           "cause": anchor["gold_cause"] if anchor else "unclear",
                           "evidence": item["prompt"], "reasoning": "test"})
        out = Path(scan["labels_dir"])
        out.mkdir(parents=True, exist_ok=True)
        (out / "labels-001.jsonl").write_text("".join(json.dumps(l) + "\n" for l in labels[skip:]))

    def test_scan_label_report_roundtrip(self):
        scan = self.scan()
        self.assertEqual(scan["status"], "ok")
        self.assertEqual(scan["model"], "claude-opus-5-5")
        self.assertGreater(scan["prompts_to_label"], 0)
        self.assertGreater(len(scan["batches"]), 0)
        self.assertIsNone(scan["interpret_batch"])
        self.write_labels(scan)
        result = self.run_cli("report", "--final")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.strip().splitlines()), 6)
        self.assertTrue((self.data / ("report-%s.html" % TODAY)).exists())
        self.assertTrue((self.data / "cache" / "labels.jsonl").exists())
        self.assertTrue((self.data / "cache" / "baselines.json").exists())
        judge = json.loads((self.data / "cache" / "judge.json").read_text())
        self.assertEqual(judge, {"agreement": 1.0, "date": TODAY})

    def test_report_retry_exit_code(self):
        scan = self.scan()
        self.write_labels(scan, skip=1)
        result = self.run_cli("report")
        self.assertEqual(result.returncode, 3, result.stderr)
        retry = self.data / "work" / "to_label" / "retry-001.jsonl"
        self.assertEqual(json.loads(result.stdout), {"status": "retry", "batches": [str(retry)]})
        self.assertEqual(len(retry.read_text().splitlines()), 1)

    def test_report_final_with_missing_label_warns(self):
        scan = self.scan()
        self.write_labels(scan, skip=1)
        result = self.run_cli("report", "--final")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 items left without a label", result.stderr)

    def test_report_final_with_zero_labels_names_no_labels(self):
        self.scan()
        result = self.run_cli("report", "--final")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no labeled prompts", result.stdout)
        self.assertNotIn("judge", result.stdout)
        self.assertFalse((self.data / "cache" / "judge.json").exists())

    def test_no_logs_exit_2(self):
        empty = Path(self._tmp.name) / "empty"
        empty.mkdir()
        result = self.run_cli("scan", "--offline", "--today", TODAY, home=empty)
        self.assertEqual(result.returncode, 2)
        out = json.loads(result.stdout)
        self.assertEqual(out["status"], "no_logs")
        self.assertIn("No session logs found in:", out["message"])

    def test_second_scan_skips_cached(self):
        scan = self.scan()
        self.write_labels(scan)
        self.assertEqual(self.run_cli("report", "--final").returncode, 0)
        again = self.scan()
        self.assertEqual(again["status"], "ok")
        self.assertEqual(again["prompts_to_label"], 0)
        self.assertEqual(again["batches"], [])

    def test_second_scan_counts_cached_labels_against_the_cap(self):
        shutil.rmtree(self.home / ".claude")
        write_logs(self.home, per_day=110)
        scan = self.scan()
        self.assertEqual(scan["prompts_to_label"], 600)
        self.write_labels(scan)
        self.assertEqual(self.run_cli("report", "--final").returncode, 0)
        self.assertEqual(self.scan()["prompts_to_label"], 0)

    def scan_in_process(self, *args: str) -> dict:
        import cli
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}), contextlib.redirect_stdout(out):
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            self.assertEqual(cli.main(["scan", "--today", TODAY, "--data-dir", str(self.data), *args]), 0)
        return json.loads(out.getvalue())

    def test_estimate_includes_interpret_batch(self):
        import overlay
        import sample
        day9 = self.home / ".claude" / "projects" / "-proj" / "day9.jsonl"
        day9.write_text(day9.read_text().replace("2.1.280", "2.1.290"))
        offline = self.scan_in_process("--offline")
        pages = {"CHANGELOG": "## 2.1.290\n- Changed the default effort level\n",
                 "incidents": '{"incidents": []}'}
        fake = lambda url, timeout=10: next(v for k, v in pages.items() if k in url)
        with mock.patch.object(overlay, "fetch", fake):
            online = self.scan_in_process()
        self.assertEqual(online["interpret_items"], 1)
        rows = [json.loads(l) for l in Path(online["interpret_batch"]).read_text().splitlines()]
        extra = sample.estimate_tokens(rows, 1)
        self.assertEqual(online["estimated_tokens"], offline["estimated_tokens"] + extra)

    def test_too_early(self):
        for path in sorted((self.home / ".claude" / "projects" / "-proj").glob("*.jsonl")):
            if path.name not in ("day8.jsonl", "day9.jsonl"):
                path.unlink()
        scan = self.scan()
        self.assertEqual(scan["status"], "too_early")
        self.assertEqual(scan["batches"], [])


if __name__ == "__main__":
    unittest.main()
