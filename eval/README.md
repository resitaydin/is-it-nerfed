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

| Date | Prompt change | Kappa steering | Kappa cause | P | R |
| ---- | ------------- | -------------- | ----------- | - | - |
