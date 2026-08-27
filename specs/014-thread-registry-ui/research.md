# Research: Thread Registry Surface (014, CG#337)

**Date**: 2026-08-25 · **Spec**: [spec.md](./spec.md) · **Branch**: `feat/337-thread-registry-ui`

Codebase survey behind the plan. Every finding below was read out of the tree
at `27204e7`, not inferred. Extend this file rather than re-deriving it.

---

## D1 — The dead-end is real and has exactly three links

Traced end to end:

1. `frontend/src/views/grounding/ProjectionSections.vue` renders one row per
   section from `GET /api/projections/sections`, with a checkbox and a
   "Rebuild selected section(s)" button. The row shows `state` and an
   **input count** (`{{ s.inputs.length }} file(s)`) — never the input paths.
2. `server/routers/projections.py::get_sections` shells out to
   `grounding_sections list --doc <doc> --json` and returns the payload
   verbatim; `::run_build` shells out to `grounding_sections build`.
3. `pipelines/grounding/grounding_sections.py`'s `SPECS["planning"]` declares
   `Section("threads", "threads")` — **not** `optional=True`. `assemble()`
   computes `safe_to_omit = sec.optional or (sec.mode == "synthesis" and not
   section_inputs(...))`; `threads` satisfies neither, so a missing
   `threads.md` raises `SystemExit(f"error: missing section file {f} — build
   it first")` for **every** `--sections` build of the planning doc.
4. `threads` renders from `args.thread_registry_path`, resolved from
   `cfg.stores.thread_registry` (default `docs/thread_registry.yaml`,
   `campaignlib/projection_config.py:64`). That file is written **only** by
   `pipelines/grounding/thread_registry.py`.

`grep -rn "thread_registry" server/ frontend/` returns nothing outside
`ensemble_config_shared.py`'s unrelated `threads_out` and ensemble's
`/run/threads` (a *different*, free-text threads render). **Confirmed: the
thread registry has no server or frontend surface at all.**

---

## D2 — The engine can harvest and ratify, but cannot record a ruling

`thread_registry.py`'s subparsers are exactly: `propose`, `add`, `log`,
`set-status`, `alias`, `check`, `render`, `speculate`.

- `propose` **writes** `thread_proposals.yaml` with everything
  `status: pending`, and **preserves** any proposal it finds already carrying
  `ratified` / `rejected` / `deferred` (`load_prior_rulings`, "GM rulings are
  a one-way door").
- Nothing **sets** a ruling. Today a GM records one by hand-editing the YAML.
- Nothing exports a bundle for adjudication.

So spec FR-010/FR-011/FR-019 require **new engine capability**, not just a
page. This is the single largest piece of work in the feature and the one a
naive read of #337 ("just add a UI") misses.

Decision: add one verb, `thread_registry rule`, taking the proposal's `norm`
key, one of `ratified|rejected|deferred`, an optional note, and writing back
into the same proposals file — plus, on `deferred`, appending to the
adjudication bundle. Rationale: `propose`'s existing round-trip already reads
and rewrites the whole file, and the ruling belongs next to the evidence that
justifies it. Alternative rejected: a second sidecar rulings file, which would
be a fifth store to keep in sync (cf. `project_alias_fragmentation` — four
independently-curated alias stores is the scar).

---

## D3 — "Accept" is not one write, it is two-to-many

A ratification is `add` (once, if the thread is new) followed by `log` (once
per fresh chapter). `cmd_add` refuses a title that `match_thread` already
resolves; `cmd_log` requires the thread to exist. A proposal carries
`matches: <thread-id> | null`, so the surface knows which shape applies:

- `matches: null` → `add` + one `log` per chapter in `chapters`
- `matches: <id>` → `log` per chapter in `chapters` (already-logged chapters
  are never re-proposed — `propose` filters them via `logged`)

Every verb re-runs `check_registry` after mutating and **refuses to save**
when it fails, so a partially-applied accept is possible in principle (add
succeeds, a later log fails). ~~Decision: the accept path runs as one server-side sequence…~~ **SUPERSEDED by
D18** — the GM ruled for the atomic verb, and the partial-apply case is gone.

---

## D4 — A harvested candidate can have no chapter at all

`chapter_of(path)` matches `(chapter|session|ch|gen-ch)[_-]?0*(\d+)` against
the path segments, **innermost first**, and returns `None` when nothing
matches. `harvest()` then does `if ch: g["chapters"].add(ch)` — so a corpus
laid out without a chapter-shaped directory name produces a proposal with
`chapters: []` and evidence rows whose `chapter` is `null`.

`check_registry` rejects any log row where `chapter` is not an `int >= 1`.
Therefore: **a proposal with no chapters cannot be accepted without the GM
supplying one.** This is spec edge case 4 / FR-008's "pre-filled *and
editable*" — the form's chapter field must be required and, for these
candidates, empty rather than guessed. Guessing a chapter would be an
ordering decision made by software, which Principle II forbids outright.

---

## D5 — Corpus selection: no default may exist, and none does

`campaignlib/projection_config.py`'s module docstring states the absence
explicitly: *"No `corpus` field: both consumers (event spine, thread registry)
declare `--corpus` as a required CLI argument, and a config default would
manufacture an implicit 'all chapters' (Constitution X, research D6,
FR-013)."* `tests/test_projection_config.py` asserts the absence recursively.

`server/routers/projections.py::run_recent_events` shows the established
shape: `corpus: list[str] = Query(default=[])`, then a 400 naming the problem
when the list is empty. The threads harvest route MUST copy it exactly.

To let the GM *pick* rather than type, the surface needs the glob resolved to
a file list. `GET /api/ensemble/chapters` does this — but it falls back to
`ensemble.yaml`'s `paths.chapters_glob` when `glob` is omitted, and reading
another service's config document is the defect `_backend_flags` was deleted
for (`ProjectionInputs` docstring, spec 006 research D5). Decision: a new
**projections-owned** resolve route that accepts explicit patterns only, has
no config fallback, and confines matches to the workspace the way
`list_chapters` does (`if cwd not in r.parents: continue`). Alternative
rejected: reusing `/api/ensemble/chapters` — cross-service config read, and it
resolves chapter *markdown*, whereas the harvest reads per-chapter
`merged.json`.

---

## D6 — `RunPanel` silently refuses to run without an API key

**Corrected 2026-08-25 — an earlier draft of this entry said the click is
"silently swallowed". It is not.** `RunPanel.vue:133` disables the button and
`:137` renders the warning `ANTHROPIC_API_KEY not set`. The defect is not
silence; it is that the run is blocked **at all**, and that the stated cause is
irrelevant to it.

`RunPanel.vue:70` (`if (!config.apiKeyPresent) return`) backs a gate keyed on
`server/config.py::api_key_present()`, which checks **only**
`os.environ["ANTHROPIC_API_KEY"]`. Two consequences:

- The thread harvest is **deterministic and spends zero tokens** (spec FR-004),
  as is every ratification verb. Through `RunPanel` unchanged, it would be
  unavailable on a machine with no Anthropic key, above a warning naming a key
  it never uses.
- More broadly, the same gate blocks every run on the **dgx**, **openrouter**
  and **claude-code** backends, which are first-class supported and never read
  that variable.

~~Decision: an opt-out prop on `RunPanel`…~~ **SUPERSEDED by D19** — the GM
ruled for a dedicated control instead. The defect itself stands as described,
and is **fixed in this feature** (D21, Phase 6b) — by correcting the question
the gate asks, which is not what D19 rejected.

---

## D7 — Registry writes are one-shot, not streams

`get_sections` establishes the read shape: `subprocess.run(cmd,
capture_output=True, text=True)`, non-zero → `HTTPException(400,
detail=(stderr or stdout).strip())`. Every ratification verb is the same
shape: fast, small output, a refusal on stderr that the GM must read
(`"error: thread id … already exists"`, `"error: alias … already matches
thread …"`, `"error: resolving/abandoning needs --chapter"`, `"error:
refusing to save a registry that fails check"`).

Decision: rulings and maintenance verbs use `subprocess.run` + 400-with-stderr,
not SSE. Only the harvest (which walks a whole corpus) streams. This maps
directly onto FR-021 — the CLI's own refusal text *is* the message the GM
sees, so the two can never drift.

---

## D8 — The no-literals guard shapes every new route

`tests/test_projection_routes.py::test_no_literals_in_router` AST-parses
`server/routers/projections.py` and fails on any non-docstring string constant
matching `^(docs/|summaries/|summaries$)`. So the new routes may not name
`docs/thread_registry.yaml`, `docs/ensemble/thread_proposals.yaml`, or the
adjudication bundle's path. All three must come from
`ProjectionConfigService.resolved()`.

`stores.thread_registry` and `stores.thread_proposals` already exist. The
adjudication bundle does not. Decision: add **one** field,
`ProjectionStores.thread_adjudication` (default
`docs/ensemble/thread_adjudication.json`). It is a store this service's own
CLI writes, which is exactly what `ProjectionStores` is for
(cf. `thread_proposals`' placement in `_SOURCE_FIELD`). **Verified safe**:
`tests/test_projection_config.py:192` guards a *named* set,
`FORBIDDEN = {"corpus", "sections", "specs"}`, recursively — not a closed
field list. A new store field is allowed; those three names stay forbidden.

---

## D9 — Layering: the engine may not import the server

`tests/test_layering.py` fails the build if anything under `campaignlib`,
`pipelines`, `session_doc`, `entity_registry` or `provenance` imports
`server.*`. `thread_registry.py` already reads its own config through
`campaignlib.projection_config` — the correct direction. Any shared shape the
new ruling verb and the new routes both need (the proposal model, the ruling
enum) belongs in `campaignlib`, never in `server`.

---

## D10 — Where the surface lives

`frontend/src/router.ts` mounts grounding children under `/grounding/*`;
`AppSidebar.vue:77` lists `State Projection → /grounding/projections`.
`server/main.py:55` mounts the projections router at `/api/projections`.

Decision: a sibling page, `/grounding/threads` → `views/grounding/Threads.vue`,
with a sidebar entry next to State Projection, served by new routes on the
**existing** projections router (`/api/projections/threads/*`). Rationale: the
thread registry is a projection store this service already declares and
resolves (`stores.thread_registry`, `stores.thread_proposals`); a second
router and a second config document for two YAML files would be the tax
"Architecture is Destiny" warns about. Alternative rejected: a `threads` tab
inside `ProjectionSections.vue` — that page is deliberately stateless and
per-document; a triage queue is neither.

---

## D11 — `no-input` rows already carry the missing path; the UI throws it away

`grounding_sections.py`'s list payload per section is
`{name, mode, state, inputs, provenance}` where `inputs` is
`[str(p) for p in section_inputs(sec, args)]` — for `threads` that is exactly
`[<resolved thread_registry path>]`. `state` is `no-input` when a
non-optional section has any missing input.

So FR-024 needs no CLI change to *name* the store: the row can render
`s.inputs` instead of `s.inputs.length`. It cannot say **which** input is
missing when a section has several (`tracking` has N lists plus the event
store). Decision: add a `missing: [paths]` key to the list payload — a small,
additive contract change that keeps the "which one" answer in the engine
where `section_inputs` already knows it, rather than having the browser
re-derive existence. FR-025's link is then a UI-side special case on
`name === "threads"`.

---

## D12 — `save_registry` is not atomic; `save_projection_config` is

`thread_registry.save_registry` does `path.write_text(...)` directly, while
`campaignlib/projection_config.py` uses `campaignlib.util.atomic_write_text`.
Single-user, one-page-at-a-time usage (memory: `project_web_ui_usage_pattern`)
makes a torn write unlikely, but the surface turns hand-typed CLI invocations
into rapid button presses. Decision: switch `save_registry` (and the
proposals writer) to `atomic_write_text` as part of this feature — one-line
change, removes the only way a ratification can leave a half-written canon
file. Not spec'd; flag as a plan-level hardening.

---

## D13 — Prior scope call, and why the reversal is narrow

`server/routers/projections.py`'s module docstring says: *"Release scope is
deliberately narrow (spec Q2) — staleness and per-section rebuild only. There
is no route for thread triage … adding a write route for proposals would move
a judgment checkpoint into the interface."*

That paragraph will be false when this ships and must be rewritten, not left
to rot. The principle it protects survives intact in the spec: one candidate
per ruling (FR-007), every field shown before it is written (FR-008), no bulk
control at all (SC-004). What moves is the keyboard, not the decision. The
GM ruled on this on 2026-08-25.

Note the asymmetry worth preserving in the rewrite: the **harvest** is
deterministic (no model call), and `speculate` — the one LLM pass in
`thread_registry.py` — stays out of the interface entirely. The surface never
asks a model what a thread is.

---

## D14 — The "thread-triage skill" does not exist

`thread_registry.py`'s docstring twice refers to "the thread-triage skill
driving them". `~/.claude/skills/` contains `entity-triage/` and no thread
equivalent. So the documented alternative to raw CLI verbs is not available
today — which is why #337's workaround section lists hand-typed `add`/`log`
commands. Relevant to scoping: this feature is not duplicating an existing
skill, and the "discuss" bundle (FR-011) is the seam where such a skill or an
ad-hoc Claude conversation plugs in later.

---

## Open for plan review

1. **D3** — one-shot `ratify --from-proposal` verb (atomic add+log+rule) vs.
   the server sequencing three existing verbs. Trade: less partial-apply risk
   vs. more engine surface.
2. **D6** — an opt-out prop on the shared `RunPanel` touches every run
   surface in the app. Confirm that is acceptable before doing it.
(D8 is closed — the guard is a named-set check, so `stores.thread_adjudication`
may be added.)

---

## D15 — MEASURED: the queue is ~1000 candidates, and ~97% of it is chaff

Run against two live corpora on 2026-08-25 (`harvest()` called directly, no
model, no writes):

| Corpus | Chapters | Candidates | Span ≥2 chapters | ≥2 evidence rows | ≥3 evidence rows |
|---|---|---|---|---|---|
| `~/out-of-the-abyss/out-of-the-abyss` | 62 | **986** | **16** | 70 | 16 |
| `~/toee/toee` | 31 | **415** | **2** | — | — |

The reason is visible in the data: `harvest()` keys a candidate on a
`thread`-typed fact's **`subject`**, which is free text the extraction lens
wrote. On OOTA that yields entries like *"ajar third-floor door"*, *"actor
namesake"*, *"accuracy of Sethir's map"* — single-chapter observations, not
running threads. It also yields *"Ajar door on third floor"* **and** *"ajar
third-floor door"* as separate candidates, and *"divine plan"* separately from
*"Buppido's divine plan"*.

What actually looks like a thread is the head of the distribution: `Buppido's
divine plan` (4 chapters), `Stool's home` (4), `the Great Seeder` (3),
`identity of the killer` (3), then a dozen two-chapter entries.

**This breaks the spec's primary flow as written.** FR-007 requires one ruling
per candidate with no bulk control — correct, and not being reopened — but
986 × one-at-a-time is 16 hours of clicking. SC-003's "clear a queue of 20
candidates in a single sitting" silently assumed a queue two orders of
magnitude smaller than the real one.

**Decision — filter the view, never the decision:**

1. **No engine-side default filtering.** `propose` gains `--min-chapters` and
   `--min-evidence`, both defaulting to `1` — i.e. today's behaviour exactly.
   A default that dropped 970 of 986 candidates would be software making a
   scope decision, which is the thing this whole feature is careful about.
   (Precedent for the flag itself: `EnsembleTuning.threads_min_facts: int = 2`
   already exists for the unrelated free-text threads track.)
2. ~~**The page defaults to the plausible head** — candidates spanning ≥2
   chapters or carrying ≥2 evidence rows — and states the number it is not
   showing: *"showing 16 of 986 — 970 single-chapter candidates hidden."* One
   click shows them.~~ **SUPERSEDED, twice.** D16 removed the one-click
   escape hatch; D17 replaced the single filtered view with two named bands.
   The arithmetic here was also wrong: span≥2 *implies* ≥2 evidence rows (each
   chapter contributes at least one), so that OR was 70 candidates, never 16.
3. **Sort by span, then evidence count, then title** — retained, now applied
   within each band (D17).

Alternatives rejected:

- *Raise the bar in `propose` and be done.* Cheaper, and wrong: a
  single-chapter candidate can be a genuine thread that opened last session.
  The GM must be able to reach it.
- *Cluster near-duplicate titles automatically* ("ajar third-floor door" ≈
  "Ajar door on third floor"). That is a similarity-based identity assertion —
  forbidden outright (FR-022, and the `norm_title` docstring: *"Exact-match
  key; never similarity"*). Aliasing is the GM's act.
- *Ask the model to pre-triage the queue.* Would make thread scope an LLM
  decision fed downstream — Principle II, straightforwardly.

**Follow-on worth filing separately**: the extraction lens's `thread` subject
is doing double duty as both "what this fact is about" and "what thread this
belongs to", and it is not good at the second job. Improving that is upstream
of this feature and out of its scope.


---

## D16 — The tail is reached by query, not by a "Show all" button

GM ruling, 2026-08-25, on reviewing D15: *"I like the idea of not showing all
986."* Pushed back on my own D15 wording — "the full set reachable in one
action" was satisfied by a **Show all** button that dumps 970 cards of
*"ajar third-floor door"*, which is reachability on paper and a wall in
practice.

Decision: **no Show all control.** The default view stays the multi-chapter
head; the tail is reached by

- **free-text search** over `title`, every entry in `all_titles`, and evidence
  `fact` + `quote` text, across the **full** set *including already-ruled
  candidates* (a rejected candidate must stay findable — "what did I already
  decide about this" is a question the GM will ask);
- **chapter filter** — every candidate whose `chapters` includes N, which is
  the realistic post-session move ("what did chapter 41 throw up");
- **ruling filter** — pending / ratified / rejected / deferred.

Composable, with the header restating the count under the current query.

**Where search runs: the browser.** Measured — `proposals --json` for the
986-candidate OOTA harvest serialises to **484 KB** (986 proposals × up to 8
evidence rows). That is nothing for a localhost single-user server, and it
keeps the route dumb: no query parameter, no paging, no server-side relevance.
The moment the server decides *which* candidates come back, it is deciding
which candidates matter — the thing this feature is built to keep with the GM.

Alternative rejected: server-side search/paging on `GET /threads/proposals`.
Only justified above a payload size we are two orders of magnitude below.


---

## D17 — Two named bands, computed counts, and `ratified` is not a door

Two GM rulings, 2026-08-25, both prompted by `/speckit-analyze` finding real
defects in D15/D16 as written.

### 17a — The default view is banded, not a single filter

D15's "span ≥2 **or** ≥2 evidence" was arithmetically confused: every chapter
contributes at least one evidence row, so span≥2 implies ev≥2 and the OR set is
just ev≥2. Measured, that is **70** candidates on OOTA — not the 16 that D15,
`ui.md`, T029/T030 and quickstart all went on to state as a literal header
string.

Ruling: show **both**, banded and separately counted.

| Band | Rule | OOTA (62 ch) | toee (31 ch) | Hillsfar (15 ch) |
|---|---|---|---|---|
| **Recurring** | appears in ≥2 chapters | 16 | 2 | 3 |
| **Single chapter, repeated** | `len(chapters) < 2`, ≥2 mentions | 54 | 19 | 12 |
| *(excluded)* | mentioned exactly once | 916 | 394 | 104 |

The band names carry the reasoning, which a bare count cannot: *recurring* is
what a thread structurally is; *single chapter, repeated* is where a thread
that opened last session lives before it has had a chance to recur. Both are
in the default view; only the mentioned-once tail is excluded, reachable by
search or chapter filter (D16).

**Amended 2026-08-26 (D20 consistency).** The rule above originally read
*"1 chapter, ≥2 mentions"*, which contradicts D20: a candidate with
`chapters: []` has **zero** chapters, so `== 1` would drop it into the excluded
tail — the one place the GM cannot see the chapterless warning D20 moved onto
the card. The predicate is `< 2`, and `contracts/ui.md` and `tasks.md` T029
already said so; this table was the stale copy.

**This table is the single authority for the band rules.** `contracts/ui.md`,
`quickstart.md` and `tasks.md` T029/T030 restate it for local readability —
if they ever disagree with this row, this row wins and the others are the bug.

**Every count is computed from the loaded set** (FR-028a). The literal-string
bug D15 introduced is the reason this is now a requirement rather than a
convention — the numbers differ by an order of magnitude across corpora.

### 17b — `ratified` re-evaluates for fresh chapters

`propose()` short-circuits `if key in prior: proposals.append(prior[key]);
continue` **before** the `matches`/`logged` filter, and `load_prior_rulings`
counts `ratified` among the prior rulings. So the accept sequence ending in
`rule --status ratified` would have frozen the candidate permanently: ratify a
thread at chapter 41 and chapters 50–60 of that same thread never surface
again. FR-009 and US2's second acceptance scenario would have been reachable
only for threads created by bare CLI `add`.

Ruling: **only `rejected` and `deferred` short-circuit.** A `ratified`
candidate falls through to the existing `matches` + `logged` filter and
reappears carrying only its unlogged chapters, keeping the `ruled_thread`
audit link.

The engine comment *"GM rulings are a one-way door"* stays true of the rulings
it was actually about. A rejection is a door. An acceptance is not a door at
all — it is a statement that this became a thread, and threads keep moving.
Alternatives rejected: dropping `rule --status ratified` from the accept
sequence (loses the candidate→canon audit link), and leaving the freeze in
place (makes US3's manual "add log row" the only advance path, and three
artefacts would need correcting to say so).


---

## D18 — Accept is one atomic verb, not a route-side sequence

GM ruling, 2026-08-25, closing the question D3 parked and that the first draft
of tasks.md quietly answered by building the sequencing branch.

`thread_registry ratify --norm KEY --plan -` does the whole accept in one call:
locate or create the thread, append every log row, mark the proposal
`ratified` with its `ruled_thread` link. The registry is assembled in memory,
validated by `check_registry`, and written once via `atomic_write_text`.

What this buys:

- **No partial-apply state.** The sequencing design needed `/threads/ratify` to
  return `207` with a per-step report, and the page to render that report — a
  second error-display path alongside the plain 400 one, for a case that only
  exists because of the design. Both disappear.
- **The whole accept is reproducible in one command** at the terminal, which is
  what FR-019 is actually asking for. Three chained verbs are reproducible only
  as a transcript.

What it costs: a verb whose argument surface overlaps `add` + `log`. Mitigated
by taking the ratification as a **JSON plan** (file or stdin) rather than
repeated flags — summaries and quotes are prose and contain colons — and by
`--emit-plan`, which prints the derived starting point so a CLI user edits the
same object the web form renders as fields.

`--plan` is required. There is deliberately no "accept as proposed" flag: the
harvest's derived id, title and summaries are a *starting point*, and a flag
that committed them unread would be the one-click path FR-008 and SC-004 exist
to forbid, just spelled at the CLI.

**The one seam that is not atomic, and is stated rather than hidden**: registry
and proposals are two files. `ratify` writes canon first, then the ruling. A
failure between them leaves the thread created and the candidate still
`pending`; the re-run refuses with `error: thread id 'X' already exists` — a
readable, recoverable state. The other order could leave a proposal marked
ratified with no thread behind it, which is a lie on disk rather than a
conflict, and Principle I says take the conflict.


---

## D19 — A second Run button, not a second mode on the shared one

GM ruling, 2026-08-25, on the `RunPanel` API-key gate.

The reasoning, in the GM's terms: there are **two behaviours** here — a run that
spends tokens and a run that cannot. One button carrying a flag to switch
between them is more confusing than two buttons that each do one thing. If real
duplication appears later, refactor and share it then.

Decision: **do not modify `frontend/src/components/shared/RunPanel.vue`.** The
Threads page gets its own run control for the harvest, streaming through the
existing `connectSSE` client (shared infrastructure, already the right seam)
with no API-key check, no `SelectionPanel`, and no model/backend preview —
because none of those mean anything for a pass that cannot reach a model.

This is a deliberate trade against DRY, and it is the right one here: the two
controls differ in what they *are*, not merely in a setting. `RunPanel` exists
to make token spend visible and overridable before a run (FR-019 of spec 003).
A control for a zero-token pass has no such job. Sharing them would mean the
shared component grows a branch for the case where its entire reason for
existing does not apply.

**Not fixed by this ruling, and now visible rather than assumed**: the same
gate still applies on the State Projection page, where a `planning --sections
threads` or `campaign_state --sections recent_events,party` build calls no model
at all, and where a run explicitly targeting the dgx backend never reads an
Anthropic key either. Filed as **#341** — and then, on a second GM ruling
(2026-08-26), **pulled into scope**: see D21. D19's own decision is untouched by
that; the Threads page still gets its own control, and the shared button still
gets no opt-out prop.


---

## D20 — The corpus preview lists files only; the chapter warning moves to the card

GM ruling, 2026-08-25, closing analysis finding C2.

`GET /threads/corpus` resolves the GM's explicit patterns to a file list and
**does not annotate each file with a chapter number**. The engine's
`chapter_of()` stays in the engine, unimported and unwrapped.

This closes the contradiction the analysis found — plan's Principle V row says
the server reaches the engine "through `console_script()`/`subprocess` only",
and the two ways to get chapter numbers into the route both broke it: import
the helper (a second seam) or add a `corpus` verb (a third read verb existing
only to feed one preview). Neither is worth it for a column.

**What the ruling costs, and where it is recovered.** D4's early warning —
"this file will produce a candidate you cannot accept without typing a chapter"
— was going to sit in the pre-harvest file list. It now sits on the candidate's
own card instead: a proposal with `chapters: []` is flagged, and the accept
form requires a chapter before it will submit (FR-008, D4). The warning arrives
later but at the point of decision, which is arguably where it belonged.

Band 2's rule is therefore `len(chapters) < 2 and len(evidence) >= 2`, not
`== 1`, so a chapterless candidate lands somewhere visible rather than falling
through into the excluded tail.

Measured: **zero** chapterless candidates across all three live corpora (OOTA
986, toee 415, Hillsfar 119) — every workspace lays chapters out in
chapter-named directories that `chapter_of()`'s regex matches. This is a
correctness edge, not a common case, which is the other reason a whole seam was
not worth building for it.

---

## D21 — The gate asks the wrong question, and that gates this feature

> **Outcome, 2026-08-26 — SUPERSEDED IN PART by #342 / PR #343.** The GM took
> the wider question (is the predicate worth having at all?) and ruled
> **delete it**. The four numbered decisions below are the *narrow* fix and were
> not built: no `BACKEND_CREDENTIAL` map, no `credential_present(backend)`, no
> `credentials` map on `/api/config/status`, no resolved-backend gate. What
> shipped instead: `api_key_present` and `apiKeyPresent` deleted outright, with
> `_require_anthropic_credential` refusing at the four entry points that reach
> the metered API. The **diagnosis** below stands unchanged and is why the
> deletion is safe; only the remedy changed.
>
> One thing the narrow design had wrong, found while implementing: the check
> cannot live in `make_client()`. Every `--dump-only` path (`campaign_state.py:247`,
> `party.py:300`, `planning.py:903`, `synthesise_world_state.py:713`) constructs
> a client before it knows whether it will call one — the documented keyless
> subscription workflow. Constructing a client is not calling one.

GM ruling, 2026-08-26, reopening what D19 deferred.

**Why it stopped being someone else's bug.** US4 walks the GM from a `threads`
row that says "no input" to the Threads surface, and back to the projection
table to build. On a machine with no `ANTHROPIC_API_KEY`, that last step is
refused before it starts. #337's complaint is *a dead-end the interface offers
no way past*; shipping US1–US4 without this moves the dead-end one step later
and calls it fixed. It gates SC-001 directly, so it is in scope (Phase 6b).

**The defect, precisely.** `server/config.py:63`'s `api_key_present()` is
`bool(os.environ.get("ANTHROPIC_API_KEY"))` — one global boolean, surfaced at
`GET /api/config/status` and consulted before every run. It answers *"is an
Anthropic key set?"* where the only useful question is *"does **this** run need
a credential, and is it there?"*. Two populations are wrongly refused:

- **Runs that reach no model.** `grounding_sections build --doc planning
  --sections threads` and `--doc campaign_state --sections recent_events,party`
  are deterministic assembly; the engine's own usage block advertises the
  latter as `# deterministic, free`.
- **Runs on three of the four supported backends.** `dgx`, `openrouter` and
  `claude-code` are first-class (`campaignlib/selection.py:25`'s `BACKENDS`),
  and none reads `ANTHROPIC_API_KEY`. On a setup where extraction runs on the
  Spark and generation on the subscription, *every* Run button in the app is
  dead.

**Why this is not a reversal of D19.** D19 rejected a *mode*: a
`:requires-api-key="false"` prop letting one button be two things. This changes
the gate's **condition**, adds no prop and no branch, and leaves the Threads
page's dedicated control exactly as ruled — that control has no gate to fix,
because it can never reach a model. The two rulings are about different things:
D19 about how many buttons exist, D21 about what the surviving one checks.

**Decision.**

1. Declare the credential beside the backend list — `BACKEND_CREDENTIAL` next
   to `BACKENDS` in `campaignlib/selection.py:25`, mapping each backend to an
   env var name or `None`. #341 is what a hardcoded provider name does when a
   backend is added; a map keyed off `BACKENDS` with a set-equality test is the
   thing that stops the next one. `None` means *no environment credential* —
   `claude-code` needs the `claude` CLI, `dgx` an endpoint. **Neither is
   probed.** A gate that pings an endpoint is a liveness check pretending to be
   a credential check, and it would fail closed on a Spark that is merely
   asleep; the backend already raises a clear error at call time.
2. `server/config.py` replaces `api_key_present()` with
   `credential_present(backend)`, and `/api/config/status` returns a
   `credentials` map. The scalar is **deleted**, not kept alongside — a second
   probe in a second place is the split-brain this repo has been removing
   everywhere else.
3. `RunPanel` gates on the credential for the **resolved** backend. It already
   mounts `SelectionPanel`, which already fetches
   `/api/<service>/selection/resolved` and already holds `resolved.backend` —
   the fix consumes a value that is on screen, and adds no fetch. Where no
   `selectionService` is passed, fall back to the platform default
   (`config.backend`).
4. The warning names what is actually missing. `AppSidebar.vue:209` already
   half-does this (`!config.apiKeyPresent && currentBackend !== 'claude-code'`)
   — a hand-rolled special case for one backend, which is the same fix stopped
   two backends short.

**Blast radius, counted:** eight views mount `RunPanel`; five sites in
`ExtractSynthesizePanel.vue` (`:99,116,255,258,334`), one in
`ConnectionGraph.vue:382` and one in `AppSidebar.vue:209` repeat the check
directly. All are mechanical once the store's shape changes (T057f–T057i).

