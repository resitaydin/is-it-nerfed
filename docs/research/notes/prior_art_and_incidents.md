# Prior Art and Incidents: LLM "Nerfing" (Real and Perceived Degradation of Hosted Models)

Research date: 2026-10-03. Labels: **[VERIFIED]** = primary source (vendor postmortem, tracker methodology page, peer-reviewed or arXiv paper). **[SECONDARY]** = press or blog report of a primary event. **[ANECDOTAL]** = user reports, gists, Reddit or HN, single-org data.

## (a) Documented real degradation incidents and root causes

### Takeaway
Real, vendor-confirmed "nerfs" exist, and they almost never come from a silent weight swap. The confirmed root causes are (1) inference infrastructure bugs (routing, hardware misconfiguration, compiler precision), (2) product-layer changes in the harness (default reasoning effort, thinking-cache bugs, system-prompt edits), and (3) post-training updates that shift behavior (sycophancy, "laziness"). In both Anthropic postmortems, user complaints came weeks before the vendor's internal evals caught the problem.

### Cited Findings

**Anthropic, Aug to Sep 2025: three infrastructure bugs [VERIFIED]**
- From early August to mid-September 2025, three overlapping bugs degraded Claude output quality. All were resolved by 2025-09-18. — [Anthropic: A postmortem of three recent issues](https://www.anthropic.com/engineering/a-postmortem-of-three-recent-issues)
- Bug 1, the context-window routing error (2025-08-05 to 2025-09-18): servers set up for the 1M-token context window received short-context Sonnet 4 requests. The bug hit 0.8% of Sonnet 4 requests at first. A load-balancing change on 2025-08-29 raised this to 16% at the peak. About 30% of Claude Code users had at least one misrouted message. On Bedrock the peak was 0.18%, and on Vertex it was under 0.0004%. Routing was "sticky", so an affected user tended to stay affected. — [Anthropic postmortem](https://www.anthropic.com/engineering/a-postmortem-of-three-recent-issues)
- Bug 2, output corruption (2025-08-25 to 2025-09-02): a TPU server misconfiguration put wrong tokens into responses, for example Thai or Chinese characters in English replies and syntax errors in code. It hit Opus 4.1, Opus 4, and Sonnet 4 on TPUs only. — [Anthropic postmortem](https://www.anthropic.com/engineering/a-postmortem-of-three-recent-issues)
- Bug 3, an approximate top-k XLA:TPU compiler bug (2025-08-25 to 2025-09-12): a bf16 vs fp32 precision mismatch sometimes dropped the most probable token from the candidate set. It hit Haiku 3.5 and possibly Sonnet 4 and Opus 3. — [Anthropic postmortem](https://www.anthropic.com/engineering/a-postmortem-of-three-recent-issues)
- Anthropic said that its evals "simply didn't capture the degradation users were reporting". Privacy controls limited engineer access to user conversations, so engineers could not easily reproduce the problems. Different platforms showed different symptoms, so reports conflicted. Anthropic also said it "relied too heavily on noisy evaluations". — [Anthropic postmortem](https://www.anthropic.com/engineering/a-postmortem-of-three-recent-issues)
- Commitments: more sensitive evals, continuous quality evals on production systems, faster privacy-safe debugging of community feedback, and a request that users report through `/bug` or the feedback button. — [Anthropic postmortem](https://www.anthropic.com/engineering/a-postmortem-of-three-recent-issues)
- The same postmortem says Anthropic never reduces model quality because of demand, time of day, or server load. (I am fairly sure this sentence is in the post, but I did not re-quote it in this session. Check the exact wording before you use it.) — [Anthropic postmortem](https://www.anthropic.com/engineering/a-postmortem-of-three-recent-issues)

**Anthropic, Mar to Apr 2026: three Claude Code harness and product changes ("April 23 postmortem") [VERIFIED]**
- 2026-03-04: Anthropic changed the Claude Code default reasoning effort from high to medium to reduce UI latency, because the UI looked frozen during long thinking. Anthropic reverted it on 2026-04-07. — [Anthropic: April 23 postmortem](https://www.anthropic.com/engineering/april-23-postmortem)
- 2026-03-26: a caching optimization had a bug that cleared prior reasoning on every turn, not once. The model became forgetful and repetitive. Each cleared turn was also a cache miss that users paid for. The bug happened only in a corner case (stale sessions). A separate change in how the CLI shows thinking hid the bug in most CLI sessions. Anthropic fixed it on 2026-04-10. — [Anthropic April 23 postmortem](https://www.anthropic.com/engineering/april-23-postmortem); [InfoQ, 2026-05](https://www.infoq.com/news/2026/05/anthropic-claude-code-postmortem/)
- 2026-04-16: a system-prompt verbosity limit ("25 words between tool calls, 100 words for final responses") caused a 3% drop on one eval in later ablations. Anthropic reverted it on 2026-04-20 in v2.1.116. — [InfoQ](https://www.infoq.com/news/2026/05/anthropic-claude-code-postmortem/); [Anthropic April 23 postmortem](https://www.anthropic.com/engineering/april-23-postmortem)
- Affected models: Sonnet 4.6, Opus 4.6, and Opus 4.7, across different issues. Affected surfaces: Claude Code and Claude Cowork. Anthropic said: "The API was not impacted" and "we were able to immediately confirm that our API and inference layer were unaffected". Usage limits were reset for subscribers on 2026-04-23. — [Anthropic April 23 postmortem](https://www.anthropic.com/engineering/april-23-postmortem)
- Why detection was hard: "Each change affected a different slice of traffic on a different schedule", and "two unrelated experiments made it challenging for us to reproduce the issue at first". — [Anthropic April 23 postmortem](https://www.anthropic.com/engineering/april-23-postmortem)
- Anthropic's internal Code Review tool found the caching bug when it ran on Opus 4.7 with enough context. Opus 4.6 did not find it. — [InfoQ](https://www.infoq.com/news/2026/05/anthropic-claude-code-postmortem/)
- Commitments: more staff on exact public builds, per-model eval suites for every system-prompt change, per-line ablations, prompt review and audit tooling, gating of model-specific changes to the target models, and soak periods with gradual rollouts. — [Anthropic April 23 postmortem](https://www.anthropic.com/engineering/april-23-postmortem)
- Earlier product changes (reported, not in the postmortem's list of three): adaptive thinking became the default on 2026-02-09, and thinking-content redaction shipped in v2.1.69 in early March. — [lilting.ch analysis](https://lilting.ch/en/articles/claude-code-quality-regression-thinking-redaction); [The Register, 2026-04-06](https://www.theregister.com/2026/04/06/anthropic_claude_code_dumber_lazier_amd_ai_director/) [SECONDARY]
- After the announced reverts, Reddit and HN users still reported sub-agent delegation to Haiku that users could not see, and leftover verbosity instructions. — [InfoQ](https://www.infoq.com/news/2026/05/anthropic-claude-code-postmortem/) [ANECDOTAL]

**Claude Code / Opus 4.7, May 2026: tracker-detected drop with no vendor postmortem found [ANECDOTAL / tracker-derived]**
- A gist by "yurukusa" (2026-05-27) cites Marginlab data for Opus 4.7. The baseline pass rate was 65%, the 7-day rate was 57%, and a single day reached 52%, against a ±4.3% significance threshold. The author dates the degradation from 2026-05-22. The gist cites no Anthropic response. — [yurukusa gist](https://gist.github.com/yurukusa/77bf08523bda41132087a03de4523d7a)
- Press reported Marginlab drops for Claude Code Opus 4.5 in late January 2026. — [WinBuzzer, 2026-01-29](https://winbuzzer.com/2026/01/29/claude-code-performance-drops-independent-tracker-xcxwbn/); [GIGAZINE, 2026-01-30](https://gigazine.net/gsc_news/en/20260130-claude-code-opus-performance/) [SECONDARY]

**OpenAI [VERIFIED / SECONDARY]**
- GPT-4o sycophancy: on 2025-04-25, OpenAI rolled out a GPT-4o update in ChatGPT that made the model too sycophantic. The rollback started on 2025-04-28. The postmortem says the update put too much weight on "short-term feedback". Some expert testers said that the model "felt" slightly off. OpenAI also said: "We also didn't have specific deployment evaluations tracking sycophancy." — [OpenAI: Expanding on what we missed with sycophancy](https://openai.com/index/expanding-on-sycophancy/); [Simon Willison summary](https://simonwillison.net/2025/May/2/what-we-missed-with-sycophancy/)
- "Lazy GPT-4" (Dec 2023): OpenAI said: "we haven't updated the model since Nov 11th, and this certainly isn't intentional. Model behavior can be unpredictable". It also said "only a subset of prompts may be degraded, and it may take a long time for customers and employees to notice". The fix was a new snapshot, gpt-4-0125-preview (Jan 2024), which reduced "laziness". — [Search Engine Roundtable](https://www.seroundtable.com/openai-chatgpt-gpt-4-getting-lazier-36529.html); [InfoQ 2024-02](https://www.infoq.com/news/2024/02/openai-model-updates/) [SECONDARY]

**Google [SECONDARY / ANECDOTAL]**
- Gemini 2.5 Pro 05-06 (May 2025): power users reported a regression from 03-25 that included less precision and weaker instruction-following. Logan Kilpatrick of Google said that the 06-05 model "closes [the] gap on 03-25 regressions". This is a partial acknowledgment that a version-to-version regression occurred. — [CTOL Digital](https://www.ctol.digital/news/gemini-2-5-05-06-pro-slow-performance-instruction-issues/); [Google AI Developers Forum thread](https://discuss.ai.google.dev/t/gemini-2-5-pros-response-quality-regression/91240)
- I found no formal Google postmortem on Gemini quality degradation.

### Inferences
- A taxonomy of confirmed root causes: (1) inference infra, which covers routing, hardware config, and compiler numerics (Anthropic 2025); (2) harness and product defaults, which cover effort level, thinking cache, system prompt, and thinking display (Anthropic 2026); (3) a post-training update to an "alias" model (OpenAI 2025 sycophancy, Gemini 05-06); (4) unexplained snapshot behavior (GPT-4 lazy). I found no confirmed case of covert quantization or load-based downgrades. Users claim these often, but no vendor has confirmed one.
- The 2026 incident shows that "the API was fine" and "the product got worse" can both be true. A tracker that hits only the raw API would miss harness regressions. A tracker that runs through the real CLI (Marginlab) or reads real session logs (Laurenzo) would catch them.
- Effects are partial and sticky. One vendor statement says "a subset of prompts". Another says "different slice of traffic on a different schedule", and the routing was sticky. Some users see a large effect and others see none. This explains the conflicting reports, and it favors per-user measurement over aggregate measurement.

### Gaps
- I did not find the exact Anthropic quote that rules out demand-based degradation in this session. Re-check the Sept 2025 postmortem.
- I found no official Anthropic statement on the May 2026 Opus 4.7 Marginlab signal.
- I found no OpenAI postmortem for Codex-specific quality complaints in 2025-2026. I did not search this in depth.

## (b) Public trackers: what they measure, how, sample sizes, weaknesses

### Takeaway
Current trackers fall into three families: fixed-benchmark daily runs (Marginlab, AIStupidLevel, IsItNerfed's automated part), community votes (the IsItNerfed "Vibe Check"), and general leaderboards that are not built for drift (LiveBench, Artificial Analysis, OpenRouter). The best ones use real statistical tests. All of them measure a fixed synthetic task set, not the user's own work, and their daily samples are small (n≈50 or less).

### Cited Findings

**Marginlab Claude Code Performance Tracker** — [marginlab.ai/trackers/claude-code](https://marginlab.ai/trackers/claude-code/) [VERIFIED methodology page, read 2026-10-03]
- The tracker runs the Claude Code CLI every day, with no custom harness, on a curated subset of SWE-Bench-Pro that resists contamination. It uses the latest Claude Code release and the SOTA model, now Opus 5.5 at high effort. So it captures model regressions and harness regressions together.
- N=50 instances per day. Each test is a Bernoulli trial with 95% CIs. The significance thresholds are ±12.8% daily, ±4.7% weekly, and ±2.3% monthly.
- On 2026-10-03, today's pass rate was 77% (n=50), the 7-day rate was 76% (n=350), and the 30-day rate was 81% (n=1,200). A new Opus 5.5/high baseline started on 2026-09-24. Degradation detection is paused until the baseline is complete, so a model switch resets detection.
- Marginlab says it is independent of model vendors. The project started after the Anthropic Sept 2025 postmortem. — [WinBuzzer](https://winbuzzer.com/2026/01/29/claude-code-performance-drops-independent-tracker-xcxwbn/)
- Weakness (inference): one model and one harness. A daily n=50 cannot detect a drop under about 13 points. Task mix is SWE-Bench-Pro (Python-heavy, issue-fix), not the user's workload. There is a cost per run, which limits scale. Copycat projects exist, for example [zscole/ai-poc model-tracker](https://github.com/zscole/ai-poc-20260131-model-tracker) and [mesmer.tools Claude performance](https://mesmer.tools/random/claude-performance).

**IsItNerfed.org** — [About page](https://isitnerfed.org/about); [Home](https://isitnerfed.org/)
- Two parts. (1) A "Vibe Check" where users vote "Smarter / Same / Nerfed" for coding agents and LLMs over time. (2) Automated tests: a private set of easy, medium, and hard coding challenges (algorithms, data structures, DP, graphs, math) checked by unit tests. The set stays private to avoid contamination. The tests also include the Aider Polyglot benchmark, run as 34 Python-only Exercism exercises in isolated containers.
- Weakness: the About page gives no sample sizes, no statistical tests, no vote aggregation method, and no run frequency. Votes are self-selected and open to social contagion: a viral "it's nerfed" thread drives votes. 34 exercises is a small set.
- Third-party coverage says that its monitoring showed Claude Code volatility. — [AI Report Digest](https://aireportdigest.com/isitnerfed-real-time-monitoring-finds-claude-code-volatility/) [SECONDARY]

**AIStupidLevel.info** — [Methodology](https://aistupidlevel.info/methodology); [Home](https://aistupidlevel.info/); [HF org](https://huggingface.co/AIStupidLevel)
- The site re-runs a fixed fleet of models several times a day on the same tasks through vendor APIs. It has a 9-axis coding suite scored by running the code (7 Python tasks × 7 trials, every 4 hours), a 13-axis reasoning suite that includes long-context retention, and a 7-axis tool-calling suite. It also tracks hallucination and calibration through unanswerable questions (fabrication rate, abstention, ECE).
- Drift detection uses Page-Hinkley change-point detection on each suite's daily series. A suite needs 10 days on its current config before it can fire. Scores include confidence intervals. The code is open source and claims zero vendor funding.
- Weakness (inference): 7 coding tasks is a very small, toy-scale set. It measures the raw API, so it would miss harness regressions like the March-April 2026 Claude Code incident, where the API was unaffected.

**Session-log analysis (closest prior art to "measure from your own sessions")** [ANECDOTAL single-org, but quantitative]
- On 2026-04-02, Stella Laurenzo (Senior Director of AI at AMD, formerly lead of OpenXLA) filed anthropics/claude-code#42796, "Claude Code is unusable for complex engineering tasks with the Feb updates". — [The Register, 2026-04-06](https://www.theregister.com/2026/04/06/anthropic_claude_code_dumber_lazier_amd_ai_director/); [TechRadar](https://www.techradar.com/pro/claude-cannot-be-trusted-to-perform-complex-engineering-tasks-amd-ai-head-slams-anthropics-coding-tool-after-months-of-frustration)
- Data: 6,852 Claude Code session JSONL files, 17,871 thinking blocks, and 234,760 tool calls from one "very consistent, high complexity work environment". — [The Register](https://www.theregister.com/2026/04/06/anthropic_claude_code_dumber_lazier_amd_ai_director/); [InfoQ](https://www.infoq.com/news/2026/05/anthropic-claude-code-postmortem/)
- Metrics: median thinking length fell from about 2,200 chars (Jan) to about 600 chars (Mar), which is -73%. Files read before an edit fell from 6.6 to 2.0. Stop-hook violations ("laziness") went from 0 before 2026-03-08 to about 10 per day. Full-file rewrites rose relative to targeted edits. — [lilting.ch](https://lilting.ch/en/articles/claude-code-quality-regression-thinking-redaction); [The Register](https://www.theregister.com/2026/04/06/anthropic_claude_code_dumber_lazier_amd_ai_director/)
- Commentators credit this analysis as a trigger for the 2026-04-23 Anthropic postmortem. — [DEV: "AMD Caught It in 6,852 Sessions Before Anthropic Did"](https://dev.to/rentierdigital/claude-code-was-broken-for-6-weeks-amd-caught-it-in-6852-sessions-before-anthropic-did-7i5) [SECONDARY / opinion]
- Caveat: the data comes from one org and was not peer reviewed. Thinking-length metrics are confounded, because redaction and display changes alter what the logs contain. — [The Register](https://www.theregister.com/2026/04/06/anthropic_claude_code_dumber_lazier_amd_ai_director/); (confound inference from [Anthropic April 23 postmortem](https://www.anthropic.com/engineering/april-23-postmortem), which says a thinking-display change hid the cache bug)
- An open-source tool, `lucemia/claude-session-analyzer`, repeats the #42796 method on local Claude Code logs: thinking depth, Read:Edit ratio, behavioral signals, sentiment, and cost. — [GitHub](https://github.com/lucemia/claude-session-analyzer)

**General leaderboards (not built for drift)** [from prior knowledge, NOT re-verified in this session]
- LiveBench refreshes its questions often to limit contamination and scores model snapshots. It does not re-measure a hosted endpoint daily for drift. It was cited for Gemini 2.5 Pro coding scores (72.87) in the 05-06 debate. — [CTOL Digital](https://www.ctol.digital/news/gemini-2-5-05-06-pro-slow-performance-instruction-issues/)
- Artificial Analysis publishes intelligence indexes and continuous speed and latency tracking per provider. Its quality numbers are point-in-time evals, not daily quality drift. OpenRouter publishes usage rankings and provider uptime and latency, with no quality measurement. (Unverified in this session. Treat as a gap.)

### Inferences
- No current tracker measures a user's own task distribution. All fixed-benchmark trackers face a trade-off: a small daily n (cheap but noisy) or a large n (expensive). Marginlab's ±12.8% daily threshold means it cannot see a "subset of prompts" drop of the type OpenAI described.
- API-level trackers (AIStupidLevel) and harness-level trackers (Marginlab) detect different failure classes. The 2026 Claude Code incident could only appear at harness level.
- The Laurenzo analysis is the clearest evidence that passive session logs contain detectable behavioral signals: read:edit ratio, thinking length, rewrite rate, and hook violations. These signals moved weeks before any vendor admitted a problem.

### Gaps
- Published criticism of Marginlab or AIStupidLevel methods: I found none beyond inferred weaknesses. HN threads were not fetched.
- The exact sample sizes and vote counts for IsItNerfed are not on its About page.
- A full verification of LiveBench, Artificial Analysis, and OpenRouter methods was not done in this session.

## (c) Perception side: why users think models got dumber when they did not

### Takeaway
The best-known "it got worse" paper (Chen, Zaharia, Zou 2023) shows behavior drift more than capability loss, and its headline result was largely an artifact (Narayanan and Kapoor). I found no rigorous empirical study that measures honeymoon, novelty, or confirmation-bias effects on LLM quality perception. That evidence is mostly vendor statements and opinion. Vendor postmortems show that real problems often affect only a subset, which makes perception and reality hard to separate.

### Cited Findings
- Chen, Zaharia, Zou (2023): GPT-4 (March 2023) got 84% on prime vs composite identification, and GPT-4 (June 2023) got 51%. GPT-4 also became less willing to answer sensitive and opinion questions. — [arXiv 2307.09009 / Semantic Scholar](https://www.semanticscholar.org/paper/How-is-ChatGPT's-behavior-changing-over-time-Chen-Zaharia/e51d38bbabca719cd9c845d1e004c724e9cbdfa4); [HDSR journal version, 2024](https://assets.pubpub.org/rpn900pr/Chen%20et%20al.%20(2024)_Just%20Accepted-11710285512753.pdf)
- Narayanan and Kapoor (July 2023): "the new paper doesn't show that GPT-4 capabilities have degraded." The test set had only primes. With composites added, the "collapse" mostly disappears, so it was a change in default answer preference ("yes" vs "no"), not lost reasoning. They add that fine-tuning "can have unintended effects, including drastic behavior changes on some tasks", and they stress "how hard it is to quantitatively evaluate language models." — [AI Snake Oil / normaltech.ai: Is GPT-4 getting worse over time?](https://www.normaltech.ai/p/is-gpt-4-getting-worse-over-time)
- Earlier longitudinal work: ChatLog (2023) tracked ChatGPT outputs over time. — [arXiv 2304.14106](https://arxiv.org/pdf/2304.14106)
- OpenAI on GPT-4 "laziness" (Dec 2023): no model update since 2023-11-11, but "only a subset of prompts may be degraded, and it may take a long time for customers and employees to notice". So both a real effect on a subset and a perception effect are possible with no weight change. — [Search Engine Roundtable](https://www.seroundtable.com/openai-chatgpt-gpt-4-getting-lazier-36529.html)
- OpenAI sycophancy postmortem: optimizing for short-term thumbs-up feedback produced a worse model. User-rating signals can push quality in the wrong direction, and that is a caution for vote-based trackers. — [OpenAI](https://openai.com/index/expanding-on-sycophancy/)
- The novelty effect, defined: performance or satisfaction rises when a new technology arrives because of interest, not real improvement. — [Wikipedia: Novelty effect](https://en.wikipedia.org/wiki/Novelty_effect)
- Opinion on the end of an "LLM honeymoon phase" (2024). — [Baldur Bjarnason](https://www.baldurbjarnason.com/2024/the-llm-honeymoon-phase/) [OPINION]
- One vendor-blog explanation: users with high expectations from earlier good results feel let down, and "model fatigue" makes familiar output seem worse. — [enterprise-ai.io](https://enterprise-ai.io/knowledge/why_do_many_users_feel_that_chatgpt_has_declined_in_quality_recently.php) [LOW QUALITY / no data]
- A claim seen in search results: "91% of production LLMs experience measurable behavioral drift within 90 days, with an average 14–18 day lag between degradation onset and first user complaint." **I could not trace this to a primary source. Do not use it.**
- Anthropic (2025) said that contradictory reports across platforms made diagnosis hard. Real degradation on one platform and none on another produces "it's nerfed" / "works fine for me" splits that look like bias. — [Anthropic postmortem](https://www.anthropic.com/engineering/a-postmortem-of-three-recent-issues)

### Inferences
- The likely perception mechanisms are listed below. None is backed by a dedicated LLM-specific study that I found. Treat them as hypotheses to test:
  - Novelty or honeymoon effect. Users remember early successes on easy demos.
  - Rising task difficulty. Users trust the model with larger tasks over time, so the failure rate goes up even with a fixed model.
  - Context bloat. Projects grow, so CLAUDE.md files, MCP tools, and conversation length grow, and the effective quality per turn drops.
  - Regression to the mean. A user first notices a model after a lucky streak.
  - Confirmation bias and social contagion. Viral threads prime users to see failures. Vote trackers amplify this.
  - Stochastic sampling. One bad sample is remembered more strongly than many good ones.
- Real incidents and perception effects overlap in time. Sept 2025 and March-April 2026 were both "people said it was in your head, and it was real" events. A credible tool must separate (i) the model and harness changing from (ii) the user's workload changing. This requires controlling for task difficulty and context size in the user's own history.

### Gaps
- I found no peer-reviewed study that measures the honeymoon or novelty effect, or confirmation bias, specifically in perceived LLM quality over time.
- I found no study that measures how user task difficulty or context size grows over weeks of agent use.
- I found no quantitative analysis that relates social-media "nerf" volume to tracker scores. This could be a novel analysis.

## (d) The gap: does any tool measure degradation from the user's OWN real session histories?

### Takeaway
Partly. The Laurenzo / AMD analysis (2026-04) and the `lucemia/claude-session-analyzer` repo show the method on local Claude Code JSONL logs. They are one-off forensic analyses or DIY scripts, not a product. I found no tool that continuously compares a user's sessions over time, with controls for task difficulty and context, and gives a statistical verdict.

### Cited Findings
- Laurenzo's analysis used the AMD team's own session JSONL logs and behavioral proxies (thinking length, reads before edit, rewrite rate, stop-hook violations). Commentators say it found the problem before the vendor admitted it. — [The Register](https://www.theregister.com/2026/04/06/anthropic_claude_code_dumber_lazier_amd_ai_director/); [DEV](https://dev.to/rentierdigital/claude-code-was-broken-for-6-weeks-amd-caught-it-in-6852-sessions-before-anthropic-did-7i5)
- `lucemia/claude-session-analyzer` repeats the #42796 method on local logs. — [GitHub](https://github.com/lucemia/claude-session-analyzer)
- Fixed-benchmark trackers (Marginlab, AIStupidLevel, IsItNerfed) do not use user sessions. — [Marginlab](https://marginlab.ai/trackers/claude-code/); [AIStupidLevel methodology](https://aistupidlevel.info/methodology); [IsItNerfed about](https://isitnerfed.org/about)
- Anthropic cited privacy limits on engineer access to user conversations as a reason that it was slow to diagnose. A local, user-side analyzer avoids this problem. — [Anthropic 2025 postmortem](https://www.anthropic.com/engineering/a-postmortem-of-three-recent-issues)

### Inferences
- Open space for a product: continuous, local or opt-in analysis of the user's own agent sessions. It would (1) extract behavioral proxies (read:edit ratio, thinking tokens, tool-error rate, retries, user corrections and interrupts, hook violations, rewrite vs edit), (2) control for confounders (task size, repo size, context length, model, effort, CLI version), (3) run change-point tests (Page-Hinkley as in AIStupidLevel, or a binomial CI as in Marginlab), and (4) line up detected shifts with known version or default changes (CLI release notes, effort defaults). Pooled opt-in data from many users could separate "my workload changed" from "the product changed".
- Confounder warning from the 2026 postmortem: changes to the thinking display and redaction change what the logs record. Log-based metrics must detect format and version changes, or they will report false nerfs.

### Gaps
- I did not find whether `lucemia/claude-session-analyzer` has a statistical test, multi-user aggregation, or confounder controls. Its README was not fetched.
- I did not search for equivalent session-analysis tools for Codex CLI or Gemini CLI logs.
