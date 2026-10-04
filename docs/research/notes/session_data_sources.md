# Session data sources: Claude Code and Codex CLI local history, signals, and one-line-install packaging

Research date: 2026-10-03. Local machine: Claude Code 2.1.288 (`claude --version`). Codex CLI is not installed on this machine (`~/.codex/sessions` does not exist; `~/.codex` holds only `hooks.json`), so all Codex facts come from source code (openai/codex `main` at commit b741e480e2, 2026-10-03; latest release `rust-v0.160.0`, 2026-10-01) and third-party write-ups.

"Local inspection" below means: `jq` over 512 JSONL files under `~/.claude/projects` (83 project dirs) and `~/.claude-second/projects` (a second `CLAUDE_CONFIG_DIR`), structure and key names only. No message content was copied. Counts are line counts across those files. Versions seen in the sample: 2.1.260 to 2.1.288 (local, July to October 2026).

## 1. Claude Code: storage, schema, retention, and version recording

### Takeaway
Claude Code writes one append-only JSONL per session at `<config dir>/projects/<sanitized-cwd>/<sessionId>.jsonl`, plus `<sessionId>/subagents/agent-<id>.jsonl` (+ `.meta.json`) and `<sessionId>/tool-results/`. Every message line carries `version` (Claude Code CLI version), `timestamp`, `cwd`, `gitBranch`, `uuid`/`parentUuid`, `isSidechain`; every assistant line carries `message.model`, full `message.usage`, `stop_reason`, plus harness fields `effort`/`perTurnEffort`. That is enough to separate harness changes (by `version`) from model changes (by `message.model`) and to compute error, interrupt, retry, compaction, and token signals. Default retention is 30 days (`cleanupPeriodDays`), so history is shallow unless the user raises it.

### Cited Findings

Storage and retention
- Path is `~/.claude/projects/<project>/<session-id>.jsonl`; the project dir name replaces every non-alphanumeric char (incl. underscores) with `-`; adjacent folders `tool-results/`, `subagents/`, `file-history/`; format plaintext JSONL, unencrypted, "OS file permissions are the only protection" — [ghinda, "Where Six AI Coding CLIs Store Your Session Logs" (2026-08-06)](https://allaboutcoding.ghinda.com/where-ai-coding-clis-store-session-logs/)
- Confirmed locally: e.g. `~/.claude/projects/-Users-resit-Documents-RA-is-it-nerfed/<uuid>.jsonl`, `.../<uuid>/subagents/agent-<17 hex>.jsonl` and `agent-<id>.meta.json` with keys `agentType, description, requestNonInteractive, requestShape, spawnDepth, toolUseId` — local inspection (CC 2.1.288)
- `CLAUDE_CONFIG_DIR` relocates "settings, session history, and plugins" — [Claude Code docs: Settings](https://code.claude.com/docs/en/settings). Locally a second root `~/.claude-second/projects` exists, so an analyzer must scan every config dir, not only `~/.claude`.
- `cleanupPeriodDays`: default `30` days; scope any settings file; deletes session transcripts in the Claude directory — [Claude Code docs: Settings reference](https://code.claude.com/docs/en/settings-reference). Conflict on the minimum: the docs page states minimum `0` and that `0` deletes transcripts right after each session; [ghinda (2026-08-06)](https://allaboutcoding.ghinda.com/where-ai-coding-clis-store-session-logs/) states minimum 1 day. Treat the official page as current.
- Related: `desktopSessionCleanupPeriodDays` (Desktop/Cowork transcripts, default unset) — [Settings reference](https://code.claude.com/docs/en/settings-reference). `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1` disables transcript writing; `claude project purge --dry-run` exists since v2.1.124 — [ghinda](https://allaboutcoding.ghinda.com/where-ai-coding-clis-store-session-logs/) (not verified on the official page).
- `claude -p --resume` accepts the absolute path to a session `.jsonl` transcript file — [Claude Code docs: headless](https://code.claude.com/docs/en/headless)
- Other local files (CC 2.1.288): `~/.claude/history.jsonl` (keys `display, pastedContents, project, sessionId, timestamp` — typed prompts only); `~/.claude/stats-cache.json` (keys `dailyActivity, dailyModelTokens, dailyModelTokensVersion, firstSessionDate, hourCounts, lastComputedDate, longestSession, modelUsage, totalMessages, totalSessions, version`); `~/.claude/file-history/` — local inspection.

Line types (top-level `type`), counts from local sample (CC 2.1.260–2.1.288)
- `attachment` 194k, `assistant` 67k, `user` 42k, `last-prompt` 13k, `mode` 13k, `atis-latch` 13k, `ai-title` 13k, `permission-mode` 12k, `system` 4.9k, `pr-link` 4.9k, `queue-operation` 2.8k, `file-history-snapshot` 2.2k, `frame-link` 2k, `file-history-delta` 509, `cost-state` 188, plus rare `artifact-*`, `fork-context-ref` — local inspection. Note: no `summary` line type appears in this version range; titles now come from `ai-title` (`aiTitle`) and compaction from `system/compact_boundary` (below). Older blog posts describing `type:"summary"` lines refer to older versions (gap: exact version of the change not found).

Common envelope on user/assistant/system/attachment lines (CC 2.1.288)
- `uuid, parentUuid, sessionId, timestamp, type, cwd, gitBranch, version, entrypoint, userType, isSidechain`; some lines also `session_id`, `slug`, `isMeta`, `promptId` — local inspection. `version` is the Claude Code CLI version string (e.g. `2.1.263`); it is present on every message line, so harness version is recorded per message.
- Subagent transcripts add `agentId` (and `slug`) and have `isSidechain: true` (103k sidechain lines vs 206k main) — local inspection.

Assistant lines
- Envelope extras: `requestId, effort, perTurnEffort, advisorModel, apiBlockIndex, attributionSkill, serverClassifierRequest, wireToolInputs`, sometimes `thinkingDurationMs` — local inspection (2.1.288). `effort` values seen: `low`, `medium`, `high` (null on 88 lines).
- `message` keys: `id, model, role, type, content, stop_reason, stop_sequence, stop_details, usage, diagnostics`, sometimes `container, context_management, input_transformations` — local inspection.
- `message.model` values seen: `claude-opus-5`, `claude-opus-5-5`, `claude-fable-5-1`, `claude-sonnet-5`, `claude-sonnet-5-5`, and `<synthetic>` (103 lines; harness-generated messages such as API-error placeholders, must be excluded from model stats) — local inspection.
- `message.usage` keys: `input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens, cache_creation{ephemeral_5m_input_tokens, ephemeral_1h_input_tokens}, service_tier, inference_geo`, and on newer lines `iterations, output_tokens_details, server_tool_use, speed`, sometimes `fallback_credit` — local inspection.
- `stop_reason` counts: `tool_use` 47k, `null` 15.7k, `end_turn` 3.7k, `stop_sequence` 103 — local inspection. One API response is split into several JSONL lines (one per content block, same `message.id`/`requestId`), so `null` stop_reason lines are partial blocks; dedupe by `message.id` before summing usage (inference from `apiBlockIndex` field and counts; ccusage also dedupes, see section 3).
- Content block types: `tool_use` 37.9k, `tool_result` 37.9k, `thinking` 20.1k, `text` 8.9k, `image` 28 — local inspection.

User lines / tool results / interrupts
- Tool results are `user` lines whose `message.content[]` has `{type:"tool_result", tool_use_id, content, is_error}`; `is_error` true 1,128, false 28,354, absent 8,411 — local inspection. Envelope adds `toolUseResult` (structured result) and `sourceToolAssistantUUID`.
- `toolUseResult` for Bash: `stdout, stderr, interrupted, isImage, noOutputExpected`, sometimes `returnCodeInterpretation`, `backgroundTaskId`, `gitOperation`. No numeric exit code field; a failed command shows as `is_error: true` with "Exit code N" in content text (inference from field list; text not copied). Edit/Write: `filePath, oldString, newString, originalFile, structuredPatch, userModified, replaceAll`. Agent: `agentId, status, resolvedModel, isAsync, ...` — local inspection.
- Interrupt markers in user text: `[Request interrupted by user]` (46) and `[Request interrupted by user for tool use]` (22) — local inspection.
- `userModified` on Edit results and `edited_text_file` attachments indicate the user changed Claude's edit — local inspection (signal for "user had to fix it").

System lines (subtypes): `turn_duration` 2.4k (keys `durationMs, messageCount, pendingBackgroundAgentCount`), `stop_hook_summary` 2.3k, `compact_boundary` 116 (`compactMetadata{trigger, preTokens, postTokens, durationMs, cumulativeDroppedTokens, preservedMessages, preservedSegment, preCompactDiscoveredTools}`, plus `logicalParentUuid`), `informational`, `local_command`, `away_summary`; `api_error` lines carry `apiErrorStatus, error, isApiErrorMessage, quotaLimits, requestId` — local inspection. The compaction summary itself is a `user` line with `isCompactSummary: true`.

Detecting CLAUDE.md / settings / model-identity changes
- `attachment.type == "instructions"` carries `files[]{path, type, content}` — the loaded instruction files (CLAUDE.md etc.) with full content, so a hash per session detects CLAUDE.md changes — local inspection (2.1.288).
- `attachment.type == "model"` carries `identity{modelId, marketingName, knowledgeCutoff}`; `environment` carries `snapshot{platform, osVersion, shell, isGitRepo, isWorktree, workingDirectory, ...}`; `output_style`, `skill_listing`, `deferred_tools_record`, `mcp_instructions_delta`, `hook_success`, `auto_mode` also appear — local inspection. Settings files themselves are not snapshotted in the transcript (only their effects: `permission-mode`, `mode`, `effort`, hooks); settings drift must be read from `settings.json` directly (gap: no official doc found).

### Inferences
- Model-vs-harness separation is possible per message: group by (`message.model`, `version`, `effort`). A metric change that coincides with a `version` bump and no `model` change points to the harness; the reverse points to the model or serving.
- Strong cheap signals (no LLM needed): tool error rate (`is_error`), interrupt rate (marker strings), user-fix rate (`userModified`, `edited_text_file`), API error rate and status (`isApiErrorMessage`, `apiErrorStatus`), compaction frequency and `preTokens`, turn duration (`turn_duration.durationMs`), output tokens per turn, thinking share and `thinkingDurationMs`, cache-read ratio, `<synthetic>` count, `service_tier`/`speed`/`inference_geo` (serving-path changes).
- 30-day default retention limits any baseline. The installer should tell users to raise `cleanupPeriodDays` (e.g. 365) on day one, or the analyzer should keep its own compact derived store.
- Schema is undocumented and changes often (many fields are newer than 2.1.26x). The parser must be tolerant: ignore unknown types, branch on presence, never on version.

### Gaps
- No official Anthropic schema document for the transcript JSONL was found; all field facts come from local inspection of 2.1.260–2.1.288.
- Exact version where `summary` lines were replaced by `ai-title`/`compact_boundary` not found.
- Whether `claude -p` sessions write transcripts by default, and a `--no-session-persistence` flag, could not be confirmed from the headless page fetched.

## 2. Codex CLI: storage, schema, model, effort, tool calls, exit codes

### Takeaway
Codex writes `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl` (default `CODEX_HOME=~/.codex`), with no automatic age-based deletion. Each line is `{timestamp, type, payload}` with `type` in `session_meta | response_item | turn_context | event_msg | compacted | token_usage_record | ...`. `session_meta` has `cli_version` and `model_provider`; `turn_context` has `model` and `effort` per turn; `event_msg/token_count` gives token usage and rate limits. In current source, `exec_command_end` (which carries `exit_code`) is NOT persisted; exit status must come from `function_call_output` text or, in the newer paginated mode, `item_completed` command items.

### Cited Findings
- Path `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<timestamp>-<uuid>.jsonl`; line 1 is `session_meta`; then mixed `event_msg`, `response_item`, `turn_context`, `compacted` — [agent-ouija rollout package docs](https://pkg.go.dev/github.com/kylesnowschwartz/agent-ouija/codex/rollout); [ghinda (2026-08-06)](https://allaboutcoding.ghinda.com/where-ai-coding-clis-store-session-logs/)
- `~/.codex/history.jsonl` holds only typed text `{session_id, ts, text}`; `[history] persistence = "none"` affects only that file, not rollouts; no automatic age-based deletion; `archive`/`unarchive`/`delete` subcommands since v0.136 — [ghinda](https://allaboutcoding.ghinda.com/where-ai-coding-clis-store-session-logs/)
- `session_meta.source` is `"cli"`, `"exec"`, `"vscode"`, `"mcp"` or an object for derived (sub-agent) sessions; event_msg types include `task_complete, turn_aborted, user_message, agent_message, error`; tolerant decoding recommended — [agent-ouija](https://pkg.go.dev/github.com/kylesnowschwartz/agent-ouija/codex/rollout)
- Real files (v0.130.0) differ from what `protocol.rs` suggests; tool calls and results are flat `function_call {name, arguments, call_id}` / `function_call_output {call_id, output}` linked by `call_id` — [MilkoorY, DEV (2026-05-14)](https://dev.to/milkoor/reverse-engineering-codex-cli-rollout-traces-3b9b)
- `RolloutItem` variants (wire tag `type`, snake_case): `session_meta, response_item, inter_agent_communication, inter_agent_communication_metadata, compacted, turn_context, token_usage_record, world_state, retained_context, security_risk_score, event_msg, realtime_item` — [openai/codex codex-rs/history/src/lib.rs, rollout_payload.rs @main 2026-10-03](https://github.com/openai/codex/blob/main/codex-rs/history/src/lib.rs)
- `SessionMeta` fields include `id, session_id, forked_from_id, parent_thread_id, timestamp, cwd, originator, cli_version, source, thread_source, agent_nickname, agent_role, agent_path, model_provider, base_instructions, dynamic_tools, memory_mode, history_mode` — [codex-rs/protocol/src/protocol.rs @main](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs)
- `TurnContextItem` fields include `turn_id, cwd, current_date, timezone, approval_policy, approvals_reviewer, sandbox_policy, permission_profile, model, comp_hash, personality, collaboration_mode, multi_agent_mode, effort` (plus `summary` in older versions per community parsers) — [protocol.rs @main](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs)
- `TokenUsage {input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens, reasoning_output_tokens, total_tokens}`; `TokenUsageInfo {total_token_usage, last_token_usage, model_context_window}`; `TokenUsageRecord {thread_id, turn_id, session_id, response_id, usage, turn_token_usage, thread_token_usage}`; `RateLimitSnapshot {primary, secondary, credits, plan_type, rate_limit_reached_type, ...}` — [protocol.rs @main](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs)
- `ExecCommandEndEvent {call_id, turn_id, command, cwd, parsed_cmd, aggregated_output, exit_code, duration, status, ...}`; `TurnAbortedEvent {turn_id, reason, duration_ms, ...}` with `TurnAbortReason` = `interrupted | replaced | review_ended | budget_limited ...` — [protocol.rs @main](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs)
- Persistence policy: always persisted event_msgs are `token_count, thread_goal_updated, thread_rolled_back, turn_aborted, turn_started, turn_complete, thread_settings_applied`; `user_message, agent_message, agent_reasoning, patch_apply_end, context_compacted, mcp_tool_call_end, web_search_end` only in Legacy history mode; `exec_command_end`, `error`, `stream_error`, `model_reroute`, `model_verification`, `warning` are NOT persisted. Persisted response_items: `message, agent_message, reasoning, local_shell_call, function_call, function_call_output, custom_tool_call, custom_tool_call_output, web_search_call, compaction, context_compaction, ...`. Paginated mode persists `item_completed` with `CommandExecution` items (output truncated at 64 KiB) — [codex-rs/rollout/src/policy.rs @main](https://github.com/openai/codex/blob/main/codex-rs/rollout/src/policy.rs)
- Legacy rollouts persisted `ExecCommandEnd`, `PatchApplyEnd`, `McpToolCallEnd`; paginated history persists `ItemCompleted(TurnItem)` instead (migration code exists) — [codex-rs/thread-store/src/local/rollout_migration/legacy_event.rs](https://github.com/openai/codex/blob/main/codex-rs/thread-store/src/local/rollout_migration/legacy_event.rs)

### Inferences
- Codex per-turn `turn_context.model` + `effort` + `session_meta.cli_version` allow the same model-vs-harness split as Claude Code.
- `model_reroute` (server rerouted the model) is not persisted, so a silent server-side swap cannot be seen from rollouts; only the requested `model` is recorded. The same caveat applies to Claude Code: `message.model` is what the API returned, not proof of weights.
- The Codex format has at least two generations (Legacy vs Paginated, plus pre-0.130 shapes). A parser needs per-type tolerant handlers and tests on real files from several versions.

### Gaps
- No real Codex rollout files were available on this machine to confirm field names; all Codex facts are from source and third parties.
- The exact text format of exit codes inside `function_call_output.output` for current versions was not confirmed.

## 3. Existing open-source parsers and analyzers

### Takeaway
Cost/token tools (ccusage) and viewers (claude-code-log, sniffly) exist and already parse both formats, but none targets model-quality drift. Anthropic's built-in `/insights` produces a local 30-day HTML workflow report. Reuse is best at the parsing layer (ccusage's multi-CLI loaders, `--json`), not the analysis layer.

### Cited Findings
- ccusage: daily/weekly/monthly/session reports, 5-hour billing blocks, per-model `--breakdown`, USD cost; reads Claude Code and Codex (`@ccusage/codex`) plus many other CLIs; TypeScript/Node with Rust parts; MIT; `--json` output; CLI-focused, no explicit library API — [ryoppippi/ccusage](https://github.com/ryoppippi/ccusage)
- sniffly: Claude Code only; usage patterns, "error breakdown", message history; Python 3.10+; `uvx sniffly@latest init`; local dashboard on `localhost:8081`; MIT — [chiphuyen/sniffly](https://github.com/chiphuyen/sniffly)
- claude-code-log: converts transcripts to HTML/Markdown, per-message and per-session token usage, thinking, tool use/results, session summaries, TUI; `uv tool install claude-code-log`; MIT — [daaain/claude-code-log](https://github.com/daaain/claude-code-log)
- `/insights`: built-in command; analyzes the last 30 days of local sessions; writes `~/.claude/usage-data/report.html`; covers usage patterns, friction points, context usage, suggests CLAUDE.md lines/skills; analysis stays local per the source — [MindStudio blog](https://www.mindstudio.ai/blog/claude-code-insights-command-workflow-audit) (secondary source; no official doc page fetched)
- Other community Codex parsers: agent-ouija (Go) — [pkg.go.dev](https://pkg.go.dev/github.com/kylesnowschwartz/agent-ouija/codex/rollout); vibe-replay schema-watch issue on `token_usage_record` — [tuo-lei/vibe-replay#578](https://github.com/tuo-lei/vibe-replay/issues/578)

### Inferences
- None of these tools splits metrics by (`model`, CLI `version`, `effort`) over time or flags regressions; that is the open gap.
- `/insights` and `stats-cache.json` show Anthropic already computes local aggregates; our product must exceed them with a cross-user baseline ("the central brain"), not repeat them.
- ccusage's MIT license allows reuse of its loaders; a Python analyzer may be simpler to ship inside a skill (no npm build), but must reimplement dedupe by `message.id`/`requestId`.

### Gaps
- The precise metric list of sniffly and `/insights` (e.g. whether they compute interrupt rate) was not available from the fetched pages.

## 4. Packaging for one-line install (Claude Code and Codex) and headless LLM judging

### Takeaway
Claude Code: ship a GitHub repo with `.claude-plugin/marketplace.json`; users run `claude plugin marketplace add owner/repo` then `claude plugin install <name>@<marketplace>` (or `/plugin ...` in-session). Skills can bundle and run Python/Node scripts via `${CLAUDE_SKILL_DIR}` / `${CLAUDE_PLUGIN_ROOT}`. Codex: skills use the same `SKILL.md` format (Agent Skills standard) under `.agents/skills`; plugins install with `codex plugin marketplace add owner/repo`. One repo can serve both.

### Cited Findings
- A marketplace is a repo with `.claude-plugin/marketplace.json` (`name`, `owner`, `plugins[]{name, source, description}`); sources: relative path, `github`, `git-subdir`, `url`, `archive`, `npm`, `command`; install: `claude plugin marketplace add <owner>/<repo>` then `claude plugin install <plugin>@<marketplace>`; in-session `/plugin marketplace add`, `/plugin install`; `claude plugin validate` checks it — [Claude Code docs: Create a marketplace](https://code.claude.com/docs/en/plugin-marketplaces)
- Skills locations: `~/.claude/skills/<name>/SKILL.md`, `.claude/skills/`, `<plugin>/skills/`; skills can bundle scripts in any language run via `python3 ${CLAUDE_SKILL_DIR}/scripts/x.py`; `allowed-tools: Bash(python3 *)` pre-approves; substitutions `${CLAUDE_SESSION_ID}`, `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}` (persistent plugin data dir); `` !`cmd` `` injects command output; `context: fork` runs in a subagent; Claude Code follows the Agent Skills open standard (agentskills.io) with portable fields `name, description, license, compatibility, metadata, allowed-tools` — [Claude Code docs: Skills](https://code.claude.com/docs/en/skills)
- Synced claude.ai skills do not run `` !`cmd` `` injection on the local machine (v2.1.228+) — [Skills docs](https://code.claude.com/docs/en/skills)
- Codex skills: `SKILL.md` plus optional `scripts/`; read from `$CWD/.agents/skills`, `$REPO_ROOT/.agents/skills`, `$HOME/.agents/skills`, `/etc/codex/skills`; `$skill-installer <name>` installs curated skills from openai/skills — [OpenAI: Build skills](https://learn.chatgpt.com/docs/build-skills)
- Codex plugins: `plugin.json` at root (legacy `.codex-plugin/plugin.json`); `codex plugin marketplace add owner/repo`; marketplace files `.agents/plugins/marketplace.json` or `~/.agents/plugins/marketplace.json`; plugins bundle `skills/`, `hooks/hooks.json` (`${PLUGIN_ROOT}`), `mcp.json` — [OpenAI: Build plugins](https://developers.openai.com/plugins/build/plugins)
- Headless judging: `claude -p` with `--output-format json` returns `total_cost_usd` and per-model cost (client-side estimates); `--json-schema` for structured output; `--bare` skips hooks/skills/plugins/CLAUDE.md and does NOT use subscription login (needs `ANTHROPIC_API_KEY`); without `--bare`, `-p` loads the full user context incl. hooks — [Claude Code docs: headless](https://code.claude.com/docs/en/headless)

### Inferences
- Simplest cross-tool package: one GitHub repo containing a Claude marketplace manifest, a Codex `plugin.json`, and one shared `skills/is-it-nerfed/SKILL.md` + `scripts/analyze.py` (stdlib only, no install step).
- For LLM judging, running inside the user's live session (the skill asks the current agent to judge a small sample) uses their subscription and needs no key; `claude -p` without `--bare` also uses the subscription but loads hooks and CLAUDE.md, which adds noise and cost; `--bare` needs an API key. Deterministic metrics should do most of the work; the LLM should judge only a small sampled set to keep cost per run near zero.
- Judge runs themselves write new transcripts into `~/.claude/projects`, which would pollute the dataset; the analyzer must tag and exclude its own sessions (e.g. by `entrypoint`, cwd, or a marker prompt).

### Gaps
- Exact `entrypoint` values for `-p` vs interactive sessions were not confirmed (field exists in every line).
- Whether Codex `$skill-installer` accepts arbitrary GitHub URLs (not only openai/skills) was not confirmed.

## 5. Privacy

### Takeaway
All needed data is local, plaintext, and highly sensitive (full prompts, file contents, tool output, CLAUDE.md, emails, git status). An analyzer must compute metrics locally and send only aggregates, if anything.

### Cited Findings
- Transcripts are unencrypted; only OS file permissions protect them — [ghinda](https://allaboutcoding.ghinda.com/where-ai-coding-clis-store-session-logs/)
- Transcripts include `session_context.context{gitStatus, userEmail}`, `environment.snapshot{workingDirectory, osVersion, ...}`, `instructions.files[].content` (full CLAUDE.md text), Edit `originalFile`/`oldString`/`newString`, and Bash `stdout/stderr` — local inspection (CC 2.1.288)
- `/insights` runs locally and sends nothing to Anthropic per secondary sources — [MindStudio](https://www.mindstudio.ai/blog/claude-code-insights-command-workflow-audit)

### Inferences
- A cross-user "central brain" baseline requires opt-in upload of numeric aggregates keyed by (`model`, CLI `version`, `effort`, date), never text. Project paths and emails must be hashed or dropped.
- LLM judging of transcripts sends content to the model provider again (same provider the user already uses); state this plainly and keep it opt-in.

### Gaps
- No official Anthropic or OpenAI statement found on third-party tools reading local transcripts (terms-of-use angle).
