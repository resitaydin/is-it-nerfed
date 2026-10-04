# Session quality metrics for human–AI coding-agent transcripts (no ground-truth labels)

Research date: 2026-10-03. Source dates are marked. Scope: metrics that can be computed from a transcript (user prompts, agent messages, tool calls/results, timestamps, tokens), split into cheap deterministic heuristics and LLM-judged signals.

## How do researchers and companies measure implicit user feedback in conversational AI?

### Takeaway
The dominant 2024–2026 approach is an LLM classifier applied per user turn, with a small taxonomy (positive / rephrase / make-aware / correction / ask-clarification), validated against ~100 human gold labels. Dissatisfaction signals are much more frequent and informative than satisfaction signals, but they are noisy and depend strongly on prompt quality and user type.

### Cited Findings
- SPUR (Microsoft, ACL 2024): supervised, iterative prompting. An LLM (1) extracts satisfaction/dissatisfaction signals from user utterances in a labeled set, (2) summarizes them into rubrics, (3) applies the rubrics to unseen conversations. Evaluated on Bing Copilot, MultiWOZ, SGD, ReDial; beats embedding baselines, especially with little training data; rubrics can be distilled into a cheaper model for scale. — [ACL Anthology 2024.acl-long.598](https://aclanthology.org/2024.acl-long.598/); [Microsoft Research](https://www.microsoft.com/en-us/research/publication/interpretable-user-satisfaction-estimation-for-conversational-systems-with-large-language-models/)
- RUBICON (Microsoft, 2024): rubric-based evaluation of domain-specific human–AI conversations, a sibling of SPUR. — [RUBICON PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2024/05/RUBICON__Rubric_Based_Evaluation_of_Domain_Specific_Human_AI_Conversations-10.pdf)
- WildFeedback (Microsoft, arXiv Aug 2024): applies user-satisfaction-estimation rubrics turn-by-turn to 148,715 multi-turn WildChat conversations to label SAT/DSAT. DSAT is far more common than SAT (about 12% vs 5% of conversations). — [arXiv 2408.15549](https://arxiv.org/html/2408.15549v1); stats restated in [DRIFT, arXiv 2510.02341](https://arxiv.org/html/2510.02341v1)
- "User Feedback in Human-LLM Dialogues" (EMNLP 2025, arXiv Jul 2025): taxonomy of implicit feedback in WildChat and LMSYS: Positive, Rephrasing, Make Aware without Correction, Make Aware with Correction, Ask for Clarification. Feedback is more than half of user utterances at later turns of long conversations. Human agreement: Cohen's κ 0.70 (binary), 0.74 (3-way), 0.60 (fine-grained). Prompts that get positive feedback are slightly more toxic than random (users praise compliance with bad requests). Lower-quality initial prompts correlate with more feedback of both polarities. Title conclusion: feedback is "a lens to understand users but noisy as a learning signal". — [arXiv 2507.23158](https://arxiv.org/html/2507.23158v1); [EMNLP PDF](https://aclanthology.org/2025.emnlp-main.133.pdf)
- SWE-chat (Stanford et al., COLM 2026; arXiv Apr 2026, rev. Oct 2026): ~18,000 real coding-agent sessions, 229k user prompts, 2M tool calls. Pushback taxonomy per user prompt: correction, rejection, failure report, non-pushback; plus "hard interruption" detected from the literal string `[Request interrupted by user]`. Users push back after ~46% of prompts and hard-interrupt ~4.5% of turns; agents stop to ask (AskUserQuestion) in ~1.5–6.8% of turns depending on slice. — [arXiv 2604.20779](https://arxiv.org/abs/2604.20779) (PDF read directly)
- SWE-chat pushback labels are reliable: human–human κ = 0.832 (4-class) and 0.888 (binary pushback), 94.4% binary agreement on 90 items. The pushback classifier needs the full transcript up to the prompt as context, which makes it the most expensive annotation; authors used qwen-3.5-9b for cost over a slightly better gpt-5.4. — [arXiv 2604.20779](https://arxiv.org/pdf/2604.20779)
- Anthropic Clio (privacy-preserving pipeline) is the basis for Anthropic's classifications of Claude.ai and Claude Code conversations; the Economic Index uses it to label "collaboration modes". — [Anthropic, Apr 2025](https://www.anthropic.com/research/impact-software-development)
- "How Coding Agents Fail Their Users" (arXiv May 2026, rev. Aug 2026): 20,574 coding-agent sessions from 1,639 repos (IDE + CLI). Operationalizes misalignment as "a breakdown made visible through developer pushback", annotated on form, cause, cost, resolution. Seven forms span: reading the project, interpreting intent, following rules, bounding actions, implementing code, reporting progress. 90.50% of episodes cost effort/trust, not system damage; 91.49% of visible resolutions needed explicit user correction; issues persist across adjacent sessions; "constraint violations and inaccurate self-reporting grow in share" over time. — [arXiv 2605.29442](https://arxiv.org/abs/2605.29442)
- OpenAI GPT-4o sycophancy postmortem (May 2025): an additional reward signal from user thumbs-up/down feedback was reported as one factor that weakened the primary reward and pushed the model toward sycophancy. — [OpenAI "Expanding on sycophancy"](https://openai.com/index/expanding-on-sycophancy/) (note: fetch returned HTTP 403; this summary is from prior knowledge of the post and should be verified)

### Inferences
- For transcripts, a per-user-turn classifier with the SWE-chat labels (correction / rejection / failure report / none) plus a deterministic interrupt flag is the best-validated starting point for coding agents.
- Explicit praise ("thanks", "perfect") is a weak positive: rare, and biased (EMNLP 2025 toxicity finding; OpenAI thumbs-up finding). Absence of DSAT is a better positive than presence of SAT.
- SPUR's method (learn rubrics from a small labeled set, then distill) fits a low-cost pipeline: a frontier LLM writes rubrics once, a small model applies them at scale.

### Gaps
- No public study found that reports precision/recall of simple regex frustration lexicons ("no", "wrong", "that's not what I asked", profanity, ALL CAPS) against LLM labels for coding sessions.
- Dialogue breakdown detection (DBDC challenge series) and regeneration/abandonment signals in ChatGPT-style products were not covered with primary sources in this pass.

## Coding-agent-specific signals and what eval frameworks use

### Takeaway
Real-world studies use four families: (1) friction (interrupts, pushback, agent clarification stops), (2) outcome (LLM-judged session success 0–100, code survival into commits), (3) efficiency (tokens, cost, time, user characters per committed line; trajectory length), and (4) process anti-patterns (search loops, verification skips, long/high-variance trajectories). Benchmarks (SWE-bench) use hidden tests for resolve rate, which a transcript does not have.

### Cited Findings
Catalogue (D = deterministic, L = LLM-judged, G = needs git/repo state):

| Metric | Type | Definition / extraction | Evidence | Pitfalls |
|---|---|---|---|---|
| Hard interrupt rate | D | Count of user turns with `[Request interrupted by user]` / per turn. | SWE-chat: 4.5% of turns; most common cause of lowest-success sessions is an interrupt that ends the session early. Interrupts cluster at ExitPlanMode (14.7% of last tool calls before interrupt) — users stop at plan→execute. [SWE-chat](https://arxiv.org/pdf/2604.20779) | Anthropic: experienced users interrupt *more* (9% vs 5% for new users) because they auto-approve and monitor; so interrupt rate rises with trust, not only with failure. [Anthropic, Feb 2026](https://www.anthropic.com/research/measuring-agent-autonomy) |
| Soft pushback rate (correction / rejection / failure report) | L | Classify each user prompt given prior transcript. | ~46% of prompts; κ 0.83–0.89 human agreement. [SWE-chat](https://arxiv.org/pdf/2604.20779) | "Expert nitpicker" persona is the most common (39% nitpicky); pushback reflects user style as much as model error. |
| Agent clarification stops | D | Count of AskUserQuestion (or equivalent) tool calls / turn. | Anthropic: on complex tasks Claude Code stops to ask >2x as often as on minimal tasks, more often than humans interrupt. [Anthropic](https://www.anthropic.com/research/measuring-agent-autonomy). SWE-chat: agents "rarely stop". | Ambiguous direction: a good agent asks on vague prompts; too many asks is friction. |
| Human interventions per session | D/L | Interrupts + corrections per session. | Anthropic internal: interventions dropped 5.4 → 3.3 per session while success on complex tasks doubled (Aug–Dec 2025). [Anthropic](https://www.anthropic.com/research/measuring-agent-autonomy) | Classifications by Claude without manual validation (stated limitation). |
| Turn duration (autonomy) | D | Wall time per agent turn from timestamps. | Median ~45 s stable; p99.9 rose from <25 min to >45 min (Oct 2025–Jan 2026). [Anthropic](https://www.anthropic.com/research/measuring-agent-autonomy) | Measures autonomy granted, not quality; long turns can be loops. |
| Session success (0–100) | L | LLM rates full conversation + tool-call summary. | SWE-chat mean 73.2; LLM vs human gold ICC(2,1) = 0.605, Spearman 0.60 (claude-sonnet-4-6); but human–human ICC only 0.503 (ρ 0.757). [SWE-chat](https://arxiv.org/pdf/2604.20779) | Low ceiling: humans themselves disagree. Abandoned sessions are often missing; if 10/20/30% were abandoned and scored 0, mean falls to 65.9/58.6/51.2. |
| Code survival rate / coding efficiency | D+G | Replay every write/edit tool call with line provenance (difflib); survival = agent lines surviving / agent lines in final state; efficiency = agent lines surviving / cumulative agent lines produced. | 59.4% survival overall; 65.0% in vibe coding vs 55.9% collaborative. Audit: 92/100 deleted agent lines did not reappear in any form. [SWE-chat](https://arxiv.org/pdf/2604.20779) | Needs the commit; higher survival in vibe coding may mean less scrutiny, not better code (authors' caveat). |
| Tokens / cost / time / user chars per committed line | D+G | Total tokens (in+out+cache) ×100 / committed lines; same for $, runtime, prompt characters ("cognitive efficiency"). | Vibe coding median 2.7M tokens per 100 committed lines, ~3x collaborative; $2.71 vs $0.92 per 100 lines. [SWE-chat](https://arxiv.org/pdf/2604.20779) | Line count is a poor unit of value; confounded by task type. |
| Trajectory length & variance | D | Tool calls / steps per task. | Failed SWE-bench trajectories are consistently longer and higher-variance than successful ones (OpenHands, SWE-agent, Prometheus). File localization is correct in 72–81% even of failures. [arXiv 2511.00197, Oct 2025](https://arxiv.org/abs/2511.00197) | Benchmark setting; in the wild, long sessions can be big tasks. Normalize by task type. |
| Search loops / verification skips | D (on normalized action taxonomy) | Map tool calls to a 9-type action taxonomy; detect repeated search without progress; edit-then-finish with no test run. | "Search loops" were the most stable corpus-level anti-pattern over 2,500 SWE-bench Verified trajectories; resolve rate hides efficiency differences (time to relevant code, failed work). [TraceProbe, arXiv 2607.06184, Jul 2026](https://arxiv.org/abs/2607.06184) | Thresholds need tuning per agent harness. |
| Collaboration mode (directive vs feedback loop vs augmentation) | L | Clio classification of conversation. | Claude Code: 79% automation (43.8% directive, 35.8% feedback loop) vs Claude.ai 49%. [Anthropic, Apr 2025](https://www.anthropic.com/research/impact-software-development). Directive share on Claude.ai rose 27%→39% (Sep 2025), read as possibly better first-attempt quality. [Anthropic, Sep 2025](https://www.anthropic.com/research/anthropic-economic-index-september-2025-report) | Mode mix shifts with product, user population, and features; not a quality metric by itself. |
| Misalignment episode type | L | Annotate pushback episodes by form (intent, rule-following, scope, implementation, reporting). | Inaccurate self-reporting and constraint violations rising in share. [arXiv 2605.29442](https://arxiv.org/abs/2605.29442) | Annotation cost; method details (agreement) not visible in abstract. |
| Developer time / speed | external | Wall-clock task time with vs without AI (RCT). | METR RCT (Jul 2025): 16 experienced devs, 246 tasks in own repos; AI-allowed tasks took ~19% longer, while devs believed they were ~20% faster. [METR](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/). METR now labels the result historical. [secondary](https://letsdatascience.com/blog/developers-thought-ai-made-them-faster-the-data-said-otherwise) | Self-reported satisfaction/speed is unreliable — a direct warning against using "thanks" or user sentiment as the quality metric. |

- SWE-chat failure modes in lowest-rated sessions: interrupt before output; work/commit unrelated to the request; 42 tool calls searching and never finding the code; usage-limit message with no work; delegated to sub-agent and nothing implemented; diagnosed but refused to fix. — [SWE-chat](https://arxiv.org/pdf/2604.20779)
- SWE-chat pushback/interrupt/ask rates were "relatively stable" over Feb–Sep 2026 (Figure 31), even as turn durations grew. — [SWE-chat](https://arxiv.org/pdf/2604.20779)

### Inferences
- For a "nerf" detector, the most useful deterministic time series are: interrupt rate, tool-error rate, retry-same-call rate, trajectory length per task, tokens per task, and agent-ask rate — each stratified by task intent and user cohort. The most useful LLM signals are per-prompt pushback type and session success.
- Because friction rates were stable in SWE-chat across model releases, a single-metric change is weak evidence; look for coordinated shifts (pushback up AND tokens per task up AND success down) within the same users.
- Task-completion markers that are deterministic: a git commit/PR tool call, tests passing in a bash result after the last edit, user ending with no further request. These are proxies; SWE-chat notes abandonment is invisible when logs are not committed.

### Gaps
- Terminal-Bench and SWE-bench metric definitions were not fetched in this pass; both are known to use hidden-test pass rate, which transcripts lack.
- No primary source found that measures "hallucinated file/API" rate in the wild; it can be approximated deterministically (Read/Edit on a path that returns "file not found"; import errors after edit) but no validation study was found.
- No source quantified "edit reverted within session" separately from code survival.

## How to segment a session into tasks/episodes and define task success

### Takeaway
No coding-agent-specific segmentation standard was found. SWE-chat scores whole sessions and individual prompts; it does not split sessions into tasks. Generic dialogue topic segmentation (topic-shift detection) with LLMs is an active field and is the practical tool.

### Cited Findings
- SWE-chat annotates at two levels: session (success 0–100, persona) and user prompt (intent: create, refactor, debug, understand, connect, git, test, other; pushback). — [SWE-chat](https://arxiv.org/pdf/2604.20779)
- SWE-chat links sessions to commits via a shadow branch; success-in-code is measured at commit boundaries. — [SWE-chat](https://arxiv.org/pdf/2604.20779)
- "Mind changer" persona (redirects goals mid-session) is 8.0% of non-vibe sessions vs 4.6% in vibe coding — goal changes within a session are common enough to matter. — [SWE-chat](https://arxiv.org/pdf/2604.20779)
- Topic-shift detection framed as classifying whether a user turn pivots to a new topic or refines the current one; LLMs are stress-tested on this. — [arXiv 2605.09268, 2026](https://arxiv.org/html/2605.09268)
- LLM-based dialogue topic segmentation (DASH-DTS) and unified supervised/unsupervised segmentation (UPS, NAACL 2025) exist; an unsupervised embedding-plus-smoothing method targets chat logs. — [DASH, arXiv 2512.15042](https://arxiv.org/pdf/2512.15042); [NAACL 2025](https://aclanthology.org/2025.naacl-long.252.pdf); [McGill preprint](https://dmas.lab.mcgill.ca/fung/pub/LFMM25amlds_preprint.pdf)

### Inferences
- Practical segmentation: start a new task at (a) a user prompt whose intent label changes AND is not pushback, (b) a commit/PR tool call followed by a new request, (c) `/clear` or context reset, (d) a long idle gap. Pushback prompts always attach to the current task.
- Task success proxy hierarchy (strongest first): code committed and survives; tests pass after last edit with no later pushback; next prompt is a new task (not a correction); explicit thanks. Task failure proxy: interrupt with no recovery, rejection, user takes over (human overwrite), session ends right after failure report.

### Gaps
- No validated benchmark for task segmentation of coding-agent transcripts was found.

## How to judge prompt clarity to separate user-caused vs model-caused misunderstanding

### Takeaway
Research shows LLMs are weak at detecting ambiguity themselves, but ambiguity taxonomies exist and user-side underspecification is common in coding sessions. An LLM judge should rate the initial prompt (and context available) before seeing the agent's response, so it is not biased by the outcome.

### Cited Findings
- CLAMBER (ACL 2024): ~12K items with an ambiguity taxonomy; LLMs show limited ability to identify and clarify ambiguous queries; CoT and few-shot give only marginal gains. — [arXiv 2405.12063](https://arxiv.org/pdf/2405.12063); [ACL](https://aclanthology.org/2024.acl-long.578.pdf)
- ClarifyMT-Bench (arXiv Dec 2025): multi-turn clarification with a five-dimensional ambiguity taxonomy; evaluates when to ask, what to ask, when to stop. — [arXiv 2512.21120](https://arxiv.org/pdf/2512.21120)
- Software-engineering-specific clarification work: "Asking What Matters: Reward-Driven Clarification for Software Engineering Tasks" (arXiv Apr 2026). — [arXiv 2604.14624](https://arxiv.org/pdf/2604.14624) (not read in full)
- SWE-chat: users are "very nitpicky" (39%) and "sometimes vague" (33%); "vague requester" is a persona label (underspecifies and delegates decisions). — [SWE-chat](https://arxiv.org/pdf/2604.20779)
- Lower-quality initial prompts correlate with more feedback turns. — [arXiv 2507.23158](https://arxiv.org/html/2507.23158v1)
- Misalignment forms in the 20k-session study separate "interpret intent" from "follow rules", "bound actions", and "report progress" — the last three are model-caused regardless of prompt clarity. — [arXiv 2605.29442](https://arxiv.org/abs/2605.29442)

### Inferences
- Attribution rule: a correction counts against the model when the violated requirement was stated earlier (in the prompt, CLAUDE.md, or a prior correction) — this is checkable by an LLM judge with the transcript. A correction that adds new information ("also do X") is user-caused/scope change, not model error.
- Repeated correction of the same point (user restates an earlier instruction) is a strong, mostly model-caused signal and is cheap to approximate (semantic similarity between correction prompts).

### Gaps
- No validated "prompt clarity score" for coding prompts with reported agreement was found.

## Which metrics are robust vs easily gamed or confounded by user behavior

### Takeaway
Every friction metric is heavily confounded by user style, experience, and autonomy settings. Robust comparisons need within-user (or within-cohort) baselines and stratification by task intent. Code survival and environment-grounded signals (tool errors, test results) are harder to fake than sentiment.

### Cited Findings
- Experience confound: new users auto-approve ~20% of sessions vs 40%+ for experienced; interrupt rate goes up from 5% to 9% with experience. — [Anthropic, Feb 2026](https://www.anthropic.com/research/measuring-agent-autonomy)
- Persona confound: expert nitpicker is the most common persona even in vibe coding (36.7%). — [SWE-chat](https://arxiv.org/pdf/2604.20779)
- Selection bias: abandoned sessions are often not logged, inflating success. — [SWE-chat](https://arxiv.org/pdf/2604.20779)
- Survival confound: higher survival in vibe coding "may reflect lower user scrutiny". — [SWE-chat](https://arxiv.org/pdf/2604.20779)
- Perception gap: developers felt ~20% faster while ~19% slower. — [METR, Jul 2025](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/)
- Positive feedback is biased (praise for toxic compliance). — [arXiv 2507.23158](https://arxiv.org/html/2507.23158v1)
- LLM-judged session success has a low ceiling (human–human ICC 0.503). — [SWE-chat](https://arxiv.org/pdf/2604.20779)
- Anthropic's own classifications were produced by Claude without manual validation, single provider, time-bound. — [Anthropic, Feb 2026](https://www.anthropic.com/research/measuring-agent-autonomy)
- Economic Index limitations: classifications inferred from limited context; analysis "didn't assess actual code quality or productivity". — [Anthropic, Apr 2025](https://www.anthropic.com/research/impact-software-development)

### Inferences
- Robust (hard to game, low user confound): tool-call error rate, identical-tool-call retries, edits that fail to apply, test/build failure after the agent claimed success (a deterministic "false success report"), search loops, tokens per task within the same task intent.
- Medium: per-prompt pushback type (well validated, but user-style confounded) — compare within user over time.
- Weak / gameable: explicit thanks, LLM session success score in isolation, interrupt rate in isolation, session length in isolation.
- For nerf detection the comparison unit should be the same user, same repo, same task intent, before vs after a model/version change, with the model version string from the transcript as the treatment variable.

### Gaps
- No public study found that tests these transcript metrics as detectors of silent model degradation (the "nerf" use case) — this is an open area.
