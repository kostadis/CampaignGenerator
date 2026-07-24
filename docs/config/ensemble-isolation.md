# Ensemble Configuration Isolation Design

> **Status: ✅ Done (2026-07-24).** All six phases shipped on
> `feat/ensemble-config-isolation`. Ensemble — the largest remaining
> `ui.<section>` tenant — now owns a strict `<config>/ensemble.yaml` through
> `EnsembleConfigService`, the third service to take its config out of
> `ui_state.yaml` after `session-editor-isolation.md` and
> `planning-isolation.md`, on top of the platform tier
> `platform-isolation.md` extracted. Per-phase detail and the delivered API are
> in [Implementation Status](#implementation-status).
>
> **Gate cleared:** `specs/002-ensemble-run-observability` T033 (manual
> quickstart validation) was completed by the operator; Phases 0–2 were scoped
> additive so they could land before it, and Phases 3–6 followed after.
>
> **Parallel work:** the `fix/ui-model-config-drift` branch has uncommitted
> edits to `server/routers/ensemble.py`, deriving `SYNTHESIS_CAPABLE` from the
> `MODELS` registry instead of a frozen literal. It touches only that module
> constant, not route signatures — no conflict with anything here, and it makes
> Phase 4's "leave `SYNTHESIS_CAPABLE` alone" decision doubly correct.

## Overview

Ensemble is drawn in [service-cut.md](./service-cut.md) as a service with
"service-local config: `ui.ensemble`, `manifest.json`, `merge.yaml`, aliases file,
`*_draft.md`". That row is optimistic. In the shipped code, `ui.ensemble` is not
the ensemble service's config — it is a **frontend-only scratchpad** that the
ensemble backend has never read.

This design gives the Ensemble service what Session Doc Editor and Planning
already have: its own strict schema, its own file, its own service, its own REST
surface — and, uniquely for this service, closes a genuine split-brain between
where the defaults are declared and where they are used.

## Current state (code-verified)

### 1. The router cannot see its own config

`server/routers/ensemble.py` (647 lines, 10 routes) imports:

```python
from campaignlib.registry import find_registry
from server.backend_forwarding import backend_cli_args
from server.party_config_shared import load_party_config
from server.planning_config_shared import load_planning_config
from server.subprocess_runner import console_script, stream_subprocess, sse_error_stream
```

No `PlatformConfigService`, no `UIStateService`, no `require_platform`, no
`Depends`, no `app.state`. **`ui.ensemble` has zero backend readers.** Every value
reaches the engine as a query parameter the browser supplied, or as a literal
baked into the route signature.

### 2. Three-way default drift

Because there is no shared source, the same default is declared independently in
Python-model, Python-router, and TypeScript:

| Value | `EnsembleSection` | Router signature | Frontend fallback |
|---|---|---|---|
| `chapters_glob` | `config_models.py:141` | `list_chapters` `glob=` (`ensemble.py:287`) **and** `status` `chapters=` (`ensemble.py:249`) | `useEnsembleRun.ts:118` |
| `backend` | `BackendProfile.backend` (`config_models.py:124`) | `"anthropic"` ×5 routes | `useEnsembleRun.ts:111` |

Four copies of `docs/chapters/chapter_*.md`. Changing the campaign's chapter
layout means editing three languages.

### 3. Router-only paths that are not configurable at all

These are hardcoded in route signatures, absent from the schema, and unreachable
from the UI — a campaign that lays out `docs/ensemble/` differently must edit
Python:

| Literal | Route(s) |
|---|---|
| `docs/ensemble/per_chapter` | `list_chapters`, `run_extract` |
| `docs/ensemble/merged.json` | `run_extract` |
| `docs/ensemble/per_chapter/*/merged.json` | `run_bundle`, `run_recent_events`, `run_threads` |
| `docs/ensemble/state_dossiers` | `run_bundle` |
| `docs/ensemble/merged_dossiers/*.md` | `run_synthesize` |
| `docs/ensemble/threads.md` | `run_threads`, `_default_threads_file` |
| `docs/recent_events.md` | `run_recent_events` |

Plus tuning knobs with no persisted home: `chapter_parallel=3`, `chunk_parallel=4`,
`min_facts` (3 in bundle, 2 in threads), `dossier_min_facts=10`, `entity_parallel=0`,
`window=0`, `depth="scene"`.

### 4. Six unmodelled keys survive only on `extra="allow"`

`EnsembleSection` (`config_models.py:129`) is `extra="allow"` and declares seven
fields. `EnsembleSynthesize.vue` persists six more that the model has never heard of:

```js
config.updateSection('ensemble', {
  planning_synth_mode, planning_npc, planning_arc_scores,
  planning_context, planning_depth, planning_force_include,
})
```

They round-trip because the model is loose. Nothing validates them; nothing on
the server reads them.

### 5. `BackendProfile` is singular in Python, plural in TypeScript

`config_models.py:125` declares `endpoint: OptStr = None`. The TS interface
declares `endpoints: string[]`, and `readEnsembleConfig` carries a migration shim
(`useEnsembleRun.ts:112-113`) reading the plural and falling back to the singular.
The plural field — the one actually written to disk today, and the one both
`run_extract` and `run_bundle` accept as `endpoints: list[str]` — exists in
`ui_state.yaml` only as unvalidated overflow. **The typed model documents a shape
the system stopped using.**

### 6. `campaign_dir` is dead and duplicated

`EnsembleSection.campaign_dir` is written by `EnsembleSetup.vue:31` and read back
by `readEnsembleConfig` — and used by nothing. The platform already owns
`campaign_dir` (`PlatformConfigService`, boot overrides). It is a second, stale
source of truth for a platform-tier value.

### 7. Ensemble is the only `/run/*` router outside `resolve_default_model`

Phase 5a of `platform-isolation.md` routed fourteen `/run/*` model fields through
`resolve_default_model` (`platform_config_service.py:119`) — `grounding.py` ×5,
`prep.py` ×3, `experimental.py` ×2, `session_workflow.py` ×1, `connections.py` ×1,
`setup.py` ×2. Ensemble's five LLM-bearing routes were not included; they hardcode
`backend="anthropic", model=""`. **The sidebar model picker
(`platform.runtime.default_model`) has no effect on any ensemble run.**

## Problems, stated plainly

1. **Split-brain.** Two independent declarations of the same defaults, in two
   languages, with no mechanism keeping them in sync. Already drifted (§5).
2. **Config that configures nothing.** `ui.ensemble` is a browser-local
   preference blob wearing a server-config file's clothes.
3. **No validation.** Loose section + six unmodelled keys + a shape mismatch that
   a strict schema would have caught at write time.
4. **Blast radius.** A malformed `ui.ensemble` write shares one file, one schema
   version, and one write lock with six other services' sections.
5. **Unreachable knobs.** Seven output paths and eight tuning values are
   Python literals — not settable per campaign without a code edit.

## Proposed solution

Follow the shipped pattern exactly: **strict schema → owning service → dedicated
file → REST surface → retire the section**.

### The load-bearing design constraint

`specs/002-ensemble-run-observability` (US1/FR) requires each run to emit an
**exact, copyable, reproducible command**. If the router silently reads config to
fill blanks, the echoed command stops reproducing the run.

**Resolution: config supplies defaults, the request carries resolved values, the
echoed command stays fully explicit.** The service resolves
`config → concrete value` and the router builds the command from resolved values
only. No implicit reads inside command construction. Phase 4 must not regress the
spec-002 contract, and its test plan says so.

### 1. Schema (`server/ensemble_config_shared.py`)

Strict (`extra="forbid"`), grouped, mirroring `SessionEditorConfig`:

```python
class EnsembleBackend(BaseModel):          # replaces BackendProfile
    model_config = ConfigDict(extra="forbid")
    backend: Literal["anthropic", "dgx", "openrouter", "claude-code"] = "anthropic"
    endpoints: list[str] = Field(default_factory=list)   # plural — the shipped shape
    model: OptStr = None

class EnsemblePaths(BaseModel):            # §3's seven literals, now declared once
    chapters_glob: str = "docs/chapters/chapter_*.md"
    per_chapter_dir: str = "docs/ensemble/per_chapter"
    corpus_glob: str = "docs/ensemble/per_chapter/*/merged.json"
    merged_out: str = "docs/ensemble/merged.json"
    state_dossiers_dir: str = "docs/ensemble/state_dossiers"
    dossiers_glob: str = "docs/ensemble/merged_dossiers/*.md"
    threads_out: str = "docs/ensemble/threads.md"
    recent_events_out: str = "docs/recent_events.md"

class EnsembleTuning(BaseModel):           # §3's eight knobs
    chapter_parallel: int = 3
    chunk_parallel: int = 4
    bundle_min_facts: int = 3
    threads_min_facts: int = 2
    dossier_min_facts: int = 10
    entity_parallel: int = 0
    recent_events_window: int = 0

class EnsemblePlanning(BaseModel):         # §4's six overflow keys, now typed
    synth_mode: Literal["config", "flat"] = "config"
    npc: list[str] = Field(default_factory=list)
    arc_scores: list[str] = Field(default_factory=list)
    context: list[str] = Field(default_factory=list)
    depth: Literal["scene", "full"] = "scene"
    force_include: list[str] = Field(default_factory=list)

class EnsembleConfig(BaseModel):           # root of <config>/ensemble.yaml
    model_config = ConfigDict(extra="forbid")
    chapters_selected: list[str] = Field(default_factory=list)   # no silent "all"
    known_names: list[str] = Field(default_factory=list)
    aliases_path: OptStr = None
    extract: EnsembleBackend = Field(default_factory=EnsembleBackend)
    synthesize: EnsembleBackend = Field(default_factory=EnsembleBackend)
    paths: EnsemblePaths = Field(default_factory=EnsemblePaths)
    tuning: EnsembleTuning = Field(default_factory=EnsembleTuning)
    planning: EnsemblePlanning = Field(default_factory=EnsemblePlanning)
```

`campaign_dir` is **not** carried — it is platform-tier (§6).
`Principle X` is preserved: `chapters_selected` empty means nothing runs; there is
no `select_all` boolean and no implicit glob expansion at run time.

### 2. Service (`server/ensemble_config_service.py`)

```python
class EnsembleConfigService:
    """Owns <config>/ensemble.yaml. Composes PlatformConfigService for path
    resolution and platform-owned reads — never re-implements them."""
    def __init__(self, platform: PlatformConfigService): ...
    @property
    def ensemble_config_path(self) -> Path: ...
    def resolved(self) -> EnsembleConfig: ...
    def update(self, partial: dict) -> EnsembleConfig: ...     # atomic, write-locked
```

Composition mirrors `SessionEditorConfigService`. Lazy on first write, atomic
writes, own lock — a bad ensemble write physically cannot corrupt `ui_state.yaml`
or `platform.yaml`.

### 3. REST surface (`server/routers/ensemble.py`, or a sibling)

Ensemble config is one document with grouped fields, not a collection — so it
takes **Session Doc Editor's document shape** (`GET`/`PUT /api/editor/config`),
not Planning's per-resource CRUD:

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/ensemble/config` | 200 `EnsembleConfig` |
| `PUT` | `/api/ensemble/config` | 200 `EnsembleConfig`; 400 on validation failure |

`PUT /api/config/section/ensemble` 404s afterwards (unknown section), matching the
`PUT /section/session_doc` precedent.

## Phases

Numbered to match the house convention. Each phase is independently shippable and
leaves the tree green.

### Phase 0 — delete the dead config

- Drop `EnsembleSection.campaign_dir`; remove its write in `EnsembleSetup.vue:31`
  and its read in `readEnsembleConfig`.
- **Decide the `endpoint`/`endpoints` mismatch (§5) explicitly** rather than
  carrying it forward: plural is the shipped truth; singular becomes a read-side
  migration shim only, deleted after Phase 5's migration.
- Precedent: Phase 0 of `platform-isolation.md` deleted twelve dead boot flags.

### Phase 1 — schema, no behavior change

- Add `server/ensemble_config_shared.py` with the models above +
  `load_ensemble_config` / `save_ensemble_config` (atomic —
  `campaignlib.util.atomic_write_text` already exists).
- Unit tests only. Nothing reads it yet.

### Phase 2 — the owning service

- Add `server/ensemble_config_service.py`; construct it after
  `PlatformConfigService` in `server/main.py`; per-request DI via `Depends`
  (Planning's shipped approach — not an `app.state` singleton).
- Add `GET`/`PUT /api/ensemble/config`.
- Regression test in the shape of
  `test_ui_section_write_cannot_touch_platform_yaml`:
  `test_ensemble_write_cannot_touch_ui_state_yaml`.

### Phase 3 — one default source

- Delete the router's duplicate literals. Route signatures keep their query
  params (spec-002 reproducibility depends on explicit values) but their
  **defaults come from `EnsembleConfigService.resolved()`**, resolved at the route
  edge before command construction.
- Delete the TS fallbacks in `readEnsembleConfig`; the frontend reads
  `GET /api/ensemble/config` and holds no defaults of its own.
- Test: assert no `docs/ensemble/` or `docs/chapters/` string literal remains in
  `server/routers/ensemble.py` — the mechanical guard that keeps §2 from
  re-drifting, in the spirit of `tests/test_retrieve_render_isolation.py`.

### Phase 4 — close the `resolve_default_model` gap

- Route ensemble's five LLM-bearing routes (`run_extract`, `run_bundle`,
  `run_synthesize`, and the two `backend_cli_args` call sites) through
  `resolve_default_model`, so the sidebar picker finally reaches ensemble.
- Precedence, matching Phase 5a: explicit request value → `ensemble.yaml`'s
  per-stage `EnsembleBackend.model` → `platform.runtime.default_model` →
  `campaignlib.constants.DEFAULT_MODEL`.
- Note the ensemble-specific wrinkle: ensemble legitimately runs non-Anthropic
  backends (dgx/openrouter/claude-code), so `resolve_default_model` applies to the
  **anthropic** branch only; the `SYNTHESIS_CAPABLE` warning stays as-is.

### Phase 5 — migration + retire the section

- `python -m server.migrate_ensemble_config --campaign-dir DIR` — one-shot lift of
  `ui.ensemble` (including the six overflow keys and the singular `endpoint`) into
  `ensemble.yaml`. Mirrors `server/migrate_session_doc.py` and
  `server/migrate_platform_config.py`.
- Remove `ensemble` from `UISection`; bump `SCHEMA_VERSION` 3 → 4. `UIState` stays
  `extra="allow"`, so a pre-migration file's leftover `ui.ensemble` loads
  harmlessly and is ignored — the precedent both prior removals set.

### Phase 6 — docs

Reconcile `schema.md`, `values.md`, `crud.md`, `subsystems.md`, `service-cut.md`,
`master.md` (layer table gains a `3c. Ensemble` row; the "No service ownership"
gap goes from **2 of ~9** to **3 of ~9**), and mark this doc Done.

## Explicitly out of scope

- **Gap #3, backend/model *selection* unification** (`service-cut.md`). Ensemble
  is one of four independent selectors (the others: `session_doc.yaml` `backends.*`,
  grounding's global picker, connections' per-request field). Phase 4 closes
  ensemble's *default-model* gap; it does not build the one platform provider all
  four would request from. That remains deferred.
- **Phase 5b of `platform-isolation.md`** (model registry source → `wiring.yaml`,
  [#177](https://github.com/kostadis/CampaignGenerator/issues/177)) — cross-repo,
  unchanged by this work.
- **The ensemble run artifacts** (`manifest.json`, `merge.yaml`, per-pass facts,
  `*_draft.md`). Disk stays truth; this design touches operator *selections* only.

## Test plan

| Area | Test |
|---|---|
| Schema | `tests/test_ensemble_config_shared.py` — strict rejection, defaults, round-trip |
| Service | `tests/test_ensemble_config_service.py` — lazy create, atomic write, empty-file reads as empty config (the bug `planning-isolation.md` hit twice) |
| Isolation | `test_ensemble_write_cannot_touch_ui_state_yaml[_via_route]` |
| No-drift guard | assert zero `docs/ensemble/`-shaped literals in `server/routers/ensemble.py` |
| Spec-002 contract | existing `tests/test_ensemble_gates.py` + the emitted `command` SSE event still reproduces the run verbatim after Phase 3 |
| Migration | `tests/test_migrate_ensemble_config.py` — incl. singular→plural `endpoint` lift |
| Routes | mount at `/api/ensemble/config`, not double-prefixed (the bug `planning-isolation.md` shipped) |

## Effort

| Phase | Rough size |
|---|---|
| 0 | S — deletions + one decision |
| 1 | S — new file, pure models |
| 2 | M — service + DI + 2 routes + isolation test |
| 3 | **L — the real work**; touches all 10 routes + 5 Vue files |
| 4 | S — 5 call sites, one precedence rule |
| 5 | M — migration CLI + schema bump |
| 6 | S — 6 docs |

## Implementation Status

| Phase | Item | Status |
|---|---|---|
| 0 | Drop `EnsembleSection.campaign_dir` + its frontend write/read | ✅ done |
| 0 | Resolve `endpoint`/`endpoints` (§5) | ✅ done — plural is declared in `EnsembleBackend`; `BackendProfile` left untouched (Session Doc Editor legitimately uses its singular `endpoint` for dgx) |
| 1 | `server/ensemble_config_shared.py` (models + load/save) | ✅ done |
| 2 | `server/ensemble_config_service.py` (`EnsembleConfigService`) | ✅ done |
| 2 | `GET`/`PUT /api/ensemble/config` + per-request DI | ✅ done |
| 2 | Isolation regression test | ✅ done |
| 3 | Router + frontend read from the service; delete duplicate literals | ✅ done |
| 4 | `resolve_default_model` for ensemble's LLM-bearing run routes | ✅ done |
| 5 | `migrate_ensemble_config` CLI; drop `ensemble` from `UISection`; bump schema 3 → 4 | ✅ done |
| 6 | Reconcile the six config docs | ✅ done |

**Shipped surface (Phases 1–2).** `<config>/ensemble.yaml`, lazy on first write,
atomic (`campaignlib.util.atomic_write_text`), strict (`extra="forbid"`):

| Method | Path | Success | Errors |
|---|---|---|---|
| `GET` | `/api/ensemble/config` | 200 `EnsembleConfig` (all-defaults if no file yet) | 400 malformed stored YAML |
| `PUT` | `/api/ensemble/config` | 200 merged+validated `EnsembleConfig` | 400 unknown key, bad value, or non-object body |

The `PUT` body is the grouped partial itself (`{"tuning": {"chapter_parallel": 6}}`),
**not** the `{"values": …}` envelope the generic `PUT /api/config/section/{name}`
uses — a `values` key is now a 400, since the schema is strict.

**Deviation from the design above:** `EnsembleConfigService` exposes both
`get_config()` and `resolved()`, currently identical. The seam is deliberate —
Phase 3 points the routes at `resolved()`, so a later change to how defaults
layer in doesn't have to touch every call site.

**Tests:** `tests/test_ensemble_config_shared.py` (defaults transcribed from the
shipped route literals so Phase 3 can't silently change behavior, strict-rejection
of all six legacy `planning_*` keys and the singular `endpoint`, empty/null/
malformed-file handling) and `tests/test_ensemble_config_service.py` (merge
semantics, the empty-selection round-trip Principle X requires, the HTTP contract,
the double-prefix guard, and `TestIsolationInvariant`). 44 tests, all passing;
full suite is at parity with `main` (same 7 pre-existing environmental failures).

## Open decision

**Phase 3's blast radius.** It rewrites the same route bodies
`specs/002-ensemble-run-observability` just rewrote, and spec-002's T033 (manual
end-to-end validation) has not been run. Two orderings:

- **(a) T033 first, then Phases 0–6.** Validates the observability work against a
  real workspace on a known-good tree, then refactors. Slower to start.
- **(b) Phases 0–2 now** (all additive — new files, new routes, nothing existing
  is edited), **T033, then Phases 3–6.** Parallel-safe, since 0–2 cannot break the
  routes T033 exercises.

Recommendation: **(b)**. It gets the schema and service landed without touching
the code under validation.

**Resolved: (b), and now complete.** Phases 0–2 landed first (additive only), T033
was run by the operator, then Phases 3–6 followed.
