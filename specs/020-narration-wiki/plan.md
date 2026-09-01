# Implementation Plan: Persistent Narration Wiki

**Branch**: `358-narration-wiki` | **Date**: 2026-08-31 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/020-narration-wiki/spec.md`

## Summary

Build a deterministic, disk-backed narration-wiki engine for one explicitly selected session. The engine collects immutable evidence, persists and binds a baseline measurement before Gate 1, records seed-conflict and per-pattern GM rulings, stages one hash-bound comparison edit to one authorized campaign-guidance file, and completes Gate 2 by either retaining accepted bytes or restoring the prior bytes while appending one durable impact record.

The engine is a Python package under `session_doc` exposed through one console script. FastAPI remains a thin adapter over `server/subprocess_runner.py`: `status` is the sole bounded read-only JSON projection, while every validation or workflow command streams Server-Sent Events (SSE) and causes the UI to refresh disk-derived status afterward. The Vue page reuses the existing visual system and owns scrolling at the sole supported 1280x720 viewport and within every resizable panel at its 320x160 minimum.

The portable wiki and its versioned capability manifest are read-only deployed dependencies owned by the companion skill repository. CampaignGenerator may validate them and create promotion handoffs, but it never writes another repository or feeds wiki content into the narration renderer.

## Technical Context

**Language/Version**: Python >=3.9; TypeScript 5.9; Vue 3.5

**Primary Dependencies**: Python standard library (`argparse`, `asyncio`, `dataclasses`, `difflib`, `fcntl`, `hashlib`, `json`, `pathlib`, `unicodedata`), PyYAML, Pydantic 2, FastAPI, Vue Router, Pinia, and pinned `@playwright/test` as a frontend test-only dependency

**Storage**: Human-readable Markdown and YAML, canonical JSON, exact byte snapshots, and crash-recovery journals on local disk; no database and no browser-only workflow state

**Testing**: pytest unit/contract/integration tests; shared subprocess-runner cancellation and logging regressions; `vue-tsc` and Vite production build; pinned Playwright end-to-end resize and scrolling tests

**Target Platform**: Linux/WSL local application using the existing FastAPI server and a modern desktop browser; sole supported UI viewport 1280x720; every declared resizable panel supports a 320x160 minimum

**Project Type**: Python CLI/library, FastAPI adapter, and Vue single-page application

**Performance Goals**: Deterministic commands operate on one selected session, make no model or network calls, use bounded filesystem enumeration, and support the complete operator workflow in under 900 seconds of active operator time, excluding separately recorded companion-model response time

**Constraints**: Explicit non-empty session selection; no traversal or followed link outside the campaign; immutable raw inputs; byte-identical read-only output for identical inputs; persisted baseline required before Gate 1; one authorized target per proposal; rejected-proposal reconsideration checked before staging from canonical digest/rule bindings or an explicit GM override; hash-checked exact restoration; evidence never decides a gate; no render-path wiki reads; no companion-repository writes; additive state only; existing colors and control conventions; visible vertical and horizontal scrolling when content exceeds the supported page or panel region

**Scale/Scope**: One operator, one campaign, one session per iteration, three historical input layouts, normally fewer than 100 selected-session artifacts, hundreds of durable patterns or impact entries over time, and one active comparison proposal awaiting Gate 2

## Constitution Check

### Pre-design gate

| Principle | Result | Design evidence |
|---|---|---|
| I. Disk is Truth, the Model is a Draft | PASS | Manifests, measurements, drafts, rulings, snapshots, conflicts, journals, wiki pages, and impact records are files. Model-produced drafts have no authority until a recorded gate. |
| II. The Human Checkpoint is Non-Negotiable | PASS | Gate 1 is per pattern and tier, seed conflicts require a GM ruling, and Gate 2 is per atomic proposal. No measurement or model output can infer a decision. |
| III. Retrieval and Render are Separated | PASS | Collection and measurement live in `session_doc.narration_wiki`; render modules neither import nor read wiki state. |
| IV. Verbatim is Sacred | PASS | Raw critiques, narration, source records, and exact before snapshots are read-only and hash-verified. Rejection restores original bytes. |
| V. One Seam per Boundary | PASS | One narration-context resolver owns campaign guidance, one portable adapter owns companion deployment validation, and all server process execution lives in `server/subprocess_runner.py`. |
| VI. CLI is the Engine, UI is a Face | PASS | Every domain operation is a `narration_wiki` command. Validation and workflow commands use the established SSE runner; the explicitly clarified read-only status projection uses a bounded JSON helper in the same seam. Routers only validate, build argv, and adapt transport. |
| VII. Extract Once, Synthesize Deliberately | PASS | Collection, baseline measurement, maintainer drafting, conflict and pattern rulings, proposer drafting, comparison, and Gate 2 remain separate stages. |
| VIII. State is Discoverable | PASS | Iteration progress, dependency compatibility, and recovery state are derived from human-readable files and exposed identically to CLI and UI. |
| IX. The UI Mechanizes; Claude Converses | PASS | The page invokes deterministic commands and presents evidence. Companion skills remain draft producers; the UI never performs semantic drafting. |
| X. Selection is Explicit; There Is No Silent "All" | PASS | Both campaign and session are explicit. Empty selection refuses before enumeration, process creation, or artifact creation. |
| XI. Parity Is Bidirectional; Every CLI Capability Has a Face | PASS | Every public command, including seed-conflict adjudication, has an action on `/workflow/wiki`. |
| XII. One Spelling per Option; No Configuration Drift Across CLIs | PASS | Common scope, identity, evidence, and ruling options are owned once by the narration-wiki parser and forwarded unchanged. |
| XIII. Breaking State Changes Migrate Out of Band | PASS | Wiki state is additive and created only by an explicit confirmed operation. Existing workspaces remain valid; no backfill, fallback probe, or migration is required. |

**Pre-design gate result**: PASS. No unresolved clarification or constitutional exception remains.

## Project Structure

### Documentation (this feature)

```text
specs/020-narration-wiki/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── artifacts.md
│   ├── cli.md
│   ├── http-api.md
│   ├── companion-capability.schema.json
│   ├── conflict-ruling.schema.json
│   ├── manifest.schema.json
│   ├── measurement.schema.json
│   └── usability-result.schema.json
├── validation/
│   └── usability-result.json       # created by the post-implementation exercise
└── tasks.md                        # regenerated later by $speckit-tasks
```

### Source Code (repository root)

```text
campaignlib/
├── narration_context.py            # read-only authoritative-guidance resolver
└── util.py                         # exact-byte atomic writer beside text/JSON writers

session_doc/
├── voice_lint.py                   # structured analysis API; legacy behavior preserved
└── narration_wiki/
    ├── __init__.py
    ├── cli.py                      # public console-script surface
    ├── models.py                   # disk and JSON contracts
    ├── paths.py                    # containment and authorized-target policy
    ├── collect.py                  # bounded three-layout trace collection
    ├── measure.py                  # D4 checks and cross-narrator reuse
    ├── indexes.py                  # page, index, conflict, slug, and tier validation
    ├── proposals.py                # snapshots, comparison, retain, and restore
    └── storage.py                  # canonical I/O, locks, journals, gates, and ledgers

server/
├── main.py                         # mount narration-wiki router once
├── subprocess_runner.py            # existing SSE runner plus bounded JSON status helper
├── session_editor_config_service.py
└── routers/narration_wiki.py

frontend/src/
├── router.ts
├── style.css                       # reused; no narration-wiki theme
├── views/SessionWorkflow.vue
├── views/session/NarrationWiki.vue
├── api/narrationWiki.ts            # status JSON and streamed-command adapters
├── api/sse.ts                      # retain EventSource; add POST-SSE fetch support
└── components/narration-wiki/
    ├── ConflictRulingCard.vue
    ├── MeasurementTable.vue
    ├── PatternGateCard.vue
    └── ProposalGatePanel.vue

frontend/
├── package.json                    # pinned Playwright dependency and test:e2e script
├── playwright.config.ts
└── e2e/narration-wiki.spec.ts

docs/
├── README.md
└── cli/narration-wiki.md

tests/
├── fixtures/narration_wiki/        # minimal old/middle/current layouts
├── test_narration_wiki_cli.py
├── test_narration_wiki_collect.py
├── test_narration_wiki_companion.py
├── test_narration_wiki_conflicts.py
├── test_narration_wiki_indexes.py
├── test_narration_wiki_measure.py
├── test_narration_wiki_patches.py
├── test_narration_wiki_renderer_isolation.py
├── test_narration_wiki_routes.py
├── test_narration_wiki_storage.py
└── test_narration_wiki_ui.py
```

## Phase 0: Research Decisions

Research is complete in [research.md](research.md). All technical uncertainties are resolved.

1. Use a small `session_doc.narration_wiki` package so scope security, measurement, indexes, proposals, and persistence remain independently auditable.
2. Refactor `voice_lint` to expose a structured D4 profile while preserving its legacy CLI and message projection.
3. Collect fixed-depth allowlisted paths, hash raw bytes, store session-relative POSIX paths, and refuse every resolved candidate outside the session or campaign.
4. Bind Gate 1 rulings to the baseline artifact hash, corpus digest, and guidance digest. Drift before any ruling permits remeasurement; drift after a ruling requires a new iteration.
5. Represent reconsideration with canonical source-digest/affected-rule bindings validated before staging, or a stage-time GM override with rationale. A changed path or ID with the same digest never qualifies.
6. Persist seed conflicts through a separate `conflict-rule` command. An affected pattern cannot be promoted until each referenced conflict has a durable campaign-scoped GM resolution.
7. Bind each proposal to exact before and after byte snapshots and hashes. The unified diff is display evidence, never an executable patch.
8. Serialize mutations with a campaign lock and an idempotent journal. Gate 2 retains accepted comparison bytes or restores rejected prior bytes and appends exactly one impact record.
9. Keep the portable tier read-only and require companion-owned `capabilities.yaml` metadata declaring contract version 1, `guidance_source: campaign-resolved`, and maintainer/proposer support.
10. Route every process through `server/subprocess_runner.py`. Disable timestamped runner logs for narration-wiki streams so UI and CLI persist the same artifacts. Use a POST-capable fetch-SSE client for command bodies and reload status after completion, failure, or cancellation.
11. Test the page only at 1280x720 and each declared resizable panel at exactly 320x160. Panel internals respond to their own size rather than relying only on viewport media queries.
12. Persist the timed acceptance result separately from runtime state, with total elapsed, excluded model-response, derived active-operator duration, and both Gate references.

## Phase 1: Design

### Data and persistence

[data-model.md](data-model.md) defines all entities, invariants, relationships, and state machines. Canonical files use UTF-8, sorted JSON keys and arrays, a final newline, SHA-256 over raw bytes, stable explicit IDs, and no absolute host paths or read-time timestamps.

Iteration state lives under `<session>/narration_wiki/<iteration-id>/`. Durable campaign knowledge and resolved seed conflicts live under `<campaign>/wiki/`. The deployed portable tier and `capabilities.yaml` are read from `~/.claude/narration-wiki/`; CampaignGenerator never writes them. Missing or incompatible capability state blocks portable confirmation and proposal staging that requires cross-tier validation, while campaign-local collection and measurement remain usable.

The post-implementation timed exercise writes `validation/usability-result.json` under this feature directory. It is acceptance evidence rather than runtime workflow state and is validated by `contracts/usability-result.schema.json`.

### Engine and command flow

The public commands are `status`, `collect`, `measure`, `index-check`, `conflict-rule`, `pattern-rule`, `proposal-stage`, `proposal-apply`, and `proposal-rule`.

```text
explicit session
  -> collect
  -> measure(before)
  -> companion maintainer writes pattern and optional seed-conflict drafts
  -> conflict-rule once per disputed seed, when present
  -> pattern-rule once per draft (Gate 1)
  -> companion proposer writes one atomic candidate
  -> proposal-stage (validate new evidence or record a GM override before recurrence)
  -> proposal-apply (apply candidate for comparison)
  -> measure(after, same corpus)
  -> proposal-rule Accept or Reject (Gate 2)
  -> completed impact record
```

Gate 1 is unavailable until the baseline exists and matches current corpus and guidance digests. Every conflict or pattern ruling records the baseline artifact hash. A pattern that references an unresolved seed conflict cannot be accepted. Rejected or unreviewed drafts never enter a confirmed index.

`proposal-stage` checks prior equivalent rejections before changing the target. It validates each canonical evidence binding against the current manifest and prior impact record, or records an explicit GM override supplied through CLI/UI. `proposal-rule` then consumes that staged reconsideration basis; Gate 2 cannot invent a late justification.

Campaign pattern acceptance journal-writes one page and index entry. Portable acceptance writes a local promotion handoff and remains `pending_portable_sync` until the compatible read-only deployment contains the validated slug. Gate 2 acceptance retains the comparison bytes; rejection restores the prior bytes. Both outcomes retain the wiki pattern, evidence, complete diff, measurements, reconsideration basis, and history.

### HTTP and process boundary

The router derives campaign and non-empty session paths from the existing platform service and builds fixed argv with `console_script("narration_wiki")`. Browser requests contain stable IDs, phases, rulings, canonical evidence bindings, and optional human rationale; they never contain campaign/session paths, arbitrary targets, or file content.

`GET /api/narration-wiki/status` is the sole non-streaming operation. It calls a bounded read-only JSON helper added to `server/subprocess_runner.py`, maps the CLI envelope to HTTP, and performs no domain interpretation. Every other command, including `index-check`, returns `text/event-stream` from `stream_subprocess(..., save_run_log=False)`. The backward-compatible logging flag defaults to `True` for existing routes; narration-wiki disables it because the engine already owns canonical journals and timestamped runner logs would break CLI/UI artifact parity.

POST command bodies are streamed with a fetch/ReadableStream SSE client using `AbortController`; GET streaming may use the same parser. CLI stdout is accumulated across arbitrary chunks and is not parsed per chunk. The `done.returncode` carries exit semantics, and the page reloads status after success, findings, failure, abort, or reconnect. Disconnect cancellation propagates to the existing process-group SIGTERM/SIGKILL behavior. The UI never claims restoration from transport state; the engine journal and refreshed status are authoritative.

### Interfaces

- [cli.md](contracts/cli.md) defines commands, arguments, envelopes, exit codes, baseline enforcement, reconsideration timing, and public UI parity.
- [http-api.md](contracts/http-api.md) defines the status projection, streamed endpoints, SSE result/error mapping, cancellation, and Vue actions.
- [artifacts.md](contracts/artifacts.md) defines disk layout, pattern and conflict contracts, proposal snapshots, capability deployment, journals, and ledgers.
- [manifest.schema.json](contracts/manifest.schema.json) and [measurement.schema.json](contracts/measurement.schema.json) define collection and measurement artifacts.
- [conflict-ruling.schema.json](contracts/conflict-ruling.schema.json), [companion-capability.schema.json](contracts/companion-capability.schema.json), and [usability-result.schema.json](contracts/usability-result.schema.json) define seed adjudication, companion verification, and acceptance timing.

### UI design and resize behavior

`/workflow/wiki` is step 7 of the existing session workflow and is linked as `③ Narration Wiki` in the existing sidebar. It reloads status on mount and after every streamed action, transport error, or cancellation. It keeps no authoritative state in Pinia or local storage.

The page presents selection and dependency status, collection and baseline controls, seed-conflict cards, per-pattern Gate 1 cards, one Gate 2 proposal with complete diff and before/after evidence, and durable history. It exposes no bulk ruling or automatic advancement.

All new CSS uses existing Catppuccin variables, font families, button classes, focus states, status meanings, spacing, radii, and scrollbar skin. No feature-specific color token or literal color is added. Because the application shell owns `overflow: hidden`, the layout chain receives `min-width: 0` and `min-height: 0`; the page owns `overflow: auto` and a stable scrollbar gutter.

The manifest/evidence, measurement, diff/prior-ruling, and history/output regions share a border-box resizable contract: `min-width: 320px`, `min-height: 160px`, `resize: both`, `max-width: 100%`, `overflow: auto`, and stable gutters on both axes. Diff text keeps `white-space: pre`; measurement tables use an intrinsic minimum width and scroll horizontally. Panel internals wrap or use intrinsic/container-sized grids, and Gate controls remain in a reachable scroller or a non-obscuring sticky action bar. The workflow step strip owns horizontal overflow.

The broader UI-style and scrolling doctrine remains tracked separately by [issue #360](https://github.com/kostadis/CampaignGenerator/issues/360); this feature does not amend the constitution.

### Verification strategy

pytest covers the three documented layouts, path escapes, deterministic bytes, structured `voice_lint` compatibility, D4 budgets, maximal cross-narrator reuse, missing or drifted baselines, the Phandalin em-dash conflict, companion manifest incompatibility, same-digest/new-path reconsideration refusal, genuinely new digest/rule acceptance, explicit override, unauthorized or stale proposals, byte-exact restoration, duplicate ledger refusal, transaction recovery, route argv and transport parity, runner logging disabled/default-on compatibility, cancellation process-group cleanup, empty selection, and renderer isolation.

Frontend tests cover POST-SSE parsing across arbitrary chunks, return-code classification, `AbortError` versus transport errors, mandatory status refresh, route/action parity, existing style tokens, and the production build. Pinned Playwright runs at exactly 1280x720 and resizes every declared panel to exactly 320x160. Deterministic long, tall, and wide fixtures must produce positive horizontal or vertical scroll ranges as appropriate; the test scrolls to maximum extents and keyboard-focuses both Gate actions without clipping.

The real-session timed exercise begins when `/workflow/wiki` opens with an explicitly selected session and ends when the Gate 2 ruling is persisted. It records total elapsed seconds, excluded companion-model response seconds, derived active-operator seconds, both Gate references, and the persisted ruling path. Passing requires active operator time below 900 seconds.

The runnable validation sequence is in [quickstart.md](quickstart.md).

## Post-design Constitution Check

The Phase 1 design continues to pass all thirteen principles:

- Disk artifacts remain canonical and every semantic decision remains explicit.
- The checker is deterministic and one-directional; no wiki import reaches rendering.
- All process execution remains in `server/subprocess_runner.py`; routers and Vue only adapt or present the CLI contract.
- Session selection is mandatory and empty never means all.
- Every public command has a page action; low-level byte and ledger operations remain internal.
- Existing campaign state is not migrated or probed from a legacy location.
- Portable writes and companion model behavior remain outside this repository.
- UI style and scrolling requirements are local to this feature; issue #360 remains a future constitution change.

**Post-design gate result**: PASS. No unresolved clarification, constitutional violation, or unwaived complexity remains.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| None | N/A | N/A |
