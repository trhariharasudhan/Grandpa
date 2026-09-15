# Migrating a handler to the action layer

Notes was the first domain moved off chat's keyword waterfall. This is the path
it took, written down so the remaining handlers follow the same one rather than
each inventing a variation.

The audit found six desktop-control stacks with four approval models
(`docs/audit/FEATURE-INVENTORY.md`, sections 4.1–4.2). The action layer replaces
them with one contract, one catalogue, one executor and one audit trail. A
migration does not rewrite a domain's code — it moves the *decisions* out of the
handler and leaves the implementation where it is.

## What moves, and what does not

| Stays where it is | Moves into the layer |
|---|---|
| The domain's implementation (`grandpa.notes`) | Risk rating |
| Its natural-language parser | Whether to ask for confirmation |
| Its result messages | Asking, and honouring the answer |
| Its storage and safety rules | The audit record |
| CLI subcommands for that domain | Dispatch |

A parser is a *front end*, not a handler. `NotesParser` still turns
"delete note shopping" into a structured `NotesAction`; what changed is that
nothing after the parser lives in `chat_cmd.py` any more.

## The six steps

### 1. Find the structured seam

Look for the function that takes a *structured* request rather than a string.
For notes that was `NotesAutomation.execute(action, confirmed=, confirm=)`; the
string-taking `handle_notes_command(text)` is the waterfall's entry point and is
the thing being replaced, so it is the wrong target.

If a domain has no structured seam, add the smallest one that exposes what is
already there. Do not move logic into the action layer to create one.

### 2. Catalogue every action the domain can perform

Not just the common ones. Notes catalogued all twelve actions
`NotesActionType` allows, because leaving four behind would mean two routes to
the same store — the exact condition the migration removes.

Each entry needs a name, a one-line description, a JSON schema, a risk tier, and
the dotted path to the implementation. Tiers mirror `pc_control`'s existing ones
rather than introducing a new scale:

- reading, listing, searching, creating → **LOW** (as `file_create` is)
- changing existing content → **MEDIUM** (as `file_rename` is)
- destroying something unrecoverable → **HIGH** (as `file_delete` is)

Confirmation then falls out of one rule — HIGH, or on
`pc_control.APPROVAL_REQUIRED_ACTIONS` — and must land exactly where the domain's
own policy already put it. For notes, `NotesSafetyPolicy.requires_confirmation`
returns true only for `delete`, and `notes_delete` is the only notes action the
catalogue marks confirmable. If those two disagree, the tier is wrong.

### 3. Declare the actions in `LAYER_OWNED`

`pc_control`'s risk tables are the authority for everything it dispatches, and
`tests/action_layer/test_catalogue_coverage.py` holds the catalogue to them. A
migrated domain has no entry there, so each action goes in `LAYER_OWNED` with the
reason it lives only in the layer. Two properties are preserved: nothing appears
in the catalogue silently, and an action in `LAYER_OWNED` may **not** also be in a
`pc_control` table, so the list cannot be used to dodge a risk disagreement.

Add the expected tier to `EXPECTED_LAYER_RISK` in the coverage test too. That is
a second, independent statement of intent — without it, "the catalogue agrees
with itself" is all the test proves.

### 4. Give the domain a calling convention

The executor has one adapter per argument shape, named in `Binding` and chosen
per entry in the `_CALLS` table. Notes needed a new one (`NOTES_ACTION`) because
its implementation takes a `NotesAction` rather than a request.

A new domain often needs a new shape. That is fine and expected: it is one
reviewable row in one table, not a branch buried in a dispatch chain. A missing
row is an import-time error.

**Confirmation must not happen twice.** The notes binding passes
`confirmed=True`, which is safe *only because* the catalogue rates
`notes_delete` HIGH, so the executor cannot reach the implementation without
consent. If a domain confirms internally, the migration must either pass consent
through like this or the domain will prompt for something the layer already
holds — and a prompt nobody reads is how the decorative-prompt bug happened in
the first place.

### 5. Route the chat phrase

Put the parse-and-map step in its own module (`grandpa.cli._notes_route`) so
`chat_cmd.py` gains three lines rather than thirty. The route returns
`(ActionRequest, parsed_action)` or `(None, None)`, and the branch becomes:

```python
request, parsed = build_notes_request(text)
if request is not None:
    result = execute_action(request, _confirm_action)
    ...  # print result, record the outcome, continue
```

Keep the user-visible wording byte-identical. A declined notes delete still says
`Note deletion cancelled.`, because that is what it said before and the e2e suite
pins it. **A migration the user can notice is a failed migration.**

Chat supplies one confirm callback for the whole layer (`_confirm_action`),
which turns `(action, parameters, risk)` into the sentence chat already used.
Later domains reuse it; they do not add their own prompt.

### 6. Remove only that branch

Delete the migrated domain's branch from the waterfall and nothing else. Leave
every other handler, including its imports — the notes branch happened to
contain the `format_operation_plan` import that the *downloads* branch uses, and
that import stays.

## How you know it worked

- **The domain's existing e2e tests pass unmodified.** This is the proof, and it
  only counts if you did not touch them. If a test needs changing, behaviour
  changed, and the migration is not behaviour-preserving.
- The domain's actions appear in `as_tool_definitions()`, so a model can now
  reach what only a keyword could reach before.
- Actions show up in the audit log with `source: "action_layer"` and the calling
  origin, which the waterfall never recorded.

## What notes cost

| | Before | After |
|---|---|---|
| Notes branch in `chat_cmd.py` | 35 lines | 18 lines |
| Mapping module (`_notes_route.py`) | — | 110 lines |
| Notes actions reachable by a model | 0 | 12 |
| Notes actions audited | 0 | 12 |

Total lines went *up*. That is expected for the first migration: the mapping
module is shared machinery the next domain reuses, and the 18 lines left in chat
carry no decisions. The measure that matters is how much of the waterfall is
left, not how many lines the diff removed.

## Order for the rest

Downloads next — it sits directly below notes in the same waterfall, has the same
`_ChatConfirmation` shape, and its e2e tests are already written. Then the
desktop and browser branches, which are the ones `pc_control` already rates, so
they need no new `LAYER_OWNED` entries.
