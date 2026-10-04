# is-it-nerfed

is-it-nerfed is a Claude Code plugin. It tells you if your Claude model got worse for you,
from your own session logs. A script samples the prompts you typed, and Sonnet subagents
decide for each prompt if you had to steer the model because the model made an error. The
script then compares the last two weeks with an earlier window and prints a short verdict.
It also writes one HTML report with a chart, the Claude Code changes in that time, and the
status incidents.

## Install

```
claude plugin marketplace add resitaydin/is-it-nerfed && claude plugin install is-it-nerfed@is-it-nerfed
```

## Run

In any Claude Code session, type:

```
/is-it-nerfed
```

Claude shows how many prompts need a label and the token cost, and asks before it starts.
The result has 5 lines, for example:

```
Opus 5.5 — slightly worse (78% probability)
Model-caused steering: 9% → 15% (+6 pts), Sep 24–28 vs Sep 30–Oct 4
Your side: CLAUDE.md changed 2×, CLI 2.1.271 → 2.1.289
Harness: 2.1.285 changed default effort (possible cause)
Report: ~/.claude/is-it-nerfed/report-2026-10-04.html
```

## What data it reads

- Your local session logs in `~/.claude*/projects/` (and in `$CLAUDE_CONFIG_DIR/projects/`
  if you set that variable).
- It writes its cache and the reports to `~/.claude/is-it-nerfed/`.

Your prompts do not leave your machine, other than to the Sonnet subagents that run in your
own Claude Code session. The script makes only two network requests, both public GETs with
no data from you:

- `https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md`
- `https://status.claude.com/api/v2/incidents.json`

## Cost

The labels use your Claude plan, at about 1.4k Sonnet tokens per labeled prompt. A first run
labels about 600 prompts, which uses about 0.9M tokens. Later runs label only the new prompts, because the labels are
cached.

## Keep more history

Claude Code deletes session logs after 30 days by default. To keep more history for a
better baseline, set `cleanupPeriodDays` in `~/.claude/settings.json`:

```json
{
  "cleanupPeriodDays": 365
}
```

## Uninstall

```
claude plugin uninstall is-it-nerfed@is-it-nerfed
claude plugin marketplace remove is-it-nerfed
rm -rf ~/.claude/is-it-nerfed
```
