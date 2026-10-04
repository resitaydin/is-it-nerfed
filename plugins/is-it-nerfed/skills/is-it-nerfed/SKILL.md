---
name: is-it-nerfed
description: Checks whether the user's Claude model got worse for them, from their own local Claude Code session logs, and gives a verdict plus an HTML report. Use this skill when the user asks if Claude, Opus, Sonnet, or "the model" is nerfed, dumber, lazier, degraded, or worse lately, this week, or since an update, even when the question is casual ("did claude get dumber?", "is opus worse this week"). Do not use it for "nerf" in games, balance patches, or difficulty settings.
---

# Is it nerfed?

This skill tells the user whether their model got worse *for them*. A script reads their
local session logs and samples prompts. Haiku subagents label each prompt: did the user have
to steer the model, and was the model the cause? The script then compares a recent window with
a baseline window and writes a verdict.

`${CLAUDE_SKILL_DIR}` is the folder of this skill. Run every command below as written.

## Privacy rules

The batch files and label files hold the user's own prompts. Keep them out of this
conversation:

- Do not read the batch files or the label files yourself. They would fill your context, and
  the subagents read them instead.
- Do not print any of the user's prompts in the chat.
- Only the subagents open those files.

## 1. Scan

Run:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/cli.py" scan
```

It prints one JSON object. Read `status`:

- `no_logs` (exit code 2): show the `message` and stop.
- `no_model`: tell the user "I found no recent replies from a Claude model in your logs." Stop.
- `too_early`: tell the user "Your logs for <model> cover fewer than 3 active days. Try again
  after a few more days of use." Stop.
- `ok`: continue.

## 2. Ask for consent

If `batches` is empty, all prompts already have a label from an earlier run. Skip to step 4
(if `interpret_batch` is not null, do step 3 for it first, without the question).

Otherwise ask, with N = `prompts_to_label` and X = `estimated_tokens` rounded to the nearest
thousand (for example 463,210 → "about 463k tokens"):

> <N> prompts need a label. This uses about <X> tokens from your plan. Continue?

If the user says no, stop. Do not label anything.

## 3. Label with Haiku subagents

For each path in `batches`, start one Agent with `model: "haiku"` and this prompt (put in the
real paths):

> Read ${CLAUDE_SKILL_DIR}/judge-prompt.md. Then label every item in <batch path> and write
> the labels to <labels_dir>/<batch file name>. Reply with only: done <lines written>.

`<batch file name>` is the last part of the batch path, for example `batch-003.jsonl`.

If `interpret_batch` is not null, start one more Agent with `model: "haiku"`:

> Read ${CLAUDE_SKILL_DIR}/interpret-prompt.md. Then label every item in <interpret_batch>
> and write the labels to <interpret_labels>. Reply with only: done <lines written>.

Run at most 4 agents at a time. Start the next agent when one finishes. If an agent fails or
writes fewer lines, continue with the others. The report step finds missing labels and asks
for them again.

## 4. Report

Run:

```
python3 "${CLAUDE_SKILL_DIR}/scripts/cli.py" report
```

- Exit code 0: stdout has the summary lines. Go to step 5.
- Exit code 3: stdout is `{"status": "retry", "batches": [<path>]}`. Label that batch with one
  Haiku agent, the same way as in step 3. Then run:

  ```
  python3 "${CLAUDE_SKILL_DIR}/scripts/cli.py" report --final
  ```

If stderr says "N items left without a label", tell the user that number in one line. The
verdict still uses all the labels that exist.

## 5. Show the result

Show the summary lines exactly as printed, in a code block. Do not add your own analysis of
the numbers. The last line names the HTML report. Ask the user if they want to open it; on
yes, run `open "<report path>"` (macOS) or `xdg-open "<report path>"` (Linux).
