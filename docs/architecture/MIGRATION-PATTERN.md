# Migrating a handler to the action layer

Nine domains have now been moved off chat's keyword waterfall — notes,
downloads, memory, one-shot reminders, routines, web search, the clock,
calendar and mail. This is the path they took,
rewritten after the fact so it describes what actually recurred rather than what
seemed likely after the first one.

The audit found six desktop-control stacks with four approval models
(`docs/audit/FEATURE-INVENTORY.md`, sections 4.1–4.2). The action layer replaces
them with one contract, one catalogue, one executor and one audit trail. A
migration does not rewrite a domain's code — it moves the *decisions* out of the
handler and leaves the implementation where it is.

## What moves, and what does not

| Stays where it is | Moves into the layer |
|---|---|
| The domain's implementation | Risk rating |
| Its natural-language parser | Whether to ask for confirmation |
| Its result messages | Asking, and honouring the answer |
| Its storage and safety rules | The audit record |
| CLI subcommands for that domain | Dispatch |

A parser is a *front end*, not a handler. What changed is that nothing after the
parser lives in `chat_cmd.py` any more.

## The six steps

### 1. Find — or build — the structured seam

Look for the function that takes a *structured* request rather than a string.

**This is where the domains differed most, and it is the step to budget for.**

| Domain | Seam | Work needed |
|---|---|---|
| notes | `NotesAutomation.execute(action, ...)` | none, it was there |
| downloads | `DownloadsAutomation.execute(action, ...)` | none |
| web search | `WebSearchAutomation.execute(action)` | none |
| calendar | `CalendarAutomation.execute(action, ...)` | none |
| mail | `GmailAutomation.execute(action, ...)` | none |
| memory | — | split `handle_memory_command` into `parse_memory_command` + `execute_memory_action` |
| routines | — | same split on `handle_scheduler_command` |
| the clock | — | same split on `handle_datetime_intent` |
| reminders | — | three private helpers **inside `chat_cmd.py`** moved into `reminders.py` |

Five of nine had a seam. Four did not, and one of those kept its operations in
the CLI module rather than the domain at all.

The split is mechanical when it works, and it works when **every branch of the
parser decides from the text alone**. Check that first: if a branch consults the
store before deciding, parse and execute are genuinely entangled and the split
is a design change, not an extraction. Memory's, the scheduler's and the clock's
chains were all pure, so the regexes lifted out whole every time.

Do not move logic into the action layer to create a seam. Extract it into the
domain.

### 2. Catalogue every action the seam can produce, and count the tokens

**A tool definition is not free.** The catalogue is served in two tiers (see
`tool_schema.py`): twenty core actions always sent, everything else grouped by
domain and fetched with `load_tools`. Adding a domain adds to the *deferred*
tier, which costs nothing until a model asks for it — but adding to `CORE`
costs prompt tokens on every cold start, so that list is budgeted at twenty and
changing it is a decision, not a detail.

Prefer one action with a parameter over several near-identical ones. The clock
is one `datetime_now(kind)` rather than five actions, because "what year is it"
is a parameter and not a capability.

**A domain half in CORE is the worst place to be.** Measured on
grandpa-brain, not assumed: given a goal needing a deferred action, the model
called `load_tools` every time the subject was *wholly* absent from the core
list (downloads, calendar, mail) and never once when part of it was already
there. Asked to pin a note, with `notes_create`, `notes_list`, `notes_read` and
`notes_search` in front of it, it answered "I cannot directly pin a note to the
top" -- and with the whole catalogue sent it calls `notes_pin` immediately.
Seeing four notes tools reads as having all the notes tools. Ten of the twenty
domains are split this way, covering 51 deferred actions.

Two prompt fixes were tried against this and neither moved it, so they were
reverted rather than shipped as unmeasured tokens. Naming whole domains in
CORE would fix it and costs 5,233 tokens against 1,665 -- three times the cold
start to recover half the saving. It is an open trade-off, recorded here rather
than decided: **if you add a partial domain to CORE, you are making its other
actions harder for the model to find, not easier.**


Otherwise, catalogue the whole vocabulary, not just the common parts. Notes
catalogued all twelve `NotesActionType` allows; downloads all fourteen. Leaving some behind means two routes to the same store,
which is the condition the migration removes.

Catalogue actions that are **currently broken**, too, as long as you say so.
`downloads_latest` answers "That Downloads action is not supported yet." — the
parser produces it and `_execute` has no branch for it. Cataloguing it preserves
the honest refusal; dropping it would have sent the phrase to the LLM to guess
at.

Tiers mirror `pc_control`'s existing ones rather than introducing a new scale:

- reading, listing, searching, creating → **LOW** (as `file_create` is)
- changing existing content → **MEDIUM** (as `file_rename` is)
- destroying something unrecoverable → **HIGH** (as `file_delete` is)

### 3. Decide who asks — there are three answers, not two

This is the correction the first version of this document most needed.

| Mode | Meaning | Example |
|---|---|---|
| `NONE` | nothing to ask | every read |
| `LAYER` | the executor asks first, from the parameters alone | `notes_delete` |
| `DOMAIN` | the domain asks, through the layer's callback | `downloads_delete` |

`DOMAIN` exists because downloads' prompt is *"Archive 1 download (6 B)?"* — a
sentence that does not exist until the folder has been scanned — and because
whether it asks at all depends on the count: a one-file move is silent, a
two-file move asks. The layer knows neither before calling.

**Use `LAYER` when the parameters fully describe what will happen. Use `DOMAIN`
when the domain must look before it can say.** `DOMAIN` is not a loophole: with
no callback to hand over, the executor still refuses *before* calling, and a
test should assert that the file is still on disk afterwards.

Whichever mode, the callback is the layer's one callback, so the wording and the
audit record do not change. A `DOMAIN` action passes its sentence back through
a `_plan` key that chat renders verbatim.

Confirmation must land where the domain's own policy already put it. For notes
that is `NotesSafetyPolicy.requires_confirmation` (delete only); for downloads
`DownloadsSafetyPolicy` (delete, organize, archive, and multi-file move). If
they disagree, the tier is wrong.

### 4. Declare the actions, and their tiers, twice

`pc_control`'s risk tables are the authority for everything it dispatches, and
`tests/action_layer/test_catalogue_coverage.py` holds the catalogue to them. A
migrated domain has no entry there, so each action goes in `LAYER_OWNED` with
the reason, **and** in `EXPECTED_LAYER_RISK` in the coverage test with its tier
and confirmation mode.

The second table is the point. Without it, "the catalogue does not contradict
itself" is all the test proves, and one careless edit changes both the claim and
the check together.

### 5. Give the domain a calling convention

The executor has one adapter per argument shape, named in `Binding` and chosen
per entry in the `_CALLS` table. There are now seventeen shapes. A new domain
usually needs one, and that is fine: it is a single reviewable row in one table,
not a branch buried in a dispatch chain. A missing row is an import-time error.

Domains with a module-level dispatcher (memory, reminders, routines) share one
shape; domains with a service class need their own.

**Pass consent through, do not re-ask.** Notes takes `confirmed=`, which the
executor sets from the answer it already has. Drop that and notes answers
"needs_confirmation" and the note survives an approved delete — the decorative
prompt, reborn.

**Check what the implementation returns.** `_as_result` reads results by
attribute, and it grew a case for a plain string only when the clock became the
first domain to return one — until then its answer was being reported as
`execution_failed` and thrown away. If a domain returns something new, the
wrapper needs to know.

### 6. Route the chat phrase and remove only that branch

Put the parse-and-map step in its own module (`cli/_notes_route.py` and friends)
so `chat_cmd.py` gains three lines rather than thirty:

```python
request, parsed = build_notes_request(text)
if request is not None:
    result = execute_action(request, _confirm_action)
    ...  # print result, record the outcome, continue
```

Keep the user-visible wording byte-identical. **A migration the user can notice
is a failed migration** — with the one exception in step 7.

Delete the migrated branch and nothing else. Leave every other handler,
including its imports: the notes branch happened to contain the
`format_operation_plan` import that the *downloads* branch used.

Also delete what the migration orphans. `_ChatConfirmation` went when notes and
downloads — its only two users — were both migrated.

## 7. When behaviour has to change, change it loudly

One exception earned itself. `memory_clear` erases everything irreversibly, and
chat did it without a word. It is rated HIGH, so it now asks.

The reasoning to reuse: **the tier is a statement of fact about the action.**
Rating an irreversible total wipe as LOW in order to preserve a missing prompt
would put a falsehood in the catalogue, where every future caller would read it.
Change the behaviour, say so in the commit, and add the test.

Everything else stayed identical, including the things that are wrong:
"remind me to X at 5pm" still becomes a *daily* reminder, and reminders still
live in two databases. Both are catalogued as they behave, with tests pinning
them, because a migration that quietly fixes bugs makes the fix invisible and
the regression unattributable.

## How you know it worked

- **The domain's existing e2e tests pass unmodified.** This is the proof, and it
  only counts if you did not touch them.
- The domain's actions appear in `as_tool_definitions()`, so a model can reach
  what only a keyword could reach before.
- Actions show up in the audit log with `source: "action_layer"` and the calling
  origin, which the waterfall never recorded.

## What five migrations cost

| | Before notes | After nine |
|---|---|---|
| `chat_cmd.py` | 2247 lines | 2196 lines |
| Waterfall branches migrated | 0 | 10 |
| `should_fallback` left in the REPL waterfall | 10 | 5 |
| Catalogued actions | 57 | 139 |
| Tool tokens on a cold start | 9,372 | 1,665 |

Line count barely moved, and that is the honest result: the route modules are
about as long as the branches they replaced. The measure that matters is that
six branches of decision-making became five parse-and-delegate blocks, and that
51 new actions became reachable by something other than a keyword.

## Things that surprised us

- **Migrating a domain finds its other callers.** Moving reminders' helper out
  of `chat_cmd.py` broke `grandpa/voice/assistant.py`, which had been importing
  a *private chat function*. That was a fourth route into reminders, and nothing
  short of moving the code would have surfaced it.
- **Splitting parse from execute exposes dead branches.** `continue my <topic>
  project` can never match its regex: an earlier branch claims anything
  containing "project" and "my". Found, recorded in a test, left alone.
- **Domains are not the same size.** Notes was twelve actions and one afternoon.
  Reminders was two domains, two stores, two waterfall branches and a seam that
  had to be evicted from the CLI.

## What is left, and which parts look hard

Remaining waterfall branches, in the order they are tried:

| Branch | Difficulty | Why |
|---|---|---|
| file_action | **blocked on a decision** | `grandpa.files` reimplements create / rename / copy / move / delete, which the catalogue already has pointing at `desktop.control.files`. Migrating it now would put two routes to the same operation in the catalogue — the exact thing this removes. Decide which implementation owns file operations first; that is a design task, not a migration |
| browser_awareness / browser_action | **hard** | the browser confirmation tier added in Wave 2 is a second approval mechanism. `Confirmation.DOMAIN` now exists and is probably the answer, but reconciling them is the work, not moving the branch |
| desktop_action | **hard** | this is `pc_control` itself, already catalogued from the other side. The migration is deleting a path, not adding one, and it is where the stacks finally collapse |
| local_action | **hard** | `local_actions.py` is the legacy facade with ~46 branches; last, and in pieces |

The easy ones are done. What is left is the three genuinely hard branches plus
one blocked on an ownership decision. Browser is the one to plan first: it has
the only other approval mechanism in the codebase, and `Confirmation.DOMAIN`
exists now precisely because a domain sometimes has to do the asking.

Note also the three `should_fallback` sites in `_handle_natural_assistant_intent`.
That is a *second* dispatch chain, used by voice, not the chat REPL. It will
need the same treatment and has not been counted as part of the waterfall.
