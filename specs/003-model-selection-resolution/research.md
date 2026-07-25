# Phase 0 Research: Model Selection Resolution

All findings verified against source at `d678684` (main). Every claim below cites the file and
line it was read from.

## R1 — How many resolution rules exist today, and where

**Decision**: There are **five** independent spellings of "which model/backend does this run use",
not the three the spec's Overview counted. The fifth lives *below* the CLI seam and silently
undoes any decision made above it.

| # | Site | Levels resolved | Behaviour on a foreign model id |
|---|---|---|---|
| 1 | `server/platform_config_service.py:137` `resolve_default_model` | 3: explicit → `platform.runtime.default_model` → `DEFAULT_MODEL` | no concept of one |
| 2 | `server/routers/ensemble.py:117` `_backend_args` | 4: explicit → per-stage `ensemble.yaml` → platform → literal | **silently discards**, substitutes platform (`ensemble.py:170`) |
| 3 | `server/routers/scene_editor.py:554` `_model_args` | 2: `backends.<active>.model` → `cfg.model` | passes through |
| 4 | `server/routers/grounding.py:72` `_backend_flags` | reads **another service's** config | n/a — emits a second `--model` |
| 5 | `campaignlib/api/backends.py:109` `_OpenAICompatMessages._resolve_model` | 2: client override → caller's id | **silently substitutes `DGX_DEFAULT_MODEL`** for any `claude-*` id |

**Rationale for calling out #5**: it is the reason the defect has been invisible. A Grounding run
that emits `--model claude-sonnet-4-6 --backend dgx` does not fail — the DGX adapter quietly swaps
in its own default and the run succeeds on a model nobody chose. FR-011 ("never silently replace an
operator-set selection") cannot be satisfied by fixing the routers alone while #5 stands.

**Alternatives considered**: leaving #5 untouched as a CLI-side safety net. Rejected for the UI
path — it converts a refusal into a silent substitution, defeating the clarified decision. See R6
for how the CLI keeps its net without the UI inheriting the lie.

## R2 — The two-owner command (the concrete bug)

**Decision**: Confirmed as a real, reproducible defect, not a theoretical one.

`server/routers/grounding.py:202` (and `:238`, `:295`, `:348`, `:386`) builds:

```
cmd += ["--model", resolve_default_model(model, request)]   # platform tier
cmd += _backend_flags(request)                              # Session Doc Editor's tier
```

`_backend_flags` (`grounding.py:72-90`) constructs a `SessionEditorConfigService` and reads
`backends.active`; `server/backend_forwarding.py:39` appends a **second** `--model` when that
service has one stored. Outcomes:

- Editor has a DGX model stored → two `--model` flags; argparse last-wins; the run works *by
  accident*, on the editor's model, not the platform's.
- Editor has none stored → a single `--model claude-…` flag reaches `--backend dgx`, and R1 #5
  silently substitutes the DGX default.

Either way the resolved model is not the one the operator picked, and nothing reports it.

**Rationale**: this is why FR-006 (backend to the platform tier) and FR-005 (no service reads
another's selection) are one change, not two — the cross-service read exists *only* because
Grounding had no tier of its own to read from.

## R3 — Where the platform tier gains `default_backend`

**Decision**: Add `default_backend` to `PlatformRuntime` (`server/platform_config_shared.py:109`),
persisted in the existing `runtime:` key of `platform.yaml`. No new file, no new service.

`PlatformRuntime` is `extra="forbid"` with two fields (`default_model`, `session_dir`). It is
already the sidebar model picker's home and is written through the one choke point
`PlatformConfigService.update_runtime`, reached by `PUT /api/config/runtime`.

**Migration**: the sidebar BACKEND toggle currently writes `session_doc.yaml`'s `backends.active`
via `PUT /api/editor/config` (`frontend/src/components/layout/AppSidebar.vue:20` `setBackend` →
`config.ts` `updateEditor`). The value must move to `platform.yaml`. `server/migrate_platform_config.py`
is the established precedent for a one-shot migration of exactly this shape.

**Alternatives considered**:
- A new `platform.backend` section rather than a `runtime` field — rejected; `runtime` already
  means "the cross-service defaults the sidebar sets", and a second section would re-open the
  "which global tier owns this" question the platform isolation closed.
- Leaving backend in `session_doc.yaml` and having Grounding read the platform for model only —
  rejected by the clarified decision, and it would preserve the two-owner command of R2.

## R4 — Where the five services store their override

**Decision**: A single reusable `ModelSelection` shape (`model` + `backend`, both optional),
embedded in each service's **existing** document. Zero new files, per FR-004.

| Service | Document | Existing override today | Change |
|---|---|---|---|
| Ensemble | `ensemble.yaml` | `EnsembleBackend` per stage (`ensemble_config_shared.py:62`) — has `backend`, `endpoints`, `model` | already conformant; re-express in shared terms |
| Session Doc Editor | `session_doc.yaml` | `Backends` per backend (`session_editor_config_shared.py:73`) — `backend`, `endpoint`, `model` | already conformant |
| Grounding | `grounding.yaml` | none | add the field |
| Party | `party.yaml` | none | add the field |
| Planning | `planning.yaml` | none | add the field |

**Rationale**: Ensemble and Session Doc Editor already encode model+backend as a unit; the two
schemas differ only in `endpoints` (plural, DGX fan-out) vs `endpoint` (singular), which is a real
distinction the spec's Assumptions preserve. The shared shape must therefore be the *common* core,
not a forced unification of those two.

**Alternatives considered**: hoisting all five into one `selections:` block on `platform.yaml`.
Rejected — it recreates the fused-ownership anti-pattern `docs/config/platform-isolation.md`
Phase 2 split apart, and would let a service's write corrupt the platform tier.

## R5 — How compatibility is decided (FR-009)

**Decision**: Compatibility is a **backend-declared predicate**, and the `claude-` prefix test
already used by `ensemble.py:170` is the correct basis for the Anthropic branch — with its existing
rationale carried forward verbatim (`ensemble.py:160-166`): membership of `server/config.py`'s
`MODELS` list is **not** the test, because `MODELS` is a hand-maintained snapshot and testing
against it would reject a legitimate new Claude id that simply had not been added yet.

Rules per backend:

| Backend | A model id is compatible when | Source |
|---|---|---|
| `anthropic` | it starts with `claude-` | `ensemble.py:160-166` |
| `dgx` | it does **not** start with `claude-` | `backends.py:115` inverted |
| `openrouter` | it is vendor-namespaced (`vendor/model`), never a bare `claude-…` | `backends.py:221-225` |
| `claude-code` | it starts with `claude-` | shares the Anthropic vocabulary |

**Rationale**: the predicate only rejects ids that *cannot* belong to the target backend, and never
second-guesses one that could. This keeps a new model working the day it ships without a code
change — the property `MODELS`-membership would destroy.

**Alternatives considered**: asking each backend adapter to validate at call time. Rejected — that
is exactly R1 #5, and it happens after tokens are committed rather than before the run starts.

## R6 — Where the refusal is enforced

**Decision**: Refuse at **resolution time, in the server, before the subprocess is spawned** —
i.e. inside the single resolver, whose return value the routers already use to build `cmd`.

The refusal cannot live in the CLI scripts: Principle VI makes the CLI the engine, and a GM typing
`--model Qwen/… --backend anthropic` at a shell is making an explicit act the way a typed glob is
explicit under Principle X. The UI, which resolves on the operator's behalf from stored state, is
where an unchosen substitution can occur, so that is where it must be blocked.

**Consequence for R1 #5**: `campaignlib/api/backends.py`'s `claude-* → DGX_DEFAULT_MODEL`
substitution stays for direct CLI use but must no longer be reachable from a UI-launched run,
because the resolver will have refused first. This is a behaviour-preserving split, not a removal.

**Alternatives considered**: refusing inside `subprocess_runner.stream_subprocess`. Rejected — by
then the command is built and the router has already lost the structured reason for the refusal;
the operator would get a stream error instead of an actionable message (the failure mode
`specs/002` exists to eliminate).

## R7 — Satisfying FR-014 (record what a run used)

**Decision**: Already satisfied by existing infrastructure; no new persistence.

`specs/002-ensemble-run-observability` shipped a durable run record written by
`server/subprocess_runner.py::_save_run_log` to `<campaign>/logs/<timestamp>_<script>.md`, whose
`command` field is the full, secret-free invocation (`specs/002/data-model.md`, T004 complete).
Because the resolved model and backend reach the subprocess *as `--model`/`--backend` flags on that
command line*, the record already contains them.

**Rationale**: this is Principle VIII (state discoverable on disk) already paid for. FR-014 becomes
a verification task, not a build task.

**Alternatives considered**: a dedicated selection-history file. Rejected as a recurring tax under
"Architecture is Destiny" with no truth it would hold that the run log does not.

## R8 — Existing tests that assert the behaviour being reversed

**Decision**: Three tests assert the silent substitution that FR-009/FR-011 reverse, and must be
rewritten to assert refusal:

- `tests/test_ensemble_gates.py:83` `test_synthesize_ignores_stale_model_for_anthropic`
- `tests/test_ensemble_gates.py:107` `test_bundle_ignores_stale_model_for_anthropic`
- `tests/test_ensemble_gates.py:129` `test_extract_ignores_stale_model_for_anthropic`

`tests/test_synthesis_capable_registry.py:130` references the first by name in a docstring and
needs its comment updated.

Tests that must keep passing unchanged (they encode the resolution chain this feature unifies):
`tests/test_default_model_resolution.py` (whole file), `tests/test_ensemble_config_defaults.py`
`TestModelResolution`, `tests/test_editor_service_integration.py` `TestO3ModelResolution`.

**Rationale**: naming these up front prevents the reversal from being discovered as a "broken test"
during implementation and silently re-reverted to make the suite green.

## R10 — The endpoint count was wrong (correction)

**Decision**: The feature covers **22** token-spending endpoints, not the 17 quoted in the first
draft of the spec, plan and contracts. All artifacts have been corrected.

The undercount came from treating the Session Doc Editor as two endpoints (narrate, scrub). It has
**six**, and they are spread across more command builders than any other router:

| Router | Endpoints | Count |
|---|---|---|
| `grounding.py` | campaign-state, distill, party, planning, build-dossiers | 5 |
| `ensemble.py` | extract, bundle, recent-events, threads, synthesize | 5 |
| `prep.py` | session-prep, npc-table, query | 3 |
| `setup.py` | dnd-sheet, make-tracking | 2 |
| `scene_editor.py` | enhance, extract, narrate/{n}, scrub/{n}, scrub-all, plan | **6** |
| `connections.py` | extract | 1 |
| | | **22** |

Within `scene_editor.py`, `_model_args` has **7** call sites and `_backend_flags` **6**, spread over
`_build_enhance_cmd` (:599), `_build_reextract_cmd` (:632), `_build_narrate_cmd` (:683),
`_build_consistency_cmd` (:1124), `_build_plan_cmd` (:1159) and the handlers `api_enhance` (:962),
`api_extract` (:993), `api_narrate` (:1016), `api_scrub` (:1052-53), `api_scrub_all` (:1083-84),
`api_plan` (:1184-85).

**Rationale for recording it**: T013 was written as "narrate and scrub" and would have left four
session-editor endpoints on the old two-level chain — a silent partial migration that the
characterization test (T002/T020) would not have caught, because the test's endpoint list was
derived from the same wrong count. Both were corrected together.

## R9 — Technical context resolved

No `NEEDS CLARIFICATION` items remain.

- **Language/Version**: Python 3.13 (server + CLI), TypeScript/Vue 3 (frontend).
- **Primary dependencies**: FastAPI, Pydantic v2 (`extra="forbid"` schemas), PyYAML, Vue 3 + Pinia.
- **Storage**: YAML documents in the campaign workspace — `platform.yaml`, `ensemble.yaml`,
  `session_doc.yaml`, `grounding.yaml`, `party.yaml`, `planning.yaml`. No database.
- **Testing**: pytest (`python -m pytest tests/`).
- **Scale/scope**: 6 routers, 22 token-spending endpoints, 5 override-capable services, 5
  inheriting services, 1 platform tier.
- **Constraint**: single-user deployment. Per the standing project rule, migrate-and-delete rather
  than dual-location probes or back-compat shims.
