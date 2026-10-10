# Research Decisions: Promotion Gate

Baseline `5e63e85`; read-only code discovery through codebase-memory-mcp project `cg548`. Source inspections and the original campaign spike were performed by Sol; Astra consolidated the design. No runtime code or campaign state was changed.

## R1 — Five-example spike and human ruling

**Decision:** All five original prose failure shapes require candidate interpretation plus GM judgment with the currently available campaign data. Implement narrow mechanical comparisons only after exact claim meaning/scope is reviewed. Use reconstructed negative/positive fixtures based on surviving Phandalin sources, explicitly approved by the user on 2026-10-10.

**Rationale:** [spike.md](spike.md) identifies the surviving sources. Petra's later summary repeats an earlier refused proposal, demonstrating why recency alone cannot settle truth. None of the five examples has both sides as already-reviewed normalized claim data. Three bad draft sentences are missing; the other two survive partially outside/across the original generation. The user accepted reconstruction, not a claim of historical replay.

**Alternatives considered:** Pure deterministic prose interpretation would overstate capability. Waiting indefinitely for lost originals was offered and the user chose labeled reconstruction. Existing Earthstone synthetic authority tests alone do not establish campaign evidence.

## R2 — Atomic live publication

**Decision:** Stage a complete versioned generation and activate it with one relative `current` symlink replacement. Supported readers pin that generation once under the shared campaign lock and capture their complete input bytes. Keep a retained `published/` snapshot and an editable `live/` tree per generation; use distinct copies, not hard links. See [publication contract](contracts/publication.md).

**Rationale:** `review/documents.py:promote_document_bundle` delegates to sequential authority transaction targets. That is recoverable but does not atomically replace a live bundle for uncoordinated readers. Renaming a single pointer gives one activation boundary; directory/file synchronization is separately needed for durability. [Linux rename documentation](https://man7.org/linux/man-pages/man2/rename.2.html) and [fsync documentation](https://man7.org/linux/man-pages/man2/fsync.2.html) establish those distinct properties.

**Alternatives considered:** Sequential live copies with rollback can expose mixed files; swapping all of `docs/` would involve unrelated summaries, authority and reviews; individual symlinks changed per document have multiple commit points. Holding a lock around arbitrary file readers is insufficient unless consumers participate. No new database or daemon is justified.

## R3 — Receipt and crash semantics

**Decision:** Persist a self-contained receipt candidate inside the sealed generation before activation. The pointer transition, followed by synchronization, establishes activation; a receipt file alone does not. Reconcile interrupted operations before accepting another promotion. Recorded activation history distinguishes committed historical operations from orphan candidates.

**Rationale:** A receipt written only after the swap can be lost while live content changes. Before-swap receipt plus explicit activation evidence avoids pretending two distinct file writes are atomic. Post-swap acknowledgment/durability uncertainty is `commit_unknown`, not a claimed failed/rolled-back publication. Preserve old generation and exact precommit bytes in all cases.

**Alternatives considered:** Promoting then hoping receipt creation succeeds, or calling every crash a failed publication, would violate accountability. Automatically activating an orphan during read/recovery would publish without current consent. A new user-facing rollback workflow is unnecessary here; retain snapshots and recover interrupted operations only.

## R4 — Existing consumers, writers, and migration

**Decision:** Introduce `campaignlib.grounding_bundle` as a shared snapshot boundary. Migrate config to managed current paths and replace the six known loose document/reference entry points with explicit compatibility aliases. A separate `migrate_grounding_bundle` CLI performs preview/apply/status/verify/recovery with equivalent application controls. Keep `docs/` itself a real directory.

**Evidence / inventory:**

| Existing area | Integration |
|---|---|
| `campaignlib.config.assemble_docs` / `load_file` | Batch managed paths through a single snapshot; generic nonbundle reads remain ordinary reads. |
| `pipelines/session_prep/prep.py`, `pipelines/grounding/npc_table.py` | Capture grounding inputs together before model/render work. |
| `session_doc/check_consistency.py`, `session_doc/sd_consistency.py`, session context/party consumers | Recognize managed explicit paths and use operation-scoped snapshots. |
| `pipelines/rlm/mcp_server.py:_read_doc` / `read_document` and context assembly | Same generation resolver and structured refusal; no independent cache of live files. |
| `pipelines/summary_native/cli.py:_compare` | Pin current live bytes; drafts remain range-local. |
| `server/routers/summary_native.py`, `review_routes.py`, prep routes | CLI invocation for domain behavior; managed live reads through the same snapshot. |
| Legacy grounding/ensemble generators and generic document editors | Refuse generated replacement of managed targets or use a lock-bound explicit manual edit; never replace/detach managed aliases silently. Nonmanaged destinations remain supported. |
| `review/documents.py`, review CLI and ReviewLauncher publication controls | Retire individual prepare/promote with precise whole-bundle instructions; retain historical receipts and exact document review. |

Implementation must finish the call-site inventory through graph callers plus exact-path searches and add a regression check for bypasses. This is an explicit work item, not permission to omit a consumer.

**Alternatives considered:** No migration would silently reinterpret old paths. Optional aliases would strand known `docs/*.md` users. Existing loose files cannot be assumed one coherent generation: adoption validates them and records `legacy-adoption`, never retroactive GM approval. Migration changes neither entity registry nor authority ledger schema.

## R5 — Manual live edits

**Decision:** Human edits remain possible in the active live tree and are identified as drift from its retained published snapshot. Snapshot readers return actual live bytes plus drift metadata. A later promotion preview shows their overwrite, and commit records the exact current bytes as its previous snapshot before activating new output. Destination drift invalidates preview, not source sign-off.

**Rationale:** Current documentation explicitly permits prose edits after promotion. Permanently read-only generation files would silently remove that workflow. Separating retained publication evidence from editable live content avoids losing what was actually approved.

**Alternatives considered:** Silently rewriting the publication manifest to bless edits falsifies history. Reading a historical snapshot instead of the live edit violates disk truth. Automatically treating edits as authority rulings would bypass #546. External concurrent editors cannot be controlled by advisory locks and remain outside the cooperative writer guarantee.

## R6 — Exact complete bundle and destination checks

**Decision:** Enumerate all four drafts, `canon_events_timeline.md`, and the full nested `reference/` tree from one range. Preserve embedded reading-contract paths and bind run records, source corpus, notes, registry, players, thread registry and configured relevant authority. Validate copied bytes in their final generation layout before activation.

**Evidence:** `state_sections.reading_contract` and `pointers.check_paths` define relative references/timeline and campaign-root source resolution. `_check_document` currently looks for `timeline.md`; actual generation/manual promotion documentation names `canon_events_timeline.md`. Correct the bundle enumeration and test the real generated layout instead of perpetuating that mismatch. Existing subset/create-only `state/reviewed` publication does not meet #521 replacement requirements.

**Alternatives considered:** Taking only paths explicitly referenced by a selected single document omits the parent issue's complete reference directory. Rewriting approved path comments on copy would invalidate exact approval. Carry forward only prior managed membership when computing removals; never guess ownership of unrelated live files.

## R7 — Pure dry-run and stable preview identity

**Decision:** Implement top-level promote dispatch outside the existing build/scan path, with a pure manifest/diff/gate computation. `--dry-run` does not create files, reports, locks or caches. Return a canonical preview digest bound to all inputs and actual destination bytes; commit recomputes it under the mutation lock.

**Rationale:** Existing CLI dispatch writes validation reports for many operations; `authority_lock` can create directories/lock files. Neither behavior is acceptable in an uninitialized dry-run. An existing-lock reader mode and explicit migration-required refusal solve this without silent initialization.

**Alternatives considered:** Persisting every dry-run as a proposal violates #521. Requiring a hidden browser-only preview state violates parity and discoverability. Timestamps are excluded from the consent digest to make it reproducible.

## R8 — Source selection and normalized claim view

**Decision:** A versioned selection manifest lists exact four draft hashes, source revisions, authoritative note/ruling revisions, effective horizon, permitted audience and explicit chunk set. Source suggestions may follow existing citations, aliases and authority links, but GM confirms the materialized selection before model work. The checker compares only validated structured assertions or GM-approved interpretations of exact source spans.

**Rationale:** Existing `authority.py:BaseRecord` supports claim keys/normalized values, but the real campaign currently has prose. `resolve_planning_precedence` applies planning authority ordering; it is not a general truth resolver. Identity comes from the registry, chapter/effective scopes from reviewed metadata, and supersession from explicit links or rulings. Later filename/date is never an automatic winner.

**Alternatives considered:** Arbitrary full-campaign scraping obscures scope and spend. Treating every prose sentence as mechanically normalized invents semantics. A second canonical claim ledger would compete with source authority: reviewed annotations describe what a span says, not a new fact store.

## R9 — Optional candidate extraction; deterministic gate

**Decision:** Add separately invoked `claims extract` and a manual `claims import` alternative. Retrieval builds bounded input packets first; `claims/extract.py` only sends those packets through campaignlib and writes strict candidate output. Mechanical schema/excerpt checks run after each call. No candidate from one call becomes a precision-bearing input to another model call before GM approval. Promotion/check/status never call a model.

**Human decision removed:** None. Candidate meaning, identity, ordering, attribution and conflicts remain unaccepted until reviewed; exact source and proposed normalization appear together in #547's review surface. Model output may suggest both mappings and findings but cannot certify absence of errors.

**Rationale:** The spike justifies semantic assistance for all five examples. Extraction is optional, explicitly selected and cached by input/model/prompt/rule identity. Human-authored/imported mappings have the same evidence and review requirements. Whole-document sign-off includes coverage limits, so an empty candidate list is not a proof of correctness.

**Alternatives considered:** An automatic LLM promotion gate violates the parent constraint. A purely manual-only pipeline ignores the identified need for candidate extraction. Model voting and automatic source correction would add cost without a human precision boundary.

## R10 — Review and freshness integration

**Decision:** Keep shared review storage and ledger v2. New typed `proposed_action.details` payloads distinguish normalized mapping confirmation, finding disposition and document sign-off under the existing grounding-document domain. Existing verdicts map to explicit displayed actions; no new catch-all approval. New action validators enforce allowed decisions in CLI, local HTTP and private service. Rule version `grounding-bundle-signoff/2` binds all support/claim/report context.

**Rationale:** Existing ReviewItem semantic digests already include evidence, scope, rules and semantic input bindings; decisions have stable event IDs and expected revisions. Historical `grounding-document-signoff/1` approvals lack the required complete-bundle binding and must be refreshed/reviewed, not silently upgraded. A whole-ledger hash must not stale unrelated review; bind relevant accepted record revisions while still validating ledger integrity.

**Alternatives considered:** Extending accepted old decisions in place falsifies history. Allowing `approve` to waive a mechanical defect defeats the gate. A duplicate review store loses phone/CLI continuity. No authority schema v3 is needed for these audit-only annotations; a new strict versioned sidecar holds report/normalization details bound by review items.

## R11 — Main application and private review boundary

**Decision:** Use typed local application endpoints invoking installed CLI commands. Add a Promotion section to SummaryNative for scope, manifests/diffs, extracted candidates, check status, private review launch, final publication, receipts and recovery; reuse ReviewLauncher and the existing phone surface for judgment. Do not give the capability server a new publication or arbitrary-path endpoint.

**Rationale:** Constitution VI/XI require both directions of parity; the existing private service has a deliberately narrower authority boundary. Phone readability and saved-decision feedback from #547 remain regression requirements.

**Alternatives considered:** CLI-only delivery requires an exemption the user has not given. A second review UI would duplicate decisions. Public hosting is outside scope.

## R12 — Validation and unresolved questions

**Decision:** Validate boundaries with process fault injection, concurrent reader/promoter tests, exact filesystem snapshots for dry-run/refusal, stale-decision tests, labeled reconstructed claim examples plus positive controls, CLI/HTTP parity, browser review and installed-wheel checks. Keep all campaign experiments disposable.

**Rationale:** Unit tests of rename calls do not prove reader consistency or recovery. Tests that fabricate a structured assertion and claim to reproduce missing prose would hide the spike's result.

**Alternatives considered:** Exhaustive unrelated regression runs before any feature risk is exercised add cost without closing the actual risks. Only broaden tests for shared seams identified here or required repository gates.

All Phase 0 technical choices are resolved by these decisions and the explicit user evidence ruling. No `NEEDS CLARIFICATION` items remain. Historical replay is a recorded limitation, not an unresolved implementation choice.
