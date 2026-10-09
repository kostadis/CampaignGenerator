# Implementation Plan: GM Rulings and Authority Tiers

**Branch**: `codex/546-gm-rulings` | **Date**: 2026-10-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/035-gm-ruling-authority/spec.md`

## Summary

Add a campaign-local authority ledger and explicitly selected planning-note inputs. A reviewed `RULED` item proposes an exact, digest-guarded replacement in an authoritative summary; it has no power over unchanged source text. Applying or withdrawing a correction uses a recoverable journal and atomic per-file replacement, then invalidates every dependent extraction and draft. Planning inputs are classified as `CANON`, `TABLE`, `RULED`, `PREP`, `OVERLAY`, or `OPEN`, and carry audience metadata that is enforced before extraction, cache lookup, or rendering. The existing Summary Native CLI remains the engine; the Summary Native page exposes the same preview, validation, apply, recovery, selection, conflict, and provenance operations.

## Technical Context

**Language/Version**: Python 3.10+; TypeScript 5.9 and Vue 3.5 for the existing web face

**Primary Dependencies**: Pydantic 2, PyYAML 6, FastAPI, the existing `campaignlib` atomic-write and subprocess seams, Vue/Pinia, Playwright

**Storage**: Campaign-local YAML and Markdown files; JSON run records, cache manifests, transaction journals, and immutable before-image snapshots

**Testing**: pytest for schema, CLI, integration, migration, transaction recovery, routing, cache/freshness, and audience isolation; Playwright plus the frontend production build for UI parity

**Target Platform**: Local campaign workspaces on Linux/macOS-compatible filesystems supported by the current CLI and web application

**Project Type**: Existing Python CLI and FastAPI service with a Vue web face

**Performance Goals**: Policy resolution and selection preview remain linear in selected records/files; unchanged, audience-compatible extractions continue to reuse cache; no additional model call is required for validation, apply, recovery, freshness, or audience filtering

**Constraints**: Summaries remain authoritative; no shadow override; explicit human apply; exact source-digest guard; no verbatim-source rewrite; audience filtering before model input and cache lookup; explicit selection with empty selection refusal; recoverable rather than falsely multi-file-atomic writes; no lazy migration or retired-shape fallback

**Scale/Scope**: One campaign workspace, hundreds of summaries and selected notes, four Summary Native projections, one authority ledger, and one active source-change transaction at a time

## Constitution Check

*GATE: Passed before Phase 0 and re-checked after Phase 1.*

| Principle | Design evidence | Gate |
|---|---|---|
| I. Disk Is Truth | `docs/authority.yaml`, authoritative summaries, note files, transaction journals, and run records are the complete state. The browser holds no exclusive workflow state. | PASS |
| II. Human Checkpoint | A proposed correction cannot change a source until the GM reviews the exact before/after patch and applies it against the reviewed digest. Generated text is never approval. | PASS |
| III. Retrieval and Render Are Separated | Code resolves exact source/note sections, identities, classifications, audience grants, and selection snapshots before any extractor or renderer receives inputs. Renderers cannot discover or broaden authority scope. | PASS |
| IV. Verbatim Is Sacred | Source adapters refuse changes inside verbatim claims and retain original evidence. Derived source corrections remain traceable to evidence and decision. | PASS |
| V. One Seam per Boundary | No new external service or model boundary is introduced. File and subprocess operations continue through `campaignlib` and existing server seams. | PASS |
| VI. CLI Is the Engine | Authority and planning-note operations are CLI commands; FastAPI routes build and run those commands rather than duplicating policy logic. | PASS |
| VII. Extract Once | Audience-filtered payload revision is part of the extraction cache key, so safe compatible results are reused and incompatible cached content is never borrowed. | PASS |
| VIII. State Is Discoverable | Ledger status, pending transaction, conflicts, selected note set, stale projections, and recovery action are readable from files and CLI/UI status. | PASS |
| IX. UI Mechanizes | The UI previews selections and patches, invokes operations, streams results, and opens written artifacts; judgment remains with the GM. | PASS |
| X. Selection Is Explicit | Note paths/globs resolve to a materialized preview; an empty resolved set refuses. “Select all” must write the concrete chosen set. | PASS |
| XI. Bidirectional Parity | Every new command and option is exposed on the Summary Native page in the same change, including recovery and withdrawal review. | PASS |
| XII. One Spelling | Shared options retain `--config`, `--campaign-dir`, and `--force` meanings. New authority identifiers and audience options use one spelling across sibling commands and routes. | PASS |
| XIII. Out-of-Band Migration | The design is additive and retires no existing store. `migration.md` states affected workspaces and verification; any future detected retired shape must be handled by a separate one-shot migrator, never by a reader fallback. | PASS |

### Post-design re-check

Phase 1 contracts keep the user-approved source-authority rule: `RULED` is a reviewed source-change instruction, not an evidence overlay. The transaction contract records durable intent before source replacement, performs digest-guarded per-file atomic writes, and provides idempotent recovery. The input contract filters restricted payloads before extraction and binds audience policy into cache and run-record revisions. CLI and HTTP/UI contracts cover the same state and operations. No constitutional exception is required.

## Project Structure

### Documentation (this feature)

```text
specs/035-gm-ruling-authority/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── migration.md
├── evidence.md
├── checklists/
│   └── requirements.md
└── contracts/
    ├── authority-ledger.md
    ├── cli.md
    ├── http-ui.md
    ├── input-and-cache.md
    └── transaction.md
```

### Source Code (repository root)

```text
campaignlib/
├── planning_config.py
└── util.py

pipelines/summary_native/
├── authority.py
├── authority_apply.py
├── authority_inputs.py
├── cli.py
├── extract.py
├── freshness.py
├── notes.py
└── synth.py

server/
├── planning_config_service.py
└── routers/
    ├── planning_routes.py
    └── summary_native.py

frontend/
├── src/views/grounding/SummaryNative.vue
└── e2e/summary-native-state.spec.ts

tests/
├── test_summary_native_authority.py
├── test_summary_native_authority_apply.py
├── test_summary_native_authority_audience.py
├── test_summary_native_authority_freshness.py
├── test_summary_native_planning.py
├── test_summary_native_routes.py
└── test_planning_config_service.py
```

**Structure Decision**: Extend the existing Summary Native and planning-configuration seams. Keep the strict ledger, source transaction engine, and audience input policy in separate modules so synth does not become the authority implementation. Reuse `campaignlib.util` atomic writes and the server subprocess runner. Add no database, daemon, external service, or separate web application.

## Complexity Tracking

No constitution violations require justification.
