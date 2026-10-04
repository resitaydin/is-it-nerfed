# Judge evaluation

This folder measures the judge against labels that the author corrects by hand.
The release gate is Cohen's kappa of 0.7 or more on both steering and cause.
The folder `eval/data/` is git-ignored. It holds private prompts.

## Procedure

1. Run `python3 eval/make_set.py --n 200 --seed 1`.
   The script writes `eval/data/items.jsonl` and `eval/data/key.jsonl`.
   Half of the items come from prompts that follow an interrupt or start with a negation word.
2. Ask Claude to label `items.jsonl` with `judge-prompt.md`. Write the result to `eval/data/pred.jsonl`.
   Use one Sonnet agent for each 40 items. Use the same dispatch text as the skill.
3. Copy `pred.jsonl` to `gold.jsonl`. Correct each line by hand.
   Do not open `key.jsonl` during this step. The key holds the date and the model.
4. Run `python3 eval/score.py eval/data/gold.jsonl eval/data/pred.jsonl`.
   The script scores only the ids that are in both files. It prints how many ids it skipped.
5. Check the gate. Kappa on steering and kappa on cause must both be 0.7 or more.
   If one kappa is lower, change `judge-prompt.md`, run steps 2 to 4 again, and add a row to the table.

## Metrics

- Kappa on steering: binary, `kind == steering`, over all common ids.
- Kappa on cause: three classes, over the ids where gold kind is steering.
- Precision and recall of model-caused steering: gold is the truth.

## Attempts

The reference is the consensus of independent Opus and Fable labels (175 of 200 items), because the author chose model reference labels instead of hand labels; Opus vs Fable agreement is 0.88 / 0.67, which is the ceiling.

| Date | Attempt | Judge and prompt | Kappa steering | Kappa cause | Model-caused precision | Model-caused recall |
| ---- | ------- | ---------------- | -------------- | ----------- | ---------------------- | ------------------- |
| 2026-10-04 | 1 | Haiku, original prompt | 0.54 | 0.20 | 0.13 | 0.33 |
| 2026-10-04 | 2 | Sonnet, original prompt | 0.85 | 0.62 | 1.00 | 0.67 |
| 2026-10-04 | 3 | Sonnet, stricter cause rules (reverted) | 0.72 | 0.40 | 1.00 | 0.83 |

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

Measured on the author's local logs (2026-10-04). A/A: random halves of the sessions of one
model, 200 runs. Planted: extra events added to one half at the given ratio.

| Model (sessions) | A/A: any signal rises | Blind edits ×2 / ×3 | Interrupts ×2 / ×3 |
| ---------------- | --------------------- | ------------------- | ------------------ |
| Opus 5.5 (46) | 22% | 80% / 100% | 44% / 74% |
| Fable 5.1 (47) | 24% | 38% / 67% | 70% / 98% |
| Opus 5 (28) | 25% | 74% / 100% | 60% / 90% |

So the confirmation rule removes about 75% of the judge's firm false alarms. In the March 2026
regression the signals moved 3–6×; at ×3 they confirm in 67–100% of runs.
