# is-it-nerfed MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Claude Code plugin whose `/is-it-nerfed` skill reads the user's local session logs, has the user's own Claude label prompts, and gives a fair, probability-backed verdict on whether the current model needs more steering than in its first days.

**Architecture:** A stdlib-only Python script runs in two commands. `scan` parses the logs, samples and blinds prompts, and writes batch files. The skill then has Sonnet subagents label the batches. `report` validates the labels, runs a cluster-bootstrap verdict, and writes a terminal summary and one self-contained HTML file. The script and Claude talk only through files in `~/.claude/is-it-nerfed/`.

**Tech Stack:** Python 3.9 standard library (`json`, `random`, `statistics`, `urllib`, `hashlib`, `dataclasses`), `unittest` for tests, inline SVG for the chart, Claude Code plugin + skill format.

**Spec:** `docs/superpowers/specs/2026-10-04-is-it-nerfed-design.md`. Research: `docs/research/report.md`.

## Global Constraints

- Python 3.9 compatible. Every module starts with `from __future__ import annotations`. No third-party imports anywhere, including tests (pytest is not installed; use `unittest`).
- Run all tests with: `python3 -m unittest discover -s tests -t . -v`
- `SCRIPTS` = `plugins/is-it-nerfed/skills/is-it-nerfed/scripts`. Modules import each other flat (`import parse`). `tests/__init__.py` inserts `SCRIPTS` into `sys.path`.
- Data directory default: `~/.claude/is-it-nerfed/` (override with `--data-dir`). Layout: `cache/labels.jsonl`, `cache/interp.jsonl`, `cache/baselines.json`, `cache/judge.json`, `work/` (cleared on each `scan`), `report-YYYY-MM-DD.html`.
- Values pinned by the spec: cap 200 prompts per window; batch size 40; previous agent reply max 1,500 chars; earlier prompts max 2,000 chars total, newest first; 5,000 bootstrap resamples; 90% interval; SESOI 5 points; "clearly worse" at estimate ≥ 10 points; anchor agreement threshold 80%; 30 anchors; windows split at 28 active days, 14-day windows; "too early" below 3 active days.
- Blinding removes: dates, model names, version strings, and the words nerf, nerfed, dumber, degraded (case-insensitive).
- Network: only two public GETs — `https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md` and `https://status.claude.com/api/v2/incidents.json`, timeout 10 s.
- Commits: author `resitaydin`, no Claude co-author line. Each commit message in ASD-STE100 style.
- The HTML report makes no external requests (no CDN, no fonts from the web).

## Review Focus

- A JSONL file with a truncated last line (the CLI was killed mid-write) → the parser skips that line and keeps the rest. Test in Task 1.
- A user who used two models in the same session (`/model` switch) → each prompt takes the model of its own next reply, not the session's first model. Test in Task 1.
- The subagent writes labels with ids that do not exist, or duplicates → unknown ids are ignored, the first valid label per id wins. Test in Task 3.
- A day with prompts but zero labeled prompts in the chart → the day is drawn as a gap, not as a 0% point. Test in Task 6.
- The tool's own run sessions (`/is-it-nerfed`) inside the analysed windows → excluded, so a run never counts itself. Test in Task 1.

---

### Task 1: Repo skeleton and log parser

**Files:**
- Create: `.gitignore` (ignore `__pycache__/`, `eval/data/`, `.DS_Store`)
- Create: `tests/__init__.py`, `tests/fixtures/` (hand-written JSONL), `tests/test_parse.py`
- Create: `SCRIPTS/parse.py`

**Interfaces:**
- Produces:
  - `@dataclass Prompt`: `uuid: str, session_id: str, project: str, timestamp: datetime (UTC), text: str, model: Optional[str], cli_version: str, is_first: bool, is_command: bool, after_interrupt: bool, prev_agent_text: str, history: List[str]` (earlier user prompts of the session, newest first, untruncated)
  - `@dataclass Session`: `session_id: str, project: str, prompts: List[Prompt], claude_md_hash: Optional[str], cli_versions: List[str], tool_results: int, tool_errors: int, interrupts: int, user_modified_edits: int, compactions: int, output_tokens: int, is_own: bool`
  - `find_roots(home: Path, env: Mapping[str, str]) -> List[Path]` — `home/.claude`, `env["CLAUDE_CONFIG_DIR"]`, and every `home/.claude*` dir that has a `projects/` subdir; deduplicated, existing only.
  - `parse_session(path: Path) -> Session`
  - `load_sessions(roots: List[Path]) -> List[Session]` — all `projects/*/*.jsonl` (never `subagents/`), drops `is_own` sessions and sessions with no prompts.

Parser rules (from spec §3, verified on CLI 2.1.260–2.1.289):
- Human prompt: `type == "user"`, not `isMeta`, not `isSidechain`, content is a string or has a `text` block, and has no `tool_result` block.
- Text starting with `[Request interrupted by user` is not a prompt: count it in `interrupts` and set `after_interrupt=True` on the next prompt.
- Text starting with `<local-command-`, `<task-notification>`, `<bash-stdout>`, `<bash-stderr>`, `<system-reminder>` is not a prompt.
- `is_command`: text starts with `<command-name>` or `/`.
- `is_own`: any prompt text contains `<command-name>/is-it-nerfed` or `is-it-nerfed/work/`.
- Assistant lines: group by `message.id`; `output_tokens` counted once per id; skip model `<synthetic>`. `prev_agent_text` = concatenated `text` blocks of the last assistant message before the prompt.
- `Prompt.model` = model of the first non-synthetic assistant line after the prompt; `None` if none.
- `tool_errors` = `tool_result` blocks with `is_error: true`; `user_modified_edits` = user lines whose `toolUseResult.userModified` is true; `compactions` = `type == "system"` lines with `subtype == "compact_boundary"`.
- `claude_md_hash` = sha256 (first 12 hex) of the joined `content` of `attachment.type == "instructions"` files, from the first such line.
- `project` = the name of the parent dir of the JSONL file.
- Bad JSON lines and unknown types are skipped.

- [ ] **Step 1: Write fixtures** in `tests/fixtures/`: `basic.jsonl` (3 prompts, one after an interrupt, one `/clear` command, two assistant blocks sharing one `message.id` with `usage.output_tokens: 50` each, one `<synthetic>` line, one `is_error` tool result, one instructions attachment), `two_models.jsonl` (model switch mid-session), `own_run.jsonl` (contains `<command-name>/is-it-nerfed`), `truncated.jsonl` (last line cut mid-object). Put them under `tests/fixtures/root/projects/-proj-a/` so `find_roots`/`load_sessions` can run on them.

- [ ] **Step 2: Write the failing tests** in `tests/test_parse.py`:
  - `test_prompts_exclude_interrupt_and_system_lines`: `basic` has 3 prompts; second has `after_interrupt is True`; `interrupts == 1`.
  - `test_command_and_first_flags`: first prompt `is_first`; `/clear` prompt `is_command`.
  - `test_usage_deduplicated_by_message_id`: `output_tokens == 50`.
  - `test_synthetic_skipped`: no prompt has model `<synthetic>`.
  - `test_counts`: `tool_errors == 1`, `claude_md_hash` is a 12-char hex string.
  - `test_model_per_prompt`: `two_models` prompts have two different `model` values.
  - `test_own_run_excluded`: `load_sessions` on the fixture root returns no session with that id.
  - `test_truncated_line_skipped`: `truncated` parses with all complete prompts.
  - `test_find_roots`: a temp home with `.claude/projects` and `.claude-second/projects` returns both.

- [ ] **Step 3: Run tests, verify they fail.** Run: `python3 -m unittest tests.test_parse -v`. Expected: ImportError / FAIL.

- [ ] **Step 4: Implement `parse.py`** with the interfaces above.

- [ ] **Step 5: Run tests, verify they pass.** Then run `python3 -c "import sys; sys.path.insert(0,'SCRIPTS'); import parse, pathlib, os; s=parse.load_sessions(parse.find_roots(pathlib.Path.home(), os.environ)); print(len(s), sum(len(x.prompts) for x in s))"` on the author's machine. Expected: hundreds of sessions, about 3,000 prompts, no traceback.

- [ ] **Step 6: Commit** — `git add .gitignore tests SCRIPTS/parse.py && git commit -m "Add the session log parser"`

---

### Task 2: Windows, cluster bootstrap, verdict

**Files:**
- Create: `SCRIPTS/stats.py`, `tests/test_stats.py`, `tests/synth.py`

**Interfaces:**
- Produces:
  - `Window = Tuple[date, date]` (inclusive)
  - `make_windows(days: List[date]) -> Optional[Tuple[Window, Window]]` — `days` are sorted distinct active days. `< 3` → `None`. `< 28` → first half `days[: n//2]`, second half `days[n - n//2 :]` (middle day dropped when odd). `≥ 28` → `days[:14]`, `days[-14:]`.
  - `SessionCount = Tuple[str, int, int]` (session_id, model-caused steering count, labeled count)
  - `@dataclass BootResult`: `diff: float, lo: float, hi: float, p_worse: float, base_rate: float, recent_rate: float, n_base: int, n_recent: int` (rates and diff in percentage points)
  - `cluster_bootstrap(base: List[SessionCount], recent: List[SessionCount], n: int = 5000, seed: int = 0) -> BootResult` — resample sessions with replacement inside each window; rate = Σk/Σn; diff = recent − base; `lo`/`hi` = 5th/95th percentiles; `diff` is the observed (not resampled) difference; `p_worse` = share of resampled diffs > 0.
  - `verdict(r: BootResult, sesoi: float = 5.0) -> str`, checked in this order: `"no_change"` if `lo >= -sesoi and hi <= sesoi`; `"clearly_worse"` if `lo > 0 and diff >= 2*sesoi`; `"slightly_worse"` if `lo > 0`; `"better"` if `hi < 0`; else `"leaning_worse"` if `p_worse >= 0.5` else `"leaning_better"`.
- `tests/synth.py`: `make_counts(n_sessions: int, prompts_per: int, rate: float, seed: int) -> List[SessionCount]` — per-session rate drawn from `random.betavariate` with mean `rate` and concentration 20 (to model clustering).

- [ ] **Step 1: Write the failing tests:**
  - `test_windows_too_early`: 2 days → `None`.
  - `test_windows_halves_odd`: 7 days → first 3, last 3.
  - `test_windows_fixed_14`: 30 days → `days[:14]`, `days[-14:]`.
  - `test_bootstrap_identical_windows`: same counts both sides → `diff == 0`, `lo <= 0 <= hi`.
  - `test_verdict_table`: one `BootResult` per row of the spec table maps to the expected string (include `lo=1, hi=4` → `"no_change"`).
  - `test_aa_false_alarm_rate`: 200 runs, both windows `make_counts(40, 8, 0.12, seed)`, `n=1000`, seed per run → share of `slightly_worse|clearly_worse` ≤ 0.08 and share of `better` ≤ 0.08.
  - `test_planted_nerf_power`: 200 runs, base rate 0.12, recent 0.22 → share of `slightly_worse|clearly_worse` ≥ 0.80.

- [ ] **Step 2: Run, verify fail.** `python3 -m unittest tests.test_stats -v`
- [ ] **Step 3: Implement `stats.py`.** Use `random.Random(seed)`; percentiles by sorting the resampled list.
- [ ] **Step 4: Run, verify pass.** Expected: all pass in under 60 s.
- [ ] **Step 5: Commit** — `git commit -m "Add windows, cluster bootstrap and verdict rule"`

---

### Task 3: Sampling, blinding, batches, label validation, cache

**Files:**
- Create: `SCRIPTS/sample.py`, `SCRIPTS/labels.py`, `tests/test_sample.py`, `tests/test_labels.py`

**Interfaces:**
- Consumes: `Prompt` (Task 1), `Window` (Task 2).
- Produces (`sample.py`):
  - `eligible(p: Prompt) -> bool` — not `is_first`, not `is_command`.
  - `select(prompts: List[Prompt], window: Window, cap: int = 200, seed: int = 0, skip: Set[str] = frozenset()) -> List[Prompt]` — eligible prompts in the window, not in `skip` (cached uuids); if more than `cap`, take round-robin across days after a seeded shuffle inside each day.
  - `blind(text: str) -> str` — replace with `[x]`: ISO dates and times, month-name dates (`Sep 24`, `24 September 2026`), `claude-[\w.-]+`, `(Opus|Sonnet|Haiku|Fable)( \d+(\.\d+)*)?`, `\b\d+\.\d+\.\d+\b`, `\b(nerf|nerfed|dumber|degraded)\b` (case-insensitive).
  - `item_id(key: str) -> str` — `sha1(key)` first 10 hex chars.
  - `build_item(p: Prompt) -> dict` — `{"id": item_id(p.uuid), "prompt": ..., "previous_agent_reply": ... (≤1500 chars, keep the end), "earlier_prompts": [...] (newest first, stop before the total passes 2000 chars)}`, all fields blinded.
  - `write_batches(items: List[dict], anchors: List[dict], out_dir: Path, batch_size: int = 40, seed: int = 0) -> List[Path]` — anchors get `id = item_id("anchor-" + anchor["anchor_id"])` and lose their gold fields; all items are shuffled together; files `batch-001.jsonl`, …
  - `estimate_tokens(items: List[dict], n_batches: int) -> int` — `Σ len(json.dumps(item)) // 4 + 3000 * n_batches + 120 * len(items)`.
- Produces (`labels.py`):
  - `KINDS = {"new_work", "steering", "other"}`, `CAUSES = {"model", "user", "unclear"}`, `STEERING_TYPES = {"correction", "rejection", "failure_report", "redirect", None}`
  - `item_text(item: dict) -> str` — whitespace-normalized concatenation of all text fields.
  - `valid(label: dict, item: dict) -> bool` — enums valid; `evidence` (whitespace-normalized) is a non-empty substring of `item_text(item)`.
  - `read_labels(paths: List[Path], items_by_id: Dict[str, dict]) -> Tuple[Dict[str, dict], List[str]]` — returns valid labels by id (first valid wins, unknown ids ignored, bad JSON lines skipped) and the ids with no valid label.
  - `load_cache(path: Path) -> Dict[str, dict]` (keyed by prompt uuid) and `append_cache(path: Path, records: List[dict]) -> None`.
  - `is_model_steering(label: dict) -> bool` — `kind == "steering" and cause == "model"`.

- [ ] **Step 1: Write the failing tests:**
  - `test_select_cap_round_robin`: 10 days × 50 prompts, cap 200 → 200 prompts, 20 per day.
  - `test_select_skips_cached_and_ineligible`.
  - `test_blind`: `"Opus 5.5 on 2026-09-24 got nerfed, v2.1.285, claude-opus-5-5"` → contains none of `Opus`, `2026`, `nerfed`, `2.1.285`, `claude-`.
  - `test_build_item_truncation`: previous reply 5,000 chars → 1,500; earlier prompts total ≤ 2,000.
  - `test_write_batches_hides_anchor_gold`: no written line has a `gold_kind` key; 45 items + 30 anchors → 2 files.
  - `test_valid_rejects_fake_evidence` and `test_valid_accepts_whitespace_variant`.
  - `test_read_labels_unknown_and_duplicate_ids`: unknown id ignored; for a duplicated id, the first valid one wins; a missing id is in the returned list.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement `sample.py` and `labels.py`.**
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "Add sampling, blinding and label validation"`

---

### Task 4: Changelog and incident overlay

**Files:**
- Create: `SCRIPTS/overlay.py`, `tests/test_overlay.py`, `tests/fixtures/changelog_sample.md`, `tests/fixtures/incidents_sample.json`

**Interfaces:**
- Consumes: `Session` (Task 1).
- Produces:
  - `fetch(url: str, timeout: int = 10) -> Optional[str]` — `None` on any error.
  - `parse_changelog(md: str) -> Dict[str, List[str]]` — `## <version>` headers, `- ` bullet lines under each.
  - `KEYWORDS = re.compile(r"effort|thinking|system prompt|compact|default model|context|reasoning", re.I)`
  - `relevant_lines(changelog: Dict[str, List[str]], versions: Iterable[str]) -> List[dict]` — `{"id": item_id(version + line), "version", "line"}` for keyword matches.
  - `version_first_seen(sessions: List[Session]) -> Dict[str, date]` — first prompt date per CLI version.
  - `@dataclass Incident`: `name: str, impact: str, start: datetime, end: Optional[datetime]`
  - `parse_incidents(text: str) -> List[Incident]` — from `incidents[].started_at|created_at`, `resolved_at`, `impact`, `name`.

- [ ] **Step 1: Write fixtures** (3 versions, 6 bullets, 2 matching keywords; 2 incidents, one unresolved) **and failing tests:** `test_parse_changelog`, `test_relevant_lines_keyword_filter` (exactly 2), `test_parse_incidents` (unresolved has `end is None`), `test_fetch_returns_none_on_error` (unroutable URL `http://127.0.0.1:9/`), `test_version_first_seen`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement `overlay.py`** (`urllib.request` with a `User-Agent` header).
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "Add the changelog and incident overlay"`

---

### Task 5: Analysis

**Files:**
- Create: `SCRIPTS/analyze.py`, `tests/test_analyze.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces:
  - `family(model: str) -> str` — strip a trailing `-<digits>(-<digits>)*` (`claude-opus-5-5` → `claude-opus`).
  - `current_model(sessions, today: date) -> Optional[str]` — most prompts in the last 7 days.
  - `previous_model(sessions, model: str) -> Optional[str]` — same family, different id, ≥ 3 active days, latest last active day before `model`'s first day.
  - `model_days(sessions, model) -> List[date]`
  - `windows_for(sessions, model, baselines: dict) -> Optional[Tuple[Window, Window]]` — the saved base (if any) plus the recent window; otherwise `stats.make_windows(model_days(...))`. `scan` and `run` both use it.
  - `prev_window(sessions, prev_model) -> Window` — the last 14 active days of `prev_model` (all days if fewer).
  - `session_counts(sessions, model, window, labels: Dict[str, dict]) -> List[SessionCount]` — only labeled prompts count in `n`.
  - `side_changes(sessions, model, window) -> dict` — `{"claude_md_hashes": int, "cli_versions": List[str], "median_prompt_chars": int, "top_projects": List[Tuple[str, float]] (top 3 shares), "compactions_per_session": float, "interrupts_per_prompt": float, "tool_error_rate": float, "user_edits": int, "output_tokens_per_prompt": float}`
  - `daily(sessions, model, labels) -> List[Tuple[date, int, int]]` — days with prompts but 0 labeled are included with `n=0`.
  - `receipts(sessions, model, window, labels, k: int = 3) -> List[dict]` — `{"date", "quote", "reason"}` from model-caused labels, taken from the sessions with the highest k first.
  - `attribution(recent: Window, harness: List[dict], version_dates: Dict[str, date], incidents: List[Incident]) -> List[str]` — one sentence per `affects_behavior == "yes"` line whose version first appears inside `recent`, and per incident overlapping `recent`.
  - `@dataclass Analysis`: `status: str ("ok" | "too_early" | "judge_drift" | "no_model"), model, prev_model, base: Window, recent: Window, boot: BootResult, verdict: str, shared_verdict: Optional[str], compare: Optional[BootResult], compare_verdict: Optional[str], daily, markers: List[Tuple[date, str, str]], side: Dict[str, dict] ("base", "recent"), harness: List[dict], receipts: Dict[str, List[dict]], attribution: List[str], judge_agreement: Optional[float], overlay_ok: bool`
  - `run(sessions, labels, interp, incidents, version_dates, baselines: dict, judge_agreement: Optional[float], overlay_ok: bool, today: date) -> Tuple[Analysis, dict]` — returns the analysis and the possibly updated `baselines` dict. Freeze rule: when `model_days ≥ 28` and the model has no saved baseline, save `{"start", "end", "sessions": [[sid, k, n], ...]}`; when one is saved, use it as `base`. `judge_agreement < 0.8` → `status="judge_drift"`. `shared_verdict` = verdict on projects present in both windows, set only when it differs from `verdict`.

- [ ] **Step 1: Write the failing tests** with synthetic `Session` objects built in the test: `test_family`, `test_previous_model_same_family`, `test_too_early_status`, `test_judge_drift_status`, `test_baseline_frozen_at_28_days` (second call with more days reuses the saved base), `test_shared_projects_verdict_set_only_when_different`, `test_daily_keeps_zero_label_days`, `test_attribution_sentences`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement `analyze.py`.**
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "Add the analysis step"`

---

### Task 6: Report (terminal and HTML)

**Files:**
- Create: `SCRIPTS/report.py`, `SCRIPTS/report_template.html`, `tests/test_report.py`

**Required skills:** load `frontend-design:frontend-design` and `dataviz` before writing the template or the chart code.

**Interfaces:**
- Consumes: `Analysis` (Task 5).
- Produces:
  - `VERDICT_TEXT: Dict[str, str]` — `no_change: "no change"`, `slightly_worse: "slightly worse"`, `clearly_worse: "clearly worse"`, `better: "better"`, `leaning_worse: "probably worse"`, `leaning_better: "probably better"`.
  - `summary(a: Analysis, report_path: Path) -> List[str]` — exactly the 5 lines of spec §2 when `status == "ok"`; for other statuses, one line naming the status and the counts, then the report path.
  - `chart_svg(daily, markers, width: int = 720, height: int = 240) -> str` — faint dots per day (`k/n`), 5-day rolling line of pooled `Σk/Σn`, band = Wilson 90% interval of the pooled counts, vertical markers. Days with `n=0` break the line and draw no dot.
  - `render(a: Analysis) -> str` — fills the template; all user text HTML-escaped.

Template sections, in this order (spec §6): verdict + probability; chart; model against model; "Is it you?" panel (base vs recent table from `side`); harness changes (or "changelog not available: offline" when `overlay_ok` is false); evidence receipts. Colors as CSS tokens on `:root` with a `prefers-color-scheme: dark` override. No external requests. Works at 375 px width.

- [ ] **Step 1: Write the failing tests:** `test_summary_five_lines_ok`, `test_summary_too_early`, `test_render_escapes_html` (a receipt quote `<script>` appears escaped), `test_render_no_external_urls` (no `http` in `src=`/`href=`), `test_chart_gap_on_zero_label_day` (the SVG path for the line has two `M` segments around a 0-label day).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Design the template** with `frontend-design` and `dataviz`, then implement `report.py`.
- [ ] **Step 4: Run, verify pass.** Render a fixture `Analysis` to a scratch file, open it in a browser, check light and dark mode and 375 px width.
- [ ] **Step 5: Commit** — `git commit -m "Add the terminal summary and the HTML report"`

---

### Task 7: CLI (`scan` and `report`) and the end-to-end test

**Files:**
- Create: `SCRIPTS/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: all earlier modules.
- Produces:
  - `python3 cli.py scan [--model M] [--data-dir D] [--offline] [--today YYYY-MM-DD]` — clears `work/`; loads sessions; picks the model; builds windows with `analyze.windows_for` and `analyze.prev_window`; selects prompts per window minus cached uuids; reads `anchors.jsonl` from the skill dir (`Path(__file__).parent.parent`); writes `work/to_label/batch-*.jsonl` (anchors only when at least one real item exists); unless `--offline`, fetches the changelog and incidents into `work/`, and writes uncached relevant lines to `work/to_interpret.jsonl`; writes `work/plan.json` (model, windows, id → uuid map); prints one JSON object to stdout: `{"status", "model", "prompts_to_label", "batches": [paths], "interpret_items", "estimated_tokens", "labels_dir"}`.
  - `python3 cli.py report [--final] [--data-dir D] [--today YYYY-MM-DD]` — reads `work/labels/*.jsonl` against the batch items; if ids are missing and `--final` is absent, writes them to `work/to_label/retry-001.jsonl`, prints `{"status": "retry", "batches": [...]}` and exits with code 3; otherwise merges valid labels into `cache/labels.jsonl` (keyed by uuid), stores anchor agreement in `cache/judge.json`, merges interpretation labels into `cache/interp.jsonl`, runs `analyze.run`, saves `cache/baselines.json`, writes `report-<today>.html`, prints the summary lines.
  - Exit codes: 0 ok, 2 no logs found (message names the roots searched), 3 retry needed.

- [ ] **Step 1: Write the failing end-to-end test** `test_scan_label_report_roundtrip`: build a temp home with a synthetic log tree (10 days, 2 models in one family), run `scan` via `subprocess` with `--offline --today`, write fake labels for every item id (anchors labeled with their gold values), run `report --final`, assert exit 0, a report file exists, and stdout has 5 lines. Add `test_report_retry_exit_code` (drop one label → exit 3 and a `retry-001.jsonl`), `test_no_logs_exit_2`, `test_second_scan_skips_cached`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement `cli.py`** with `argparse`.
- [ ] **Step 4: Run the full suite, verify pass.** `python3 -m unittest discover -s tests -t . -v`
- [ ] **Step 5: Commit** — `git commit -m "Add the scan and report commands"`

---

### Task 8: Judge prompt and anchors

**Files:**
- Create: `plugins/is-it-nerfed/skills/is-it-nerfed/judge-prompt.md`, `plugins/is-it-nerfed/skills/is-it-nerfed/anchors.jsonl`, `tests/test_anchors.py`

**Interfaces:**
- Produces: anchor lines `{"anchor_id": "a01", "prompt", "previous_agent_reply", "earlier_prompts": [...], "gold_kind", "gold_steering_type", "gold_cause"}`; `labels.anchor_agreement(labels_by_id: Dict[str, dict], anchors: List[dict]) -> float` (add to `labels.py`; match on `kind` and `cause` both).

`judge-prompt.md` holds: the task in two sentences; the label definitions and `cause` rules copied from spec §4; "reason first, then label"; the output schema; "evidence must be an exact quote from the item"; "one JSON object per line, one line per item, nothing else"; 6 worked examples that are not anchors (2 new_work, 2 steering/model, 1 steering/user, 1 other). It never mentions models, dates, or degradation.

Anchor mix (30, all synthetic, no real user text): 8 new_work, 6 steering/model with the requirement in `earlier_prompts`, 4 steering/model with a clear agent error, 6 steering/user (new info or scope change), 2 steering/unclear, 4 other.

- [ ] **Step 1: Write the failing tests:** `test_anchor_count_and_mix` (counts above), `test_anchor_evidence_possible` (every anchor has non-empty `prompt`), `test_anchor_agreement` (perfect labels → 1.0; flip 7 → < 0.8).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Write `anchors.jsonl`, `judge-prompt.md`, and `anchor_agreement`.**
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "Add the judge prompt and the anchor set"`

---

### Task 9: Skill, plugin manifests, install check

**Files:**
- Create: `.claude-plugin/marketplace.json`, `plugins/is-it-nerfed/.claude-plugin/plugin.json`, `plugins/is-it-nerfed/skills/is-it-nerfed/SKILL.md`, `README.md`

**Required skills/agents:** `skill-creator:skill-creator` for `SKILL.md` and its trigger description; the `claude-code-guide` agent to confirm the current marketplace and plugin manifest fields and the `${CLAUDE_SKILL_DIR}` variable.

`SKILL.md` flow (the skill is user-invoked as `/is-it-nerfed`):
1. Run `python3 "${CLAUDE_SKILL_DIR}/scripts/cli.py" scan` and parse the JSON.
2. If `status` is not `ok`, show the message and stop.
3. Tell the user the model, the prompt count, and `estimated_tokens`; ask "Continue?". Stop on no.
4. For each batch path, start one Agent with `model: "sonnet"` (at most 4 at a time). Each agent reads `judge-prompt.md` and its batch file and writes `<labels_dir>/<batch name>`. The same for `to_interpret.jsonl` with the interpretation question (`affects_behavior: yes|no`, `reason`).
5. Run `report`. On exit 3, label the retry batch the same way and run `report --final`.
6. Show the summary lines and offer to open the HTML file.

README: what it does, the one install line, what data it reads, that nothing leaves the machine except the two public GETs, and how to raise `cleanupPeriodDays`.

- [ ] **Step 1: Confirm manifest formats** with the `claude-code-guide` agent. Record the answer in the commit message body.
- [ ] **Step 2: Write the manifests, `SKILL.md`, `README.md`.**
- [ ] **Step 3: Install check.** Run `claude plugin marketplace add ./` from the repo root and `claude plugin install is-it-nerfed@is-it-nerfed`. Expected: both succeed; `/is-it-nerfed` appears in a new session.
- [ ] **Step 4: Trigger check** with `skill-creator`'s description evals: the skill triggers on "is my model nerfed?" and "did claude get dumber" and not on "nerf the enemy damage".
- [ ] **Step 5: Commit** — `git commit -m "Add the skill and the plugin manifests"`

---

### Task 10: Judge eval harness

**Files:**
- Create: `eval/make_set.py`, `eval/score.py`, `eval/README.md`, `tests/test_eval.py`

**Interfaces:**
- Produces:
  - `python3 eval/make_set.py --n 200 --seed 1` → `eval/data/items.jsonl` (built with `sample.build_item`, eligible prompts sampled across all models and days; 50% of the sample taken from prompts with `after_interrupt` or that start with a negation word to oversample steering).
  - `score.py`: `cohen_kappa(a: List[str], b: List[str]) -> float`, `precision_recall(gold: List[str], pred: List[str], positive: str) -> Tuple[float, float]`; CLI `python3 eval/score.py eval/data/gold.jsonl eval/data/pred.jsonl` prints kappa for `kind == steering` (binary) and for `cause` on gold-steering items, plus precision and recall of model-caused steering.
- `eval/README.md`: the labeling procedure — Claude pre-labels `items.jsonl` with `judge-prompt.md` into `pred.jsonl`; the author copies it to `gold.jsonl` and corrects every line by hand without looking at the date; the release gate is kappa ≥ 0.7 on both.

- [ ] **Step 1: Write the failing tests:** `test_kappa_perfect` (1.0), `test_kappa_chance` (known 2×2 table → expected value to 3 decimals), `test_precision_recall`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "Add the judge evaluation harness"`

---

### Task 11: First real run and the judge gate (needs the author)

- [ ] **Step 1:** Run `/is-it-nerfed` on the author's machine. Record the real token use against `estimated_tokens`, and correct the estimate formula if it is off by more than 30%.
- [ ] **Step 2:** Run `eval/make_set.py`, pre-label, and ask the author to correct `gold.jsonl`. This step waits for the author.
- [ ] **Step 3:** Run `eval/score.py`. If kappa < 0.7, change `judge-prompt.md` (never the anchors to fit), re-run, and log each attempt's numbers in `eval/README.md`.
- [ ] **Step 4:** Commit the prompt changes and the numbers (never the data).

---

### Task 12: Final review

- [ ] **Step 1:** Run `simplify` and the `code-simplifier` agent over the branch.
- [ ] **Step 2:** Run `code-review` on the branch and fix the findings.
- [ ] **Step 3:** `superpowers:verification-before-completion`: the full test suite passes; a fresh install from GitHub works; the report opens offline.
- [ ] **Step 4:** `superpowers:finishing-a-development-branch`.
