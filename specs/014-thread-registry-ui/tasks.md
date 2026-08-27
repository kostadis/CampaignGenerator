---
description: "Task list for 014-thread-registry-ui (CG#337)"
---

# Tasks: Thread Registry Surface

**Input**: Design documents from `specs/014-thread-registry-ui/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md) (D1–D21), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: INCLUDED. The plan names five new test files in its source-tree layout and six existing guards that must stay green (T003 enumerates the six); these are not speculative TDD tasks, they are the plan's own deliverables.

**Organization**: grouped by user story. US1 and US2 are both P1 and together form the MVP — a queue you cannot rule on leaves #337 exactly as broken as it is today (spec US2 rationale).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3 / US4 from [spec.md](./spec.md)

## Path Conventions

Repo root is the worktree `/home/kroussos/src/CampaignGenerator-worktrees/337-thread-registry-ui`. Engine under `pipelines/` + `campaignlib/`, web layer under `server/`, UI under `frontend/src/`, tests under `tests/`.

---

## Phase 0: Blocking GM rulings ⛔

**Purpose**: three questions this plan parked for a human and then quietly answered by writing tasks for one branch of each. Per the constitution's Authority clause and the standing rule that *an unanswered question is not a decision*, none of the dependent tasks could start until these were ruled. **All three are now ruled** — kept here as the record of what was decided and why.

- [x] T000a ~~Atomic ratify vs. server sequencing~~ — **RULED 2026-08-25: the atomic verb** (research D18). T032b builds it; T038 becomes a single subprocess call; the 207 partial-apply branch is gone
- [x] T000b ~~Shared `RunPanel` opt-out~~ — **RULED 2026-08-25: do not touch the shared component.** The Threads page gets its own run control; two behaviours deserve two buttons, and duplication gets refactored if and when it is real (research D19)
- [x] T000c ~~Corpus-resolution seam~~ — **RULED 2026-08-25: the preview lists files only, with no chapter numbers** (research D20). No new verb, no import, no second seam; the chapterless warning moves onto the candidate card and into the accept form

**Checkpoint**: ✅ all three ruled 2026-08-25 and recorded in research D18/D19/D20. Phase 1 may start.

---

## Phase 1: Setup

**Purpose**: make sure what you run is what you changed. Two of this repo's recorded scars live here.

- [ ] T001 Editable-install this worktree into the server's venv so the routes' `console_script()` lookups resolve: `uv pip install -e . --python "$VIRTUAL_ENV/bin/python"` (per `CLAUDE.md`; symptom when skipped is `Stream error — check terminal`)
- [x] T002 Confirm imports resolve inside the worktree and not the main checkout: `python -c "import campaignlib, pipelines; print(campaignlib.__file__, pipelines.__file__)"` must print paths under `.../337-thread-registry-ui/` (the editable `.pth` hardcodes the main checkout — a green run here otherwise proves nothing)
- [x] T003 Record the baseline across **all six** binding guards: `python -m pytest tests/test_projection_routes.py tests/test_projection_isolation.py tests/test_projection_config.py tests/test_thread_registry.py tests/test_layering.py tests/test_retrieve_render_isolation.py -q` green before any edit. `test_projection_isolation.py::test_no_docs_literals` covers `pipelines/grounding/thread_registry.py` itself — binding on T033's `--adjudication` default and T058's flags — and `test_thread_registry.py` has 10 existing tests over `propose`/`save_registry` that T006 and T032a change

---

## Phase 2: Foundational (blocks every user story)

**Purpose**: the config field, the machine-readable read verbs every route consumes, and the shared subprocess helper. **⚠️ No story work starts until T012.**

- [x] T004 Add `thread_adjudication: str = "docs/ensemble/thread_adjudication.json"` to `ProjectionStores` in `campaignlib/projection_config.py`, with a docstring line saying it is a store this service's own `thread_registry rule` writes (research D8)
- [x] T005 [P] Assert the addition is legal in `tests/test_projection_config.py`: `thread_adjudication` round-trips through `PUT`/`GET`, and `FORBIDDEN = {"corpus","sections","specs"}` still holds recursively
- [x] T006 Switch `save_registry` and the `propose` proposals writer in `pipelines/grounding/thread_registry.py` to `campaignlib.util.atomic_write_text` (research D12 — the surface turns hand-typed invocations into rapid button presses)
- [x] T007 Add a `list` subcommand emitting `{"version","threads","count"}` to `pipelines/grounding/thread_registry.py` per [contracts/cli.md](./contracts/cli.md)
- [x] T008 Add a `proposals` subcommand emitting `{"proposals","counts"}` to `pipelines/grounding/thread_registry.py`, returning the **full** unpaged set (research D16)
- [x] T009 Add `--json` to the existing `check` subcommand emitting `{"threads","problems"}` in `pipelines/grounding/thread_registry.py`, preserving exit 1 when `problems` is non-empty
- [x] T010 [P] Cover the three read verbs in `tests/test_thread_registry_json.py`: shapes, empty-registry case (absent file reads as `{"version":1,"threads":[]}`), and `check --json` exit code
- [x] T011 Add a `_thread_registry(*args)` helper to `server/routers/projections.py` that runs `console_script("thread_registry")` via `subprocess.run` and raises `HTTPException(400, detail=(stderr or stdout).strip())` on non-zero (research D7) — no path literal may appear in it
- [x] T012 Rewrite the module docstring of `server/routers/projections.py`: the current "There is no route for thread triage … would move a judgment checkpoint into the interface" becomes false here. State the reversal, its date, and the constraints preserving the principle — one candidate per ruling, every field shown before it is written, no bulk control (research D13, plan "Reversal of a prior scope call")

**Checkpoint**: engine is machine-readable, config declares all three stores, the router has its subprocess seam.

---

## Phase 3: User Story 1 — See what threads the corpus is offering (P1) 🎯 MVP part 1

**Goal**: the GM can harvest from an explicitly-chosen corpus and read the candidate queue, without a terminal. Nothing enters canon.

**Independent Test**: on a campaign with extraction output and no registry, open `/grounding/threads`, choose a corpus, harvest, and see the queue with per-candidate evidence — with `docs/thread_registry.yaml` still absent and the planning `threads` section unchanged.

### Routes

- [x] T013 [US1] `GET /threads/registry` in `server/routers/projections.py` — shells to `thread_registry list --json`, returns the payload verbatim
- [x] T014 [US1] `GET /threads/proposals` in `server/routers/projections.py` — shells to `thread_registry proposals --json`; **no** query, filter or paging parameter (research D16)
- [x] T015 [US1] `GET /threads/check` in `server/routers/projections.py` — shells to `thread_registry check --json`; returns **200** even when `problems` is non-empty (the CLI's exit 1 is data here, not a transport error)
- [x] T016 [US1] `GET /threads/corpus` in `server/routers/projections.py` — resolves explicit `pattern` params to a file list (`path`, `size`) and **nothing else**: no chapter numbers, so `chapter_of()` is neither imported nor wrapped in a verb, and plan's Principle V row stays true (GM ruling, research D20). Empty pattern list → **400**; matches confined to the workspace (`if cwd not in r.parents: continue`, mirroring `ensemble.py::list_chapters`). No config fallback — reading `ensemble.yaml` here would be a cross-service config read (research D5)
- [x] T017 [US1] `GET /threads/run/propose` (SSE) in `server/routers/projections.py` — `corpus: list[str] = Query(default=[])`, empty → **400** *"corpus is required — pass at least one --corpus glob."*; streams via `stream_subprocess`. **No `resolve_selection`, no backend flags, no `--model`** — this pass is deterministic

### Route tests

- [x] T018 [US1] `tests/test_thread_registry_routes.py`: the four read routes return their CLI payloads; `/threads/check` is 200 with problems present; a CLI non-zero becomes a 400 carrying the stderr text
- [x] T019 [US1] `tests/test_thread_registry_routes.py`: `/threads/run/propose` and `/threads/corpus` both refuse an empty selection with 400 (not 422) and no subprocess is spawned — Constitution X, mirroring `tests/test_ensemble_chapters.py`
- [x] T019a [US1] `tests/test_thread_registry_routes.py` — **the harvest writes no canon** (FR-006): run `/threads/run/propose` to completion against a fixture campaign and assert `docs/thread_registry.yaml` is byte-identical afterwards (and still *absent* when it started absent), while the proposals file did change. FR-006 is asserted today only in US1's prose Independent Test — the one requirement separating "harvest" from "ratify", checked by eye
- [x] T020 [P] [US1] Extend `tests/test_projection_routes.py::test_no_literals_in_router` coverage by adding a case asserting the new routes resolve `stores.thread_registry` / `stores.thread_proposals` / `stores.thread_adjudication` from `ProjectionConfigService.resolved()` rather than literals
- [x] T040a [US1] `tests/test_thread_registry_routes.py` — **no model call**: assert the argv built for `/threads/run/propose` contains no `--model`, `--backend` or `--endpoint`, and that the route never calls `resolve_selection` (FR-004, SC of zero-token operation). Currently claimed in T017's prose and asserted nowhere
- [x] T040b [US1] `tests/test_thread_registry_routes.py` — **no server-side query**: assert `GET /threads/proposals` declares no query or paging parameter and returns the full candidate count for a fixture with N proposals (research D16). Currently claimed in T014's prose and asserted nowhere

### Frontend

- [x] T021 [P] [US1] Build a dedicated harvest run control for `frontend/src/views/grounding/Threads.vue` — streams through the existing `connectSSE` client (`frontend/src/api/sse.ts`), renders the output, reports the exit code, and performs **no API-key check**, because the harvest cannot reach a model. (`RunPanel` blocks visibly, not silently — it disables the button and warns `ANTHROPIC_API_KEY not set` — but blocking a zero-token pass above a warning about a key it never uses is the wrong behaviour, not merely an unexplained one.) No `SelectionPanel` and no model/backend preview: neither means anything for a zero-token pass. **Do not modify `frontend/src/components/shared/RunPanel.vue`** (GM ruling, research D19)
- [x] T022 [P] [US1] Register `/grounding/threads` → `views/grounding/Threads.vue` in `frontend/src/router.ts`
- [x] T023 [P] [US1] Add a **Threads** entry beside **State Projection** in `frontend/src/components/layout/AppSidebar.vue`
- [x] T024 [US1] Create `frontend/src/views/grounding/Threads.vue` shell — page header, and the fetch-on-mount of registry + proposals + check, re-fetched after any successful write and never cached across a reload (FR-023)
- [x] T025 [US1] Registry region in `Threads.vue` — ratified threads grouped by `open`/`dormant`/`resolved`/`abandoned` with id, title, opened/closed chapters, tracker, aliases and log rows in chapter order; an empty registry renders as "no threads yet", never an error
- [x] T026 [US1] Health region in `Threads.vue` — `N thread(s), M problem(s)` from `/threads/check`, each problem listed, a clean registry saying so
- [x] T027 [US1] Harvest region in `Threads.vue` — corpus field (whitespace-separated patterns), **Resolve** listing the matched files, then **Run harvest** through the dedicated control from T021 (research D19)
- [x] T028 [US1] Queue region in `Threads.vue` — one card per proposal showing title, `all_titles`, chapters, `matches`, and evidence rows (chapter · fact · quote · source; a row with no `source` renders without one, never as "None"), with quotes rendered verbatim and visually distinct from the paraphrased fact (Principle IV). **A candidate with `chapters: []` is flagged on the card** — "no chapter recorded; you must supply one to accept" — which is where D4's warning now lives (research D20)
- [x] T029 [US1] Two named bands in `Threads.vue` (GM ruling, research D17a; FR-027) — **Recurring** (appears in ≥2 chapters) then **Single chapter, repeated** (`len(chapters) < 2` and ≥2 mentions — `< 2`, not `== 1`, so a chapterless candidate lands somewhere visible instead of the excluded tail; research D20), each under its own heading with its own count; within a band sort by chapters spanned, then evidence count, then title. Measured band sizes: 16/54 on OOTA, 2/19 on toee, 3/12 on Hillsfar
- [x] T030 [US1] Excluded-count line in `Threads.vue` — below both bands, in words: *"916 candidates mentioned exactly once are not shown — search or filter by chapter to reach them."* **Every count on the page (both bands and this one) MUST be computed from the loaded set, never a literal** (FR-028a) — they differ by an order of magnitude across corpora, and a hardcoded string is the exact defect this replaced. **Do not add a "Show all" control** (FR-028, research D16)
- [x] T031 [US1] Search + filters in `Threads.vue` — free-text over `title`, every `all_titles` entry, and evidence `fact`/`quote`; chapter filter; ruling filter. Composable, run in the browser over the whole payload (484 KB measured), covering **already-ruled** candidates, each badged with its ruling (FR-029, FR-030). **Bands, ordering, search and filters are presentation only: nothing here may rule on, merge, group or discard a candidate, including by similarity between titles (FR-031)**
- [x] T031a [US1] Guard FR-031 in `tests/test_threads_ui_absences.py` — fail the build if `frontend/src/views/grounding/Threads.vue` grows a fuzzy-match, clustering or "did you mean" helper, in the spirit of `tests/test_no_prefix_identity.py`. FR-031 is the one requirement the late renumbering left with no task at all
- [x] T031b [US1] Guard **FR-028a** in the same `tests/test_threads_ui_absences.py` — fail the build if either band count or the excluded count in `frontend/src/views/grounding/Threads.vue` is a numeric literal rather than an expression over the loaded set. A static check, so it needs no component harness (contrast T045a, whose question is still open). FR-028a is bolded in T030 and asserted nowhere: its three sibling absences each got a guard (T031a, T040b, T041) and the one that names the *specific defect this feature replaced* — a hardcoded "916" that is wrong on every other corpus — did not
- [x] T045a [US1] ~~Component test in `frontend/` asserting `Threads.vue` renders no control whose action reveals the excluded set wholesale~~ — **RULED 2026-08-26: deferred and tracked as #345.** The fork this task carried ("component test **or** downgrade the claim") turned out to be a repo-wide infrastructure question, not a page-level one: `frontend/` has *no* test runner at all — no vitest, no jest, no jsdom, no `@vue/test-utils`, zero `.spec`/`.test` files, and only `dev`/`build`/`preview` in `package.json`. Branch (a) was therefore "introduce frontend testing to this repo", which is disproportionate to decide as a side effect of one checkbox. **The claim is not left un-backed**: `tests/test_threads_ui_absences.py::test_no_show_all_control` statically guards the absence of the control, which is the regression that actually happens. What it cannot prove — that the *rendered* page exposes no such affordance, and that the counts track the filtered set as the GM types — is exactly what #345 scopes

**Checkpoint**: the GM can see everything the corpus offers and find any candidate. Canon is untouched.

---

## Phase 4: User Story 2 — Rule on a candidate: accept / reject / discuss (P1) 🎯 MVP part 2

**Goal**: one candidate, one ruling, one act — and the planning document's `threads` input finally exists.

**Independent Test**: from a US1 queue, accept one candidate, reject another, discuss a third; the registry gains exactly one thread with the confirmed fields, the rejected and discussed candidates do not return as pending after a re-harvest, and the discussed one is in the adjudication file with its evidence.

### Engine

- [x] T032 [US2] Add the `rule` verb to `pipelines/grounding/thread_registry.py` per [contracts/cli.md](./contracts/cli.md): `--norm` (exactly one — no `--all`, no repetition, no glob; FR-007 enforced by the argument shape), `--status {ratified|rejected|deferred}`, `--note`, `--thread`, rewriting the named proposal in place and preserving the file's `note:` preamble and every other proposal
- [x] T032a [US2] Narrow `propose()`'s short-circuit in `pipelines/grounding/thread_registry.py` to `rejected`/`deferred` only, so a `ratified` candidate falls through to the existing `matches`/`logged` filter and is re-offered carrying **only its unlogged chapters** (GM ruling, research D17b; FR-009a). Without this, accepting a thread at chapter 41 hides chapters 50–60 of that thread forever and FR-009 is unreachable through the surface. Keep the *"GM rulings are a one-way door"* comment, scoped to rejections
- [x] T032b [US2] Add the atomic `ratify` verb to `pipelines/grounding/thread_registry.py` per [contracts/cli.md](./contracts/cli.md) — `--norm KEY` plus `--plan FILE|-` (JSON: id/title/status/opened/tracker/notes/log[]), or `--emit-plan` to print the derived starting point and write nothing. Locate-or-create the thread, append every log row, mark the proposal `ratified` with `ruled_thread`, validate with `check_registry`, write **once** via `atomic_write_text`. `--plan` is required — there is deliberately no "accept as proposed" flag (FR-008, SC-004). When the proposal carries `matches`, ignore `id`/`title`/`opened` with a note and append to the matched thread (FR-009)
- [x] T032c [US2] `tests/test_thread_registry_ratify.py` — a plan with no `matches` creates the thread with exactly its log rows; a plan with `matches` appends and creates **no** second thread; a log row without a real chapter is refused with nothing written; a plan that would fail `check_registry` writes nothing; `--emit-plan` writes nothing and its output is accepted verbatim by `--plan -`; and the **registry-then-proposals order** holds — simulate a proposals-write failure and assert the thread exists while the candidate stays `pending` (research D18's stated seam)
- [x] T033 [US2] Adjudication bundle in `pipelines/grounding/thread_registry.py` — `rule --status deferred` **appends** to `stores.thread_adjudication` (creating `{"version":1,"entries":[]}` when absent), carrying the candidate's evidence with it so the file is self-sufficient (SC-007). Re-ruling a deferred proposal updates its status and leaves the bundle entry in place
- [x] T034 [US2] Refusals in `rule`: unknown `norm`, bad status, absent proposals file — exact messages per [contracts/cli.md](./contracts/cli.md)
- [x] T035 [US2] `tests/test_thread_registry_rule.py` — each status writes back correctly; other proposals and the preamble survive; `deferred` appends without overwriting a prior entry; re-ruling `deferred`→`ratified` keeps the bundle entry; every refusal exits non-zero with its message
- [x] T036 [US2] `tests/test_thread_registry_rule.py` — **the round-trip that matters**: `propose` → `rule` (one of each status) → `propose` again. Assert three distinct things, not one: a **rejected** and a **deferred** candidate keep their status and do not return as `pending` (SC-006); a **ratified** candidate's already-logged chapters are not re-proposed; and — the assertion that would have caught this defect — after adding a **later chapter** mentioning a ratified thread to the corpus, a re-`propose` **does** offer that chapter (FR-009a, research D17b)

### Routes

- [x] T037 [US2] `POST /threads/rule` in `server/routers/projections.py` — `{norm, status, note?, thread?}` → `thread_registry rule …`; CLI stderr becomes the 400 detail verbatim
- [x] T038 [US2] `POST /threads/ratify` in `server/routers/projections.py` — **one** call to `thread_registry ratify --norm <norm> --plan -`, forwarding the request body as the plan JSON on stdin. **200** on success, **400** carrying the CLI's own message on refusal. No 207, no per-step report, no partial-apply state — that is what the atomic verb bought (research D18)
- [x] T039 [US2] Route-edge validation for `/threads/ratify` **before the subprocess**: `log` non-empty and every `chapter` an `int >= 1`; `norm`/`id`/`title` non-empty. A chapterless accept is refused here naming the field, so the GM is not handed `check_registry`'s wording for a form problem (research D4)
- [x] T040 [US2] `tests/test_thread_registry_routes.py` — `/threads/ratify` spawns exactly **one** subprocess with `--norm` and `--plan -`, forwards the body verbatim on stdin, returns 200 on exit 0 and 400 with the CLI's stderr on non-zero; a chapterless body is refused at the route edge with no subprocess spawned at all
- [x] T041 [US2] `tests/test_thread_registry_routes.py` — **no bulk route exists**: assert the router exposes no endpoint accepting a list of `norm` values (SC-004's absence test, mirroring the shape of `test_no_literals_in_router`)
- [x] T041a [US2] `tests/test_thread_registry_routes.py` — **every write goes through the engine** (FR-018/FR-019): AST-parse `server/routers/projections.py` and assert no threads route body performs a write of its own — no `open(..., "w")`, `Path.write_text`, `yaml.safe_dump`, or `atomic_write_text` — so the registry, the proposals file and the adjudication bundle are only ever mutated by `_thread_registry`. Same shape as `test_no_literals_in_router`, and the reason `check_registry` cannot be bypassed by the surface (FR-020)

### Frontend

- [x] T042 [US2] Three per-card actions in `frontend/src/views/grounding/Threads.vue` — Accept, Reject, Discuss. **No select-all, no multi-select, no "accept remaining"** anywhere on the queue (FR-007)
- [x] T043 [US2] Ratification form in `Threads.vue` — pre-filled from the proposal (`id` = `norm`, title, `opened` = `min(chapters)`, one log row per chapter with `change` = `opened` then `advanced`, `summary` from that chapter's evidence fact, `quote` from its verified quote), every field editable, rows addable/removable, and **nothing written until Confirm** (FR-008)
- [x] T044 [US2] Matched-thread variant of the form in `Threads.vue` — when `matches` is set, thread fields render read-only naming the matched thread and only log rows are editable; `opened` is **empty and required** when `chapters` is `[]` (research D4)
- [x] T045 [US2] Reject and Discuss controls in `Threads.vue` — optional note, one POST each; Discuss additionally tells the GM where the adjudication file is, and the card stays visible and re-rulable (FR-012)
- [x] T046 [US2] Render every 400 `detail` verbatim in an error box on the control that caused it, using `ProjectionSections.vue`'s `.error-box` pattern — no swallowed errors, no tracebacks (FR-021)

**Checkpoint**: MVP complete. `grounding_sections build --doc planning --sections threads` now succeeds on a campaign driven entirely from the browser (SC-001).

---

## Phase 5: User Story 3 — Maintain the ratified registry (P2)

**Goal**: a thread's life after ratification does not send the GM back to a terminal one chapter later.

**Independent Test**: add a log row, resolve a thread with a closing chapter, add an alias, run the check — each visible on reload and in the rendered planning section.

- [x] T047 [US3] `POST /threads/log` in `server/routers/projections.py` — `{id, chapter, change, summary, quote?}` → `thread_registry log …`
- [x] T048 [US3] `POST /threads/status` in `server/routers/projections.py` — `{id, status, chapter?}` → `thread_registry set-status …`
- [x] T049 [US3] `POST /threads/alias` in `server/routers/projections.py` — `{id, alias}` → `thread_registry alias …`
- [x] T050 [P] [US3] `tests/test_thread_registry_routes.py` — each maintenance refusal reaches the caller as its CLI text: `error: no thread 'X'`, `error: resolving/abandoning needs --chapter`, `error: alias 'X' already matches thread 'Y'`, `error: refusing to save a registry that fails check`
- [x] T051 [US3] Maintenance controls in `frontend/src/views/grounding/Threads.vue` — Add log row, Change status (closing chapter required in the form *and* enforced by the CLI), Add alias; each a single POST with its refusal rendered inline
- [x] T052 [US3] Surface `check` problems per thread in `Threads.vue`, not only in the health region, so a broken thread is visible where it is edited

**Checkpoint**: the registry is maintainable end-to-end from the browser.

---

## Phase 6: User Story 4 — Get from the failed planning build to the fix (P3)

**Goal**: the GM's actual entry point is the Planning projection page; a surface they cannot find is half a fix.

**Independent Test**: on a campaign with no registry, the Planning projection table names the missing store on the `threads` row and links to the Threads page — before any build is attempted.

- [x] T053 [US4] Add `missing` (the subset of `inputs` that does not exist) to the per-section payload in `pipelines/grounding/grounding_sections.py`'s `list --json`, derived where `section_inputs()` already knows — the browser must not re-derive file existence (research D11). **`section_row()` has two return sites**: the `npc_outlook` branch returns early, before the branch that computes a local `missing`. Add the key at **both**, or the `per-npc` row arrives without it and T055's Inputs cell breaks on that row alone
- [x] T054 [P] [US4] Test the payload addition in `tests/test_grounding_sections.py`: `missing` is empty for a `fresh` section, names the store for a `no-input` one, and is **present (empty) on the `per-npc` row**
- [x] T055 [US4] `frontend/src/views/grounding/ProjectionSections.vue` — render the input **paths** in the Inputs cell instead of `s.inputs.length`, marking anything in `missing`
- [x] T056 [US4] `frontend/src/views/grounding/ProjectionSections.vue` — a `threads` row in `no-input` state shows *"no thread registry yet → Threads"* linking to `/grounding/threads` (FR-025)
- [x] T057 [US4] `frontend/src/views/grounding/ProjectionSections.vue` — when a build fails on a missing required section file, accompany the raw stderr with a line naming the section and, for `threads`, the same link (FR-026)

**Checkpoint**: no path through the UI dead-ends in a filename the UI cannot create (SC-002).

---

## Phase 6b: Run gating — ✅ MERGED (#342 / PR #343, 2026-08-27)

> **Gate resolved.** PR #343 merged into `main` on 2026-08-27. The conditional
> that stood here — "restore T057a–T057k if #343 is closed unmerged" — did not
> fire. T057a–T057k stay cancelled; **T057v is now runnable** once this branch
> has `main` merged in.
>
> **The merge was not clean, and the resolution is worth knowing.** While #343
> was open, `main` landed `8d49d4f` — *#341's narrow fix*: keep the UI-side
> predicate but key it on the resolved backend. That is the design #342
> superseded, so every conflict was the same shape: the branch removed a gate,
> `main` narrowed it. All were resolved in favour of deletion, per the ruling.
> Two things from `8d49d4f` were kept because they are improvements
> independent of the gate: ConnectionGraph's button now names the backend it
> will run on, and `SelectionPanel` emits `backend` alongside `compatible`.
> The `needsApiKey` computeds and their `selectionBackend` plumbing were
> removed as dead — they existed only to answer the question this change stops
> asking.
>
> **`main` also moved the constitution to v1.3.0** (`cace67c`), adding
> Principles XI–XIII. XI (*Parity is Bidirectional; Every CLI Capability Has a
> Face*) **strengthens** #343 rather than threatening it: the deleted gate made
> working dgx/openrouter/claude-code runs unreachable from the UI, which is
> exactly the "Orphaned Capability" XI names. See the plan's Constitution
> Check for this feature's own XI–XIII pass.

**Superseded, 2026-08-26.** This phase was written against #341's narrow fix: a
`BACKEND_CREDENTIAL` map plus a gate keyed on the resolved backend. The GM then
ruled on the wider design question (#342) — **delete the UI check entirely** —
and it shipped as PR #343 off `main`, not here.

**What landed instead**: `server/config.py::api_key_present` and the
`api_key_present` field on `GET /api/config/status` are deleted; `apiKeyPresent`
and its ten consumers are gone from the frontend; `_require_anthropic_credential`
refuses at the four entry points that reach the metered API
(`call_api`, `call_api_with_tools`, `stream_api`, `submit_batch`).
`tests/test_no_credential_gate.py` fails the build if the predicate returns.

**No `BACKEND_CREDENTIAL` map was built** — it existed to answer a pre-flight
question that is no longer asked. T057a–T057k are cancelled **in this shape** —
not deferred, but not unconditional either: see the merge gate above.

**Where each requirement is enforced**, so none of the three is left resting on
prose alone once #343 merges:

| Req | Enforced by (all in PR #343, none on this branch) |
|---|---|
| FR-032 (no interface gate) | `tests/test_no_credential_gate.py` — no `apiKeyPresent`/`api_key_present` under `frontend/src`, no `.vue` comparing `'ANTHROPIC_API_KEY'`, no `api_key_present` in `server/config.py` or in `get_status`'s dict |
| **FR-033** (the refusal names the credential *and* a way to proceed) | the same file's assertion that `_require_anthropic_credential`'s message names both `claude-code` and `dgx` — a refusal that only states the problem fails it |
| FR-034 (the check lives with the backend that needs one) | the same file's AST test that all four metered entry points (`call_api`, `call_api_with_tools`, `stream_api`, `submit_batch`) call the guard, that the three keyless adapters are never refused, and that `make_client()` still constructs with no key |

FR-033 had no enforcing task anywhere in this list before 2026-08-26; it is
covered, but by a file that arrives with the merge, not from here.

- [ ] ~~T057a–T057k~~ — **cancelled in this shape**; delivered by PR #343 (open). Restore only if #343 is closed unmerged
- [ ] T057v (SC-012) Verify only, once #343 is merged: with `env -u ANTHROPIC_API_KEY ./startup`, build the planning document's `threads` section from the State Projection page and confirm it runs. This is quickstart Scenario 5, which stays — the scenario is still the right check, only its explanation changed

**Rebase note**: if this branch predates #343, rebase before implementing —
`RunPanel.vue` and `stores/config.ts` are touched by both, and T021's dedicated
Threads control still stands (D19 is unaffected: no run control asks about
credentials any more, which is the strongest possible form of "the harvest
control checks nothing about API keys").

---

## Phase 7: Polish & Cross-Cutting

- [x] T058 [P] Add `--min-chapters` / `--min-evidence` to `propose` in `pipelines/grounding/thread_registry.py`, **both defaulting to `1`** (today's behaviour). They exist for CLI users; the web surface does not send them and filters the view instead (research D15) — a default that dropped 970 of 986 would be software making a scope decision
- [x] T058a Re-point the `emerging` section's GM-facing blurb in `pipelines/grounding/grounding_sections.py:280` — it currently tells the GM to *"ratify, alias, or reject via thread-triage"*, a skill that does not exist (research D14); it should name the Threads surface. While there: `SPECS["planning"]` declares `Section("emerging", source="thread_proposals")`, so `thread_registry.py:23` and the proposals-file preamble are wrong to say *"nothing downstream reads this file"* — correct both, and note in the howto that a triage sitting marks the planning `emerging` section stale via `inputs_sha`
- [x] T059 [P] Document the surface in `docs/cli/state_projection_howto.md` — **and correct line 282**, which still reads *"It deliberately does **not** do: thread triage, …"*. That is the second live assertion of the reversed scope call; T012 covers only the router docstring — the harvest → rule → build sequence, what "discuss" produces, and every refusal decoded, in the task-oriented register that file already uses
- [x] T060 [P] Add the Threads page to `docs/web/web_ui.md`
- [x] T061 [P] Add `stores.thread_adjudication` to the field tables in `docs/config/schema.md` and `docs/config/values.md`
- [x] T062 [P] Add the Threads page + `thread_registry`'s new verbs to the project-structure and docs tables in `CLAUDE.md`, and to the doc index in `docs/README.md`
- [ ] T063 Run [quickstart.md](./quickstart.md) end to end — Scenario 0 (reproduce), 1, 2, 3, 4 — on `~/toee/toee` and `~/out-of-the-abyss/out-of-the-abyss`, including the negative tests (no bulk control, no "Show all", rejected candidates still findable) **Scenario 5 (run gating, with `env -u ANTHROPIC_API_KEY`)**, and a CLI↔UI parity step covering SC-005/SC-009: ratify a thread at the CLI, reload the page, confirm the identical state; then ratify one through the page and confirm `thread_registry list --json` matches
- [x] T064 Re-run the four guards from T003 plus the full suite: `python -m pytest tests/ -q`. Note `tests/test_no_credential_gate.py` arrives with PR #343, not from this branch — if it is red here, rebase before investigating
      **Run 2026-08-26: 3925 passed, 190 skipped, 4 failed — none of them this feature's.** Three (`test_configure_mcp`, `test_mempalace_client`, `test_provenance_mcp`) fail identically on `main` and are pre-existing. The fourth (`test_extract_facts::test_cli_parallel_fully_cached`) is a worktree artefact: `config/wiring.yaml` is gitignored, so `dgxlib.resolve_model_config(None)` had nothing to read; it passes once the file is copied in. `test_no_credential_gate.py` is absent, as expected — it arrives with #343.
- [x] T065a [P] ~~File the follow-on research D19 names~~ — **FILED as #341**, and then **pulled into scope**: `RunPanel`'s gate keys on `ANTHROPIC_API_KEY` alone, so it blocks both zero-token section builds and every run on the dgx/openrouter/claude-code backends. GM ruling 2026-08-26 — it gates SC-001. First scoped here as Phase 6b; then #342 ruled the predicate away entirely and it moved to PR #343 off `main` (**merged 2026-08-27**)
- [x] T065 **FILED as #344** — the follow-on research D15 names: the extraction lens's `thread` subject is doing double duty as "what this fact is about" and "what thread this belongs to", and is not good at the second — 986 candidates from 62 chapters. Upstream of this feature, out of its scope

---

## Requirement Coverage

Every FR and SC mapped to the task(s) that deliver or verify it. Built by
re-deriving the inventory from `spec.md`, not by trusting the task prose — a
requirement named only inside a task's description was invisible to the earlier
ID-based sweeps, which is how FR-006, FR-018 and FR-028a stayed uncovered.

| Req | Task(s) |
|---|---|
| FR-001 surface exists | T022, T023, T024 |
| FR-002 harvest from the surface | T021, T027 |
| FR-003 refuse an empty corpus | T017, T019 |
| FR-004 deterministic, zero tokens | T017, **T040a** |
| FR-005 per-candidate evidence | T028 |
| FR-006 harvest writes no registry | **T019a** |
| FR-007 exactly three rulings | T032, T042, T041 |
| FR-008 every field shown before write | T032b, T043 |
| FR-009 matched thread appends | T032b, T044 |
| FR-009a later chapters keep surfacing | T032a, T036 |
| FR-010 reject recorded durably | T032, T035 |
| FR-011 discuss recorded likewise | T033, T045 |
| FR-012 discussed stays visible | T045 |
| FR-013 rulings survive re-harvest | T036 |
| FR-014 add a log row | T047, T051 |
| FR-015 change lifecycle status | T048, T051 |
| FR-016 record an alias | T049, T051 |
| FR-017 run the consistency check | T015, T026, T052 |
| FR-018 writes go through the engine | **T041a** |
| FR-019 rulings/exports likewise | T037, T038, **T041a** |
| FR-020 refuse an inconsistent write | T032b, T050 |
| FR-021 refusals reach the GM verbatim | T034, T046 |
| FR-022 no auto-ratify / merge / infer | T031a, T041 |
| FR-023 interface holds no state | T024 |
| FR-024 no-input row names its store | T053, T054, T055 |
| FR-025 `threads` row links to the surface | T056 |
| FR-026 failed build names the section | T057 |
| FR-027 two named bands | T029 |
| FR-028 excluded tail, no "Show all" | T030, T045a (static guard; rendered-page proof tracked as #345) |
| FR-028a counts computed, never literal | **T031b** |
| FR-029 reachable by query | T031 |
| FR-030 search covers ruled candidates | T031 |
| FR-031 presentation only | T031a |
| FR-032/033/034 credential gating | PR #343 only — see the Phase 6b table |
| SC-001 zero → assembling planning doc | T063, T057v |
| SC-002 no dead-end paths | T053–T057, T063 |
| **SC-003 60 s per ruling; band in one sitting** | **none — open GM ruling** |
| SC-004 no thread by a single click | T032b, T041, T043 |
| SC-005 CLI/UI produce identical content | T063 |
| SC-006 rulings persist across re-harvest | T036 |
| SC-007 adjudication file is self-sufficient | T033 |
| SC-008 refusals shown, no tracebacks | T034, T046, T050 |
| SC-009 nothing lost by working at the CLI | T063 |
| SC-010 bands + excluded count visible | T029, T030, **T031b** |
| SC-011 any candidate reachable by name | T031 |
| SC-012 keyless machine can start runs | T057v (PR #343) |

**SC-003 is the single uncovered row.** It is a timed observation, not a
buildable behaviour, and the two honest options — instrument it as a step in
T063, or mark it explicitly non-gating — are a GM call. It is left visibly
empty rather than quietly satisfied by a nearby task.

---

## Dependencies & Execution Order

### Phase dependencies

- **Blocking rulings (T000a–T000c)** — ✅ closed 2026-08-25. Their outcomes are folded into T016, T021, T032b/T032c, T038 and T040; nothing is blocked
> **Read the ranges as inclusive of their suffixed tasks.** Several were added
> after the first numbering (T031a/T031b, T032a–T032c, T040a/T040b, T041a,
> T045a, T058a), and a bare `T013–T031` silently drops five of them. They are
> named explicitly below for that reason.

- **Setup (T001–T003)** — depends on the rulings being recorded
- **Foundational (T004–T012)** — depends on Setup; **blocks every story**
- **US1 (T013–T031, plus T031a, T031b, T040a, T040b, T045a)** — depends on Foundational. Note T040a/T040b sit in US1's route-test block despite their numbers, and T045a in its frontend block
- **US2 (T032–T046, plus T032a, T032b, T032c, T041a)** — depends on Foundational; its frontend tasks (T042–T046) depend on US1's page existing (T024–T028)
- **US3 (T047–T052)** — depends on Foundational; T051–T052 depend on T024
- **US4 (T053–T057)** — depends on Foundational only. **Fully independent of US1–US3** and shippable alone. `T057` (the failed-build message) is a US4 task; **`T057v` is not** — despite the shared stem it belongs to Phase 6b and is gated on PR #343
- **Run gating (Phase 6b)** — no implementing tasks here; delivered by PR #343 off `main` (open). **SC-001 depends on that merge.** Only T057v (verify) is sequenced in this list, and it cannot run until #343 lands
- **Polish (T058–T065)** — after the stories you intend to ship

### Story dependencies

- **US1** is standalone once Foundational lands.
- **US2** is engine-independent of US1 (T032–T041 need nothing from it) but its UI lives on US1's page. Ship them together — that is the MVP.
- **US3** and **US4** are independent of each other and of US2.
- **Run gating** is independent of all four and lives on another branch. It shares no file with US1–US4 — the Threads page's own control (T021) has no gate to fix, by ruling D19.

### Same-file serialisation (these are NOT parallel)

- `pipelines/grounding/thread_registry.py`: T006 → T007 → T008 → T009 → T032 → T032a → T032b → T033 → T034 → T058 (and T058a's docstring/preamble corrections)
- `server/routers/projections.py`: T011 → T012 → T013–T017 → T037–T039 → T047–T049
- `frontend/src/views/grounding/Threads.vue`: T024 → T025–T031 → T042–T046 → T051–T052 (T031a and T045a are separate test files and may run alongside)
- `tests/test_thread_registry_routes.py`: T018 → T019 → T019a → T040a → T040b → T041 → T041a → T050
- `frontend/src/views/grounding/ProjectionSections.vue`: T055 → T056 → T057

### Parallel opportunities

- T005 ∥ T010 (different test files)
- T013 ∥ T014 ∥ T015 only if written as one edit pass; otherwise serialise per the rule above
- T018 ∥ T019 ∥ T020 (test files, no shared state)
- T021 ∥ T022 ∥ T023 (three different frontend files, none touching `Threads.vue`)
- T035 ∥ T031a ∥ T031b — but T031a and T031b share `tests/test_threads_ui_absences.py`, so they are one edit pass, not two concurrent ones. T036/T040/T040a/T040b/T041/T041a all share `test_thread_registry_routes.py` or `test_thread_registry_rule.py` — one edit pass each, not concurrent
- T047 ∥ T048 ∥ T049 as a single edit pass to the router
- T059 ∥ T060 ∥ T061 ∥ T062 (five docs, no overlap). T058 and T058a both edit engine files — serialise them

### Parallel example: US1 frontend scaffolding

```bash
Task: "Build the dedicated harvest run control in frontend/src/views/grounding/Threads.vue (T021 — NOT a prop on the shared RunPanel; see ruling D19)"
Task: "Register /grounding/threads in frontend/src/router.ts"
Task: "Add the Threads sidebar entry in frontend/src/components/layout/AppSidebar.vue"
```

---

## Implementation Strategy

### MVP (US1 + US2)

1. Phase 1 Setup → Phase 2 Foundational
2. Phase 3 US1 → **stop and validate**: harvest on `~/toee/toee`, confirm 415 candidates, 2 shown by default, search reaches the rest, `docs/thread_registry.yaml` still absent
3. Phase 4 US2 → **stop and validate**: accept one candidate, then `grounding_sections build --doc planning --sections threads` succeeds
4. That is SC-002 met and #337 closed. **SC-001 needs Phase 6b too** — step 3 validates at the command line; on a machine with no `ANTHROPIC_API_KEY` the same build cannot be started from the page until the gate is fixed

### Incremental after MVP

5. US3 — the registry becomes maintainable rather than write-once
6. US4 — the Planning page stops being a dead end for the *next* first-time campaign
7. Phase 6b — nothing to build; confirm PR #343 merged, then run T057v. Until it does, US4's signpost leads to a button a keyless machine cannot press
8. Polish — docs, the CLI threshold flags, the quickstart run, the upstream follow-on

### If you only have time for one slice

**US4** is a legitimate ship: it does not close #337, but it converts the raw subprocess error into a signpost, and it depends on nothing but Foundational. Its value is capped until PR #343 merges — on a keyless machine the signpost still leads to a button that will not start.

---

## Deferred, and why

Four tasks are deliberately NOT done. None is blocked on work in this repo.

- **T001 (editable-install this worktree)** — **not run on purpose.** The
  editable `.pth` in `~/.venvs/main` hardcodes
  `/home/kroussos/src/CampaignGenerator`, so installing this worktree would
  repoint the SHARED venv and make the user's running server execute worktree
  code without saying so. `pytest` does not need it (the new fixtures pin
  `PYTHONPATH` to this tree, and `tests/conftest.py` inserts `REPO_ROOT`), so
  everything testable was tested without it. It IS required before T063's
  browser run, because `console_script("thread_registry")` resolves against
  the venv and would otherwise run MAIN's engine — which has none of the new
  verbs. Run it deliberately, then reinstall main when finished.
- **T045a** — **ruled 2026-08-26: deferred, tracked as #345.** The static
  guard in `tests/test_threads_ui_absences.py` stands as interim backing; the
  rendered-page proof waits on `frontend/` having any test runner at all,
  which it does not today.
- **T057v** — verify-only, gated on PR #343 merging. Unrunnable until then.
- **T063** — the quickstart end-to-end run on `~/toee/toee` and
  `~/out-of-the-abyss/out-of-the-abyss`. Needs T001 plus a browser, and its
  Scenario 5 needs #343.
- **T065** — **done: filed as #344** (2026-08-26), on the GM's instruction.
  Re-measured against both live corpora before filing; the 2026-08-25 figures
  reproduce exactly (986/16/70 and 415/2/21).

## Notes

- **The absences are requirements**, and each now has an enforcing task — most did not until successive analysis passes caught them: no bulk ruling control (T041), no "Show all" (T030 + T045a), no server-side query on `/threads/proposals` (T014 + **T040b**), no model call anywhere (T017 + **T040a**), no similarity-based grouping (T031 + **T031a**), no literal counts (T030 + **T031b**), no registry write during a harvest (T027 + **T019a**), no write bypassing the engine (**T041a**). None is a missing feature.
- **Requirement coverage is now complete for FR-001–FR-031.** FR-032–FR-034 are covered by PR #343's `tests/test_no_credential_gate.py`, not by anything on this branch (see the Phase 6b table). **SC-003 is the one success criterion with no verification task at all** — it is a timed observation ("under 60 seconds per ruling", "clear the recurring band in one sitting"), and whether to instrument it in T063 or mark it non-gating is an open GM ruling, not an oversight to be silently closed.
- Every path in a route comes from `ProjectionConfigService.resolved()` — `tests/test_projection_routes.py` AST-parses the router and fails on any `docs/`-shaped literal.
- Nothing under `pipelines/` may import `server.*` (`tests/test_layering.py`).
- **Phase 6b is a defect fix, not a story**, and it is no longer built here — the GM's second ruling (#342) deleted the credential predicate rather than correcting it, and it ships as PR #343. D19 is untouched and in fact strengthened: no run control anywhere asks about credentials now, so the Threads page's own control differs from `RunPanel` only in the ways D19 named.
- Commit after each task or logical group; stop at any checkpoint to validate the story on its own.
