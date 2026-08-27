# Implementation Plan: Thread Registry Surface

**Branch**: `feat/337-thread-registry-ui` | **Date**: 2026-08-25 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/014-thread-registry-ui/spec.md`

**Issue**: [kostadis/CampaignGenerator#337](https://github.com/kostadis/CampaignGenerator/issues/337)

## Summary

The Planning grounding document cannot assemble until `docs/thread_registry.yaml`
exists, and nothing in the web UI can create it — `grep -rn thread_registry
server/ frontend/` returns nothing (research D1). This feature gives the thread
registry a surface: harvest candidates from an explicitly-chosen corpus, rule on
each candidate one at a time (**accept / reject / discuss**), and maintain the
ratified registry afterwards.

The approach is the one the constitution already mandates: **the CLI stays the
engine**. Every write — ratification, ruling, status change, alias — is the
existing `thread_registry` console script invoked as a subprocess, so a thread
ratified in the browser and one ratified in a terminal are byte-identical on
disk. The work splits three ways:

1. **Engine** (`pipelines/grounding/thread_registry.py`): two new verbs — `ratify`, which turns one proposal into canon atomically (GM ruling, D18), and `rule`,
   because nothing today records a GM ruling into `thread_proposals.yaml` —
   `propose` only *preserves* rulings it finds already written (research D2).
   `rule … --status deferred` additionally appends to an adjudication bundle,
   which is the "discuss" outcome's whole point: a file to hand to a Claude
   conversation. Plus a `--json` read mode so the server never screen-scrapes.
2. **Server** (`server/routers/projections.py`): read routes for the registry
   and the proposal queue, an SSE route for the harvest, and one-shot
   subprocess routes for each write, each surfacing the CLI's own refusal text
   verbatim (research D7). No path literal may appear in this file — the AST
   guard in `tests/test_projection_routes.py` enforces it (research D8).
3. **Frontend** (`frontend/src/views/grounding/Threads.vue`): a sibling page to
   State Projection under `/grounding/threads`, plus two small changes to
   `ProjectionSections.vue` so the `no-input` row names its missing store and
   points here (US4).

4. **The gate on the build this all leads to** (#341 → #342, GM rulings of
   2026-08-26). The projection page refuses to *start* a build whenever
   `ANTHROPIC_API_KEY` is absent — including builds that call no model, and
   every run on the three backends that never read it. Fixing 1–3 without this
   moves #337's dead-end one step later. The first ruling scoped a corrected
   gate into this feature; the second **deleted the predicate outright**, and it
   ships as PR #343 off `main` rather than here. **Merged 2026-08-27** — see Phase 6b.

Deliberately unchanged: `speculate`, the one model call in `thread_registry.py`,
stays CLI-only. Nothing on this surface spends a token.

## Technical Context

**Language/Version**: Python 3.11+ (engine, server), TypeScript 5 / Vue 3
`<script setup>` (frontend)

**Primary Dependencies**: FastAPI + `StreamingResponse` SSE (server), pydantic
v2 strict models in `campaignlib` (shared shapes), PyYAML (registry and
proposals I/O), Vue Router + Pinia (frontend); no new third-party dependency

**Storage**: Files on disk, all resolved from `<config>/projections.yaml`:
`stores.thread_registry` (YAML, canon), `stores.thread_proposals` (YAML,
candidates + rulings), and one new field `stores.thread_adjudication` (JSON,
the discuss bundle). No database.

**Testing**: `pytest` (`tests/`), with **six** existing guards this feature must
keep green:

| Guard | What it forbids | Where it binds here |
|---|---|---|
| `test_projection_routes.py` | `docs/`-shaped literals in the router; a silent "all" | every new route |
| `test_projection_isolation.py` | `docs/`-shaped literals in the **four State Projection engine files**, `thread_registry.py` among them; any cross-service config read from `pipelines/grounding/` | the `rule` verb's `--adjudication` default and `propose`'s new flags |
| `test_projection_config.py` | the named-forbidden fields `corpus`/`sections`/`specs` | `stores.thread_adjudication` |
| `test_thread_registry.py` | (10 existing tests over `propose`, `save_registry`, refusals) | the `propose` short-circuit change and the atomic-write switch |
| `test_layering.py` | anything under `pipelines/` importing `server.*` | shared shapes go in `campaignlib` |
| `test_retrieve_render_isolation.py` | retrieval and render in one function | unaffected, but must stay green |

**Target Platform**: Linux; FastAPI server run from a campaign workspace
directory (`cwd == campaign_dir`), console scripts resolved via
`console_script()` against the server's own venv

**Project Type**: Web application over a CLI engine — `pipelines/` + `server/`
+ `frontend/`

**Performance Goals**: Harvest over a 60-chapter corpus completes in seconds
(deterministic file walk, no model call). A ruling round-trips in well under a
second — one short-lived subprocess. Spec SC-003's "rule on a candidate in
under 60 seconds" is a *human* budget, not a machine one.

**Constraints**: **Zero tokens.** Every operation this feature exposes is
deterministic. No route added here may reach a model, and no control on this
page may require an API key — which is why the harvest gets its own run control
rather than a flag on the shared `RunPanel` (research D19). The same
zero-token property is what makes the shared gate a defect rather than a
preference: it refuses deterministic builds, and every run on the three
backends that never read an Anthropic key. Filed as #341; the GM then ruled the
whole predicate away (#342). It ships as PR #343 off `main` — **open, not
merged** — so SC-001 depends on that merge, not on a task here (Phase 6b).

**Scale/Scope**: One GM, one campaign at a time. **Measured (research D15),
not assumed**: a 62-chapter corpus harvests to **986 candidates**, of which
**16** span more than one chapter; a 31-chapter corpus gives 415 and 2. The
queue UI must stay usable at ~1000 rows while making the multi-chapter head
reachable immediately — and must hide nothing without saying how much
(FR-027–FR-031).

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1 design. All **thirteen**
principles, by name, as Governance requires — the constitution moved to v1.3.0
on `main` (`cace67c`, 2026-08-25) while this feature was in flight, adding
XI–XIII. They are evaluated in their own subsection below.*

| # | Principle | Verdict | How this design satisfies it |
|---|---|---|---|
| I | Disk is Truth, the Model is a Draft | **PASS** | The registry and proposals YAML are the truth; the page holds no thread state of its own (FR-023) and re-derives every view from disk on load. No model output enters canon — the harvest is deterministic. |
| II | The Human Checkpoint is Non-Negotiable | **PASS** | Thread identity, scope and ordering stay the GM's: one candidate per ruling, every field shown pre-filled and editable before it is written, no bulk control anywhere (FR-007/FR-008, SC-004). A candidate with no chapter cannot be accepted until the GM supplies one (research D4) — software never guesses ordering. |
| III | Retrieval and Render are Separated | **PASS** | Nothing here retrieves or renders — no `stream_api`/`call_api` call is added. `test_retrieve_render_isolation.py` is unaffected. |
| IV | Verbatim is Sacred | **PASS** | Evidence quotes are carried through from `source_quote` where `quote_verified` was set, and displayed unmodified. The accept form pre-fills a log row's `quote` from that evidence; the GM may delete or edit it, but nothing paraphrases it. |
| V | One Seam per Boundary | **PASS** | One seam per boundary is preserved: registry writes go through `thread_registry` only; the server reaches it through `console_script()`/`subprocess` only; config comes from `ProjectionConfigService.resolved()` only. No new integration point. |
| VI | CLI is the Engine, UI is a Face | **PASS** | The `rule` verb and the adjudication export are added **to the CLI first** precisely so the UI is not their only home (FR-019). The router builds argv and streams output; it contains no registry logic. |
| VII | Extract Once, Synthesize Deliberately | **N/A** | No extraction or synthesis pass is added or collapsed. |
| VIII | State is Discoverable | **PASS (re-checked against FR-027–FR-031)** | This is the principle #337 violates. After the fix, a section in `no-input` names the store it is missing on the row itself (FR-024), and the route to creating it is a link, not tribal knowledge (FR-025). Rulings live on disk, so "what have I already decided" survives a reload, a re-harvest and a reboot. **The banded default view was re-tested against this principle after the spec was amended**: two named bands with computed counts, the excluded count stated on screen, every candidate reachable by search or chapter filter, and ruled candidates findable with their ruling shown (FR-027–FR-030). Nothing about the queue's real size is concealed — the numbers are on screen and derived from the loaded set, never written into the interface (FR-028a). |
| IX | The UI Mechanizes; Claude Converses | **PASS, with the load-bearing detail** | The page mechanizes *invoking* the verbs; it never adjudicates. "Discuss" is the explicit hand-off: it writes a file for a Claude conversation and takes the answer back through the GM (FR-011/FR-012). Every action is performable at the CLI with nothing lost (SC-009). |
| X | Selection is Explicit; No Silent "All" | **PASS (re-checked against FR-027–FR-031)** | The harvest refuses an empty corpus with a 400 naming the problem, copying `run_recent_events`' shape exactly; no config default for `corpus` exists or may be added (research D5). There is no "ratify all" — the strongest possible reading of this principle. **The late-added filtering was tested against it too**: a band is a *view*, never a selection, and no operation acts on "everything currently shown" — every ruling names one candidate (FR-007). The engine's `propose --min-chapters/--min-evidence` default to `1`, so no harvest silently narrows its own input either (research D15). |

### Principles XI–XIII (constitution v1.3.0, evaluated 2026-08-27)

`main` amended the constitution mid-flight. All three new principles were run
against this feature; **one produced real findings.**

| # | Principle | Verdict | Notes |
|---|---|---|---|
| XI | Parity is Bidirectional; Every CLI Capability Has a Face | **PASS, with three rulings recorded below** | This feature IS an instance of XI — #337 is precisely an Orphaned Capability, a `thread_registry` engine no human could reach. But XI also applies *to this feature's own additions*, and three of them are deliberately CLI-only. XI requires that ruling be recorded here, naming who decided and why — so it is. |
| XII | One Spelling per Option; No Configuration Drift | **PASS** | No existing option is re-spelled. `--registry`/`--proposals`/`--adjudication` follow the established sentinel-plus-config-resolution pattern; `--force` is untouched; the new `--json` matches `grounding_sections`' existing spelling exactly, which is why the routes parse nothing. Defaults are declared once, in `ProjectionStores` — `tests/test_thread_registry_routes.py::test_threads_routes_name_no_store_and_no_path_literal` fails the build if a route re-spells one. |
| XIII | Breaking State Changes Migrate Out of Band | **N/A — nothing breaks shape** | `stores.thread_adjudication` is an **additive** field with a default, so an existing `projections.yaml` loads unchanged and needs no migrator. The registry and proposals files keep their schemas; `ratify` adds a `ruled_thread` key to a proposal, which is additive and read defensively. No workspace requires a one-shot command, so no `migration.md` is owed. |

**XI's three recorded rulings** — deliberately CLI-only, per its exemption
clause ("an omission is not an exemption"):

1. **`speculate`** — the one LLM call in `thread_registry`. Excluded by the
   spec itself, not by oversight: it writes non-canon idea material to
   `notes/`, and exposing a model call on a page whose entire premise is
   "deterministic, zero tokens, no credential" would undo the property
   `contracts/ui.md` and T021's dedicated run control are built around.
   *Decided by:* the GM, at spec time (`contracts/cli.md`: "NOT exposed by
   this feature").
2. **`render`** — superseded in practice. `grounding_sections`' inline
   `threads` section reads the registry directly, so `render`'s markdown has
   no consumer and no declared `ProjectionOutput` field; the engine says so
   in its own comment. Giving it a button would surface a path the product
   does not use. *Decided by:* research D8/the 006 design, carried forward.
3. **`propose --min-chapters` / `--min-evidence`** (new in T058) — the web
   surface never sends them. This is the closest call of the three, and the
   reasoning is D15's: they exist so a CLI user can narrow a 986-candidate
   harvest by hand, whereas the page **filters the view and states the hidden
   count**. Sending them from the UI would delete candidates from disk rather
   than from a view, and a default that dropped 970 of 986 would be software
   making a scope decision. The *capability* the GM needs — reaching the tail —
   has a face: search plus the chapter filter (FR-029/FR-030). *Decided by:*
   the GM, research D15.

### Post-design re-evaluation (2026-08-26)

*The gate above was first evaluated before Phase 0. Re-run after Phase 1 and
after the design moved (D18 atomic `ratify`, D19/D20, #342, and the coverage
sweep that produced T019a/T031b/T041a). **No verdict changed**, but three of
them were resting on prose and are now test-backed — the distinction matters,
because a principle the build does not check is precisely the "Optimistic Lie"
Principle I names.*

| # | Claim in the table above | Enforced before | Enforced now |
|---|---|---|---|
| I | "No model output enters canon — the harvest is deterministic" | US1's prose Independent Test, checked by eye | **T019a** — `/threads/run/propose` leaves `docs/thread_registry.yaml` byte-identical (FR-006) |
| V / VI | "registry writes go through `thread_registry` only" | the router's construction, by convention | **T041a** — AST guard: no threads route performs a write of its own (FR-018/019), so `check_registry` cannot be bypassed by the surface (FR-020) |
| VIII | "derived from the loaded set, never written into the interface" | T030's prose, bolded | **T031b** — static guard: neither band count nor the excluded count may be a numeric literal (FR-028a) |

Two further notes from the re-run:

- **Principle V is satisfied by subtraction twice over.** D18 replaced the
  `add` + N × `log` + `rule` sequence with one atomic verb, so the ratify path
  has a single write and a single failure mode — no 207, no partial-apply state
  for the UI to model. #342 removed the second place a credential requirement
  was declared. Both are boundaries that stopped existing rather than being
  documented.
- **Principle II's checkpoint survived the convenience pressure.** `ratify`
  deliberately has no "accept as proposed" flag: `--plan` is required. The
  cheapest possible UI — one click from the queue card — is the one thing
  SC-004 forbids, and the atomic verb made that click *technically* easy for
  the first time. It was still not built.

**One criterion remains unverified by anything**: SC-003's timed budget
("under 60 seconds per ruling", "clear the recurring band in one sitting").
It is a human budget, as Performance Goals above already says, and is left
openly uncovered in `tasks.md`'s coverage table rather than assigned to a
task that would not really measure it. Closing it is a GM call.

### A defect fix pulled in scope — declared, not silent

#341 is a pre-existing defect on another feature's page, and the first ruling
(D19, 2026-08-25) deferred it. The second (D21, 2026-08-26) pulls it in, and
the justification is constitutional, not convenience: **Principle VIII**. A
control that refuses a deterministic build under a warning naming a credential
that build never reads does not merely inconvenience — it states a false cause,
which is the discoverability failure #337 is itself an instance of. Fixing
US1–US4 while leaving it is fixing the signpost and not the door.

**Resolved, 2026-08-26, more simply than planned**: the GM ruled the predicate
away entirely (#342, PR #343). No control asks about credentials; each backend
refuses for itself at the call. That satisfies **Principle V** by subtraction —
there is no second place for the requirement to be declared *in* — and leaves
D19 untouched, since "the harvest control checks nothing about API keys" is now
true of every control in the app.

### Reversal of a prior scope call — declared, not silent

`server/routers/projections.py`'s module docstring currently states that thread
triage is excluded because "adding a write route for proposals would move a
judgment checkpoint into the interface." The GM reversed that on 2026-08-25.
Per Governance ("a conflict requires written justification … not a silent
override"), the justification is: **the checkpoint moves keyboards, not
owners.** The judgment being protected — is this a real thread, what is it
called, which chapter did it open in — is still made by the GM, on evidence, one
candidate at a time, with every written field visible first. What the original
exclusion actually prevented was *a button that ratifies without reading*, and
FR-007/FR-008/SC-004 forbid exactly that. Rewriting that docstring is a task,
not an afterthought (research D13).

## Project Structure

### Documentation (this feature)

```text
specs/014-thread-registry-ui/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 — codebase survey, D1–D21
├── data-model.md        # Phase 1 — entities, validation, state transitions
├── quickstart.md        # Phase 1 — end-to-end validation walkthrough
├── contracts/
│   ├── cli.md           # `thread_registry` surface incl. the new `rule` verb
│   ├── api.md           # `/api/projections/threads/*` routes
│   └── ui.md            # Page contract: states, controls, refusals
├── checklists/
│   └── requirements.md  # Spec quality checklist (complete)
└── tasks.md             # Phase 2 — /speckit-tasks, NOT created here
```

### Source Code (repository root)

```text
campaignlib/
└── projection_config.py         # + ProjectionStores.thread_adjudication (D8)
                                 #   (selection.py / api/backends.py: NOT touched —
                                 #    #342 deleted the gate instead; PR #343)

pipelines/grounding/
├── thread_registry.py           # + `rule` verb; + --json read modes;
│                                #   save_registry -> atomic_write_text (D12)
└── grounding_sections.py        # + `missing: [...]` in the list --json payload (D11)

server/
└── routers/
    └── projections.py           # + /threads/* read, harvest (SSE), write routes
                                 #   ; module docstring rewritten (D13)

frontend/src/
├── router.ts                    # + /grounding/threads
├── components/
│   └── layout/AppSidebar.vue    # + "Threads" entry beside State Projection
│                                #   (RunPanel/SelectionPanel/config.ts: NOT
│                                #    touched — #342 deleted the gate; PR #343)
└── views/
    └── grounding/
        ├── Threads.vue          # NEW — registry list + proposal queue + forms
        └── ProjectionSections.vue # row shows missing inputs; link for `threads`

tests/
├── test_thread_registry_rule.py     # NEW — the `rule` verb + adjudication bundle
├── test_thread_registry_routes.py   # NEW — routes, refusals, no-silent-all
├── test_thread_registry_json.py     # NEW — the three --json read verbs
├── test_thread_registry_ratify.py   # NEW — the atomic ratify verb (D18)
├── test_threads_ui_absences.py      # NEW — FR-031 no fuzzy grouping;
│                                #       FR-028a no literal counts
├── test_projection_routes.py        # existing guards stay green
├── test_projection_config.py        # existing named-forbidden guard stays green
└── test_layering.py                 # existing direction guard stays green
```

**Structure Decision**: no new service, no new config document, no new router.
The thread registry is a store the State Projection service **already declares
and resolves** (`stores.thread_registry`, `stores.thread_proposals` in
`campaignlib/projection_config.py`), so its surface belongs on that service's
existing router and config document. Spinning up a fourth config document and a
twelfth router for two YAML files is the recurring tax "Architecture is
Destiny" warns against. The frontend gets its own page rather than a tab,
because `ProjectionSections.vue` is deliberately stateless and per-document
while a triage queue is neither (research D10).

## Phase plan

**Phase A — engine (blocking; everything else depends on it).**
`rule` verb, `--json` read modes for `check`/list, the adjudication bundle
writer, `atomic_write_text`. Testable entirely at the CLI with no server and no
browser — and *must* be, since FR-019 says the interface may not be the only
place these exist.

**Phase B — routes.** Read, harvest (SSE), and write routes on the projections
router, resolving every path from `ProjectionConfigService.resolved()`. Rewrite
the module docstring (D13).

**Phase C — the page.** `Threads.vue`: ratified registry grouped by status, the
pending queue with evidence, the accept form, reject/discuss actions,
maintenance controls, and every refusal rendered. **The queue's default view,
its ordering, its visible hidden-count, and its search/chapter filters are
load-bearing here, not polish** — at 986 candidates an unordered list is the
feature failing, and so is a "Show all" button that produces one (research
D15, D16).

**Phase D — the signpost (US4).** `missing` in the sections payload, inputs on
the row, link for `threads`, and the failed-build message naming the surface.

**Phase E — the gate (#341/#342).** ✅ **Merged 2026-08-27** as PR #343, in a
different shape than planned — the GM ruled the predicate away rather than
correcting it (#342). `api_key_present` and its frontend consumers are gone
from `main`; `_require_anthropic_credential` refuses at the four entry points
that reach the metered API, naming a way to proceed.

The merge superseded `8d49d4f`, which had landed #341's *narrow* fix on `main`
in the meantime (keep the predicate, key it on the resolved backend). Every
conflict was that same either/or and was resolved for deletion. The only step
left here is verification — quickstart Scenario 5 / T057v — which needs `main`
merged into this branch first.

A–B–C is the shippable spine (spec US1+US2). D is independently valuable and can
land separately — and since E merged on 2026-08-27, its signpost now leads to a
button a keyless machine can actually press.

**Phase letters map to `tasks.md` phase numbers** as follows — the two documents
number differently because this plan groups by layer and the task list groups by
user story, which is the organisation `/speckit-tasks` requires:

| plan.md | tasks.md | Tasks |
|---|---|---|
| *(pre-work)* | Phase 0 — Blocking GM rulings | T000a–T000c (all ruled 2026-08-25) |
| *(pre-work)* | Phase 1 — Setup | T001–T003 |
| **A** — engine | Phase 2 — Foundational | T004–T012 |
| **A**+**B** — engine, routes | Phase 4 — US2 engine + routes | T032–T041a |
| **B** — routes | Phase 3 — US1 routes | T013–T020, T040a, T040b |
| **C** — the page | Phase 3 — US1 frontend | T021–T031b, T045a |
| **B**+**C** | Phase 5 — US3 | T047–T052 |
| **D** — the signpost | Phase 6 — US4 | T053–T057 |
| **E** — the gate | Phase 6b — delivered elsewhere | T057v only (PR #343) |
| *(none)* | Phase 7 — Polish | T058–T065 |

## Complexity Tracking

> No constitutional violations to justify. Two design choices carry cost and are
> recorded here so review can push back on them.

| Choice | Why | Simpler alternative rejected because |
|---|---|---|
| New CLI verb `rule` rather than the UI writing `thread_proposals.yaml` | Constitution VI, spec FR-019 — the interface may not be the only place a ruling can be recorded | Having the server write the YAML directly is ~30 fewer lines and makes the CLI and UI two implementations of one operation: Split-Brain, the exact thing Principle VI names |
| Queue filtering lives in the UI, while `propose` gains `--min-chapters`/`--min-evidence` defaulting to `1` (research D15) | A default that dropped 970 of 986 candidates would be software making a scope decision; the flags exist for CLI users who want them | Filtering in `propose` by default is one line and would make the queue tidy — and would silently decide, for the GM, which threads are worth seeing |
| One atomic `ratify --norm … --plan -` verb rather than the route sequencing `add` + N × `log` + `rule` (research D18) | No partial-apply state, and the whole accept is reproducible in one terminal command (FR-019). Removes the 207 branch and its second error-display path in the page | Route-side sequencing reuses the existing verbs untouched, but leaves a window where the thread exists with fewer log rows than intended. **Ruled by the GM, 2026-08-25** |
| Narrowing `propose`'s short-circuit to `rejected`/`deferred` (research D17b) | Without it, accepting a thread at chapter 41 hides chapters 50–60 of that same thread forever and FR-009 is unreachable through the surface | Dropping `rule --status ratified` from the accept sequence avoids the engine change but loses the candidate→canon audit link. **Ruled by the GM, 2026-08-25** |
| Pulling #341 into a feature that did not cause it (research D21) | It gates SC-001: the build US4 signposts cannot be started on a keyless machine, so shipping 014 without it relocates #337's dead-end rather than removing it | Leaving it filed keeps this feature's diff smaller and its blast radius inside `grounding/` — at the cost of shipping a surface whose last step does not work on the GM's own setup. **Ruled by the GM, 2026-08-26** |
| Two named bands rather than one filtered list (research D17a) | The single-filter rule was arithmetically wrong (span≥2 implies ev≥2, so the OR was 70 not 16), and the band names carry reasoning a count cannot | One band of 16 hides a thread that opened last session; one band of 70 buries the recurring ones. **Ruled by the GM, 2026-08-25** |
