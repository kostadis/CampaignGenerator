# Implementation Plan: Codex CLI Parity Across CLIs

**Branch**: `codex-cli-toolchain` | **Date**: 2026-08-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/016-codex-cli-parity/spec.md`

## Summary

Extend PR #350's isolated, saved-login `codex-cli` backend from the consistency
auditor to all 30 production commands that perform or forward language-model work.
The implementation keeps the ordinary text adapter narrow, adds ordered system
text-block support, and introduces a separate host-brokered structured-turn
capability for the existing ensemble polish loop. Every request or polish turn
uses a fresh ephemeral, tool-free Codex child; the parent application remains the
only executor of declared document operations.

Unify backend vocabulary and model provenance across the 26 shared registrars,
`facts_to_state`, and three ensemble dispatchers. Omitted Codex models reach
`CG_CODEX_MODEL` and then the subscription default, while explicit incompatible
models fail. Extend the existing config, resolver, router, and Vue seams so CLI and
UI launches resolve identically. Preserve all workflow artifacts, selection,
stages, checkpoints, retries, and application-level batch semantics. Add direct
UI reachability for the seven scoped capabilities that currently have no genuine
face, as required by the constitution.

## Technical Context

**Language/Version**: Python >=3.9; TypeScript ~5.9.3; Vue 3.5.30

**Primary Dependencies**: Existing `anthropic` facade, Pydantic 2, PyYAML,
FastAPI/Uvicorn, Vue/Pinia/Vue Router, Python `subprocess`, `tempfile`, and `json`;
installed Codex CLI 0.150.1 or a later version that honors the same strict command
surface. No new package dependency is planned.

**Storage**: Existing Markdown, YAML, JSON, and JSONL workflow artifacts plus
short-lived isolated temporary directories. No database.

**Testing**: pytest unit/contract/integration tests, mocked/fake Codex subprocess
tests, AST/source inventory guardrails, Vue type-check plus Vite build, and one
optional authenticated local smoke run.

**Target Platform**: Local Linux/WSL operator workstation with a saved Codex
subscription login; existing FastAPI subprocess/SSE server and browser UI.

**Project Type**: CLI-first Python application with a FastAPI command-launching
server and Vue frontend.

**Performance Goals**: Add no model work beyond each workflow's explicit units;
preserve current concurrency, resume, and skip behavior; use exactly one isolated
child per direct request or brokered polish turn; return one complete final chunk
to streaming-shaped callers; clean temporary material promptly on all exits.

**Constraints**: No metered API keys in Codex children; no provider fallback;
read-only ephemeral child with repository rules, user config, web, shell, plugins,
apps, MCP servers, and delegation disabled; no hidden selection expansion; no
automatic crossing of human-review gates; provider message batch remains
Anthropic-only; Scabard UI credentials must never appear in argv or logs.

**Scale/Scope**: 30 commands across four workflow families: 26 direct model-bearing
commands and four dispatchers; 26 shared parser registrars and four hand-written
choice surfaces; all existing backend selectors, seven new minimal invocation
faces, and their server command builders.

## Constitution Check

*GATE: Evaluated before Phase 0 research and re-checked after Phase 1 design.*

| Principle | Pre-design gate | Post-design re-check |
|---|---|---|
| I. Disk is Truth; Output is Draft | Pass: backend work retains existing artifact paths. | Pass: UI and broker results flow through existing disk-backed workflows; no browser-only result state. |
| II. Humans Own the Checkpoints | Pass: backend selection does not alter stage gates. | Pass: narration, polish, transformation, and review faces remain explicit and never auto-advance. |
| III. Retrieval and Rendering Stay Separate | Pass: provider transport does not change retrieval scope. | Pass: adapter translates already-selected prompt material only; no new hidden retrieval. |
| IV. Verbatim Material is Sacred | Pass: text, separators, roles, and ordering are requirements. | Pass: direct text blocks and typed transcript replay preserve content; no prose flattening. |
| V. One Seam, One Synthesis | Pass: feature 15's client seam is the sole provider boundary. | Pass: direct and brokered resources live in the same adapter; pipelines and routers do not invoke Codex. |
| VI. The CLI is the Engine; the UI is a Face | Pass: UI launches existing CLIs. | Pass: new faces only collect inputs and launch CLI builders; model work remains in Python CLI paths. |
| VII. Extract and Synthesize Deliberately | Pass: command stage structure is unchanged. | Pass: direct/fan-out/dispatcher coverage preserves extraction and synthesis units and reviewed inputs. |
| VIII. Context State Must Be Discoverable | Pass: selection and artifacts remain in existing config/files. | Pass: canonical config API, per-backend editor profile, logs, and ordinary outputs expose state. |
| IX. The UI Mechanizes; It Does Not Decide | Pass: UI offers provider choice but makes no content judgment. | Pass: new controls expose invocation and outcomes while retaining human decisions between stages. |
| X. Selection is Explicit; There is No Silent “All” | Pass: backend parity does not change selected work. | Pass: inventory, dispatcher, and workflow tests assert empty remains empty and children receive only explicit units. |
| XI. Parity is Bidirectional; Every CLI Capability Has a Face | Gate identified: the original “existing surfaces only” assumption was insufficient and no exemption was requested. | Pass: four commands have documented equivalent/transitive faces; seven genuinely missing capabilities receive minimal invocation faces and tested builders. |
| XII. One Spelling per Option; One Meaning per Family | Pass if the repeated backend literals are removed. | Pass: `Backend`/`BACKENDS`, one model resolver, explicit parser exceptions, and discovery guardrails define `codex-cli` once. |
| XIII. Breaking State Changes Migrate Out of Band | Pass: no breaking state change is proposed. | Pass: enum widening and one defaulted additive editor profile preserve old documents; compatibility tests replace an unnecessary migration. |

**Gate result**: PASS. There are no constitutional violations or requested
exemptions. The Phase 0 reachability finding expanded the specification and design
to cover seven missing UI faces rather than accepting an unstated CLI-only scope.

## Project Structure

### Documentation (this feature)

```text
specs/016-codex-cli-parity/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── adapter.md
│   ├── brokered-turn.schema.json
│   ├── cli-family.md
│   └── ui-selection.md
└── tasks.md                 # Created later by $speckit-tasks
```

### Source Code (repository root)

```text
campaignlib/
├── api/
│   ├── client.py            # Shared registrar, model intent, provider-neutral calls
│   └── codex_cli.py         # Direct and brokered isolated Codex transport
├── pipelines.py             # Shared sequential extract/synthesize callers
├── scenes.py                # Direct and batched-scene callers
└── selection.py             # Canonical backend vocabulary and compatibility

session_doc/
├── check_consistency.py
├── enhance_summary.py
├── scene_extract.py
├── sd_agent.py
├── sd_consistency.py
├── sd_narrate.py
├── sd_plan.py
└── vtt_voice_compare.py

pipelines/
├── content_ingest/dnd_sheet.py
├── session_prep/{prep.py,transform.py}
├── rlm/query.py
├── grounding/               # Eight scoped grounding commands
└── ensemble/                # Nine direct/dispatcher commands, including polish

scabard_sdk/scabard_sync.py

server/
├── backend_forwarding.py
├── platform_config_service.py
├── platform_config_shared.py
├── session_editor_config_{shared,service}.py
├── ensemble_config_shared.py
├── subprocess_runner.py
├── main.py
└── routers/
    ├── config_routes.py
    ├── scene_editor.py
    ├── ensemble.py
    ├── prep.py
    └── integrations.py      # New Scabard invocation route

frontend/src/
├── stores/config.ts
├── router.ts
├── components/
│   ├── layout/AppSidebar.vue
│   ├── shared/SelectionPanel.vue
│   └── scene-editor/KnobDrawer.vue
└── views/
    ├── SessionWorkflow.vue
    ├── session/SessionDocEditor.vue
    ├── prep/SessionPrep.vue
    ├── ensemble/{EnsembleSetup,EnsembleExtract,EnsembleSynthesize}.vue
    └── integrations/ScabardSync.vue

tests/
├── test_codex_cli_backend.py
├── test_polish.py
├── test_polish_codex.py
├── test_backend_seam_guardrails.py
├── test_batch_flag_uniformity.py
├── test_platform_config_service.py
├── test_session_editor_config_service.py
├── test_editor_pipeline.py
├── test_ensemble_*.py
├── test_grounding_backend.py
└── workflow-specific parser, route, and artifact tests

docs/cli/cli_tools.md
```

**Structure Decision**: Extend the existing CLI/API/server/frontend layers. The
Codex adapter remains the only child-process boundary; shared selection owns
vocabulary and compatibility; existing server builders remain the UI-to-CLI seam.
New UI files are limited to the genuinely missing invocation face for the Scabard
integration, while other missing capabilities extend their owning workflow views.

## Implementation Strategy

### Phase A: Integrate and harden the feature-15 baseline

1. Bring the merged PR #350 adapter/client baseline into this branch before parity
   edits.
2. Refactor the Codex child runner so direct and structured turns share identical
   command construction, environment sanitization, isolated cwd, timeout/error
   mapping, and cleanup.
3. Accept ordered system text blocks on the direct path without changing existing
   provider caching behavior.
4. Add brokered polish history normalization, temporary output schema, response
   facade, and usage-null compatibility. Keep `polish.run_agent_loop()` provider
   neutral and parent-owned.

### Phase B: Canonicalize selection and all command surfaces

1. Widen the canonical `Backend`/`BACKENDS` vocabulary and consume it from shared
   registrars and server types.
2. Introduce `resolve_cli_model(args, legacy_default=...)` (exact name may follow
   local style) and replace embedded parser defaults with an omission sentinel for
   every direct command. Preserve intentional `None` defaults and reject Codex plus
   Claude-specific `--fast` selections.
3. Update `facts_to_state` and the three explicit ensemble dispatcher parsers;
   prove the shared-registrar `sd_agent` dispatcher and ensemble child chains retain
   backend/model omission at every hop.
4. Refuse non-Anthropic provider `--batch` at every entry seam, including
   dispatcher-only `ensemble`, while preserving all application batch meanings.
5. Replace the stale 22-command manual guard with production discovery and the
   exact 30-command capability inventory.

### Phase C: Resolve server/config parity and persistence

1. Use model/backend origin in `resolve_selection()` to distinguish inherited from
   explicit Codex model intent. Keep generic argument emitters unchanged.
2. Add the defaulted `codex-cli` editor profile alias and broaden existing config
   models without changing existing document locations.
3. Add Codex to every existing selector/type, keep per-backend model memory, and
   preserve explicit batch-scenes overrides while treating both subscription CLI
   backends consistently by default.
4. Verify all existing router builders forward the resolved selection and no
   in-process/server consumer bypasses the canonical seam.

### Phase D: Close bidirectional UI reachability

1. Document and test the existing transitive chains for `sd_agent`, `ensemble`,
   `ensemble_extract`, and `extract_facts`.
2. Extend the session editor for `check_consistency`, `vtt_voice_compare`, and
   post-assemble `polish`, preserving their distinct outputs and checkpoints.
3. Extend Session Prep for `transform` and Ensemble views for
   `synthesise_polish` and per-chapter `narrate_chapter`.
4. Add a Scabard integration route/view that accepts the secret in the request
   body and supplies a child-only `SCABARD_ACCESS_KEY` environment override; teach
   the CLI to use that fallback and redact it from subprocess diagnostics. Test
   that command previews, logs, process listings, and errors never expose the key.
5. Map every inventory entry to a direct or transitive face and make the mapping a
   guardrail.

### Phase E: Verification and documentation

1. Prove direct and brokered adapter behavior, isolation, cleanup, errors, and
   zero fallback with mocked children.
2. Prove parser/help/model/batch parity for all 30 commands and representative
   artifact/request-shape behavior from all four families.
3. Prove CLI/UI resolution equivalence, config backward compatibility, selector
   behavior, secret redaction, and full dispatcher forwarding.
4. Update operator documentation with the complete command family, login/model/
   timeout rules, isolation, batch distinctions, UI reachability, and diagnostics.
5. Run focused tests, frontend build, and the full regression suite; keep the live
   authenticated smoke optional and operator-run.

## Implementation Coordination

Per the implementation instruction for this feature, the primary Sol agent owns
orchestration, integration decisions, and final review. Coding tasks are delegated
to Luna agents with non-overlapping file ownership; Sol reviews each change against
the contracts and runs the integrated verification before completion.

## Design Artifacts

- [research.md](./research.md): resolved decisions and rejected alternatives.
- [data-model.md](./data-model.md): selection provenance, request, transcript,
  broker result, inventory, and persisted-profile models.
- [adapter contract](./contracts/adapter.md): direct/brokered behavior and isolation.
- [broker result schema](./contracts/brokered-turn.schema.json): structured child
  response contract.
- [CLI-family contract](./contracts/cli-family.md): inventory, defaults, dispatch,
  batch, and guardrails.
- [UI-selection contract](./contracts/ui-selection.md): canonical launch flow,
  reachability, new faces, and persistence.
- [quickstart.md](./quickstart.md): implementation validation sequence.
