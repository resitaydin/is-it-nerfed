# Fair statistics for "did the model get worse?" from one user's noisy session data

Scope: the simplest defensible method to (a) score performance per day/week, (b) adjust for confounders, (c) output a verdict ("no change" / "slightly worse" / "clearly worse") with honest uncertainty. Context: one user, ~5-50 tasks/day, missing days, observational data, small local Python script. Date of research: 2026-10-03.

## 1. How big is the noise, and how should uncertainty be computed?

### Takeaway
At 5-50 tasks per day, a daily score is almost pure noise: even a dedicated tracker with 50 controlled tasks/day needs a ~13-point swing to call a daily change significant. Use clustered standard errors (tasks inside a session or project are correlated) and pool to weekly windows or longer before any verdict.

### Cited Findings
- Anthropic recommends five things for evals: report the standard error of the mean (CLT), cluster standard errors for related questions, reduce within-question variance (resampling), analyze paired differences, and use power analysis — [Anthropic, "A statistical approach to model evaluations"](https://www.anthropic.com/research/statistical-approach-to-model-evals)
- Formulas from Miller (2024): SE_CLT = sqrt( sum_i (s_i - s_bar)^2 / (n-1) / n ); for binary scores SE = sqrt( p(1-p)/n ) — [Miller 2024, arXiv 2411.00640](https://arxiv.org/html/2411.00640)
- Clustered SE adds the within-cluster cross terms: SE_clustered = ( SE_CLT^2 + (1/n^2) * sum_c sum_i sum_{j!=i} (s_ic - s_bar)(s_jc - s_bar) )^(1/2). Clustered errors on real evals can be "over 3X larger than naive" (DROP: 3.05x). "Failure to adjust standard errors for clustered sampling may lead an unsuspecting analyst to suppose that the measurement ... is much more precise than it actually is." — [Miller 2024](https://arxiv.org/html/2411.00640)
- Paired differences give a "free" variance reduction: Var(paired) = Var(unpaired) - 2*Cov(x_A, x_B)/n, because models tend to get the same questions right and wrong — [Miller 2024](https://arxiv.org/html/2411.00640)
- Resampling each question K times reduces conditional variance (sigma_i^2/K) with diminishing returns; Miller warns not to change sampling temperature just to reduce variance — [Miller 2024](https://arxiv.org/html/2411.00640)
- Power formula: n = (z_{alpha/2} + z_beta)^2 * (omega^2 + sigma_A^2/K_A + sigma_B^2/K_B) / delta^2. Example: detecting a 3-point difference at 80% power needs "at least 1,000 questions." Inverted for minimum detectable effect: delta = (z_{alpha/2}+z_beta) * sqrt((omega^2 + sigma_A^2/K_A + sigma_B^2/K_B)/n) — [Miller 2024](https://arxiv.org/html/2411.00640)
- MarginLab's Claude Code tracker runs N=50 SWE-Bench-Pro tasks per day, models each as a Bernoulli trial, and uses p < 0.05. The significance threshold is about ±12.8 points daily (50 tasks), ±4.7 weekly (350), ±2.3 monthly (1,200) — [MarginLab tracker](https://marginlab.ai/trackers/claude-code/)
- Reported daily swings for that tracker ranged mid-40s to mid-60s (10-15 points) around a ~56% baseline, while a 4.1-point 30-day drop (655 evaluations) was flagged as significant — [Explore AI Together (secondary summary of MarginLab)](https://exploreaitogether.com/ai-models-bad-days-proof/)

### Inferences
- Using the Bernoulli SE: with p≈0.6 and n=20 tasks/day, SE≈0.11, so a 95% interval is ±21 points. With 100 tasks/week, ±10 points; with 400 tasks/month, ±5 points. Clustering by session/project makes these wider (possibly 1.5-3x). So a single user can at best detect large drops (~10+ points) on a weekly-to-monthly window. The product should say this plainly.
- Cluster level for a single user: the session (or the project) is the natural cluster. Simplest implementation: compute a per-session mean, then treat sessions as the unit (cluster bootstrap: resample whole sessions/days, not individual tasks).
- Bootstrap: a cluster (block) bootstrap of sessions with 2,000-10,000 resamples is trivially cheap in numpy and gives CIs for any composite score without distribution assumptions. Note: plain i.i.d. bootstrap of tasks will understate uncertainty for the same reason naive SEs do.
- Daily scores should be shown only with wide CIs or as a rolling 7-day/28-day window; a verdict should never be issued from a single day.

### Gaps
- No source found giving typical intra-session correlation (ICC) for real coding-agent sessions; the 3x inflation figure is from static benchmarks, not agentic sessions.
- Did not find a peer-reviewed critique of MarginLab's method (e.g., multiple-looks problem from checking daily).

## 2. Confounders and how to adjust for them

### Takeaway
Observational session data is dominated by confounders (task mix, project, context length, workflow changes). The simplest defensible approach is: (1) log the confounders, (2) stratify or regress on them (logistic regression or a mixed-effects model with project as a random effect), (3) cut the series at known user-side change events (CLAUDE.md edits, MCP/skill installs, CLI version, effort setting), and (4) use a fixed canary task set as the only clean model-only signal.

### Cited Findings
- CUPED (Deng, Xu, Kohavi, Walker, Microsoft 2013) reduces variance by regressing out a pre-period covariate that is correlated with the outcome but unaffected by the treatment; effectiveness depends on the correlation; reported up to ~50% variance reduction and now standard at Netflix, Booking.com, Optimizely — [CUPED summaries: optipilot](https://optipilot.com/data/cuped-variance-reduction); [atticusli glossary](https://atticusli.com/behavioral-science-glossary/cuped-variance-reduction/); [original paper on ResearchGate](https://www.researchgate.net/publication/237838291_Improving_the_Sensitivity_of_Online_Controlled_Experiments_by_Utilizing_Pre-Experiment_Data)
- Item response theory (IRT) models P(correct) as a function of a model "ability" and per-item difficulty (and discrimination); tinyBenchmarks shows ~100 curated IRT-selected items per scenario estimate LLM performance within ~2% average error — [tinyBenchmarks (NSF PAR)](https://par.nsf.gov/servlets/purl/10547932); [alphaxiv abstract 2402.14992](https://www.alphaxiv.org/abs/2402.14992)
- Harness changes are a real confounder: MarginLab runs benchmarks directly in the Claude Code CLI precisely so that it detects "degradation related to both model changes and harness changes" — [MarginLab tracker](https://marginlab.ai/trackers/claude-code/)
- Real model-side regressions did happen: Anthropic's postmortem lists a context-window routing bug (Aug 5 - Sep 18 2025, up to 16% of Sonnet 4 requests at peak, ~30% of Claude Code users affected), an output-corruption bug (Aug 25 - Sep 2), and an XLA:TPU top-k miscompilation. Anthropic said its own evals "simply didn't capture the degradation users were reporting, in part because Claude often recovers well from isolated mistakes." — [Anthropic postmortem](https://www.anthropic.com/engineering/a-postmortem-of-three-recent-issues)
- Anthropic states: "We never reduce model quality due to demand, time of day, or server load." — [Anthropic postmortem](https://www.anthropic.com/engineering/a-postmortem-of-three-recent-issues)

### Inferences
- Recommended confounder handling, simplest first:
  1. **Log covariates per task**: task type (bugfix/feature/refactor/question), project/repo, prompt length, context tokens at start, whether compaction occurred, hour of day, CLI version, model id, reasoning effort, hash of CLAUDE.md, list of MCP servers and skills.
  2. **Exact stratification / change-event segmentation**: any user-side config change (CLAUDE.md hash, MCP set, skills set, CLI version, effort setting) defines a new "regime". Compare only within a regime, or include regime as a covariate. This addresses "user workflow change" directly without modelling.
  3. **Covariate adjustment**: logistic regression `success ~ week + task_type + log(context_tokens) + compacted + effort + C(project)` via statsmodels; with few projects use fixed effects, with many projects a mixed model `(1|project)` (statsmodels `BinomialBayesMixedGLM` or `mixedlm` on a continuous score). Report the `week` (or post-period) coefficient with clustered SE (`cov_type='cluster'` grouped by session).
  4. **CUPED-style adjustment**: use the user's own baseline-period per-project success rate as the covariate; this is cheap and removes project-mix drift.
  5. **Difficulty normalization**: full IRT needs many repeated items across "testees", which a single user's unique tasks do not provide. A cheap proxy is a difficulty score (e.g., an LLM grader or heuristic: files touched, diff size, prompt length) used as a covariate. Full IRT fits only the canary set.
- Time of day/load: Anthropic denies load-based degradation, but infrastructure bugs (routing) can still correlate with load; include hour as a covariate and let data decide rather than assume.
- User fatigue and learning effects bias in opposite directions: learning (better prompts over time) can mask a real model decline; fatigue (late-session sloppiness) can mimic one. Covariates such as task index within session and prompt length partly capture these; only the canary fully separates them.
- Simpson's paradox: if the user shifts to harder projects during a "nerf" period, pooled success falls even when within-project success is flat. Always show the within-stratum comparison next to the pooled number. (Standard statistical fact; no specific source fetched.)
- Regression to the mean: people notice "nerfs" after a bad stretch; any analysis triggered by a bad day will tend to find recovery. Fix the comparison windows in advance (e.g., previous 28 days vs last 7 days) rather than starting the window at the moment the user felt something was off. (Standard statistical fact; no specific source fetched.)

### Gaps
- No empirical source found that quantifies how much CLAUDE.md / MCP / skill changes move agent success rates.
- No source found for validated "difficulty" scoring of real-world coding prompts outside benchmarks.

## 3. Time-series change detection with 5-50 tasks/day and missing days

### Takeaway
Do not run change-point detection on daily task-level data; aggregate to daily or weekly success rates (with counts as weights) first. The simplest defensible primary test is a fixed-window comparison (baseline vs recent) with a cluster bootstrap CI. Use segmented regression when there is a known event date (e.g., new model release or CLI version), and BOCPD as an optional online alarm. Mann-Kendall and PELT are supporting tools, not the verdict engine.

### Cited Findings
- Interrupted time series (segmented regression) guidance: common rule of 12 data points before and 12 after the intervention (not power-based); other guidance asks for at least 9 points per segment and ideally ≥100 observations per data point; at least 5 points per phase are needed just to estimate intercept, slope, autocorrelation and variance — [search summary of ITS literature incl. BMC Med Res Methodol reviews](https://bmcmedresmethodol.biomedcentral.com/articles/10.1186/s12874-019-0777-x); [Wagner et al. segmented regression (ResearchGate)](https://www.researchgate.net/publication/227681545_Segmented_Regression_Analysis_of_Interrupted_Time_Series_Studies_in_Medication_Use_Research)
- Models reach >80% power for effect size ≥1.0 with ≥24 time points, depending on autocorrelation; for series with <12 points the Durbin-Watson test was inconclusive >75% of the time and failed to detect autocorrelation; segmented regression does not inherently handle autocorrelation, nonstationarity or seasonality — [Evaluation of statistical methods for ITS (BMC Med Res Methodol 2021)](https://bmcmedresmethodol.biomedcentral.com/articles/10.1186/s12874-021-01364-0); [Comparison of six methods for ITS](https://bmcmedresmethodol.biomedcentral.com/articles/10.1186/s12874-021-01306-w)
- Mann-Kendall requires independent observations; serial autocorrelation distorts Type I/II errors; methods tend to overestimate weak trends in small samples (n < 40); prewhitening helps prevent false trends when power is low but can remove real trend when samples and trends are large; effective-sample-size modification is an alternative — [Modified Mann-Kendall, Sci Rep](https://www.nature.com/articles/s41598-025-30034-0); [Yue et al. 2002, WRR](https://agupubs.onlinelibrary.wiley.com/doi/10.1029/2001WR000861); [To prewhiten or not](https://www.tandfonline.com/doi/pdf/10.1623/hysj.52.4.611)
- `ruptures` (Python) offers Pelt, Binseg, BottomUp, Window, Dynp and KernelCPD with cost functions (L1, L2, Normal, RBF, Rank, AR, etc.); the number of breakpoints is controlled by a penalty `pen` in `predict(pen=...)` — [ruptures docs](https://centre-borelli.github.io/ruptures-docs/)
- BOCPD (Adams & MacKay 2007) maintains a posterior over "run length" since the last change; a constant hazard rate H implies geometric gaps with mean 1/H; it runs online in linear time per step and yields a probability of change rather than a hard alarm — [Adams & MacKay (ResearchGate)](https://www.researchgate.net/publication/1771282_Bayesian_Online_Changepoint_Detection); [metricgate BOCPD doc](https://metricgate.com/docs/bocpd-online-changepoint/)

### Inferences
- **Primary method (simplest, robust to missing days):** fixed windows. Baseline = a frozen reference period (e.g., first 28 days of a model version, or the 28 days before the last 7). Recent = last 7 days. Compute adjusted difference (regression coefficient or CUPED-adjusted means) and a cluster bootstrap CI. Missing days are no problem because the unit is the session, not the calendar day.
- **Known event dates** (new model id, CLI upgrade, config change): segmented regression `y_t = b0 + b1*t + b2*post_t + b3*(t - T0)*post_t` on daily aggregated rates weighted by daily n, with HAC (Newey-West) or cluster SE. Needs roughly ≥9-12 active days on each side; with fewer, fall back to the window comparison.
- **Unknown dates / alerting:** BOCPD on daily success counts with a Beta-Bernoulli model is a natural fit for count data with varying n per day and gaps (just skip missing days). Set hazard to e.g. 1/60 days. Report "probability a change happened in the last 7 days" rather than a binary alarm. A one-sided Bernoulli CUSUM is a simpler alternative but needs a chosen reference rate and threshold.
- **PELT (ruptures):** fine for an after-the-fact "where did the level shift?" chart on weekly aggregates; the penalty choice is arbitrary for a tiny series, so it should not drive the verdict.
- **Mann-Kendall:** works with ~10+ aggregated points and ignores unequal spacing, but it tests monotonic trend, not a step change, and is prone to false trends at n<40 with autocorrelation. Treat it as secondary.
- **Multiple looks:** checking daily inflates false alarms (the "peeking" problem). Either use a Bayesian posterior (no fixed alpha), or correct (e.g., require the condition to hold on two consecutive weekly checks, or use a stricter alpha like 0.01 for daily checks).

### Gaps
- No source found that benchmarks BOCPD vs PELT vs CUSUM specifically on low-count Bernoulli series of 5-50 trials/day.
- The ruptures landing page gives no guidance on choosing `pen` or `min_size`; standard practice (BIC-like penalty ~ log(n)*sigma^2) was not confirmed from the fetched page.

## 4. Turning numbers into a verdict: practical significance, TOST, ROPE

### Takeaway
A fair verdict needs a pre-declared smallest effect that matters (SESOI / ROPE half-width, e.g., 5 percentage points of success rate). Then use the CI (frequentist TOST) or posterior HDI (Bayesian ROPE): both give the same four-way logic and map directly onto "no change", "slightly worse", "clearly worse", and "not enough data". The "not enough data" outcome must be a first-class verdict.

### Cited Findings
- TOST: specify lower/upper equivalence bounds from the smallest effect size of interest; test H01: Δ ≤ -ΔL and H02: Δ ≥ ΔU; if both are rejected, the effect is within bounds and practically equivalent — [Lakens, Scheel, Isager 2018 tutorial](https://journals.sagepub.com/doi/10.1177/2515245918770963); [Wikipedia: Equivalence test](https://en.wikipedia.org/wiki/Equivalence_test)
- TOST at alpha=0.05 is equivalent to the 90% CI lying entirely inside the equivalence range ("CI = 100 - 2α") — [Lakens, Improving Your Statistical Inferences ch. 9](https://lakens.github.io/statistical_inferences/09-equivalencetest.html)
- Combining a null test with an equivalence test yields four outcomes: inconclusive; significant but practically insignificant; equivalent; different from zero but magnitude unclear — [Lakens ch. 9](https://lakens.github.io/statistical_inferences/09-equivalencetest.html)
- SESOI can be set by theory/just-noticeable difference, anchor-based (perceived change), cost-benefit, or "small telescopes" — [Lakens ch. 9](https://lakens.github.io/statistical_inferences/09-equivalencetest.html)
- Kruschke HDI+ROPE rule: if the 95% HDI is entirely inside the ROPE, accept the null value for practical purposes; entirely outside, reject it; otherwise withhold a decision — [Kruschke 2018, AMPPS](https://journals.sagepub.com/doi/10.1177/2515245918771304); [bayestestR ROPE vignette](https://easystats.github.io/bayestestR/articles/region_of_practical_equivalence.html)
- With uniform priors and matching interval widths, TOST and ROPE give identical results; with Kruschke's broad priors they are "very similar" — [Lakens ch. 9](https://lakens.github.io/statistical_inferences/09-equivalencetest.html)
- MarginLab's verdict is plain NHST at p<0.05 against a baseline, with no equivalence bound — [MarginLab tracker](https://marginlab.ai/trackers/claude-code/)

### Inferences
- Proposed verdict rule (Δ = adjusted recent minus baseline success rate, in points; SESOI = 5 points, "clear" = 10 points; use the 90% interval):
  - **No change**: whole interval inside [-5, +5].
  - **Slightly worse**: interval entirely below 0 but not entirely below -10 (or point estimate between -5 and -10 with interval excluding 0).
  - **Clearly worse**: whole interval below -5 and point estimate ≤ -10 (or posterior P(Δ < -5) ≥ 0.95).
  - **Better**: mirror rules.
  - **Not enough data yet**: anything else (interval straddles a bound). Show how many more sessions would be needed (from the power formula).
- Bayesian variant for the small script: Beta-Binomial per period (prior Beta(1,1) or weakly informative from baseline), sample posteriors with numpy, compute P(Δ < -SESOI) and P(|Δ| < SESOI). This needs ~10 lines, no MCMC, and handles small n honestly. Clustering is ignored in pure Beta-Binomial, so either use session-level aggregation or widen with a design-effect factor.
- The SESOI should come from the user ("how many extra failures per 20 tasks would you notice?"), which matches Lakens' anchor-based approach and makes the threshold non-arbitrary to the user.

### Gaps
- No published SESOI for "noticeable" coding-agent degradation was found.

## 5. A control: canary / fixed task replay

### Takeaway
A fixed canary set replayed on a schedule is the only clean way to separate "the model changed" from "my work changed", because it holds task, prompt and (if pinned) harness constant and enables paired comparison. Evidence: MarginLab runs exactly this design daily, Chen et al. used fixed task sets to document large real drift in GPT-4, and black-box change detection by comparing output distributions is published. Cost is the limit: a personal canary will be small, so it detects only large shifts.

### Cited Findings
- MarginLab replays 50 SWE-Bench-Pro tasks per day through the real Claude Code CLI; as of the fetch it was collecting a new Opus 5.5/high baseline from 2026-09-24 with detection paused — [MarginLab tracker](https://marginlab.ai/trackers/claude-code/)
- Chen, Zaharia, Zou evaluated March vs June 2023 GPT-3.5/GPT-4 on fixed task sets; GPT-4 prime-identification accuracy fell from 84% to 51%; code generation had more formatting mistakes; instruction-following declined — [Chen et al. (arXiv 2307.09009, ar5iv)](https://ar5iv.labs.arxiv.org/html/2307.09009)
- "You've Changed" (arXiv 2504.12335) detects black-box LLM modification by statistically comparing distributions of linguistic and psycholinguistic features of generated text, avoiding costly benchmark runs — [arXiv 2504.12335](https://arxiv.org/abs/2504.12335)
- Paired analysis on a fixed item set reduces variance by 2*Cov/n — [Miller 2024](https://arxiv.org/html/2411.00640)
- Anthropic's own evals missed the 2025 infrastructure bugs partly because Claude recovers from isolated mistakes — [Anthropic postmortem](https://www.anthropic.com/engineering/a-postmortem-of-three-recent-issues)

### Inferences
- Design for a personal canary: 10-20 small, deterministic, auto-gradable tasks (unit tests pass/fail), run 1-3x per task per week through the user's own CLI with a pinned "clean" config (empty CLAUDE.md, no MCP, fixed effort) plus optionally the user's real config. The clean run measures model+harness; the difference between clean and real-config runs measures the user's setup.
- Analysis: per-task paired difference vs baseline (McNemar for binary, or paired bootstrap). With 20 tasks x 3 repeats, the minimum detectable drop is still roughly 15-20 points; state this.
- Cheap secondary signals per canary run (tokens used, turns, wall-clock, tool-call count) can shift before pass rate does and are cheap to log; the "You've Changed" paper supports distributional comparison of outputs as a signal.
- Anthropic's postmortem suggests outcome-only pass/fail may miss degradations the agent recovers from; logging turns/retries/tokens per task catches "worse but still passes".
- Cost per execution: a 20-task canary at a few cents to a dollar per task is a fixed weekly cost that does not scale with user activity; it holds at 100x users only if shared (one public canary like MarginLab) rather than per user.

### Gaps
- No source found on the minimum canary size that is useful for a single user, nor on how agent nondeterminism (temperature, tool timing) inflates per-task variance in Claude Code specifically.
- The query count needed by the "You've Changed" method was not in the abstract.

## 6. Composite scores without arbitrary weights

### Takeaway
Keep a single primary metric (task success rate) for the verdict, and show other metrics (turns, tokens, retries, user corrections) as secondary diagnostics. If a composite is needed, z-score each metric against the user's own baseline period, orient so higher is better, and average with equal weights; this is the most common and the most explainable choice, and results are often less sensitive to weights than expected.

### Cited Findings
- Equal weighting is the most common approach for composite indicators; PCA weights reflect each indicator's statistical contribution but can be unequal and hard to justify; experts often give near-equal weights when asked; results are often less sensitive to weights than expected; equal weights on highly correlated variables can double-count — [OECD Handbook on Constructing Composite Indicators](https://www.oecd.org/content/dam/oecd/en/publications/reports/2005/08/handbook-on-constructing-composite-indicators_g17a16e3/533411815016.pdf); [COINr weighting chapter](https://bluefoxr.github.io/COINrDoc/weighting-1.html); [Robustness and sensitivity of weighting (ResearchGate)](https://www.researchgate.net/publication/257592890_Robustness_and_sensitivity_of_weighting_and_aggregation_in_constructing_composite_indices)
- Composite indices are moderately sensitive to weighting but robust to normalization choices and missing-data treatment under best practice — [search summary of recent composite-index literature; see OECD handbook](https://www.oecd.org/content/dam/oecd/en/publications/reports/2005/08/handbook-on-constructing-composite-indicators_g17a16e3/533411815016.pdf)

### Inferences
- Z-score against the baseline period (not the full history), otherwise a later decline shifts the reference itself.
- Rank-based alternative: convert each metric to its percentile within the baseline distribution and average; robust to outliers like a single huge token count.
- Drop or merge highly correlated metrics (e.g., tokens and wall-clock) before equal weighting to avoid double counting.
- PCA on a single user's small sample is unstable and not explainable to the user; avoid.
- The verdict should be driven by one pre-declared primary metric to avoid a garden of forking paths across many metrics (multiple-comparison risk). If several metrics are tested, apply Holm correction or treat the others as descriptive only.

### Gaps
- Wainer's "equal weights" result (that equal weights often predict nearly as well as optimal weights) was not retrieved from a primary source in this session.
- No source found on which secondary agent metrics (turns, tokens, corrections) best track real quality loss.

## Summary recommendation for a small local Python script (inferred from the above)
1. Unit = session; outcome = binary success (plus secondary metrics). Log covariates and a "regime" id (hash of CLI version, model id, effort, CLAUDE.md, MCP/skill set).
2. Score: rolling 7-day and 28-day adjusted success rate, shown with cluster-bootstrap 90% intervals; never a bare daily percentage.
3. Adjust: logistic regression with task type, context size, compaction, project fixed effects (or CUPED with baseline per-project rates), clustered SE by session; compare within regime when the user changed config.
4. Test: fixed windows (baseline vs last 7/28 days) with TOST/ROPE against a user-set SESOI (default 5 points); segmented regression at known event dates when ≥9-12 active days exist on each side; optional Beta-Bernoulli BOCPD for alerting.
5. Verdict: "no change" / "slightly worse" / "clearly worse" / "better" / "not enough data yet (need ~N more sessions)".
6. Control: weekly canary replay with paired analysis to separate model/harness change from user change.
