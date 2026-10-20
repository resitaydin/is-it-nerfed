# Judge evaluation

This folder measures the judge against reference labels from two stronger models, Opus and Fable.
The verdict counts only one label: steering that the model caused. The release gate scores only that label.
It needs 30 or more reference positives, a kappa of 0.7 or more, and a false-alarm rate of 1% or less.
The folder `eval/data/` is git-ignored. It holds private prompts.

## Procedure

1. Run `python3 eval/make_set.py --n 200 --seed 1`.
   The script writes `eval/data/items.jsonl` and `eval/data/key.jsonl`.
   Half of the items come from prompts that follow an interrupt or start with a negation word.
2. Ask Claude to label `items.jsonl` with the `is-it-nerfed:judge` agent. Write the result to `eval/data/pred.jsonl`.
   Use one agent for each 40 items. Use the same dispatch text as the skill.
3. Label `items.jsonl` again with Opus agents and with Fable agents, in the same way.
   Write to `gold.jsonl` only the items where Opus and Fable agree on the model-caused label.
   Do not open `key.jsonl` during this step. The key holds the date and the model.
4. Run `python3 eval/score.py eval/data/gold.jsonl eval/data/pred.jsonl`.
   The script scores only the ids that are in both files. It prints how many ids it skipped.
5. Check the gate. If it fails, change `plugins/is-it-nerfed/agents/judge.md`, run steps 2 to 4 again, and add a row to the table.

## Metrics

The gate metrics use one binary label: `kind == steering` and `cause == model`.

- False-alarm rate: false positives over reference negatives. A false alarm adds to both
  windows, so it pulls the rate ratio toward 1 and hides a real change. This is the main metric.
- Recall: a missed positive does not bias the rate ratio while recall stays the same over
  time. It only makes the verdict less sure. The script reports it, but the gate does not use it.
- Kappa with a 95% bootstrap interval, and Gwet's AC1. Kappa is unstable when positives are
  rare, so read it with the interval and the counts.
- Diagnostics: kappa on steering, and the three-class kappa on cause. The verdict does not use
  these labels, so they are not part of the gate.

## Attempts

The reference is the consensus of independent Opus and Fable labels (175 of 200 items). Opus vs Fable agreement is 0.88 / 0.67, which is the ceiling.

| Date | Attempt | Judge and prompt | Kappa steering | Kappa cause | Model-caused precision | Model-caused recall |
| ---- | ------- | ---------------- | -------------- | ----------- | ---------------------- | ------------------- |
| 2026-10-04 | 1 | Haiku, original prompt | 0.54 | 0.20 | 0.13 | 0.33 |
| 2026-10-04 | 2 | Sonnet, original prompt | 0.85 | 0.62 | 1.00 | 0.67 |
| 2026-10-04 | 3 | Sonnet, stricter cause rules (reverted) | 0.72 | 0.40 | 1.00 | 0.83 |

### Attempts on the model-caused gate

Set: the 200 items above plus 170 model-hint items (`make_set.py --hints-only`, every unused
candidate in the author's logs). The reference is the 361 items where Opus and Fable agree on the
model-caused label. Opus vs Fable kappa on that label is 0.73, which is the ceiling.
False alarms are split into the first 200 items (191 negatives) and the hint items (157 hard negatives).

| Date | Attempt | Judge and prompt | Ref positives | TP / FP / FN | Kappa (95% CI) | False alarms first 200 / hint |
| ---- | ------- | ---------------- | ------------- | ------------ | -------------- | ----------------------------- |
| 2026-10-08 | 4 | Sonnet, current prompt | 13 | 8 / 4 / 5 | 0.63 (0.33–0.83) | 0 / 4 |
| 2026-10-08 | 5 | Sonnet, attempt 3 prompt | 13 | 5 / 3 / 8 | 0.46 (0.15–0.70) | 0 / 3 |
| 2026-10-08 | 6 | Sonnet, "repeat" and "clear instruction" rules | 13 | 10 / 20 / 3 | 0.44 (0.23–0.61) | 3 / 17 |

Result: the gate fails. The logs have only 13 reference positives, not 30. The current prompt
is the best of the three, so it stays. It has no false alarms on the first 200 items. Its recall
is about 0.6, which costs power but does not bias the rate ratio. The rules of attempt 6 found
more positives, but they added 20 false alarms, so they were not kept.

### Judge model comparison

Same 370 items and the current prompt. Each judge is scored against Fable alone (17 positives),
because the Opus+Fable reference would favor Opus. False alarms on the first 200 items have 194 Fable negatives.

| Date | Judge | TP / FP / FN | Kappa (95% CI) | False alarms first 200 |
| ---- | ----- | ------------ | -------------- | ---------------------- |
| 2026-10-08 | Opus 5.5 | 13 / 5 / 4 | 0.73 (0.52–0.88) | 3 / 194 |
| 2026-10-08 | Sonnet | 10 / 4 / 7 | 0.63 (0.39–0.81) | 0 / 194 |
| 2026-10-08 | Haiku 5.5 | 11 / 21 / 6 | 0.41 (0.22–0.58) | 10 / 194 |

Result: Sonnet stays the judge. It has the fewest false alarms, which is the main metric. Opus
finds more positives, but its kappa interval overlaps Sonnet's, and it costs more of the user's
plan. Opus would also judge its own work when the user asks about Opus. Haiku 5.5 gives too many
false alarms.

## Verdict calibration

Synthetic sessions at a 3.5% base rate (8 prompts per session, 200 runs per row), the same
windows for both rules. "Old" is the ±5-point rule; "new" is the rate-ratio rule with the
1.5-point floor. Columns: firm worse / "no change" / leaning (any direction).

| Sessions per side | True change | Old | New |
| ----------------- | ----------- | --- | --- |
| 25 | none | 3% / 42% / 51% | 3% / 0% / 22% (71% unclear) |
| 50 | ×1.5 | 16% / 44% / 40% | 16% / 0% / 37% |
| 50 | ×2 | 48% / 14% / 38% | 48% / 0% / 35% |
| 100 | none | 0% / 99% / 0% | 1% / 0% / 28% (70% unclear) |
| 100 | ×1.5 | 22% / 74% / 4% | 28% / 0% / 38% |
| 100 | ×2 | 73% / 18% / 9% | 76% / 0% / 20% |

The old rule called a real ×1.5 change "no change" in 74% of runs at 100 sessions. The new rule
never says "no change" at these sizes, because the data cannot rule out ×1.5; it says "unclear"
and shows the ratio interval.

## Behavior signals on real logs

Measured on the author's local logs. A/A: random halves of the sessions of one model, 200 runs.

| Date | Model (sessions) | A/A: any signal rises | Events: blind edits / interrupts / self-corrections |
| ---- | ---------------- | --------------------- | --------------------------------------------------- |
| 2026-10-04 | Opus 5.5 (46) | 22% | (not recorded) |
| 2026-10-04 | Fable 5.1 (47) | 24% | (not recorded) |
| 2026-10-04 | Opus 5 (28) | 25% | (not recorded) |
| 2026-10-14 | Opus 5.5 (159) | 2% | 1 / 17 / 7 |
| 2026-10-14 | Fable 5.1 (27) | 4% | 0 / 17 / 1 |
| 2026-10-14 | Opus 5 (11) | 7% | 0 / 12 / 0 |

The 2026-10-04 rows came from three faults, which the 2026-10-14 rows do not have:

- The parser missed Bash reads by a relative path, so 124 of 403 edits counted as blind. After the
  fix, 1 of 403 is blind.
- The interval for a signal was 90%. With few sessions, it gave a false rise in 8% of A/A runs
  instead of 5%. The interval is now 95%.
- A signal with no events could rise: the half hit added to each side made its ratio compare only
  the tool calls. A signal now needs 10 events in both windows together.

The planted-signal results from 2026-10-04 are removed, because they planted extra blind edits on
top of the false ones. On these logs, only interrupts have enough events to measure, so a firm
"worse" verdict is confirmed only when interrupts rise.
