# Judge instructions

You label prompts that a developer typed to a coding agent. For each prompt, you decide
whether the developer had to steer the agent, and if so, whether the agent caused it.

## Input

The batch file is JSONL: one JSON object per line, one item per object. Each item has:

- `id`: the item id. Copy it unchanged.
- `prompt`: the developer's prompt. This is the text you label.
- `previous_agent_reply`: the last text the agent wrote before this prompt. It can be empty
  (the prompt opened the session) or cut at the start.
- `earlier_prompts`: earlier prompts from the same session, newest first. It can be empty.

Some text is replaced with `[x]`. Ignore it.

## Labels

- `kind`:
  - `steering`: the prompt changes, corrects, rejects, or reports a failure of what the
    agent just did.
  - `new_work`: the prompt asks for a new task or a next step, or answers a question or offer
    from the agent with a request for work. It does not ask to change what the agent just did.
  - `other`: anything else. Examples: "continue", "yes", "go ahead", "thanks, that works",
    a question about the agent's output that does not ask for a change, small talk.
- `steering_type` (only when `kind` is `steering`; else `null`):
  - `correction`: fix or adjust a part of what the agent did.
  - `rejection`: undo it, or say it is not wanted.
  - `failure_report`: say that it does not work (an error, a crash, wrong output).
  - `redirect`: do it a different way, or in a different place.
- `cause` (when `kind` is not `steering`, always `unclear`):
  - `model`: the developer had already stated the requirement (in `earlier_prompts`) and the
    agent went against it, or the agent made a clear error on a clear instruction.
  - `user`: new information, a scope change, or a preference change. The developer now wants
    something different from what they asked before.
  - `unclear`: otherwise. When you cannot decide between `model` and `user`, use `unclear`.

## Decision procedure

Follow these steps in order for each item. Words like "no", "revert", "undo", or "wrong" do
not decide the label alone. The steps decide it.

1. Does `previous_agent_reply` end with a question or an offer to the developer ("Should I
   ...?", "Do you want me to ...?"), and does the prompt answer it? An answer to the agent's
   own question or offer is never `steering`, also when it says "no" or picks another option.
   - It asks for work: `kind = new_work`. It only accepts, declines, or confirms: `kind = other`.
   - For both: `steering_type = null`, `cause = unclear`. Stop.
2. Does the prompt react to what the agent just did, and ask to change, fix, or undo it, or
   say it does not work?
   - No, and it asks for a new task or a general question: `kind = new_work`.
   - No, and it only confirms, continues, thanks, or asks about the output: `kind = other`.
   - For both: `steering_type = null`, `cause = unclear`. Stop.
3. Yes: `kind = steering`. Pick the `steering_type`.
4. Can you name the instruction that the agent broke? Either quote the requirement from
   `earlier_prompts` that the agent did not follow, or point to a clear instruction and a plain
   error in `previous_agent_reply` (the wrong file, code that cannot run, a claim that its own
   output disproves, a result that does the opposite of the request). If yes: `cause = model`.
   Stop. If you cannot name one, the cause is not `model`.
5. Does the developer give a new fact, a new scope, or a new preference that the earlier
   prompts did not give? This includes a taste change on agent work that no earlier prompt
   specified ("I don't like it", "make it smaller", "revert that"). If yes: `cause = user`.
   Stop.
6. Otherwise: `cause = unclear`. This includes a bug or wrong-output report when no earlier
   prompt stated the requirement and the error is not plain from `previous_agent_reply`. A
   failure report alone is not new information.

Edge cases:

- "continue", "yes", "ok", "go ahead", "do it": `other`.
- A question about the agent's output with no correction ("why did you use X?"): `other`.
- A prompt that praises the last result and then asks for an unrelated task: `new_work`.
- If the agent chose a reasonable option for a loose instruction and the developer now wants
  another option: `cause = user`.

## Output

Write the labels to the output path with the Write tool. Write one JSON object per line, one
line per item, in any order. Put nothing else in the file: no headings, no code fences, no
comments. Do not print the labels in your reply.

Each object has these keys, in this order:

```
{"id": "<same id as the item>", "reasoning": "<one or two short sentences>", "kind": "new_work | steering | other", "steering_type": "correction | rejection | failure_report | redirect | null", "cause": "model | user | unclear", "evidence": "<exact quote from the item>"}
```

- Write `reasoning` first. Reason first, then label. Keep it to 2 sentences or fewer.
- Start `reasoning` with the step that decided the label, for example "Step 5: ...".
- For `cause = model`, the `reasoning` must quote or point to the instruction the agent broke.
- `steering_type` is the JSON value `null` (no quotes) when `kind` is not `steering`.
- `evidence` must be an exact quote, copied character for character from the item text.
  Quote the `prompt` when you can. Quote `earlier_prompts` or `previous_agent_reply` only to
  show a requirement or an error. Never paraphrase, never fix typos. A label with evidence
  that is not in the item is thrown away.
- Label every item in the batch. Do not skip an item and do not add items.

## Worked examples

Example 1.
Item: `{"id": "e1", "prompt": "now add a logout button to the top bar", "previous_agent_reply": "I added the profile page at /profile with the avatar upload.", "earlier_prompts": ["make a profile page with avatar upload"]}`
Label: `{"id": "e1", "reasoning": "Step 2: The agent finished the profile page and the developer asks for a separate next feature.", "kind": "new_work", "steering_type": null, "cause": "unclear", "evidence": "now add a logout button to the top bar"}`

Example 2.
Item: `{"id": "e2", "prompt": "can you explain what a race condition in a go channel looks like", "previous_agent_reply": "", "earlier_prompts": []}`
Label: `{"id": "e2", "reasoning": "Step 2: This is a general question that opens the session; nothing reacts to agent output.", "kind": "new_work", "steering_type": null, "cause": "unclear", "evidence": "can you explain what a race condition in a go channel looks like"}`

Example 3.
Item: `{"id": "e3", "prompt": "i asked for snake_case. fix the names", "previous_agent_reply": "I added the helpers getUserName and formatPrice to helpers.py.", "earlier_prompts": ["add helpers for user names and prices", "all python names in snake_case please"]}`
Label: `{"id": "e3", "reasoning": "Step 4: The developer stated 'all python names in snake_case please' and the agent used camelCase.", "kind": "steering", "steering_type": "correction", "cause": "model", "evidence": "i asked for snake_case. fix the names"}`

Example 4.
Item: `{"id": "e4", "prompt": "the build fails, you import from lib/txt but the file is lib/text", "previous_agent_reply": "I added the import `from lib/txt import slugify` to the scheduler.", "earlier_prompts": ["use the slugify helper from lib/text in the scheduler"]}`
Label: `{"id": "e4", "reasoning": "Step 4: The instruction named lib/text and the agent imported a path that does not exist. That is a plain error on a clear instruction.", "kind": "steering", "steering_type": "failure_report", "cause": "model", "evidence": "the build fails, you import from lib/txt but the file is lib/text"}`

Example 5.
Item: `{"id": "e5", "prompt": "ok but put the limit at 20 per page, the designers want shorter lists", "previous_agent_reply": "I added pagination to the orders table with 50 rows per page.", "earlier_prompts": ["paginate the orders table"]}`
Label: `{"id": "e5", "reasoning": "Step 5: The developer never gave a page size, and now gives a new preference from the designers.", "kind": "steering", "steering_type": "correction", "cause": "user", "evidence": "put the limit at 20 per page, the designers want shorter lists"}`

Example 6.
Item: `{"id": "e6", "prompt": "looks good", "previous_agent_reply": "I moved the constants into config.py and updated the imports.", "earlier_prompts": ["move the constants into config.py"]}`
Label: `{"id": "e6", "reasoning": "Step 2: The developer only confirms the result.", "kind": "other", "steering_type": null, "cause": "unclear", "evidence": "looks good"}`

Example 7.
Item: `{"id": "e7", "prompt": "no posting, just update the wiki", "previous_agent_reply": "I drafted the release notes. Do you want me to post them in the team channel and update the wiki?", "earlier_prompts": ["draft release notes for the export flag"]}`
Label: `{"id": "e7", "reasoning": "Step 1: The agent made an offer and the developer answers it and picks part of it. An answer is not steering.", "kind": "new_work", "steering_type": null, "cause": "unclear", "evidence": "no posting, just update the wiki"}`

Example 8.
Item: `{"id": "e8", "prompt": "undo the shadow on the login card, i don't like it", "previous_agent_reply": "I restyled the login card with a soft drop shadow and rounder corners.", "earlier_prompts": ["make the login card look more modern"]}`
Label: `{"id": "e8", "reasoning": "Step 5: No earlier prompt asked for or against a shadow, so no broken instruction can be named. The developer states a taste change.", "kind": "steering", "steering_type": "rejection", "cause": "user", "evidence": "undo the shadow on the login card, i don't like it"}`
