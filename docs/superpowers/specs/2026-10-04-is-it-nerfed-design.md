# is-it-nerfed: design spec

Date: 2026-10-04. Status: approved in chat, waiting for spec review.
Research base: `docs/research/report.md` and `docs/research/notes/`.

## 1. Goal

A Claude Code user installs one plugin and types `/is-it-nerfed`. The tool reads the user's
own local session logs and tells the user whether the current model needs more steering now
than in its first days. The verdict is fair: it shows the changes on the user's side and on the
harness side next to the model result, and it gives an honest probability.

The tool costs the author nothing. All LLM work runs on the user's own Claude Code session.

### Success criteria

- One install line. One command to run.
- A verdict on the first run when the model has at least about 6 active days of data.
- The A/A test gives a false "worse" verdict in 8% of runs or fewer (5% expected from the one-sided test).
- The planted-nerf test finds a +10 point drop in 80% of runs or more.
- The judge reaches Cohen's kappa of 0.7 or more on `steering` and on `cause` against the
  author's private labeled set before the first public release.

### Out of scope for the MVP

- Codex support.
- Pooled or uploaded data of any kind.
- Headless `claude -p` judging.
- A shared public canary task set.
- Thinking-length metrics.

## 2. User flow

1. Install:
   `claude plugin marketplace add resitaydin/is-it-nerfed && claude plugin install is-it-nerfed@is-it-nerfed`
2. Run `/is-it-nerfed` in any Claude Code session.
3. The script scans the logs (no LLM) and prints the counts and a token estimate.
4. Claude asks: "N prompts need a label. This uses about X tokens from your plan. Continue?"
5. On yes, Claude runs Sonnet subagents that label the batches. On 200 real prompts, Haiku
   reached kappa 0.54 (steering) and 0.20 (cause); Sonnet reached 0.85 and 0.62.
6. The script calculates the verdict, prints a 5-line summary, and writes one HTML report.

Terminal example:

```
Opus 5.5 — slightly worse (78% probability)
Model-caused steering: 9% → 15% (+6 pts), Sep 24–28 vs Sep 30–Oct 4
Your side: CLAUDE.md changed 2×, CLI 2.1.271 → 2.1.289
Harness: 2.1.285 changed default effort (possible cause)
Report: ~/.claude/is-it-nerfed/report-2026-10-04.html
```

## 3. Architecture

The LLM is the user's in-session Claude, so the script cannot call it. The script and Claude
pass work through files in the data directory.

```
/is-it-nerfed (SKILL.md)
  ├─ python3 nerf.py scan    → work/to_label/*.jsonl, work/to_interpret.jsonl, prints estimate
  ├─ Claude asks for consent, then Sonnet subagents → work/labels/*.jsonl
  └─ python3 nerf.py report  → cache merge, anchor check, stats, HTML, terminal summary
```

Data directory: `~/.claude/is-it-nerfed/` with `cache/labels.jsonl`, `cache/baselines.json`,
`work/` (cleared on each scan), and `report-YYYY-MM-DD.html`.

Python 3.9+ standard library only (tests use `unittest`). No install step, no build step.

### Modules

| File | One job |
|---|---|
| `parse.py` | Find all config roots (`~/.claude`, `$CLAUDE_CONFIG_DIR`, other `~/.claude*` dirs with `projects/`). Read the JSONL files. Yield sessions with prompts, assistant turns, tool results, and metadata. |
| `sample.py` | Select the prompts to label, sample up to the cap per window, blind them, mix in the anchors, and write the batch files. |
| `overlay.py` | Fetch `CHANGELOG.md` and the status incidents. Map CLI versions to dates from the logs. Keyword-filter the changelog lines. |
| `stats.py` | Windows, cluster bootstrap, verdict rule, project-mix check. |
| `report.py` | Terminal summary and the HTML report with inline SVG. |
| `cli.py` | The `scan` and `report` commands. |

### Parser rules (from local inspection of CLI 2.1.260 to 2.1.289)

- Path: `<root>/projects/<sanitized-cwd>/<sessionId>.jsonl`. Skip `subagents/` files.
- A human prompt is a `type: "user"` line, not `isMeta`, not `isSidechain`, whose content is
  text and not a `tool_result`.
- Skip slash-command prompts and the first prompt of each session for labeling (they cannot
  steer). They still count in the "Is it you?" panel.
- Group assistant lines by `message.id`. Count usage once per `message.id`.
- Skip assistant lines with model `<synthetic>`.
- The model of a prompt is the model of the next assistant reply.
- Deterministic signals: `[Request interrupted by user`, `tool_result.is_error`,
  `toolUseResult.userModified`, `system/compact_boundary`.
- The CLAUDE.md hash per session comes from `attachment.type == "instructions"` content.
- Exclude the tool's own sessions: any session that contains `/is-it-nerfed` or reads the
  data directory.
- Ignore unknown line types. Never branch on the CLI version.

## 4. The judge

### What gets labeled

- Three windows: baseline and recent of the current model, and the last window of the
  previous model.
- Up to 200 prompts per window, sampled at random and spread across days, with a fixed seed.
- Labels are cached by prompt `uuid`. A later run labels only uncached prompts.
- Expected first-run size: about 600 prompts, about 0.9M Sonnet tokens (about 1.4k per prompt).

### Input per item

The user prompt, the last assistant text before it (max 1,500 characters), and the earlier
user prompts in the same session (max 2,000 characters in total, newest first). The script
removes dates, model names, version strings, and the words "nerf", "nerfed", "dumber",
"degraded". Items from all windows are mixed in random order. Batches hold 40 items.

### Output per item

```json
{"id": "...", "reasoning": "...",
 "kind": "new_work | steering | other",
 "steering_type": "correction | rejection | failure_report | redirect | null",
 "cause": "model | user | unclear",
 "evidence": "<exact quote from the item>"}
```

Rules in `judge-prompt.md`:
- `steering` means the prompt changes, corrects, rejects, or reports a failure of what the
  agent just did.
- `cause = model` when the user had already stated the requirement (in this prompt's history)
  and the agent went against it, or the agent made a clear error on a clear instruction.
- `cause = user` for new information, a scope change, or a preference change.
- `cause = unclear` otherwise. Unclear does not count as model-caused.
- The script rejects a label whose `evidence` is not a substring of the item text. Rejected
  items go back into the next batch once, then count as unlabeled.

### Anchors and drift

`anchors.jsonl` holds 30 synthetic hand-labeled items. The script mixes them into the batches
with ids that look like real ids. If agreement on `kind` + `cause` is below 80%, the report
says "judge drift" and shows no verdict.

### Changelog interpretation

For CLI versions seen in the windows, the script selects changelog lines that match
`effort|thinking|system prompt|compact|default model|context|reasoning`. The same subagent flow
labels each line `affects_behavior: yes | no` with a one-sentence reason.

## 5. Statistics and verdict

- Primary metric: model-caused steering rate = prompts with `kind = steering` and
  `cause = model`, divided by labeled prompts.
- Diagnostics (not in the verdict): total steering rate, interrupts per prompt, tool error rate,
  user edits to agent edits, output tokens per prompt.
- Windows: if the model has fewer than 28 active days, split its active days into a first and a
  second half. Otherwise, the first 14 days against the last 14 days. When the model first reaches 28 active days, the baseline result
  is saved to `cache/baselines.json` and reused.
- Uncertainty: 5,000 two-stage cluster-bootstrap resamples per window. Stage 1 resamples the
  labeled sessions with replacement. Stage 2 draws the model-caused count of each picked session
  from a binomial with that session's size and rate. Output: the difference (recent minus
  baseline), a 90% interval, and P(worse) = share of resamples > 0.
- Verdict, with SESOI = 5 points:

| Verdict | Condition |
|---|---|
| No change | The 90% interval lies inside ±5 points. |
| Clearly worse | The interval lies above 0 and the estimate is 10 points or more. |
| Slightly worse | The interval lies above 0. |
| Better | The interval lies below 0. |
| Leaning worse / leaning better | Any other case. Show P(worse) or P(better). |

- Minimum data: a firm verdict needs at least 5 labeled sessions on each side. Below that,
  the verdict is at most "leaning worse" or "leaning better".

- Project-mix check: repeat the calculation on prompts from projects that appear in both
  windows. If the verdict differs, the report says "your project mix changed" and shows both.
- Model against model: the same calculation on the recent window of the current model and the
  last window of the previous model, labeled "less controlled: different weeks".
- Attribution lines: when a CLI version with an `affects_behavior: yes` line starts inside the
  recent window, or an incident overlaps it, the summary names it as a possible cause.

## 6. Report

Terminal: the 5-line summary from section 2.

HTML (one self-contained file, no external requests):
1. Verdict and probability.
2. Chart: faint daily dots, a 5-day rolling line with a band, markers for CLI versions and
   incidents.
3. Model against model.
4. "Is it you?" panel: CLAUDE.md edits, CLI versions, median prompt length, project mix,
   compaction count.
5. Harness changes: changelog lines marked `affects_behavior: yes`.
6. Evidence receipts: the 3 worst model-caused moments per window, with quotes and reasons.

The report stays local. It contains the user's own words.

## 7. Error handling

- No logs found: say where the tool looked and stop.
- Network failure: skip the overlay, say so in the report.
- Fewer than 3 active days for the model: show the counts and "too early", no verdict.
- Subagent batch fails or returns bad JSON: retry that batch once, then continue without it and
  report the missing count.

## 8. Testing and evaluation

| Layer | Check | When |
|---|---|---|
| Unit tests | Synthetic JSONL fixtures: duplicate `message.id`, `<synthetic>`, sidechains, interrupts, own-session exclusion, CLAUDE.md hash. | Every commit |
| A/A test | Random session split on fixture data, 200 runs: false "worse" verdicts ≤ 8%, false "better" ≤ 8%. | Every commit |
| Planted-nerf test | Add +10 points of model-caused steering to the recent window: "worse" verdicts ≥ 80%. | Every commit |
| Judge eval | `eval/` harness: precision, recall, kappa on the author's private labeled set (~200 prompts, git-ignored). Target kappa ≥ 0.7. | Before release, and on every `judge-prompt.md` change |

## 9. Repo layout

```
.claude-plugin/marketplace.json
plugins/is-it-nerfed/
  .claude-plugin/plugin.json
  skills/is-it-nerfed/
    SKILL.md
    judge-prompt.md
    anchors.jsonl
    scripts/  (cli.py, parse.py, sample.py, overlay.py, stats.py, report.py, report_template.html)
tests/
eval/        (harness public, labeled data git-ignored)
docs/
```

## 10. Skills and tools to use during the build

| Step | Skill or tool |
|---|---|
| Implementation plan | `superpowers:writing-plans` |
| Every module | `superpowers:test-driven-development` |
| Execution | `superpowers:subagent-driven-development` |
| `SKILL.md`, its description, and its trigger evals | `skill-creator:skill-creator` |
| HTML report design | `frontend-design:frontend-design` |
| Chart, colors, and stat tiles | `dataviz` |
| Plugin and marketplace manifest format | `claude-code-guide` agent |
| Bugs | `superpowers:systematic-debugging` |
| Cleanup | `simplify` and `code-simplifier` |
| Before merge | `code-review`, then `superpowers:verification-before-completion` |
| Branch finish | `superpowers:finishing-a-development-branch` |

## 11. Open risks

- The judge is the model family under test. The anchors catch drift, but not a shared blind spot.
- No published study validates transcript steering as a nerf detector. The A/A and
  planted-nerf tests bound the statistics, not the construct.
- Claude Code has no published log schema. A format change can break the parser.
- The token estimate per label is not yet measured. The first real run sets it.
