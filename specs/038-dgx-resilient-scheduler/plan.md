# Implementation Plan: Resilient DGX Work Scheduler

**Branch**: `codex/549-dgx-scheduler` | **Date**: 2026-10-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/038-dgx-resilient-scheduler/spec.md`

## Summary

Replace the current fixed summary-native `--parallel 6` default and best-effort shared queue with a reusable, deterministic scheduler. The concurrency resolver reads `max_concurrency` from the selected model's dgxlib record, while an explicit CLI value still wins and an absent field falls back to 6. The scheduler owns endpoint health, quarantine, cross-endpoint retry after campaignlib's transport retry chain, durable attempt/telemetry records, cache-based resume, and stable result assembly. Extraction, audit, NPC drafting, and per-NPC verification adapt their existing item/result contracts to it. FastAPI continues to invoke the CLI, and Summary Native/NPC UI controls read durable status rather than creating browser-only state.

## Technical Context

**Language/Version**: Python >=3.10; TypeScript ~5.9 with Vue 3.5

**Primary Dependencies**: campaignlib; dgxlib model registry; OpenAI-compatible DGX client; FastAPI; Pydantic 2; Vue; existing summary-native corpus/cache modules

**Storage**: Existing Markdown/JSON cache artifacts and atomic JSON run records under each summary-native range/NPC range; no database and no independent checkpoint store

**Testing**: pytest with fake clients/endpoints, injected clocks and zero-delay retry seams; existing route tests; Vue type-check/build

**Target Platform**: Local Linux CLI and CampaignGenerator local web application, with one or more configured DGX/vLLM endpoints

**Project Type**: Python CLI/library plus FastAPI and Vue web application; coordinated dgx-fun/dgxlib registry change

**Performance Goals**: Honor the selected per-endpoint limit (8 for `qwen3.8-flash-next`); keep every healthy endpoint supplied while queued work exists; no duplicate completed calls during resume; endpoint recovery within one configured health interval

**Constraints**: campaignlib remains the only model-call seam; its transport retry is not repeated on the same endpoint by the scheduler; outputs stay byte-stable by item order; cache/run files are truth; explicit selection only; no live DGX needed for tests

**Scale/Scope**: Four summary-native operations, typically tens to hundreds of items, one to several DGX endpoints, bounded worker threads, and one durable run record per invocation

## Constitution Check

*GATE: Passes before research and after Phase 1 design. No justified violation is required.*

| Principle | Design evidence | Gate |
|---|---|---|
| I. Disk is Truth | Existing result artifacts plus atomic run records determine resume; browser and memory are projections. Model results remain drafts. | PASS |
| II. Human Checkpoint | Scheduling changes transport only. It does not select scope, accept verifier findings, correct content, or promote output. Empty selection refuses. | PASS |
| III. Retrieval/Render Separation | Adapters consume already selected items/evidence and call a renderer. Scheduler performs no retrieval or model rendering itself. | PASS |
| IV. Verbatim is Sacred | Existing operation validators and exact cache keys remain authoritative; failover cannot bypass quote/citation checks or turn incomplete output into success. | PASS |
| V. One Seam per Boundary | Model calls and failure classification stay in campaignlib; per-model DGX behavior stays in dgxlib. The scheduler receives clients/callables and never imports provider SDKs. | PASS |
| VI. CLI is Engine | Scheduler behavior is implemented behind CLI commands. Routes build fixed argv and stream/read CLI artifacts. | PASS |
| VII. Extract Once | Resume reuses compatible extraction/draft caches and sends only unfinished work. No alternate checkpoint result store is introduced. | PASS |
| VIII. State is Discoverable | Run records include item state, endpoint transitions, attempts, compatibility, and telemetry; status can be reconstructed after interruption. | PASS |
| IX. UI Mechanizes | UI exposes selection, invocation, resume, and status. Human review and semantic judgment remain in CLI/chat/review flows. | PASS |
| X. Selection is Explicit | CLI adapters materialize stable selected items before scheduler invocation; UI refuses empty selection and materializes Select all. | PASS |
| XI. Parity is Bidirectional | Effective default/source, resume, and endpoint health are exposed on Summary Native and NPC workflows in the same feature. | PASS |
| XII. One Spelling per Option | Shared operations use `--endpoints`, `--parallel`, and `--resume`; default resolution has one helper and one provenance vocabulary. | PASS |
| XIII. Out-of-Band Migration | Existing cache/run readers remain compatible and no workspace shape migration is required. New record fields are additive; docs explain the changed default. | PASS |

### Post-design re-check

The data model makes the cache artifact authoritative and the run record an observable attempt journal; it cannot claim completion without a compatible artifact. Contracts preserve explicit selection, CLI/UI parity, campaignlib/dgxlib seams, and deterministic assembly. The quickstart tests human gates and cached/incomplete behavior. All thirteen gates remain PASS.

## Project Structure

### Documentation (this feature)

```text
specs/038-dgx-resilient-scheduler/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli.md
│   ├── dgxlib.md
│   ├── run-record.md
│   └── ui-api.md
├── checklists/requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
campaignlib/
└── api/client.py                         # public post-retry failure classification seam

pipelines/summary_native/
├── scheduler.py                          # generic deterministic queue/health/attempt engine
├── concurrency.py                        # explicit > dgxlib model value > fallback resolution
├── extract.py                            # chunk adapter, cache result validation/assembly
├── audit.py                              # audit-item adapter and report mapping
├── npc_draft.py                          # selected-NPC adapter and draft cache mapping
├── npc_verify.py                         # per-NPC deterministic verification item adapter
├── cli.py                                # shared flags, resume selection and orchestration
└── schema.py                             # defaults and stable outcome/taxonomy constants

server/
├── routers/summary_native.py             # extract/audit start, status and resume argv
└── routers/npc_dossiers.py               # draft/verify start, status and resume argv

frontend/src/
├── views/grounding/SummaryNative.vue     # effective concurrency and endpoint/run status
└── views/npcs/NpcDossiers.vue            # draft/verify scheduler controls and status

docs/cli/
├── summary_native_howto.md
└── npc_dossiers_howto.md

tests/
├── test_summary_native_scheduler.py
├── test_summary_native_concurrency.py
├── test_summary_native_extract.py
├── test_summary_native_audit.py
├── test_summary_native_npc_draft.py
├── test_summary_native_npc_verify.py
├── test_summary_native_routes.py
├── test_npc_dossiers_routes.py
└── test_dgx_registry.py
```

**Structure Decision**: Put provider-neutral orchestration beside its summary-native consumers, expose only model-call retry classification through campaignlib, and keep dgxlib as the sole owner of per-model behavior. Operation adapters retain ownership of prompts, cache keys, validation, artifact writes, and final reports. Existing Summary Native and NPC route/page families remain the UI faces; do not create a duplicate page.

## Delivery Sequence

1. Land the dgx-fun/dgxlib schema and `qwen3.8-flash-next: max_concurrency: 8`, including backward-compatible absence behavior and dgxlib tests.
2. Add CampaignGenerator concurrency resolution and provenance, first covering extraction/audit default behavior from issue #539.
3. Add scheduler primitives and deterministic fake-endpoint tests before adapting production operations.
4. Adapt extraction and audit, removing their caller-level same-endpoint transport retry and preserving content-validation retry only where explicitly classified as model-response rejection.
5. Adapt NPC drafting and per-NPC verification with explicit selection and their existing cache/report authority.
6. Add CLI resume/status contracts and stable run records, then route/UI parity and documentation.
7. Run focused scheduler/operation/route tests, full pytest, and frontend type-check/build; validate the quickstart failure/recovery matrices.

## Cross-Repository Coordination

The CampaignGenerator implementation can consume and test a fake `max_concurrency` field, but issue #539 is not complete until dgx-fun/dgxlib publishes the field and sets `qwen3.8-flash-next` to 8 to match the served `max-num-seqs`. Keep CampaignGenerator's absence fallback at 6 for older dgxlib installations. The dgx-fun change should land first or be pinned in the CampaignGenerator dependency/workspace instructions before end-to-end acceptance.

## Complexity Tracking

No constitution violation or exceptional complexity waiver is required. The scheduler is a shared library because four named operations require identical bounded dispatch, health, failover, resume, and telemetry semantics; operation-specific result/cache logic stays in adapters rather than being generalized into the engine.
