# Implementation Plan: Grounding Navigation Hierarchy

**Branch**: `022-grounding-nav-hierarchy` | **Date**: 2026-09-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/022-grounding-nav-hierarchy/spec.md`

## Summary

The three rendering paths that feature 006 designed to coexist are flattened in the
sidebar. Per-tool and state projection share one undifferentiated `GROUNDING DOCS` group,
and dossier synthesis is a separate top-level `ENSEMBLE WORKFLOW` group, so nothing tells
the GM they are alternative routes to the same documents.

The approach is a **sidebar-only** change. `AppSidebar.vue` gains one extra level inside
`GROUNDING DOCS`: three always-expanded, non-clickable path headers (Per-tool, Dossier
synthesis, State projection), each with a one-line description. The existing entries sit
under them. Every route address stays exactly as it is, so all existing links keep
working with no redirects (research R1). Path headers are marked active by address
prefix, which also fixes an existing gap where no entry was highlighted on the
Extract/Bundle/Synthesize stages of the Ensemble wizard (research R5). A new Playwright
spec checks the UI contract.

## Technical Context

**Language/Version**: TypeScript ~5.9, Vue 3.5 (`<script setup>`), vue-router 4.6

**Primary Dependencies**: Vue, vue-router, Pinia (existing; nothing added)

**Storage**: N/A. No disk, config or API change (FR-010)

**Testing**: Playwright 1.55 (`frontend/e2e/`, Chromium, 1280×720, API calls stubbed via `page.route`); `npm run build` (`vue-tsc -b && vite build`) as the type check

**Target Platform**: Local web UI served by Vite; desktop browser

**Project Type**: Web application (FastAPI `server/` + Vue `frontend/`). This feature touches `frontend/` only

**Performance Goals**: N/A. A static navigation structure rendered once

**Constraints**: Sidebar is a fixed 210px wide. Descriptions must fit in one or two wrapped lines at the existing 10–12px sizes. No route, view or request changes (contract C5)

**Scale/Scope**: 1 component rewritten in its nav section, 1 new e2e spec, 1 shared e2e fixture extracted from an existing one, about 19 sidebar entries re-parented or unchanged

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Checked against all thirteen principles, by name, as Governance requires.

| # | Principle | Verdict | Why |
|---|---|---|---|
| I | Disk is Truth, the Model is a Draft | **PASS** | No data, no disk read or write, no model call. |
| II | The Human Checkpoint is Non-Negotiable | **PASS** | No LLM call is added. The one judgement this feature makes, the user-facing wording that describes how the paths relate, is a draft for GM approval (research R8). |
| III | Retrieval and Render are Separated | **N/A** | No retrieval or render function is touched. |
| IV | Verbatim is Sacred | **N/A** | No transcript or quote content. |
| V | One Seam per Boundary | **PASS** | No external dependency is added or re-routed. |
| VI | CLI is the Engine, UI is a Face | **PASS** | UI-only; no pipeline logic moves into the frontend, and no router or CLI change. |
| VII | Extract Once, Synthesize Deliberately | **PASS** | No passes are merged or collapsed. The three paths stay independent; the change only makes their relationship visible. |
| VIII | State is Discoverable | **PASS: advanced** | This is the principle the feature serves. It moves "which paths overlap, and which share an extraction" from tribal knowledge into the sidebar. |
| IX | The UI Mechanizes; Claude Converses | **PASS** | No step moves into or out of the UI. Choosing between paths stays the GM's (FR-011). |
| X | Selection is Explicit; There is No Silent "All" | **N/A** | No batch operation. |
| XI | Parity is Bidirectional; Every CLI Capability Has a Face | **PASS** | Every page keeps its sidebar entry, with zero extra clicks (data-model inventory; contract C2). No capability loses its face. |
| XII | One Spelling per Option; No Configuration Drift Across CLIs | **N/A** | No option or flag. |
| XIII | Breaking State Changes Migrate Out of Band | **PASS** | No on-disk state changes shape, so no migration document is due. Route addresses are also held fixed rather than moved behind redirects (research R1), in the spirit of "no dual-location". |

**Authority & the Human Checkpoint**: this plan and its artifacts are drafts. Four
decisions were the GM's: the path labels, the three descriptions, renaming
`Ensemble Grounding Docs` → `Ensemble`, and the path order (research R7, data-model.md).
**Approved as proposed by the GM, 2026-09-23.**

**Gate result (pre-research)**: PASS. No violations, so Complexity Tracking is empty.

**Gate result (post-design)**: PASS, unchanged. The Phase 1 design adds no route, view,
request, dependency or state; it adds only two optional fields to the sidebar's own
static types (data-model.md). Every principle's verdict holds.

## Project Structure

### Documentation (this feature)

```text
specs/022-grounding-nav-hierarchy/
├── spec.md
├── plan.md                         # this file
├── research.md                     # Phase 0: decisions R1–R9
├── data-model.md                   # Phase 1: nav tree, proposed wording, inventory
├── quickstart.md                   # Phase 1: validation guide
├── contracts/
│   └── sidebar-navigation.md       # Phase 1: UI contract C1–C5
├── checklists/
│   └── requirements.md             # from /speckit-specify
└── tasks.md                        # Phase 2: /speckit-tasks (not created here)
```

### Source Code (repository root)

```text
frontend/
├── src/
│   ├── components/layout/
│   │   └── AppSidebar.vue          # CHANGED: nav types, grounding group → three paths, active rules, styles
│   ├── router.ts                   # UNCHANGED (research R1; contract C5)
│   └── views/                      # UNCHANGED
└── e2e/
    ├── fixtures/
    │   ├── appShell.ts             # NEW: the five startup-API stubs, shared
    │   └── narrationWiki.ts        # CHANGED: uses appShell.ts instead of its inline copies
    ├── narration-wiki.spec.ts      # UNCHANGED (must keep passing)
    └── sidebar-navigation.spec.ts  # NEW: contract C1–C4
```

**Structure Decision**: Web application, `frontend/` only. The change is confined to one
component plus its test. `server/`, `pipelines/`, `campaignlib/` and `tests/` are not
touched. No Python test references the sidebar (research R9).

## Complexity Tracking

No constitution violations to justify.
