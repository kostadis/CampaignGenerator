# Session Editor Configuration Isolation Design

> **Status: 📝 Draft / proposed (2026-07-23).** Not yet implemented. This is
> the design only; no code has changed. It follows the pattern established by
> [planning-isolation.md](./planning-isolation.md) but the session editor is a
> materially harder case — see [Why this is not planning](#why-this-is-not-planning).
> **Scope is decided** ([Resolved decision](#resolved-decision)): all five
> phases ship, ending with the data in its own `session_doc.yaml` (Option B).
> The single user handles the data lift by hand, so no automated migration
> tooling is in scope — and because the lift is manual, Phase 5 also
> **redesigns** the schema into a cleaner model instead of carrying the current
> `ui.session_doc` shape forward (see [Data model](#data-model)).

## Overview

The Session Doc Editor is the largest "service" in the multi-service monolith
([service-cut.md](./service-cut.md)): a four-stage post-session pipeline
(`enhance_summary` → `scene_extract` → `sd_plan`/`sd_narrate` → `assemble`)
driven by `server/routers/scene_editor.py` (1349 lines). Its configuration is
today spread across **three co-existing representations of the same truth**,
kept in sync by a per-request refresh and two separate dual-write paths.

This document proposes isolating that configuration behind a
`SessionEditorConfigService` that **owns** the editor's slice and reads its
platform dependencies (session dir, global model, campaign root, wiring)
through a clean, explicit boundary — eliminating the split-brain first, and
optionally moving the data to its own file second.

## Current state

The editor's config lives in three places at once:

| # | Representation | Where | Owner | Populated by |
|---|---|---|---|---|
| 1 | Typed `ui.session_doc` (`SessionDocSection`) + `ui.profiles` (`ProfilesSection`) | `<config>/ui_state.yaml` (shared) | `CampaignConfigService` | `PUT /api/config/section/session_doc` **and** `PUT /api/editor/config` |
| 2 | `scene_editor.CONFIG` — a flat, **module-global mutable dict** | in-memory (process-global) | nobody (a naked module global + two free functions) | `_refresh_config_from_service` (per-request) + `init_editor_config` (boot) + `PUT /api/editor/config` |
| 3 | Boot seed dict | in-memory | `server/main.py::main` | CLI flags, built **separately** from `boot_overrides` |

```mermaid
flowchart TB
  subgraph boot[Boot — server/main.py]
    FLAGS[CLI flags] --> BO["boot_overrides<br/>(dotted typed keys:<br/>session_doc.scene_extractions_dir …)"]
    FLAGS --> SEED["config dict<br/>(CONFIG-shaped keys:<br/>roleplay_extract_dir, examples …)"]
  end
  BO --> SVC[CampaignConfigService]
  SEED -->|init_editor_config| CFG["scene_editor.CONFIG<br/>(module global)"]
  SVC -->|resolved().ui.session_doc<br/>_refresh_config_from_service<br/>per request, with key renames| CFG
  SVC -->|runtime.default_model| CFG
  SVC -->|campaign_dir / config_dir| CFG
  CFG --> HELPERS["~20 module helpers &amp; command builders<br/>_session_dir(), _vtt_path(), _build_narrate_cmd(), _backend_flags() …"]

  subgraph fe[Frontend — SessionDocEditor.vue, one view]
    P1["path fields + narrate knobs<br/>→ PUT /api/editor/config"]
    P2["backend / batch / dgx_* / openrouter_model<br/>→ PUT /api/config/section/session_doc"]
  end
  P1 --> CFG
  P1 -->|api_put_config also writes| SVC
  P2 --> SVC
```

### The key-name translation layer

`ui.session_doc` (typed) and `CONFIG` (flat) do not even use the same field
names. `scene_editor._TYPED_TO_CONFIG_KEY` bridges them on every refresh and
every PUT:

| Typed (`ui.session_doc`) | CONFIG key |
|---|---|
| `roleplay_dir` | `roleplay_extract_dir` |
| `summary_dir` | `summary_extract_dir` |
| `examples_dir` | `examples` |

`CONFIG` additionally carries keys the typed section never had: `model` (from
`runtime.default_model`), `work_dir`, `campaign_dir`, `config_dir`, `vtt`,
`dossier_dir`.

### How writes reach the section today (two doors, one room)

`SessionDocEditor.vue` writes the **same** `ui.session_doc` through **two
different endpoints**, by design:

- `buildEditorConfigPayload()` → `PUT /api/editor/config` → `api_put_config`,
  which does `CONFIG.update(data)` **and** `service.update_section("session_doc",
  _config_to_typed_payload(data))`. (path fields, `narrate_tokens`, `prose_mode`,
  `reflections`, `narration_genre`, `context`, `work_dir`)
- `config.updateSection("session_doc", {...})` → `PUT /api/config/section/session_doc`.
  (`backend`, `batch`, `dgx_endpoint`, `dgx_model`, `openrouter_model`)

The Vue comments are candid about the split — `dgx_*` persistence is annotated
*"non-fatal — the next subprocess will still read the in-memory CONFIG."* The
frontend knows there is a live parallel store.

### Boot seeds the same paths twice

`server/main.py::main` derives session paths from `--session-dir`, then feeds
them into the system **twice**:

- `_boot_overrides_from_args(args)` → dotted `session_doc.*` keys → the service.
- a separate hand-built `config` dict (CONFIG-shaped) → `init_editor_config(config)`
  → `CONFIG`.

Two derivations of one truth that can drift.

## Problems

Beyond the four planning cited (coupling, blast radius, inefficiency, no
ownership), the session editor adds three of its own:

1. **Split-brain / fragmented state.** `CONFIG` is a second live copy of
   `ui.session_doc`, reconciled per-request by `_refresh_config_from_service`.
   The service comment claims it is "the single source of truth," but a mutable
   module global that carries extra keys, uses different names, and is seeded
   from a *different boot path* is a de-facto second authority. This is the
   Split-Brain / Optimistic-Lies shape the Kostadis doctrine warns about: two
   stores, a sync ritual, and a comment asserting they agree.
2. **Process-global mutable state.** `CONFIG` is module-level, not
   request-scoped. It works only because there is exactly one campaign per
   process; `_refresh_config_from_service` mutates it on every request as a side
   effect. Any move toward per-request or multi-campaign contexts breaks
   silently. There is no lock around the refresh-then-read window.
3. **Whole-file write blast radius.** `update_section("session_doc", …)`
   re-serializes the **entire** `ui_state.yaml` (a full `model_copy` +
   `_persist_ui_state`). A serialization bug on a session_doc write can corrupt
   `ui.ensemble`, `ui.grounding`, `ui.vtt_summary`, `runtime`, etc. This is
   exactly planning's problem #2 — and it is *not* fixed by an in-code service
   alone; the dedicated `session_doc.yaml` in Phase 5 is what fixes it.

## Why this is not planning

Planning was cleanly separable: `planning.yaml` was already its own file, its
data (npcs/factions) was self-contained, and it had no runtime dependencies. So
isolation there was purely additive — a new file-owning service + a new REST
collection API — with essentially zero coupling to unwind.

The session editor is the opposite. Its config is **defined in terms of
platform-global context** and cannot be made standalone:

| Session-editor config depends on | Owned by | Used for |
|---|---|---|
| `runtime.session_dir` | platform (also drives VTT Summary; set by SessionConfig picker) | resolving session-based path fields |
| `runtime.default_model` | platform (sidebar model picker) | `CONFIG["model"]` → `--model` on every stage |
| `campaign_dir` / `config_dir` | platform (boot context) | `work_dir`, subprocess `cwd`, `CG_CAMPAIGN_DIR`/`CG_CONFIG_DIR` |
| `wiring.yaml` `dgx_endpoint`/`dgx_model` | mneme (external) | `_backend_flags()` DGX fallback |
| `resolve_path` / `_PATH_FIELDS` / boot rebasing | `CampaignConfigService` | the subtle session-vs-campaign, boot-override, sibling-session-rebase logic |

Two further shape differences from planning:

- **Single blob, not a collection.** Planning gained `GET/POST/PUT/DELETE
  /{npcs,factions}/{name}`. The session editor's config is one object per
  campaign — the right HTTP shape is the `GET/PUT /api/editor/config` that
  **already exists**. So the isolation here is almost entirely *internal*; the
  wire surface barely changes. (Profiles are the one genuine sub-collection.)
- **~20 read sites, not 2.** Planning's old endpoints had only tests as callers.
  `CONFIG` is read by roughly twenty helpers and command builders across
  `scene_editor.py`. Removing the global is a real refactor of that file, not a
  route swap.

**Thesis:** isolating the session editor does not mean making its config
independent — it means giving it a service that **owns** its slice and
**reads** its platform dependencies through one explicit seam, and deleting the
`CONFIG` global that pretends to be that seam today.

## The ownership boundary

The whole design turns on drawing this line correctly.

**Owned by `SessionEditorConfigService` (service-local):**
- `ui.session_doc` fields — the knobs (`narrate_tokens`, `prose_mode`,
  `reflections`, `narration_genre`, `batch`, `scrub_*`, `backend`, `dgx_*`,
  `openrouter_model`) and the path/selector fields.
- `ui.profiles` — named knob presets. Editor-only.
- The CONFIG-key ↔ typed-key translation (`_TYPED_TO_CONFIG_KEY`) — removed when
  the `CONFIG` global goes (Phase 2); the final logical field names + grouping
  land with the reshape (Phase 5).
- The per-request **resolved editor view** (paths absolute, extras injected).
- Which `session_doc` path fields are session-based vs campaign-based
  (`_PATH_FIELDS["session_doc"]` conceptually moves here).

**Read from the platform (NOT owned — the honest part):**
- `runtime.session_dir`, `runtime.default_model` — stay in `RuntimeSection`.
- `campaign_dir` / `config_dir` — stay process context.
- `wiring.yaml` DGX defaults — stay mneme-owned.
- The path-resolution **mechanism** (`resolve_path`, boot rebasing) — stays in
  `CampaignConfigService`; the new service *delegates* to it rather than
  re-implementing the subtle bits.

`_backend_flags()` / `_model_args()` build subprocess CLI flags at request time.
They are **runtime command assembly, not stored config** — they stay in the
router (reading the resolved editor view), and are explicitly out of scope for
"config isolation."

## Proposed solution

```mermaid
flowchart TB
  FLAGS[CLI flags] --> BO["boot_overrides (single derivation)"]
  BO --> PLAT[CampaignConfigService — platform]
  PLAT -->|resolve_path, runtime.session_dir,<br/>default_model, campaign_dir, wiring| SES[SessionEditorConfigService]
  SES -->|Depends: get_editor_config| VIEW["ResolvedEditorConfig<br/>(request-scoped, immutable)"]
  VIEW --> H["scene_editor handlers &amp; helpers<br/>(receive the view; no module global)"]
  FEUI["SessionDocEditor.vue (one write path)"] -->|PUT /api/editor/config| SES
  SES -->|owns &amp; writes exclusively| STORE[("&lt;config&gt;/session_doc.yaml<br/>session_doc + profiles")]
```

### 1. `SessionEditorConfigService` (`server/session_editor_config_service.py`)

Owns the session-editor slice; composes the platform service for path
resolution and platform reads.

```python
class SessionEditorConfigService:
    def __init__(self, platform: CampaignConfigService): ...

    # Raw, typed slice (service-owned)
    def get_session_doc(self) -> SessionDocConfig: ...
    def update_session_doc(self, partial: dict) -> SessionDocConfig: ...

    # Profiles (the one sub-collection)
    def list_profiles(self) -> list[ProfileEntry]: ...
    def upsert_profile(self, p: ProfileEntry) -> ProfileEntry: ...
    def delete_profile(self, name: str) -> None: ...
    def activate_profile(self, name: str) -> SessionDocConfig: ...   # server-side mirror

    # Resolved, request-scoped view consumed by the router
    def resolved_editor_config(self) -> "ResolvedEditorConfig": ...
```

`resolved_editor_config()` is the replacement for `_refresh_config_from_service`
+ `CONFIG`: it reads the platform's resolved `session_doc` (paths already
absolute, boot overrides applied), applies the key translation and the injected
extras (`model` ← `runtime.default_model`, `work_dir`/`campaign_dir`/`config_dir`
← platform, `vtt` optional), and returns an **immutable dataclass**, not a
shared mutable dict.

### 2. Kill the `CONFIG` global

- Delete `scene_editor.CONFIG`, `_refresh_config_from_service`,
  `init_editor_config`, `_config_to_typed_payload`.
- Add `get_editor_config(request) -> ResolvedEditorConfig` as a FastAPI
  `Depends` (mirrors planning's `get_planning_service`).
- Convert the ~20 module helpers (`_session_dir`, `_vtt_path`,
  `_scene_extractions_dir`, `_narration_dir`, `_build_*_cmd`, `_backend_flags`,
  `_model_args`, …) to take the resolved view (a method on it, or a first
  argument) instead of reading a module global. This is the bulk of the work
  and is mechanical but wide.

### 3. Collapse the write paths

- `PUT /api/editor/config` becomes the **single** editor write door; it calls
  `SessionEditorConfigService.update_session_doc(...)`.
- `SessionDocEditor.vue` stops writing `ui.session_doc` through
  `config.updateSection("session_doc", …)`; `backend`/`batch`/`dgx_*`/
  `openrouter_model` move onto the same `PUT /api/editor/config` payload. The
  `AppSidebar.vue` global backend selector also routes here.

### 4. Unify boot

- Delete the separate `init_editor_config(config)` seed. Session paths flow in
  **only** through `boot_overrides` → platform → `resolved_editor_config()`.
  One derivation, one authority.

## Data model

Because the migration is manual and one-time, the new schema is **not** bound to
the current `ui.session_doc` shape. Phases 1–4 keep the existing field names (so
the split-brain removal stays low-risk and mechanical); **Phase 5 redesigns**
the schema as it relocates the data — the reshape and the manual data lift are
the same pass.

Today's `SessionDocSection` is a flat bag of ~25 fields that mixes path
selectors, narrate knobs, scrub knobs, backend selection, and roster; carries
two names for several fields (the `_TYPED_TO_CONFIG_KEY` legacy); and is
`extra="allow"` (unenforced). Proposed `session_doc.yaml` shape
(`SessionEditorConfig`, **strict** — `extra="forbid"`):

```yaml
paths:                      # base (session/campaign) is service-owned metadata, not stored per-field
  session_recap:            # gm-assist recap            (session)   [was: session]
  session_summary:          #                            (session)
  scene_extractions_dir:    #                            (session)   [was: extract_dir + scene_extractions_dir, collapsed]
  roleplay_extractions_dir: #                            (session)   [was: roleplay_dir / roleplay_extract_dir]
  summary_extractions_dir:  #                            (session)   [was: summary_dir / summary_extract_dir]
  narration_dir:            #                            (session)
  output_dir:               #                            (session)
  party:                    #                            (campaign)
  voice_dir:                #                            (campaign)
  examples_dir:             #                            (campaign)  [was: examples_dir / examples]
narrate:
  tokens: 16000             # [was: narrate_tokens]
  prose_mode: false
  reflections: false
  genre:                    # [was: narration_genre]
  batch: false
  context: []
scrub:
  enabled: false            # [was: scrub_enabled]
  tokens: 16000             # [was: scrub_tokens]
roster:
  characters:
  gm_player:
backends:                   # remembered per-backend so switching doesn't lose a model
  active: anthropic         # [was: backend]
  anthropic:  { model: }            # BackendProfile
  dgx:        { endpoint:, model: } # [was: dgx_endpoint / dgx_model]
  openrouter: { model: }            # [was: openrouter_model]
  claude-code: {}
session_name:
profiles: []                # named knob presets         [was: ui.profiles]
active_profile:
```

**Per-backend model memory — decided: the `backends` map above** (2026-07-23).
It keeps each backend's remembered model/endpoint across switches (the current
flat `dgx_model` / `openrouter_model` behavior), reuses `BackendProfile`, and
pre-shapes the eventual central backend provider (service-cut gap #3). The
anthropic/claude-code entries stay empty — their model still comes from the
global `runtime.default_model` picker (open question O3 below).

The remaining schema choices (grouping granularity, dead-field audit) are
tracked under [Open questions](#open-questions).

A **dead-field audit** rides with the reshape: e.g. `extract_dir` looks
vestigial next to `scene_extractions_dir` (boot maps `--extract-dir` →
`scene_extractions_dir`). The reshape is the moment to drop such fields rather
than copy them forward — confirm each before pruning.

`ResolvedEditorConfig` stays a separate **read-only** dataclass (not persisted):
the stored `SessionEditorConfig` with paths resolved absolute and the platform
extras layered in (`model` ← `runtime.default_model`; `work_dir` /
`campaign_dir` / `config_dir`; optional `vtt`). Those extras are **never**
written to `session_doc.yaml`.

## API surface

Mostly unchanged — this is the biggest departure from planning, which added a
whole REST surface. Here the surface is nearly stable and the win is internal.

| Method | Path | Change |
|---|---|---|
| `GET` | `/api/editor/config` | unchanged shape; now served from the resolved view |
| `PUT` | `/api/editor/config` | **now the only** editor-config write; absorbs backend/dgx/batch/openrouter |
| `GET/PUT` | `/api/config/section/session_doc` | **removed** as a session-editor write path (breaking; acceptable per the planning precedent) |
| `GET` | `/api/editor/profiles` | new — list presets |
| `POST/DELETE` | `/api/editor/profiles[/{name}]` | new — manage presets |
| `POST` | `/api/editor/profiles/{name}/activate` | new — server-side mirror into session_doc |

## Implementation phases

| Phase | Work | Risk |
|---|---|---|
| 1 | `session_editor_config_service.py` (+ `ResolvedEditorConfig`) delegating to the platform service. No behavior change yet. | low |
| 2 | Replace `CONFIG` reads with the `Depends`-injected resolved view across `scene_editor.py`; delete `_refresh_config_from_service`. | **high** (wide, mechanical) |
| 3 | Collapse frontend to the single `PUT /api/editor/config`; remove `session_doc` from the generic section route; move profiles to `/api/editor/profiles`. | medium (frontend + breaking route) |
| 4 | Delete `init_editor_config`; unify boot to `boot_overrides` only (one derivation of the session paths). | medium |
| 5 | Move `session_doc` + `profiles` out of `ui_state.yaml` into a dedicated `<config>/session_doc.yaml` the service owns exclusively, **reshaped to the logical `SessionEditorConfig` model** (rename consumers to the final field names in the same pass); carry the write-time relativization + load-time normalize for its path fields (delegating to the platform's `relativize_path`/`resolve_path`). Data lift is a documented **manual** field-by-field remap (single user). | medium (path-resolution re-expression + reshape; migration itself is manual) |
| 6 | Docs: update `schema.md`, `values.md`, `service-cut.md`, `master.md`; add this doc's "as shipped" section. | low |

## Benefits

1. **One authority.** The `CONFIG` global, its per-request refresh, and the dual
   boot seed all disappear. `ui.session_doc` (behind the service) is the only
   store.
2. **Request-scoped, lock-free.** An immutable per-request `ResolvedEditorConfig`
   removes the process-global mutable dict and its unguarded refresh-then-read
   window.
3. **One write door.** The frontend stops writing the same section through two
   endpoints; the "next subprocess still reads CONFIG" hazard is gone.
4. **Owned lifecycle.** A named service validates and owns the editor's config,
   matching planning and closing the service-cut "no service ownership" gap for
   the largest service.
5. **Clean, small wire surface.** Because the editor config is a single blob, the
   HTTP surface barely moves — the change is almost entirely internal hygiene.
6. **Bounded write blast radius.** With `session_doc` + `profiles` in their own
   `session_doc.yaml` (Phase 5), an editor write no longer re-serializes
   `ui_state.yaml`, so it can no longer corrupt `ui.ensemble` / `ui.grounding` /
   `ui.vtt_summary` / `runtime` — the same isolation guarantee planning gained.
7. **A schema worth enforcing.** The Phase 5 reshape replaces a flat,
   `extra="allow"` bag that carries two names per field with a grouped, **strict**
   `SessionEditorConfig` — closing the service-cut "no per-service schema
   enforcement" gap for the largest service, and deleting the
   `_TYPED_TO_CONFIG_KEY` translation at its root.

## Risks & blast radius

- **Phase 2 is wide.** ~20 helpers read `CONFIG`. Mitigate by keeping their
  logic identical and only changing where the values come from; land it behind
  the unchanged `GET/PUT /api/editor/config` contract so the frontend is
  untouched until Phase 3.
- **Path-resolution regressions (esp. Phase 5).** The session-vs-campaign base,
  boot-override, and sibling-session-rebase logic is subtle. **Delegate** to
  `CampaignConfigService.resolve_path` / `relativize_path` / `resolved()`; do
  not re-implement it. When the data moves to `session_doc.yaml`, the write-time
  relativization (today in `update_section`) and the load-time
  `_normalize_stored_paths` heal move *with* it — the new service must apply
  both to its own path fields, still keying off the platform's
  `runtime.session_dir`, or session-scoped paths will silently re-anchor.
- **Breaking route removal.** Dropping `session_doc` from the generic section
  route is breaking — acceptable per the planning precedent, but the frontend
  must migrate in the same change.
- **Backend/model duplication is left standing.** `session_doc.backend`/`dgx_*`,
  `runtime.default_model`, wiring `dgx_*`, and ensemble `BackendProfile` remain
  four places to pick a backend. Named and deferred — see below.

## Out of scope (named, deferred)

- **Central backend/model provider.** Unifying the four backend/model selectors
  into one platform provider is a separate re-architecture (service-cut gap #3),
  not part of isolating the editor's *storage*.
- **`_backend_flags()`/`_model_args()` behavior.** They keep working as-is,
  reading the resolved view.
- **The `.scrubbed.md` glob fragility** and other pipeline-correctness issues in
  `scene_editor.py` — unrelated to config ownership.

## Resolved decision

**Where does the session-editor config physically live? → Its own
`<config>/session_doc.yaml` (Option B). All five phases ship.** Decided
2026-07-23 by the maintainer.

The two options considered were:

- **Option A — keep in `ui_state.yaml`, own in-code (Phases 1–4 only).** Smallest
  disruption, no data lift. **Does not** fix the whole-file write blast radius
  (problem #3): a session_doc write still re-serializes the shared `ui_state.yaml`.
- **Option B — dedicated `<config>/session_doc.yaml` (adds Phase 5). ← chosen.**
  Gives the planning-style guarantee that a bad session_doc write cannot corrupt
  other services' config. Costs a data lift (move `ui.session_doc` +
  `ui.profiles` out of `ui_state.yaml`) and re-expressing session-based path
  resolution against the platform's `runtime.session_dir`.

**Sequencing:** Phases 1–4 still land first — they deliver the real prize
(killing the split-brain) independent of file location and keep each step
reviewable — and Phase 5 then completes the physical isolation. The data lift is
a **manual** step: the sole user relocates the `session_doc:` / `profiles:`
fragments from `ui_state.yaml` into `session_doc.yaml` by hand, so no automated
migration code is written. And because the lift is manual and one-time, Phase 5
also takes the opportunity to **redesign** the schema (see
[Data model](#data-model)) rather than carry the current shape forward — the
hand-migration is a field-by-field remap, cheap because it is one file, one
user, done once.

## Open questions

**Decided so far:** file location → Option B (`session_doc.yaml`), all five
phases; schema → redesigned; backend storage → `backends` map (O-resolved).

### Genuinely open — need a call before Phase 5

- **O1 — Schema grouping granularity.** Grouped (`paths` / `narrate` / `scrub` /
  `backends` / `roster`) vs a single flat-but-cleaned section. Grouped is more
  legible and lets a whole group update atomically; flat is a smaller diff from
  today. *Recommend grouped.*
- **O2 — Profiles activation location.** Today applying a knob preset happens
  **client-side** (the Vue view sets the knob fields, which persist through the
  normal save); `ui.profiles` is just stored presets. The proposed
  `POST /api/editor/profiles/{name}/activate` would move that mirror
  **server-side** (one authoritative activation, consistent with the service
  owning its slice). Isolation does not *require* moving it. *Recommend: keep
  client-side unless you want a server-authoritative activation; either way the
  presets themselves move to `/api/editor/profiles`.*
- **O3 — Anthropic/claude-code model source.** With the `backends` map
  formalized, does `backends.anthropic.model` become a real editor-local
  override, or stay empty with the global `runtime.default_model` picker
  remaining the source (status quo)? *Recommend: keep the global picker as the
  source — do not introduce a new session-local-vs-global split; revisit under
  the deferred central backend provider (service-cut gap #3).*

### Settled with a recommendation (flag if you disagree)

- **S1 — `sd_*` legacy overlay retires.** `flatten_resolved_to_legacy` projects
  `session_doc` → `sd_*` flat keys for the un-reshaped frontend, and a few
  `config.values.sd_*` reads remain (e.g. `sd_batch`). Phase 3 migrates those to
  the editor config and drops the `sd_` projection. A grouped schema cannot
  flatten to `sd_<field>` anyway, so this retirement is forced by O1-grouped.
- **S2 — Boot-override plumbing moves in Phase 5.** Boot flags currently reach
  `session_doc` via the platform's `resolved()` override pass over `ui_state`
  sections. Once `session_doc` leaves `ui_state`, the new service applies its own
  boot overrides — still fed from `main.py`'s single `boot_overrides` derivation
  (the Phase 4 unification), just consumed by `SessionEditorConfigService`
  instead of `CampaignConfigService.resolved()`.
- **S3 — Path resolution stays in the platform; the new service delegates**
  (`resolve_path` / `relativize_path` / `_normalize_stored_paths`), keyed off the
  platform's `runtime.session_dir`. Do not re-implement it.
- **S4 — Dead-field / latent-override audit.** Confirm-then-drop during the
  reshape: `extract_dir` (appears to duplicate `scene_extractions_dir`), and the
  CONFIG-only `vtt` / `dossier_dir` overrides that nothing in the current boot or
  frontend paths populates. If confirmed dead, they do not enter
  `SessionEditorConfig`; `vtt` stays a resolved-view-only optional override.

## Contrast with planning-isolation

| Dimension | Planning | Session editor |
|---|---|---|
| Starting point | already its own `planning.yaml` | typed section in shared `ui_state.yaml` **+** a module-global mirror **+** a boot seed |
| Core problem | coupling / blast radius | split-brain + process-global mutable state + blast radius |
| Data shape | collection (npcs/factions) | single blob + one sub-collection (profiles) |
| Platform coupling | none | `session_dir`, `default_model`, `campaign_dir`, wiring, path-resolution |
| API change | net-new REST collection | mostly internal; existing `GET/PUT /api/editor/config` stays |
| Read sites to unwind | tests only | ~20 helpers in `scene_editor.py` |
| Hardest part | (none — additive) | deleting the `CONFIG` global without changing behavior |
