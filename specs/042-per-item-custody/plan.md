# Implementation Plan: Per-Item Source Custody for NPC Review

**Branch**: `042-per-item-custody` | **Date**: 2026-11-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/042-per-item-custody/spec.md` (#624 and #633, both under #618)

## Summary

Today three places check source custody for the whole review at once:

- the decision save (`review/store.py::save_decisions`) re-hashes all 412 sources;
- the bundle import (`store.py::import_review_bundle`) compares the whole-review custody digest;
- the publish gate (`npc_publish.py::_current_draft_signoff`) requires every source of the signoff's review to be current.

Each of these becomes a check over the **dependency set** of only the items concerned.

A new pure module, `pipelines/summary_native/review/custody.py`, is the one seam for this (Constitution V). It computes each item's dependency set from data the review already holds. That data is the custody record, the items' bindings, and the bytes of each evidence file, which are parsed only while they still equal the bytes custody recorded (research R2). It compares the dependency set against the current files, and builds one structured refusal detail: changed file → submitted items → NPC, plus the remedy command.

The CLI, the local review routes, the capability viewer and `review status` all carry that detail unchanged. Publishing uses the same dependency sets, so one NPC's draft edit no longer holds the others. A held NPC's reason names the files that changed. Just before each target is written, the draft is re-hashed against the bytes that were signed (FR-012).

Nothing changes on disk. The review store, custody record, ledger, decision events and receipts keep their shape. Two additions are optional: a refusal `data` payload and one optional receipt key. No migration is needed (XIII). No model is called (FR-015).

## Technical Context

**Language/Version**: Python 3.12 (repo standard). Vue 3 + TypeScript for one launcher change. Plain JS for the capability viewer.

**Primary Dependencies**: stdlib (`hashlib`, `re`, `dataclasses`) and PyYAML (already used) for evidence frontmatter. The existing pydantic review models. No new dependency.

**Storage**: the existing review store under `docs/reviews/<review>/`, read only. Publish receipts (spec 039) gain one optional key, `custody_changed`.

**Testing**: pytest. New `tests/test_summary_native_review_custody.py` (unit), `tests/test_summary_native_review_item_custody.py` (store and CLI acceptance), `tests/test_summary_native_npc_publish_custody.py` (publish acceptance) and `tests/test_summary_native_custody_baseline.py` (read-only stormgiants replay, skipped without `STORMGIANTS`). The shared fixture is `tests/_custody_fixture.py`. The existing decision, routes, http, delegated, publish and delta-freshness suites are extended. One Vitest file covers `ReviewLauncher.vue`.

**Target Platform**: Linux CLI, the local FastAPI review routes, and the capability review service (phone).

**Project Type**: a CLI pipeline with thin web faces.

**Performance Goals**: a decision save hashes only its batch's dependency sets: a draft, an evidence file and about 1–20 summaries per NPC, instead of 412 files. `review status` hashes every custody source once, about the same as today's save. A publish caches digests per run instead of re-hashing all custody per sign-off record per NPC.

**Constraints**: never weaker than today's check restricted to the files a decided item depends on (precision rule, FR-002, SC-002). Deterministic. No model call. No automatic refresh, rebind or re-verify (FR-008). Nothing writes to `~/storm-giant/stormgiants`.

**Scale/Scope**: about 780 items over about 410 sources per large review, and about 165 NPCs per publish batch.

## Constitution Check

*GATE: checked before Phase 0 and re-checked after Phase 1.*

| Principle | Status | How |
|---|---|---|
| I. Disk is truth | ✅ | Staleness is computed from the files on disk against the custody record, every time. Nothing is cached across calls. Dependency sets are derived, not stored (R2). |
| II. Human checkpoint | ✅ | The feature removes no decision from the GM. It changes *which* decisions a file edit blocks, and never weakens the block for an item that depends on the file (FR-002, SC-002). Bringing items current stays the GM's explicit `review refresh` (FR-008). The dependency rule for summaries is a GM ruling (FR-003, 2026-11-12). |
| III. Retrieval/render separation | ✅ n/a | No retrieval or render calls. |
| IV. Verbatim is sacred | ✅ | A publish writes only content bound to the signed draft bytes, and holds the NPC when the draft moved (FR-012, R13). |
| V. One seam per boundary | ✅ | One `review/custody.py` serves the save, the import, `review status` and `npc_publish`. The 041 NPC-label rule moves into it so both features spell an NPC one way (R12). |
| VI. CLI is the engine | ✅ | The refusal detail is built once in the engine and carried as the CLI envelope's `data`. Both web surfaces relay it and never recompute it. |
| VII. Extract once | ✅ n/a | No extraction. |
| VIII. State discoverable | ✅ | `review status` reports stale items by NPC from the current files (FR-007). Refusals and publish receipts name the files (FR-005, FR-013). |
| IX. UI mechanizes | ✅ | The UI only shows the refusal and the status. The remedy stays a named CLI command. |
| X. No silent "all" | ✅ | Selection is unchanged. A batch is still exactly the GM's chosen items. The fallback to "all summaries" is a *dependency* widening, which is conservative. It is not a selection widening. |
| XI. Every CLI capability has a face | ✅ | **Refusal detail**: the local `/api/reviews/*` routes relay `data` (`review_routes._error`). `ReviewLauncher.vue` renders it. The capability service (`review/web/app.py`) relays a whitelisted copy, and `viewer.js` renders it under the save state. **Stale-by-NPC**: `review status` already has a face, `GET /api/reviews/{id}/status` behind the launcher's "Refresh status" button, which renders `data`. The new keys reach the GM through it with no new route. The capability viewer gets no status panel. It is a deciding surface, and the refusal detail there names the exact stale items at the moment they matter. That is a delivery-scope judgement inside an existing face, not a CLI-only capability, so no ruling is needed. **Publish held reasons**: already shown by the existing `npc-publish` route output and receipts. |
| XII. One spelling per option | ✅ | No new flags. The remedy is spelled exactly as the CLI defines it: `summary_native review refresh REVIEW --expected-generation N`. The NPC label is one helper shared with 041's `review noise`. The refusal code stays `REVIEW_STALE_CUSTODY` (FR-005). |
| XIII. Breaking state changes migrate | ✅ no trigger | No on-disk shape changes. The dependency set is computed, not recorded (R2), so existing reviews, including the real stormgiants review, get the per-item rule with no migration. The additions are an optional envelope `data` on a refusal, new `review status` keys, and one optional receipt key. All are additive. |

**Post-design re-check (after Phase 1)**: unchanged. There are no violations, so Complexity Tracking stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/042-per-item-custody/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R15
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── custody-refusal.md       # CLI --json/text + local route + capability service
│   ├── review-status.md         # stale_by_npc / changed_files
│   └── publish-held.md          # held reasons + receipt key
├── checklists/requirements.md
├── validation.md        # written during /speckit-implement (T001, T002, T046)
└── tasks.md
```

### Source Code (repository root)

```text
pipelines/summary_native/review/
├── custody.py        # NEW: roles, FileState, digest probe, evidence→summaries, dependency_sets,
│                     #      stale_report, refusal detail, stale_by_npc, remedy, npc_label
├── store.py          # ReviewStoreError.detail; save_decisions & import_review_bundle use custody;
│                     #   review_status adds changed_files / stale_by_npc
├── delegated.py      # npc label from custody.npc_label; submit_decisions keeps detail when re-wrapping
├── cli.py            # _emit carries exc.detail as data on refusal; text rendering of the detail
└── web/
    ├── app.py        # safe_command_error relays whitelisted custody detail (409)
    └── viewer.js     # render the refusal detail under the save state

pipelines/summary_native/npc_publish.py   # per-item signoff freshness via custody; reasons name files;
                                           #   pre-write draft re-hash (FR-012); receipt custody_changed

server/routers/review_routes.py           # _error relays envelope data
frontend/src/components/ReviewLauncher.vue # show refusal data
frontend/src/components/ReviewLauncher.test.ts  # NEW (Vitest)

docs/cli/summary_native_review.md         # per-item custody, the refusal, status by NPC
docs/cli/npc_dossiers_howto.md            # publish held reasons naming files

tests/
├── _custody_fixture.py                           # NEW: real multi-NPC verified dossier review
├── test_summary_native_review_custody.py         # NEW: unit (custody.py)
├── test_summary_native_review_item_custody.py    # NEW: US1–US3 acceptance via CLI/store
├── test_summary_native_npc_publish_custody.py    # NEW: US4 acceptance
├── test_summary_native_custody_baseline.py       # NEW: read-only stormgiants replay (SC-005), skips w/o STORMGIANTS
├── test_summary_native_review_decisions.py       # extended (detail shape on the existing refusal)
├── test_summary_native_review_routes.py          # extended (data relayed)
├── test_summary_native_review_http.py            # extended (capability relay, whitelisting)
├── test_summary_native_review_delegated.py       # extended (detail survives submit_decisions)
├── test_delta_freshness.py                       # extended (graph cannot narrow below FR-003)
└── test_summary_native_no_llm.py                 # + explicit custody.py assertion
```

**Structure Decision**: a single-project CLI layout, extending the existing `pipelines/summary_native/review` package. There is no new package.

## Phasing (for /speckit-tasks)

1. **Foundation**: `custody.py` and its unit tests; `ReviewStoreError.detail`; the shared multi-NPC fixture. US1–US4 all depend on it.
2. **US1**: `save_decisions` and `import_review_bundle` switch to per-item checks. Acceptance tests come first.
3. **US2**: the detail reaches the CLI text and `--json`, the local routes, the capability service, the viewer and the launcher.
4. **US3**: `review status` reports `changed_files` and `stale_by_npc`.
5. **US4**: publish freshness per item, reasons naming files, and the pre-write re-hash.
6. **Polish**: the stormgiants replay, docs, the full suite and the quickstart walkthrough.

## Complexity Tracking

No violations to justify.
