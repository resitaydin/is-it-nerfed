# Changelog interpretation instructions

You read lines from the Claude Code changelog. For each line, you decide whether the change
can alter how the model behaves for a user.

## Input

The input file is JSONL: one JSON object per line, one item per object. Each item has:

- `id`: the item id. Copy it unchanged.
- `version`: the Claude Code version that made the change.
- `line`: the changelog line. This is the text you judge.

## The question

Can this change alter how the model reasons, plans, or edits code for a user?

- `yes`: the change touches the model's work. Examples: effort level, thinking or reasoning
  settings, the system prompt, compaction or summaries of the conversation, the default
  model, context window handling, what the model sees from files or tools.
- `no`: the change does not touch the model's work. Examples: bug fixes for the UI, the
  terminal, key bindings, auth or login, plugins, the marketplace, MCP connection setup,
  installers, telemetry, performance of the CLI itself, new commands that only show
  information.

When a line names both kinds of change, use `yes`. When you cannot tell, use `no`.

## Output

Write the results to the output path with the Write tool. Write one JSON object per line, one
line per item, in any order. Put nothing else in the file: no headings, no code fences, no
comments. Do not print the results in your reply.

Each object has these keys, in this order:

```
{"id": "<same id as the item>", "affects_behavior": "yes | no", "reason": "<one short sentence>"}
```

- `reason` is one sentence or less.
- Label every item in the file. Do not skip an item and do not add items.

## Examples

Item: `{"id": "c1", "version": "2.1.285", "line": "Changed the default effort level to medium for Opus"}`
Result: `{"id": "c1", "affects_behavior": "yes", "reason": "A lower default effort can change how much the model reasons."}`

Item: `{"id": "c2", "version": "2.1.286", "line": "Fixed a crash when resizing the terminal during login"}`
Result: `{"id": "c2", "affects_behavior": "no", "reason": "A terminal and login fix does not touch the model's work."}`

Item: `{"id": "c3", "version": "2.1.287", "line": "Auto-compact now keeps fewer earlier tool results"}`
Result: `{"id": "c3", "affects_behavior": "yes", "reason": "Compaction changes what context the model sees."}`
