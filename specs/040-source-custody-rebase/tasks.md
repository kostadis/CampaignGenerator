---
description: "Task list for spec 040: reviewed source-custody rebase"
---

# Tasks: Reviewed Source-Custody Rebase for Corrected Historical Summaries

**Input**: `specs/040-source-custody-rebase/`: plan.md, spec.md, research.md (R1–R10), data-model.md, contracts/cli.md, contracts/http.md, quickstart.md

**Tests**: REQUIRED. The issue's acceptance criteria and the spec's SC-001..SC-008 are test statements. Tests use the synthetic git-initialised fixture only, with no private campaign and no model endpoint. Model calls use the existing injectable invoker with a deterministic stand-in. **Never mock `claims select/check`, review bindings or `promotion.publish`.**

**Conventions every task must follow**:
- **Paths and process.** Paths are repo-relative to the worktree `/home/kostadis/src/CampaignGenerator/.claude/worktrees/040-source-custody-rebase`. Run tests with `python -m pytest`, from the worktree.
- **Models.** New pydantic models use `ConfigDict(extra="forbid")` and are NOT subclasses of `StrictPromotionModel`.
- **Refusals.** Raise `DeltaRefusal(msg, EXIT_*)` from `pipelines/summary_native/delta/errors.py`. Exit codes: 1 refusal, 2 usage, 3 stale, 5 recovery.
- **Flags.** Use the existing family flags in `delta/cli.py` (`--source`, `--plan`, `--reviewer`, `--decision`, `--backend`, `--model`, `--json`, `--force`). Never default a reviewer or an approval, and never offer "all".
- **No model calls** in any module except `rebase propose`'s handler. Add new no-LLM modules to the AST no-LLM guard used by `tests/test_delta_no_llm_in_records.py` (or its equivalent list).
- **Authored files are read-only.** Never write `docs/summaries/*.md` (authored summaries) or anything under an existing `docs/grounding/generations/<gid>/`.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

- [x] T001 Create the synthetic rebase fixture builder in `tests/_rebase_fixture.py`, extending `tests/_delta_us2.py` / `tests/_delta_run_support.py`. It must: `git init` the campaign; commit original summaries for chapters 1–5; publish an active generation through chapter 5 through the real promotion path (as existing delta e2e tests do); create a pending chapter-6 delta plan with the NPC product published for ≥2 members (receipts on disk) and grounding staged; then commit the corrections listed in `quickstart.md` (ch2 payment terms, ch3 removed contradiction, ch4 "unaware" → "not yet told", ch5 prisoner count also carried in the ch6 candidate, ch1 whitespace-only in an uncited region, as a separate builder variant). Expose helpers returning the paths, the old/new sha256 values, the plan ids and the generation id.
- [x] T002 [P] Add a smoke test `tests/test_rebase_fixture.py` asserting that the fixture reproduces the blocker: real `claims select` for the pending plan raises `CLAIMS_SOURCE_STALE`.

---

## Phase 2: Foundational (blocks all stories)

- [x] T003 Extend `DeltaPlan` in `pipelines/summary_native/delta/plan.py` with optional `kind: Literal["delta","rebase"] = "delta"` and `rebase_id: str | None = None`. `plan_digest` and `_derive_plan_id` must omit both when they hold defaults, so existing digests are byte-stable (R10).
- [x] T004 Extend `DeltaLineageRecord` in `pipelines/summary_native/delta/lineage.py` with an optional `rebase` block (data-model.md), omitted from serialization and digest when None.
- [x] T005 [P] Add `tests/test_rebase_digest_stability.py`. Golden test: a plan and a lineage record built the pre-feature way have the identical `plan_digest`, `lineage_bytes` and id before and after T003/T004 (hard-code the expected hex computed from the current code at `3c3fbb9`).
- [x] T006 Implement `pipelines/summary_native/delta/custody_store.py` (R2):
  - **Store.** `put(root, data) -> sha256` is write-once under `docs/summaries/delta/custody/objects/<sha256>`, atomic via tmp+replace; an existing object is verified, never rewritten. `get(root, sha) -> bytes | None` verifies on read.
  - **Providers.** `recover(root, chapter, path, expected_sha, explicit: Path | None) -> (bytes, provider, detail)` tries snapshot → git → explicit file. The git provider uses a read-only subprocess (`git -C <root> rev-list --objects --all`, plus `git cat-file -p <blob>`, filtered by matching path history first, then any blob of the right size), and accepts only bytes whose sha256 equals the pin.
  - **Refusals.** `REBASE_OLD_BYTES_UNAVAILABLE` (lists the providers tried) and `REBASE_OLD_BYTES_MISMATCH` (explicit file hashes wrong; shows expected and actual).
  - This is the only module that shells out to git.
- [x] T007 [P] Add `tests/test_rebase_custody_store.py`: write-once and idempotent put; a corrupted object is refused on get; git recovery by exact hash; no-repo, wrong-file and missing cases; and corrected current summaries plus git HEAD unchanged after recovery.
- [x] T008 Make `CLAIMS_SOURCE_STALE` actionable in `pipelines/summary_native/claims/selection.py` (`_discovered_rows` around line 127, and `_read_bound` around line 222). The message must include the chapter, path, expected sha256, actual sha256 or `missing`, and the hint `run: summary_native delta rebase inspect`. Keep the code unchanged. Test in `tests/test_rebase_stale_message.py`, using the fixture.
- [x] T009 Register the new leaves in `pipelines/summary_native/delta/cli.py`: `rebase inspect`, `rebase prepare`, `rebase show`, `rebase propose`, `rebase repair` and `rebase decide`, plus `plan rebind`. Note that `plan` is currently a leaf, not a group, so add `rebind` under a new `plan-rebind` leaf name or restructure carefully. Keep `delta plan` working, and prefer the leaf name `"plan rebind"` with a parser that does not break `delta plan --source…`; if that conflicts with argparse, use `"rebind"` and record the deviation in contracts/cli.md. Add `hold` to `DECISIONS`. Add each leaf's flags per contracts/cli.md. Create `pipelines/summary_native/delta/cli_rebase.py` with stub handlers registered into `DELTA_HANDLERS`, imported where the other `cli_*` modules are. Update `tests/test_delta_cli_family.py` expectations.

**Checkpoint**: the fixture reproduces the blocker; digests are stable; the store works; the parser accepts the new leaves.

---

## Phase 3: User Story 1: Inspect and approve a bounded repair (P1) 🎯 MVP

**Goal**: The GM sees every stale pin, prepares a rebase with verified old bytes, sees impact, writes or receives repairs, and records decisions. Semantic changes cannot be adopted by hash alone.

**Independent test**: On the fixture, inspect lists chapters 2–5 with no writes and no model calls. Prepare creates snapshots and an impact set. `adopt-unaffected` for ch5 is refused. Whitespace-only ch1 is adopted unaffected with zero model calls.

- [x] T010 [US1] Implement `pipelines/summary_native/delta/rebase_inspect.py`. `inspect(root, plan_id=None) -> StaleCustodyReport` binds the active generation through `baseline.bind`/the `current` link (never the newest dir), walks `baseline._custody_rows` (make it return or expose which generation pinned each row, without changing its existing return contract for current callers: add a sibling function if needed), hashes every row (counted as `integrity_reads`), and probes old-byte availability through `custody_store` without writing. With `--plan`, also report that plan's baseline ref. No writes, no model.
- [x] T011 [US1] Implement `pipelines/summary_native/delta/rebase_impact.py` (R4):
  - **Entries.** Parse scene/entry sections of old and new bytes (reuse the `[ch NNN / ENTRY]` entry vocabulary; entries such as `016.03` and heading-named entries, following how `claims/selection.py` and `custody_resolver_for_generation` treat entries) and mark each changed/removed/unchanged with byte spans.
  - **Affected lines.** Scan the baseline generation's four published documents (and, when a pending plan is given, its `candidates/*.md`) for citations into selected chapters, and classify each line affected/unaffected/whole_chapter. Use `line_id = <doc>#<sha256(line)[:12]>@<occurrence>`.
  - **Annotations.** Find retained claims check annotations in the generation's `metadata/records` whose `source_sha256` equals the old digest and whose span intersects a change.
  - **Unknown members.** List `canon_events_timeline.md` and `reference/**` members as unknown when they cite a selected chapter or carry no citations.
  - **Follow-ups.** List `docs/npcs/*.md` citing a selected chapter as follow-ups.
  - Produce an `ImpactSet` with `impact_sha256`. Deterministic, no model.
- [x] T012 [US1] Implement `prepare` in `pipelines/summary_native/delta/rebase.py`:
  - **Selection.** Validate that every `--source` is stale per inspect (`REBASE_NOTHING_TO_REBASE`, exit 2, otherwise; empty selection exit 2). Recover and snapshot the old and current bytes.
  - **Plan.** Create the rebase plan through `plan.create_plan(..., grounding_baseline_ref=<active ref>)` with `kind="rebase"`, `products=("grounding",)` and the derived `rebase_id`; save r1.
  - **Records.** Write `rebase/<id>/{inspection,snapshots,impact}.json` atomically. `--for-plan` includes that pending plan's candidates in the impact.
  - **Idempotency.** Identical inputs re-run as a no-op returning the same ids.
- [x] T013 [US1] Implement GM repairs and holds:
  - `repair_add(root, plan_id, line_id, text, reason, reviewer)` in `rebase.py` creates a grounding edit proposal through `pipelines/summary_native/delta/grounding_edits.py`'s existing proposal model (origin `gm`, exact before = the affected line's bytes, category `source_correction`, evidence = the chapter diff ref).
  - In `grounding_edits.py`, support decision `hold`: a held edit produces no replacement, and instead appends exactly one marker line `⚠ held: superseded by correction to ch NNN — see rebase <id>` directly under the original line, which itself stays byte-identical.
  - Existing overlap/stale/duplicate validation must apply unchanged.
- [x] T014 [US1] Implement `rebase propose` in `rebase.py` / `cli_rebase.py`. The model input is only the affected lines, the selected chapters' entry diffs and the affected annotations, through the existing delta model invoker (`campaignlib` seam, `--backend/--model` required per family rules). Output is grounding edit proposals validated by the host (unknown line ids rejected). Never approves. Record the model input sources and call count for the receipt.
- [x] T015 [US1] Implement `rebase decide` in `rebase.py`, writing `rebase/<id>/decisions-r<N>.json` (append-only, reviewer required, reason required for `reject`/`attested-unaffected`). Validation per data-model.md:
  - **`REBASE_SEMANTIC_CHANGE`:** `adopt-unaffected` on a chapter with any affected line or annotation; list them.
  - **`REBASE_UNRULED_IMPACT`:** `adopt-with-repairs` while an affected line lacks an approved repair or a hold.
  - **Unknown members:** each needs a ruling.
  - **`reject`:** removes the chapter from the rebase (it stays stale; a plan revision drops it from sources).
  - **Binding:** decisions bind `snapshots_sha256`, `impact_sha256`, `baseline_ref` and `edits_sha256`.
- [x] T016 [US1] Implement `rebase show` (writes `rebase/<id>/review.md`, and `--json` returns the same data): the per-source unified diff, affected lines with repair/hold/decision state, unknown members, follow-up consumers, and the decisions so far.
- [x] T017 [US1] Wire handlers in `pipelines/summary_native/delta/cli_rebase.py` for inspect, prepare, show, propose, repair and decide, with `--json` output shaped as `{ok, code, message, data}`, matching the other delta handlers.
- [x] T018 [P] [US1] Tests in `tests/test_rebase_us1.py`:
  - inspect lists exactly chapters 2–5 (SC-008), with no file writes (snapshot the tree before and after) and model calls = 0;
  - prepare leaves summaries byte-identical and snapshots verify;
  - impact flags the ch2/3/4/5 cited lines and marks the timeline unknown;
  - `adopt-unaffected` on ch5 → exit 1 `REBASE_SEMANTIC_CHANGE` (SC-002);
  - a hold produces the marker and keeps the line;
  - the ch1 whitespace variant is adopted unaffected with zero model calls (SC-003);
  - a missing reviewer → exit 2;
  - an unselected stale chapter stays reported by inspect.

**Checkpoint**: US1 is independently demonstrable at the CLI.

---

## Phase 4: User Story 2: Apply the reviewed repair and finish the pending delta (P1)

**Goal**: A decided rebase publishes a new generation through the unmodified gates. The pending delta is rebound, NPC results are preserved, and chapter 6 publishes.

**Independent test**: The fixture end to end (quickstart scenarios 6–7) reaches an active ch6 generation, with old generations byte-identical and NPC publish count 0 during resume.

- [x] T019 [US2] Candidate build for rebase plans in `rebase.py`: apply only approved repairs and holds (via `grounding_edits` reconstruction) to the bound baseline's published documents, then call `grounding_candidates.materialize` after the existing `grounding check` runs. `build_lineage` (in `grounding_candidates.py`) fills the lineage `rebase` block for `kind=="rebase"` plans: sources with old/new sha and snapshot refs, the decisions ref/sha, and repaired/held/attested/unchanged members. Refuse (`REBASE_UNRULED_IMPACT`) if the decisions are missing, stale or incomplete.
- [x] T020 [US2] Gap-labelled staging in `grounding_candidates.stage_for_promotion`: for `plan.kind=="rebase"`, skip the contiguity refusal, and write `manifest.json` with `kind:"custody_rebase"`, `range.gaps` = the unselected chapters in `since..until`, and `files` = the selected chapters only, at their current sha256. Keep the `kind=="delta"` behavior byte-identical (existing tests must stay green). Make sure the staged-tree digest covers the new fields.
- [x] T021 [US2] Verify, and fix if needed, that the real `summary_native claims select|check` and `promotion.publish` accept the rebase bundle:
  - citations into selected chapters resolve from the staged range `files[]` (new sha);
  - other citations resolve through `delta_inherited_custody` to the parent chain;
  - `_custody_rows` for the new generation yields the new pins for the selected chapters and the parent's pins elsewhere.

  Any change must keep spec 039 tests green. Do not bypass gates.
- [x] T022 [US2] Extend `pipelines/summary_native/delta/receipt.py` with the rebase receipt fields (data-model.md RebaseReceipt), populated from the inspection, snapshot, impact, proposal and decision records and the apply result. Report `integrity_reads`, `parsed_historical`, `cached_evidence_reused`, `model_input_sources`, `model_calls`, `unselected_stale_remaining` and `followup_consumers` separately.
- [x] T023 [US2] Implement `pipelines/summary_native/delta/rebind.py` and its handler:
  - **Precondition.** `rebind(root, plan_id, baseline_generation)` requires that generation to be active and its lineage parent to equal the plan's current `grounding_baseline_ref` (`REBIND_NOT_CHILD` otherwise).
  - **Plan.** Write plan revision r+1 with the new `grounding_baseline_ref`.
  - **Grounding edits.** Re-apply approved grounding edits whose exact `before` bytes exist in the new baseline documents and do not overlap a repaired or held line; mark the others stale (they need re-deciding).
  - **Invalidation.** Delete nothing, but record as invalidated: candidates, the check report, grounding review bindings and the publication preview.
  - **Record.** Write `docs/summaries/delta/plans/rebind-<plan>-r<N>.json`. Idempotent on identical input.
- [x] T024 [US2] NPC carry rule in `pipelines/summary_native/delta/review_binding.py` `_npc_stale_reasons` (around line 275). The plan-digest mismatch is NOT stale when a rebind record for this plan lists `binding.plan_sha256` as `carried_from` AND the NPC projection (sources, npc_baselines, products, backend, model) of the old and current revisions is byte-equal. Any other difference is stale. Also make sure `run resume` skips members with existing receipts (verify; don't re-publish).
- [x] T025 [US2] End-to-end test `tests/test_rebase_e2e.py` (quickstart 1, 6, 7):
  - **Before.** The fixture is blocked.
  - **Rebase.** Prepare → repairs/holds → decide → `grounding check` → `grounding preview` → real claims select/check → exact signoffs via the existing review handoff path used by `tests/test_delta_grounding_e2e.py` → `grounding apply`. The new generation is active and its parent is the old one. A recursive sha256 map of every pre-existing `docs/grounding/generations/*`, `activations/*`, review records, receipts and `docs/npcs/*` is identical before and after (SC-004).
  - **Resume.** Rebind the pending plan. NPC bindings stay fresh and receipts are unchanged. The ch6 grounding check surfaces the old prisoner count (the candidate is flagged, not carried as verified). After repair, ch6 grounding publishes, and the NPC publish call count is 0.
  - **Receipt.** The unselected historical parse/model counts are 0 (SC-007).
- [x] T026 [P] [US2] Negative tests in `tests/test_rebase_rebind.py`: rebind to a non-active or non-child generation → `REBIND_NOT_CHILD`; an NPC-relevant plan change after rebind stales the NPC binding; an overlapping ch6 edit becomes stale; identical rebind is a no-op.

**Checkpoint**: The production blocker shape is fully resolvable at the CLI.

---

## Phase 5: User Story 3: Recover an interrupted repair and repeat it safely (P2)

**Goal**: Interrupted application is recoverable, retries are idempotent, and every stale input refuses before activation.

**Independent test**: Fault injection at each promotion journal phase, plus one mutation per bound input.

- [x] T027 [US3] Freshness binding for rebase plans. Bind the rebase decisions sha, the impact sha, the snapshot sha and the current sha of every selected source into the grounding review binding/preview for `kind=="rebase"` plans: extend `review_binding._grounding_hashes` and/or `grounding_publish.preview`'s combined digest only when `plan.kind=="rebase"`, keeping delta digests unchanged. Apply refuses `REBASE_STALE` / exit 3, naming the changed input.
- [x] T028 [P] [US3] `tests/test_rebase_stale_boundaries.py`, one test per bound input (SC-005): selected source current bytes edited again; another generation activated (publication conflict); impact file edited; repair draft edited; decisions revised; preview hash mismatch; staged draft hand-edited. Each produces exit 3 before activation, and the active generation is unchanged.
- [x] T029 [P] [US3] `tests/test_rebase_recovery.py` (SC-006). Inject a failure at each journaled promotion phase (reuse the hooks used by `tests/test_delta_grounding_recovery.py`), run the existing recover path, and assert exactly one of the old or new generation is active, whole-bundle. Re-running identical apply returns the original receipt with zero writes. Re-running identical prepare and decide are no-ops.

---

## Phase 6: Parity (CLI + UI, GM ruling 2026-11-09)

- [x] T030 Add routes to `server/routers/summary_native_delta.py` per contracts/http.md, using `build_delta_argv` and the `_json`/`_sse` helpers. An empty `sources` → 400 before any subprocess; a missing reviewer → 400. No default literals.
- [x] T031 [P] Add argv tests in `tests/test_delta_router_argv.py` (extend) and parity in `tests/test_delta_parity.py`: every new CLI leaf has a route, and every route's argv matches the contract.
- [x] T032 Add the page `frontend/src/views/grounding/SourceRebase.vue` and the route `grounding-rebase` in `frontend/src/router.ts`, following `DeltaRun.vue` patterns: inspect table with checkboxes (nothing preselected; Prepare disabled when empty), per-source diff and impact review, repair editor, decision radios with no preselection and a required reviewer, and publish/rebind steps linking the existing grounding steps for the rebase plan id. No browser-only state.
- [x] T033 [P] Add Vitest `frontend/src/views/grounding/SourceRebase.test.ts`: empty selection disables Prepare; no decision is preselected; the reviewer is required; a POST body carries an explicit `sources` list. Run `npm test` and `npm run build` from `frontend/`.

---

## Phase 7: Polish & cross-cutting

- [x] T034 [P] Write the operator runbook `docs/cli/source_custody_rebase_howto.md` (FR-020): when you need it (the `CLAIMS_SOURCE_STALE` message), inspect, old-byte providers, the decision types and why hash-only adoption is refused, holds, unknown-impact rulings, apply via the existing gates, rebind, recovery, every refusal code, the limits (NPC dossiers are follow-ups, not changed), and a ToEE ch43-shaped worked example. Add rows to `docs/README.md`, the CLAUDE.md "Detailed docs" table, and the delta CLI doc if one lists leaves (`docs/cli/` search for `delta grounding apply`).
- [x] T035 [P] Add the new no-LLM modules (`custody_store`, `rebase_inspect`, `rebase_impact`, `rebind`, `rebase` except the propose path, if separable) to the repo's AST no-LLM guard test list, and confirm `tests/test_retrieve_render_isolation.py` passes.
- [x] T036 Run the full suite `python -m pytest tests/ -q` and the frontend `npm test && npm run build`. Fix regressions. Record the results in `specs/040-source-custody-rebase/validation.md`.

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2 → US1 → US2 → US3 → Parity → Polish.** US2 needs US1's records. US3 hardens US2's apply. Parity needs the CLI leaves final.
- **Within Phase 2.** T003/T004 come before T005. T006 comes before T007. T009 can run in parallel with T006–T008.
- **Within US1.** T010 → T011 → T012 → (T013, T014) → T015 → T016 → T017 → T018.
- **Within US2.** T019 → T020 → T021 → T022. T023 → T024. T025 needs everything in this phase; T026 needs T023 and T024.

## Parallel examples

- Phase 2: T005 (digest golden) ∥ T007 (store tests) ∥ T009 (parser) once T003, T004 and T006 land.
- US3: T028 ∥ T029 after T027.
- Parity/Polish: T031 ∥ T033 ∥ T034 ∥ T035.

## Implementation strategy

- **MVP = Phases 1–3 (US1).** The GM can see and decide the full impact at the CLI. This already removes the "generic first-source error" pain.
- **Production unblock = + US2.** This is what finishes ToEE chapter 43.
- **Hardening = US3**, then parity and docs.

Orchestration: each phase goes to one Sonnet implementation subagent, and Opus reviews the diff and test output between phases. One code-review pass at the end; unresolved findings are filed as GitHub issues against kostadis/CampaignGenerator.
