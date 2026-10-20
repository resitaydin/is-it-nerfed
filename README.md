# is-it-nerfed

![is-it-nerfed, a Claude Code plugin: Claude feels dumber lately? Your own logs have the proof.](assets/preview.png)

Everyone argues about whether Claude got worse. This Claude Code plugin answers the question
for **you**, from your own session logs, not from vibes on X.

It samples the prompts you typed and asks Sonnet subagents one question for each: did you have
to correct the model because the model made an error? It then compares the last two weeks with
an earlier window and gives you a verdict.

## Install

macOS and Linux (on Windows, use WSL).

```
claude plugin marketplace add resitaydin/is-it-nerfed && claude plugin install is-it-nerfed@is-it-nerfed
```

## Run

In any Claude Code session, type `/is-it-nerfed`, or just ask "did Claude get dumber?".
Claude shows the token cost and the time, and asks before it starts. You get 7 lines:

```
Verdict:        Nerfed for you. Opus 5.5 is slightly worse for you (more mistakes in 97% of resamples).
Model mistakes: 15 of 160 work prompts before (9%, Sep 24-28), 26 of 170 now (15%, Sep 30-Oct 4).
Agent behavior: Self-corrections 3.2× as often as before.
Your setup:     No CLAUDE.md or project mix change.
Claude Code:    2.1.285: default effort lowered to medium. Same period; not tested as the cause.
Confidence:     Medium. 330 work prompts over 10 days.
Report:         ~/.is-it-nerfed/report-2026-10-04.html
```

The HTML report adds a chart, the Claude Code releases, and the status incidents in that time.

## Method and sources

- **Your own logs, not a benchmark.** A study of 6,852 real Claude Code sessions found the March
  2026 regression before Anthropic confirmed it
  ([The Register](https://www.theregister.com/2026/04/06/anthropic_claude_code_dumber_lazier_amd_ai_director/)).
- **Claude Code updates and incidents go in the report.** Past regressions were harness and serving
  bugs, not new weights ([Anthropic, Sep 2025](https://www.anthropic.com/engineering/a-postmortem-of-three-recent-issues),
  [Anthropic, Apr 2026](https://www.anthropic.com/engineering/april-23-postmortem)). The report shows
  them as "in the same period", because it does not test them as the cause.
- **A blind Sonnet judge.** It does not see dates, versions or model names, and it labels both
  windows in the same run. Opus does not judge, because judges prefer their own model's work
  ([Panickssery et al.](https://arxiv.org/pdf/2404.13076)).
- **Hidden anchor items** with known labels catch a judge that drifts
  ([arXiv 2606.15474](https://arxiv.org/html/2606.15474)). The judge was scored with kappa, not
  percent agreement ([arXiv 2606.19544](https://arxiv.org/abs/2606.19544)). See
  [eval/README.md](eval/README.md) for the scores.
- **Whole sessions are resampled**, because prompts in one session are not independent
  ([Miller 2024](https://arxiv.org/html/2411.00640)).
- **"No change" needs proof.** The verdict says "no change" only when the interval of the rate
  ratio is inside ×0.67 to ×1.5, as in an equivalence test
  ([Lakens](https://lakens.github.io/statistical_inferences/09-equivalencetest.html),
  [Kruschke 2018](https://journals.sagepub.com/doi/10.1177/2515245918771304)).
- **The limit.** Two windows of two weeks cannot separate a model change from a bad stretch of hard
  tasks. So a firm "worse" also needs the model's own behavior to change, and every "possibly"
  verdict says so. The [bias audit](eval/README.md#bias-audit-2026-10-21) has the numbers.

The research notes behind these choices are in [docs/research/](docs/research/).

## Privacy

- It reads your session logs in `~/.claude*/projects/` and writes only to `~/.is-it-nerfed/`.
- Your prompts go only to the Sonnet subagents in your own Claude Code session.
- It makes two public GET requests that carry no data from you: the
  [Claude Code changelog](https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md)
  and the [Claude status incidents](https://status.claude.com/api/v2/incidents.json).

## Cost

About 1.4k Sonnet tokens per prompt, on your own Claude plan. Each run labels up to 600
prompts (about 0.9M tokens) and takes 3 to 5 minutes. A run does not reuse old labels: one
judge labels both windows, so a change of the judge cannot look like a change of the model.

## Tip: keep more history

Claude Code deletes session logs after 30 days. The baseline is the oldest part of the logs
that remain. For a better baseline, add this to `~/.claude/settings.json`:

```json
{ "cleanupPeriodDays": 365 }
```

## Uninstall

```
claude plugin uninstall is-it-nerfed@is-it-nerfed
claude plugin marketplace remove is-it-nerfed
rm -rf ~/.is-it-nerfed
```

## License

[MIT](LICENSE)
