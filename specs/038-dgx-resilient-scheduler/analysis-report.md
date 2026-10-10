# Specification Analysis Report

**Analyzed**: 2026-10-10  
**Artifacts**: `spec.md`, `plan.md`, `tasks.md`, constitution v2.0.0  
**Method**: `$speckit-analyze` read-only pass followed by the parent-authorized post-analysis remediation and a second read-only consistency check.

## Findings and Resolution

| ID | Category | Severity | Original location(s) | Summary | Resolution |
|---|---|---|---|---|---|
| I1 | Inconsistency | HIGH | `spec.md` FR-004, FR-019, FR-020 and US5; `research.md` R8/R11; `contracts/cli.md`; `plan.md` structure | The spec implied current NPC verification was dispatched across DGX endpoints and all four workflows lived on Summary Native, while the code and plan correctly preserve deterministic model-free verification and the existing NPC Dossiers page. | Resolved. FR-004/019 now define local verification item execution with shared journaling and reserve endpoint scheduling for a future endpoint verifier. FR-020/US5 assign extract/audit to Summary Native and draft/verify to NPC Dossiers. |
| A1 | Ambiguity | MEDIUM | `spec.md` assumption and SC-003; `plan.md` Technical Context | “Configured health-check interval” could imply a missing user-facing option. | Resolved. The assumption now names one documented, status-visible implementation default, injected in tests, and explicitly excludes a new user-facing cadence option. |
| U1 | Underspecification | MEDIUM | `tasks.md` T001, T015, T016; `plan.md` Cross-Repository Coordination | Companion dgx-fun tasks referred to paths discovered by an earlier task rather than exact executable paths. | Resolved. Tasks now name `/home/kostadis/src/dgx-fun/dgxlib/registry.py`, `dgxlib/models.yaml`, and `tests/test_registry.py`; T001 records the pinned companion revision/order. |

No duplication, unresolved placeholder, untestable acceptance criterion, or constitution violation remains after remediation.

## Coverage Summary

| Requirement | Has Task? | Primary task IDs | Notes |
|---|---|---|---|
| FR-001 | Yes | T013–T019 | Precedence, fallback, parser resolution |
| FR-002 | Yes | T001, T015–T016 | Companion registry field and model value |
| FR-003 | Yes | T017–T019, T043, T047 | Provenance in record/CLI/UI |
| FR-004 | Yes | T007–T012, T023–T027 | Remote queue plus local verification executor |
| FR-005 | Yes | T003, T008, T020–T022 | Independent endpoint bounds |
| FR-006 | Yes | T009, T020–T022 | Independent health preflight/quarantine |
| FR-007 | Yes | T005–T006, T009, T020, T024 | Post-campaignlib failover only |
| FR-008 | Yes | T003, T008–T009, T020–T022 | Finite cross-endpoint attempts/exhaustion |
| FR-009 | Yes | T009, T020–T022, T041 | Probe, recovery, durable events |
| FR-010 | Yes | T003, T007–T008, T027 | Stable item identity/ordinal |
| FR-011 | Yes | T003, T008, T036, T039, T042 | Single canonical commit and byte stability |
| FR-012 | Yes | T004, T010, T029–T035 | Cache authority, journal subordinate |
| FR-013 | Yes | T029–T035 | Only unfinished work; zero-call completion |
| FR-014 | Yes | T010, T029–T034 | Compatibility binding and topology exclusion |
| FR-015 | Yes | T004, T029–T035 | Incomplete/corrupt/stale cache handling |
| FR-016 | Yes | T011, T037, T040–T042 | Separate operational outcomes |
| FR-017 | Yes | T011, T037, T040, T052 | Shared #523 taxonomy and legacy subcodes |
| FR-018 | Yes | T007, T038, T041–T042 | Per-endpoint telemetry reconciliation |
| FR-019 | Yes | T026–T027, T032, T046, T054 | Shared spelling; local verification semantics |
| FR-020 | Yes | T043–T050 | CLI-invoking existing UI faces |
| FR-021 | Yes | T004, T010, T043–T050 | Disk reconstruction after reload/disconnect |
| FR-022 | Yes | T027, T032, T043–T049 | Explicit nonempty selection |
| FR-023 | Yes | T004, T010, T019, T051–T055 | v1/cache compatibility, docs, no migration |
| FR-024 | Yes | T002–T005, T012–T015, T020–T022, T029–T031, T036–T038 | Controlled endpoints/clocks, no live model |
| SC-001 | Yes | T013–T019 | Complete concurrency matrix |
| SC-002 | Yes | T003, T008–T009, T020–T028 | Two-endpoint failure acceptance |
| SC-003 | Yes | T009, T020–T022, T028 | Recovery within injected interval |
| SC-004 | Yes | T029–T035 | Exact unfinished set and zero calls |
| SC-005 | Yes | T036, T039, T042 | Serial/parallel/failover/resume hashes |
| SC-006 | Yes | T011, T037–T042 | Unique outcome/taxonomy/reconciliation |
| SC-007 | Yes | T043–T050 | UI source/health/resume action path |
| SC-008 | Yes | T004, T010, T043–T050 | Reload-state matrix |
| SC-009 | Yes | T002–T005, T020–T022, T029–T031, T036–T038, T055 | Four operations and all required failures |

## Constitution Alignment

All thirteen principles pass before and after design. The most material safeguards are:

- operation artifacts prove completion; scheduler records prove attempts/health;
- scheduling never accepts, corrects, or promotes model/verifier content;
- provider calls and final failure classification remain at the campaignlib seam;
- per-model behavior remains in dgxlib;
- CLI remains the engine and existing UI pages invoke it;
- explicit selection is required and empty never means all;
- no workspace migration or competing checkpoint store is introduced.

## Unmapped Tasks

None. Setup/foundation tasks map to FR-002/004/007/010/012/018/023/024. Documentation and final validation map to FR-017/023/024 and SC-009.

## Metrics

- Functional requirements: 24
- Buildable success criteria: 9
- Total mapped requirements: 33
- Tasks: 55
- Story task counts: US1 7; US2 9; US3 7; US4 7; US5 8
- Parallel-marked tasks: 21
- Requirement coverage: 100%
- Findings before remediation: 3 (0 critical, 1 high, 2 medium)
- Findings after remediation: 0 open
- Ambiguities open: 0
- Duplications open: 0
- Constitution issues: 0

## Readiness

Artifacts are ready for `$speckit-implement`. Delivery should begin with the dgx-fun/dgxlib companion field and US1 concurrency resolver, then proceed through scheduler foundation, failover, resume, reporting, and UI parity. Current NPC verification must remain deterministic/model-free; its participation is stable local item scheduling, durable resume, and aligned reporting.
