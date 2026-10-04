# LLM-as-a-Judge Reliability for Labeling Coding-Agent Transcripts

Scope: best practices and risks for a judge pipeline that labels events in coding-agent session transcripts ("was this user message a correction?", "was the prompt clear?", "did the model misunderstand?", "did the task succeed?") inside a tool that tracks whether a model got worse over time. Research date: 2026-10-03. Dates are marked on every source.

## 1. Known LLM-judge biases (position, verbosity, self-preference, leniency, prompt sensitivity)

### Takeaway
The main biases are well documented since 2023 and still present in 2026 frontier judges: position, verbosity, self-preference/family bias, severity/leniency differences between judges, and sensitivity to prompt and version changes. Most of these biases are worst in pairwise or scale-based scoring. A pointwise, binary, per-event label (our use case) avoids position bias by design, but self-preference, leniency, and drift still apply.

### Cited Findings
- Zheng et al. (MT-Bench / Chatbot Arena, NeurIPS 2023, v4 Dec 2023): GPT-4 judges reach over 80% agreement with human preferences, the same level as human-human agreement. They name position bias, verbosity bias, self-enhancement bias, and limited reasoning. Proposed mitigations: swap positions, few-shot examples, chain-of-thought, reference-guided grading. — [arXiv 2306.05685](https://arxiv.org/abs/2306.05685)
- Eugene Yan's survey of LLM-evaluator papers (Aug 2024) reports from the literature: position bias, with GPT-3.5 favoring the first position about 50% of the time and Claude-v1 about 70%; verbosity bias, with both models preferring the longer answer more than 90% of the time; self-enhancement, with Claude-v1 favoring its own outputs by a 25% higher win rate. — [eugeneyan.com/writing/llm-evaluators](https://eugeneyan.com/writing/llm-evaluators/)
- Panickssery et al. (NeurIPS 2024, arXiv Apr 2024): GPT-3.5, GPT-4, and Llama 2 judges favor their own summaries although humans rate them equal. Self-recognition ability correlates linearly with self-preference strength, and fine-tuning that changes self-recognition changes self-preference (causal evidence). Judges also prefer a text that is only *labeled* as their own. — [arXiv 2404.13076](https://arxiv.org/pdf/2404.13076)
- Yang et al. (Information Sciences, Jun 2026): self-preference bias (SPB) measured on equal-quality pairs across 20 models ranged from +0.307 (LongCat-Flash-Chat) to −0.229 (Claude-Sonnet-4.5); 17 of 20 models had a statistically significant bias. Stronger capability did not mean lower SPB. Decomposing a holistic judgment into five dimension-wise forced choices reduced SPB by 31.5% on average for high-bias models. The authors did not separate self-identification from shared family style. — [arXiv 2604.22891](https://arxiv.org/html/2604.22891v4)
  - Note: a negative SPB for Claude-Sonnet-4.5 means it *under*-rated its own outputs in that study. Bias direction is model-specific, so it must be measured, not assumed.
- Family bias (models rate same-provider outputs higher) is listed as a separate documented bias in practitioner summaries. — [Adaline blog](https://www.adaline.ai/blog/llm-as-a-judge-reliability-bias) (secondary source)
- "Justice or Prejudice?" (ICLR 2025, IBM Research et al.) defines 12 judge biases and the CALM framework to quantify each; strong models still show significant bias on specific tasks. — [IBM Research](https://research.ibm.com/publications/justice-or-prejudice-quantifying-biases-in-llm-as-a-judge)
- Shi et al., "Judging the Judges: A Systematic Study of Position Bias" (IJCNLP 2025): 15 judges, about 150,000 instances; position bias varies by judge and task and is not random. — [ACL Anthology](https://aclanthology.org/2025.ijcnlp-long.18/)
- Norman, Rivera, Hughes, "Reliability without Validity" (arXiv Jun 2026): 21 judges from nine providers, about 541,000 judgments. Two production judges had test-retest reliability above 0.95 *and* severe position bias above 0.10, so consistency does not prove validity. Verbosity bias was minimal (<0.011) under a single pairwise rubric. Judge rankings moved up to 14 places between benchmarks. — [arXiv 2606.19544](https://arxiv.org/abs/2606.19544)
- Sunkavalli, essay-scoring audit (arXiv Aug 2026): judge severity (leniency) differed by up to 219 points on a 0–1000 scale; the spread across judges was 15–33% of the score range versus about 1% for trained humans. Judges were self-consistent (phi ≥ .80) but judge-human correlations were only .47–.56. — [arXiv 2608.29517](https://arxiv.org/abs/2608.29517)
- Prompt sensitivity: in a 2026 drift study, a "strict-prompt update" to the judge alone was enough to shift scores and had to be detected as judge drift. — [arXiv 2606.15474](https://arxiv.org/html/2606.15474)
- "The Silent Judge" (arXiv Sep 2025) reports shortcut biases that judges do not acknowledge in their explanations. — [arXiv 2509.26072](https://arxiv.org/pdf/2509.26072) (title/snippet only; not read in full)

### Inferences
- For per-event binary labels on one transcript, position bias is mostly irrelevant (no pair). It becomes relevant only if the tool ever compares two sessions side by side. Avoid pairwise comparisons of "old day vs new day" sessions.
- Verbosity bias can still appear in a different form: a judge may rate a long, confident assistant turn as "task succeeded". Asking for evidence (e.g., "quote the user message that confirms success") helps.
- Leniency differs strongly between judges, so absolute rates ("12% of sessions had a correction") are judge-dependent. Only trends measured by one frozen judge are comparable over time.
- The judge's written reason is not a reliable account of why it chose a label (Silent Judge). Do not use the explanation as evidence of correctness; use human agreement checks.

### Gaps
- No study found that measures self-preference specifically for *labeling another session's events* (as opposed to rating answer quality). The direction for Claude-judging-Claude transcripts is unknown; Sonnet 4.5's negative SPB suggests it may even be harsh.
- I did not find a source that measures sensitivity of binary classification labels to small wording changes in the rubric; the evidence is from scoring tasks.

## 2. The circularity risk (judge from the same family as the model under test, judge drift)

### Takeaway
If the judge is served by the same provider that may silently change models, a change in the judge can look like a change in the product. The 2026 literature gives a concrete fix: a fixed, human-labeled anchor set re-scored by the judge on a schedule. Any movement on the anchors can only come from the judge, which separates "the judge drifted" from "the model drifted".

### Cited Findings
- Yitao Li, "Who Drifted: the System or the Judge?" (arXiv Jun 2026): proposes a main monitor (cheap judge on all items, strong judge on a sample) plus an anchor process: a fixed set of human-labeled items re-scored by the current judge at intervals. Because anchors never change, only judge changes can move their gap to human labels ("one-way mirror"). A guard-window rule outputs {none, system, judge}. It detected a silent judge version bump in 60/60 runs and attributed a strict-prompt judge update correctly in 110/120. Recommendation: size the anchor budget so judge-drift detection is faster than contamination of the main signal. — [arXiv 2606.15474](https://arxiv.org/html/2606.15474)
- Survey on LLM-as-a-Judge (arXiv, v4): judge performance is not static; providers can retire or update models silently, which can make earlier evaluations impossible to reproduce; it recommends logging model version, inputs, outputs, reasoning, and timestamps, and repeating meta-evaluations. — [arXiv 2411.15594](https://arxiv.org/pdf/2411.15594) (via search summary)
- Essay-scoring audit (Aug 2026): all five judge version contrasts showed significant severity shifts (up to 133 points); one judge was deprecated mid-study and the change was caught by "identity canaries". Conclusion: LLM scoring needs version-specific validation; do not compare across judge versions. — [arXiv 2608.29517](https://arxiv.org/abs/2608.29517)
- Anthropic model lifecycle: older snapshots are retired on the first-party API (e.g., Claude Opus 4, Opus 4.1, Sonnet 4, Haiku 3.5 are "retired, except on Bedrock and Google Cloud"). A pinned snapshot therefore has a limited life. — [Claude pricing page](https://platform.claude.com/docs/en/docs/about-claude/pricing)
- Claude 4.7 and later models use a new tokenizer that produces about 30% more tokens for the same text, so a judge model change can also change cost and context limits. — [Claude pricing page](https://platform.claude.com/docs/en/docs/about-claude/pricing)
- A PLOS ONE paper describes a "human-anchored longitudinal comparison" with a bias-calibrated LLM judge; calibration raised human agreement and reduced volatility. — [PLOS ONE](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0339920) (search summary only)

### Inferences
- Recommended mitigation stack for "is-it-nerfed":
  1. Use deterministic heuristics first for anything they can decide (tool error counts, test exit codes, reverted edits, "undo"/"no, that's wrong" regex, interrupts, session length). These do not drift.
  2. Pin a dated judge snapshot ID, never an alias. Store the judge model ID and prompt hash with every label.
  3. Prefer a judge from a different provider than the model under test, or run two judges from different providers on a sample and alert on divergence. This removes self-/family-preference and makes a single-provider silent change visible.
  4. Keep a fixed anchor set (human-labeled events, never shown in prompts as examples) and re-judge it on every run or daily. If anchor agreement moves, flag "judge drift" and do not publish a nerf verdict.
  5. When a judge snapshot is retired, re-label a historical window with the new judge (back-fill) so the time series uses one judge; never splice two judges' rates.
- The anchor idea also catches subscription-side changes if the judge runs through `claude -p` (see section 6), where the user cannot fully pin a snapshot.

### Gaps
- No source quantifies how much a *same-family* judge's drift correlates with the drift of the model under test. The risk is plausible but unmeasured.
- I did not verify whether `claude -p` lets a user pin a dated snapshot ID or only an alias on a subscription; this needs a check in Claude Code docs.

## 3. Design patterns that increase reliability

### Takeaway
Practitioners and papers agree: binary or small categorical labels, a rubric written from expert critiques with examples, reasoning before the label, structured output, and repeated samples with a majority vote. Blinding the judge to date, model name, and the hypothesis is not studied directly, but label-based self-preference evidence shows that metadata in the prompt changes verdicts, so blinding is justified.

### Cited Findings
- Hamel Husain, "Creating a LLM-as-a-Judge That Drives Business Results" (Oct 29, 2024): use binary pass/fail, not 1–5 scales ("a binary decision forces everyone to consider what truly matters"); pair each verdict with a detailed critique a new employee could understand; use those critiques as few-shot examples ("critique shadowing"); start with about 30 examples and continue until no new failure modes appear; iterate by hand until agreement is high (he reached >90% in three iterations on one project); off-the-shelf generic judges "cause more confusion than value". — [Hamel Husain](https://hamelhusain.substack.com/p/llm-judge)
- Husain also states raters cannot reliably tell a 3 from a 4, and pass/fail is harder to game with verbosity. — [Comet blog summarizing Husain](https://www.comet.com/site/blog/llm-as-a-judge/) (secondary)
- Eugene Yan (Aug 2024): convert evaluations to binary so classification metrics (precision, recall) apply; CoT consistently improved evaluator accuracy; pairwise is more stable than direct scoring for subjective qualities. G-Eval reached average Spearman ρ 0.514 on summarization; Prometheus (fine-tuned judge) reached 0.897 Pearson with humans. — [eugeneyan.com](https://eugeneyan.com/writing/llm-evaluators/)
- Zheng et al. 2023: few-shot examples, CoT, and reference-guided grading reduce judge errors. — [arXiv 2306.05685](https://arxiv.org/abs/2306.05685)
- Decomposing one holistic judgment into several narrow forced-choice questions reduced self-preference by 31.5%. — [arXiv 2604.22891](https://arxiv.org/html/2604.22891v4)
- Repeated sampling: LLM judges are self-inconsistent across runs ("Rating Roulette", Oct 2025). Temperature 0 cut flip rates by 79% for GPT-4o-mini but only 43% for GPT-4.1-mini, and some flips remain at t=0 due to inference-side non-determinism (batching, kernels). Majority vote over three runs improved balanced accuracy against humans. Some work finds temperature 0 can lower human agreement. — [alphaXiv 2510.27106](https://www.alphaxiv.org/overview/2510.27106v1); [arXiv 2606.26185](https://arxiv.org/html/2606.26185v1); [arXiv 2606.13685](https://arxiv.org/html/2606.13685v1) (search summaries)
- Blinding: judges preferred a summary merely *labeled* as their own, so text labels in the prompt shift verdicts. — [arXiv 2404.13076](https://arxiv.org/pdf/2404.13076)

### Inferences
- Concrete prompt design for this tool:
  - One narrow question per call or per JSON field, e.g. `{"is_correction": bool, "evidence_quote": str, "reason": str}`; reason before label in the schema order.
  - Small categorical sets where binary loses meaning, e.g. `misunderstanding: none | scope | intent | factual`. No 1–10 scores.
  - Rubric with 3–5 positive and negative examples per label, taken from real transcripts with a human critique.
  - Strip from the input: timestamps, dates, model names/IDs, version strings, the tool's name ("is it nerfed"), and any user text that mentions "nerf" or "worse" outside the event under review. Normalize assistant self-identification ("As Claude...") where possible. Shuffle event order across days in a batch so the judge cannot infer time.
  - Require an evidence quote; reject labels whose quote does not appear in the transcript (cheap hallucination check).
  - Use k=3 samples with majority vote only for ambiguous labels or the anchor set, to control cost.
- Keep the rubric versioned; a rubric change is a judge change and needs an anchor re-baseline.

### Gaps
- No paper directly tests "blinding to date/model name" for drift-monitoring judges. The recommendation rests on the label-swap evidence and general good practice.
- No source compares binary vs. scale specifically for coding-agent transcripts.

## 4. Inter-rater agreement measures and how many human labels are needed

### Takeaway
Report Cohen's kappa (two raters) or Krippendorff's alpha (more raters, missing labels), plus per-class precision and recall, never raw percent agreement alone. Plan for roughly 100 human-labeled events per label for a usable kappa estimate, with bootstrap confidence intervals; start with about 30 to build the rubric.

### Cited Findings
- "Judging the Judges: Evaluating Alignment and Vulnerabilities in LLMs-as-Judges" (Thakur et al., Jun 2024): Cohen's kappa separates judges better than percent agreement; high percent agreement can hide very different scores. GPT-4 Turbo reached kappa 0.84 and Llama-3 70B 0.79 versus human-human 0.96. — [arXiv 2406.12624](https://arxiv.org/html/2406.12624v1)
- "Reliability without Validity" (Jun 2026): a 33–41 percentage-point gap between exact-match agreement and Cohen's kappa on MT-Bench; exact match "systematically overstates discriminative ability". Proposes a "Minimum Viable Validation Protocol". — [arXiv 2606.19544](https://arxiv.org/abs/2606.19544)
- Sample size: kappa sample size is chosen so the standard error or CI width stays under a target. One applied example needed 96 items for a 95% CI with ±0.2 margin and about 20% positive rate; another used about 375 items for a ±5% margin. Bootstrap over items (1,000–2,000 resamples) is a common way to get CIs. — [Sample-size calculations for Cohen's kappa (Cantor 1996 PDF)](https://www.ime.usp.br/~abe/lista/pdfGSoh9GPIQN.pdf); [NCSS PASS: CI for kappa](https://www.ncss.com/wp-content/themes/ncss/pdf/Procedures/PASS/Confidence_Intervals_for_Kappa.pdf); examples from search snippets of [arXiv 2511.20493](https://arxiv.org/pdf/2511.20493) and [arXiv 2505.01136](https://arxiv.org/pdf/2505.01136)
- Husain: start with about 30 expert labels and keep going until no new failure modes appear. — [Hamel Husain](https://hamelhusain.substack.com/p/llm-judge)

### Inferences
- Rare labels (e.g., "user correction" may be 5–15% of user turns) inflate percent agreement and make kappa unstable. Oversample candidate positives (from heuristics) when building the human set, and report precision/recall for the positive class.
- Practical plan: about 30 events per label to write the rubric, then about 100–200 held-out events per label for validation (target kappa ≥ 0.6–0.7 with bootstrap CI), with 30–50 of them frozen as the drift anchor set. For a solo developer, one expert labeler plus a second pass on a 20–30% subset to estimate human-human kappa as a ceiling.
- Krippendorff's alpha is the better choice if several users or the community contribute labels with gaps. I found no fetched source with alpha specifics; this is standard practice.

### Gaps
- I did not find a source that gives a kappa sample-size table for the exact case of low base-rate binary labels; the 96-item example is one data point.
- Krippendorff's alpha guidance was not sourced in this session.

## 5. Cost: tokens per session, small models, caching, batch, chunking, heuristic pre-filtering

### Takeaway
Haiku-class judging with batch plus caching is cheap: about $0.50/$2.50 per million input/output tokens in batch for Haiku 4.5, and cache reads cost 10% of input. The real cost driver is transcript length, so judge only candidate events (heuristic-flagged) with a local window of context, not whole sessions.

### Cited Findings
- Anthropic list prices (fetched 2026-10-03), per million tokens input/output: Haiku 4.5 $1/$5; Sonnet 5 and Sonnet 5.5 $2/$10; Sonnet 4.6 $3/$15; Opus 5 $5/$25; Opus 5.5 $4/$20. — [Claude pricing](https://platform.claude.com/docs/en/docs/about-claude/pricing)
- Batch API: 50% off input and output (Haiku 4.5 batch: $0.50/$2.50; Sonnet 5: $1/$5). Batch and caching discounts stack. — [Claude pricing](https://platform.claude.com/docs/en/docs/about-claude/pricing)
- Prompt caching: 5-minute write 1.25x input, 1-hour write 2x, cache hit 0.1x (0.05x on Opus 5.5). Caching pays off after one read (5-min) or two reads (1-hour). — [Claude pricing](https://platform.claude.com/docs/en/docs/about-claude/pricing)
- Claude 4.7+ tokenizer makes about 30% more tokens for the same text. — [Claude pricing](https://platform.claude.com/docs/en/docs/about-claude/pricing)
- Anthropic's own example: about 3,700 tokens per support conversation on Haiku 4.5 costs about $37 per 10,000 conversations (non-batch). — [Claude pricing](https://platform.claude.com/docs/en/docs/about-claude/pricing)
- Li (Jun 2026) uses a cheap judge on all items and a strong judge on a sample, combined with prediction-powered inference, as the cost-efficient monitoring design. — [arXiv 2606.15474](https://arxiv.org/html/2606.15474)

### Inferences (estimates, not sourced measurements)
- Per-event judging: rubric + examples ≈ 2–4k tokens (cacheable), event window ≈ 1–3k tokens (previous assistant turn + user message + next turn, with tool outputs truncated), output ≈ 100–200 tokens. On Haiku 4.5 batch with cached rubric: about 2k × $0.50/M + 3k × $0.05/M + 150 × $2.50/M ≈ $0.0015 per event, so about $1.5 per 1,000 events.
- A full coding session can be 50k–500k tokens because of tool outputs. Whole-session judging on Haiku batch at 100k tokens ≈ $0.05/session; at 100x volume that is the difference between dollars and hundreds of dollars. Chunk by user turn and drop or truncate tool results.
- Order of work: (1) heuristics label everything they can at zero cost; (2) heuristics flag candidate events; (3) Haiku-class judge labels candidates; (4) a stronger or cross-provider judge labels a small random sample plus the anchors to calibrate the cheap judge.
- Note the 5-minute cache TTL: send same-rubric requests back to back (or use 1-hour cache) so the cache hits.

### Gaps
- I did not fetch OpenAI or Google batch/caching prices for a cross-provider judge; these need a check.
- No measured token distribution for real Claude Code / Codex transcripts was found; the token numbers above are my estimates.

## 6. Privacy: local judge via user's subscription (`claude -p`) vs API

### Takeaway
Running the judge through the user's own Claude Code headless mode (`claude -p`) keeps the user's transcripts under the user's account and costs no extra API money, but billing policy for headless use has changed during 2026 and the user has less control over the exact model snapshot. The API (or a different provider) gives a pinned snapshot and batch pricing, but sends transcripts to a service the tool operator controls.

### Cited Findings
- `claude -p` / `--print` runs Claude Code non-interactively from scripts. — [Claude Code headless docs](https://docs.anthropic.com/en/docs/claude-code/sdk/sdk-headless)
- Billing has been in flux: Anthropic announced that from June 15, 2026, `claude -p` and Agent SDK usage would draw from a separate "Agent SDK credit" pool, then paused that change; as of the source date, `claude -p`, Agent SDK, and third-party app usage still draw from subscription limits. — [genaiunplugged substack](https://genaiunplugged.substack.com/p/claude-billing-change-workarounds-free-ai-automations); [claudefa.st](https://claudefa.st/blog/guide/development/agent-sdk-credit); [VentureBeat](https://venturebeat.com/technology/anthropic-reinstates-openclaw-and-third-party-agent-usage-on-claude-subscriptions-with-a-catch) (secondary sources; search summaries)
- A third-party project reported that `claude -p` headless usage was "not covered by subscription" for its daemon tasks, which shows policy risk for tools built on it. — [multica issue #2563](https://github.com/multica-ai/multica/issues/2563) (title only)
- Users have asked Anthropic to expose per-bucket rate-limit usage to headless SDK consumers, which shows rate limits are a practical constraint. — [claude-code issue #50518](https://github.com/anthropics/claude-code/issues/50518) (title only)

### Inferences
- Local `claude -p` judging fits a privacy-first, client-side tool: transcripts never leave the user's machine except to the provider the user already uses. But it conflicts with the circularity mitigation: the judge is the same provider and possibly the same model whose nerf the tool tries to detect, and the subscription may route to whatever model is current. The anchor set (section 2) becomes mandatory in this mode.
- A hybrid design works: deterministic heuristics run locally for everyone; LLM labels run locally via `claude -p` or `codex exec` with the user's subscription; only aggregated, anonymized label counts (not transcripts) go to a central server.
- Large-scale judging through a subscription will hit usage limits and may compete with the user's own work; batch API is cheaper per token for a central service.

### Gaps
- I did not find an official Anthropic statement on whether automated judging of one's own transcripts via `claude -p` is within subscription terms; this needs a check of current Consumer Terms and usage policy.
- I did not check whether `claude -p --model` accepts a dated snapshot ID on a subscription.
- I did not research Codex CLI (`codex exec`) headless behavior or OpenAI data retention.
