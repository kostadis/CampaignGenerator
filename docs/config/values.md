# CampaignGenerator Configuration — Value-Level Read/Write Map

One level below the file map: each configuration value, who reads it, who updates it.
Test-only references omitted; only runtime code paths listed.

## Write-path mechanics

```mermaid
flowchart LR
  Editor[Session Doc Editor] -->|PUT /api/editor/config| SES["SessionEditorConfigService writes session_doc.yaml"]
  Editor -->|POST /api/editor/profiles/:name/activate| SES
  Picker["model picker / SessionConfig"] -->|PUT /api/config/runtime| RT["PlatformConfigService.update_runtime writes platform.yaml"]
  LocalUI["server/nav"] -->|PUT /api/config/local| LOC["PlatformConfigService.update_local writes .campaigngenerator.local.yaml"]
  RunReq["a token-spending request that omits model/backend"] -->|resolve_selection| RT
```

**Every write door above is service-specific.** There is no generic one: the `PUT
/api/config/section/:name` route that wrote `ui.<section>` blobs — and the `UIStateService` behind
it — are deleted ([ui-state-retirement.md](./ui-state-retirement.md)), because no Vue page ever
called it.

The Session Doc Editor writes `session_doc.yaml` through `SessionEditorConfigService`, via `PUT
/api/editor/config` (the single grouped write door) and `POST
/api/editor/profiles[/{name}[/activate]]` (the profiles sub-collection). Ensemble, Grounding, Party
and Planning each have their own equivalent. `PUT /api/config/runtime` and `PUT /api/config/local`
go straight to `PlatformConfigService`. `config.yaml` has no writer; `wiring.yaml` is mneme-only.
See [Session-editor isolation](./session-editor-isolation.md) for the full design and
[schema.md](./schema.md#session_docyaml--sessioneditorconfig-grouped-strict) for the shape.

## config.yaml (writer: human / pipelines/workspace/new_workspace.py)

| Value | Read by |
|---|---|
| `system_prompt` | `pipelines/session_prep/prep.py` |
| `log_dir` | `pipelines/session_prep/prep.py`, `pipelines/grounding/npc_table.py` |
| `agents.{lore_oracle,encounter_architect,voice_keeper}` | `pipelines/session_prep/prep.py` pipeline |
| `documents[]` | `assemble_docs`, `pipelines/session_prep/prep.py`, `pipelines/rlm/mcp_server.py`, `session_doc/check_consistency.py` |
| `mempalace.canon_wing` / `index_wings` | `pipelines/rlm/mcp_server.py` |
| `mempalace.palace` | `apply_ingest_manifest.resolve_palace` (fallback) |

## ~~ui_state.yaml~~ — retired, nothing left to map

Every section this file used to track has left. `ui.session_doc`/`ui.profiles` →
`session_doc.yaml`; `ui.ensemble` → `ensemble.yaml`; `ui.grounding` + `ui.campaign_state` +
`ui.distill` + `ui.party` + `ui.planning` → `grounding.yaml`; `runtime` → `platform.yaml`.

The six that remained — `prep`, `npc`, `query`, `workflow`, `connections`, `experimental` — had
**no values to map**: empty in every campaign, with no writer, since `updateSection` had no
callers anywhere in the frontend. The document, its models and its route were deleted rather than
re-homed ([ui-state-retirement.md](./ui-state-retirement.md)); the four pages those names were
reserved for are stateless by decision (D1).

> **Correction, kept for the lesson.** This table used to claim `ui.grounding.summaries` was read
> by `pipelines/rlm/mcp_server.py` (`_find_summaries_file`, `query_lore`, `grounded_search`). It
> never was: that function probes three hardcoded paths and never touches config
> (`mcp_server.py:531-542`). **No file outside `server/` ever read `ui_state.yaml`** — and by the
> end, nothing inside `server/` did either, except the migration CLIs that exist to drain it.

## ensemble.yaml — the ensemble workflow (ensemble-isolation Phases 1-5)

Owned outright by `EnsembleConfigService`, its own file. Read through
`resolved()` by every `/api/ensemble/*` route; written only by `PUT /api/ensemble/config`.

| Value | Read by | Written by |
|---|---|---|
| `chapters_selected[]` | Extract page (the picker's state) — **not** a fallback for an omitted `chapters` request param | `PUT /api/ensemble/config` |
| `known_names[]`, `aliases_path` | `/run/bundle`, `/run/threads` (→ `facts_to_state`) | `PUT /api/ensemble/config` |
| `extract.{backend,endpoints,model}` | `/run/extract`, `/run/bundle` | `PUT /api/ensemble/config` |
| `synthesize.{backend,endpoints,model}` | `/run/synthesize` | `PUT /api/ensemble/config` |
| `paths.*` (incl. `drafts_dir`, replacing the draft half of the old `GROUNDING_DOCS` literal map) | every `/api/ensemble/*` route + `/chapters`, `/status` | `PUT /api/ensemble/config` |
| `tuning.*` | `/run/extract`, `/run/bundle`, `/run/threads`, `/run/synthesize` | `PUT /api/ensemble/config` |
| `planning.*` | `/run/synthesize?doc=planning` | `PUT /api/ensemble/config` |

**Retired, no shim**: `paths.recent_events_out` and `tuning.recent_events_window`, and with them
`/run/recent-events`. Moved to `projections.yaml`'s `output.recent_events` /
`output.recent_events_window` and `GET /api/projections/run/recent-events` — see the
`projections.yaml` section below and [projection-isolation.md](./projection-isolation.md) research
D15. Both live campaigns carried `recent_events_out`, so `GET /api/ensemble/config` returns `400`
naming it until hand-removed.

Model resolution for the Anthropic branch is `explicit request → ensemble.yaml's per-stage model →
platform.runtime.default_model → campaignlib DEFAULT_MODEL` (`ensemble._backend_args`, Phase 4).
A non-Anthropic id left over from a dgx/openrouter selection is discarded before resolution rather
than forwarded.

## grounding.yaml — the four grounding docs (grounding-isolation Phases 6-10)

Owned outright by `GroundingConfigService`, its own file. Read
through `resolved()` by every `/api/grounding/run/*` route; written by
`PUT /api/grounding/config`.

| Value | Read by | Written by |
|---|---|---|
| `summaries` (root) | all four runs, when their own `input` is blank; `SessionConfig.vue`, `QuerySummaries.vue` | `PUT /api/grounding/config` |
| `campaign_state.*` (+ `track_files`, `track_items`) | `/run/campaign-state` | as above |
| `distill.*` | `/run/distill` | as above |
| `party.*` (+ `mode`, `config_path`, flat lists) | `/run/party` | as above |
| `planning.*` (+ `synth_mode`, `config_path`, `dossiers.*`) | `/run/planning`, `/run/build-dossiers` | as above |

Input resolution is `explicit request param → that doc's stored input → the root
`summaries` → 400`. No silent fallback — the same "no silent all" rule
`ensemble.yaml`'s `chapters_selected` follows.

## projections.yaml — the State Projection service (projection-isolation.md)

Owned outright by `ProjectionConfigService`, its own file. Read through `resolved()` by every
`/api/projections/*` route and — uniquely among this table's documents — also read directly by
four CLIs (`event_spine`, `thread_registry`, `grounding_sections`, `build_recent_events`), each via
`campaignlib.constants.config_path(Path.cwd(), PROJECTION_CONFIG_FILENAME)` at the top of its own
`main()`, since these tools are also run headless, not only through the server. Written only by
`PUT /api/projections/config`.

| Value | Read by | Written by |
|---|---|---|
| `stores.events` | `event_spine update`/`render`, `grounding_sections`'s freshness hash **and** its spine/tracking reads (one resolved value — closes the three-site split [projection-isolation.md](./projection-isolation.md) documents), `build_recent_events` | `PUT /api/projections/config` |
| `stores.thread_registry`, `stores.thread_proposals` | `thread_registry`'s verbs and `propose`; `grounding_sections`'s `threads`/`emerging` sections | `PUT /api/projections/config` |
| `stores.tracking` | `grounding_sections`'s `tracking` section (a glob; zero matches skips cleanly) | `PUT /api/projections/config` |
| `inputs.dossiers`, `inputs.dossiers_fallback` | `grounding_sections`'s synthesis and `npc_outlook` sections — curated preferred, fallback used and **reported** when the curated set has no files (FR-024a) | `PUT /api/projections/config` |
| `inputs.narrative_importance`, `inputs.party`, `inputs.planning_notes`, `inputs.speculations` | `grounding_sections`'s outlook selection and its `copy`/`emerging` sections | `PUT /api/projections/config` |
| `output.sections_dir`, `output.draft`, `output.legacy_draft` | `grounding_sections`'s section files, its assembled draft, and the FR-007b legacy-draft gate | `PUT /api/projections/config` |
| `output.recent_events`, `output.recent_events_window` | `build_recent_events`, `GET /api/projections/run/recent-events` | `PUT /api/projections/config`. **Moved from `ensemble.yaml`'s `paths.recent_events_out` / `tuning.recent_events_window`** — see [projection-isolation.md](./projection-isolation.md) research D15 and the retirement note in the `ensemble.yaml` row above |
| `selection` | `resolve_selection` as the service tier for `/api/projections/run/build` | `PUT`/`DELETE /api/projections/selection` |

No `corpus` field exists to read: `event_spine`'s `--corpus` and `thread_registry`'s `--corpus` stay
`required=True` on the CLI, never defaulted from config (Constitution X).

## platform.yaml — runtime (Phase 3, O3)

Owned outright by `PlatformConfigService`, its own file. No other service's write can reach these
two values — the isolation `docs/config/platform-isolation.md` Phase 3 exists to guarantee,
regression-tested by `test_another_services_write_cannot_touch_platform_yaml` (which used a
`ui.<section>` write as its probe until that write ceased to exist, and now uses a grounding
write).

| Value | Read by | Written by |
|---|---|---|
| `runtime.default_model` | the sidebar MODEL picker's persisted choice; the platform tier of the one resolution rule (see below) | `PUT /runtime` → `PlatformConfigService.update_runtime` |
| `runtime.default_backend` | the sidebar BACKEND toggle's persisted choice (feature 003). Before 003 that toggle wrote `session_doc.yaml`'s `backends.active` — the Session Doc Editor's own config — while MODEL wrote here: two controls presented as global, owned by different tiers. That asymmetry is why `grounding.py` read another service's document to find a backend. Migrated by `python -m server.migrate_default_backend` | `PUT /runtime` → `PlatformConfigService.update_runtime` |
| `runtime.session_dir` | `resolved()` session base for session-scoped paths (`resolve_path`/`relativize_path`, `base="session"`); also read by `SessionEditorConfigService.resolved_editor_config()` for `session_doc.yaml`'s session-based path fields. Loaded during `PlatformConfigService.__init__` | `PUT /runtime` → `PlatformConfigService.update_runtime`; boot `--session-dir` wins for process |

### The model/backend resolution rule (feature 003) — the single statement

**This is the one place the rule is written down. Every other mention links here rather than
restating it** (FR-015); five independent restatements in code is what feature 003 existed to
remove, and five in prose would re-create the same drift one layer up.

```
model   := request ?? service ?? platform.default_model  ?? DEFAULT_MODEL
backend := request ?? service ?? platform.default_backend
```

Resolved once per run by `server/platform_config_service.py::resolve_selection`, which every one
of the 22 token-spending endpoints calls and none re-derives.

- **The pairing rule.** Model and backend come from the *same tier* whenever that tier supplies
  either. A tier that picks a *different backend* does not inherit the tier above's model — a
  Claude id chosen for the Anthropic API is meaningless on a DGX box, and inheriting it across a
  backend boundary would manufacture a conflict out of two individually valid choices. In that
  case no `--model` is emitted and the downstream script's own default applies.
- **No substitution.** An incompatible pair is refused with HTTP 409, never silently swapped
  (`IncompatibleSelection`, which subclasses `HTTPException` so it renders wherever the router is
  mounted). This reversed ensemble's earlier behaviour, which discarded a foreign model id and ran
  on the platform's instead.
- **Compatibility** is a `claude-` prefix test, deliberately *not* membership of
  `server/config.py::MODELS` — that list is a hand-maintained snapshot and testing against it would
  reject a legitimate new Claude id the day it ships.
- **Who may override**: the five services that own a configuration document — Ensemble
  (`ensemble.yaml`, per stage), Session Doc Editor (`session_doc.yaml`, per backend), Grounding,
  Party and Planning (`selection` in the file each already owned). Setup, Session Prep, NPC Table,
  Query and Connection Graph own no document and always inherit; they get a read-only
  `GET /api/<service>/selection/resolved` preview but nowhere to set anything.
- **Endpoint** for a dgx run resolves from `wiring.yaml` (`dgx_endpoint`) when the service pins
  none. The *model* deliberately does not fall back to wiring's `dgx_model` — that would be a
  substitution of the operator's pick.

`server/config.py::MODELS` (the selectable-model list `GET /api/config/models` serves) is a
hardcoded Python list, not a `runtime` value — relocating its *source* into `wiring.yaml` is
Phase 5b, deferred pending a cross-repo change (tracked as
[issue #177](https://github.com/kostadis/CampaignGenerator/issues/177)).

## session_doc.yaml (Session Doc Editor's own document)

Writer: `SessionEditorConfigService` exclusively, via `PUT /api/editor/config` (grouped
partial-merge write) and the `/api/editor/profiles` CRUD + `/activate` endpoints. No other
route, and no `PUT /section/session_doc` shim, writes this file — see
[Session-editor isolation](./session-editor-isolation.md) for the full design and
[schema.md](./schema.md#session_docyaml--sessioneditorconfig-grouped-strict) for the field list.

| Value(s) | Read by |
|---|---|
| `paths.*` (session/campaign based) | `scene_editor.py` resolved paths for the narrate pipeline (via `Depends(get_editor_config)` → `ResolvedEditorConfig`) |
| `narrate.tokens, prose_mode, reflections, genre, context[]` | `scene_editor.py` narrate knobs (also mirrored from `profiles` via `activate_profile`) |
| `backends.active, backends.<b>.model, backends.<b>.endpoint, backends.<b>.batch` | `scene_editor._backend_flags`/`_model_args` (dgx/openrouter forward `--backend`/`--endpoint`/`--model`; anthropic/claude-code use the per-backend `model` override, else `runtime.default_model`; `batch` resolves through `resolve_selection`/`selection_cli_args`, 005-ui-batch-selection) and `grounding.py._backend_flags` (global sidebar backend selector for campaign_state/distill/party/planning runs) |
| `roster.gm_player, roster.characters` | `scene_editor.py` |
| `profiles[], active_profile` | `scene_editor.py` profile endpoints; `active_profile` set by `activate_profile` |

There is no `scene_editor.CONFIG` mirror and no `sd_*` flat overlay anymore (both retired in
Phase 3b of the isolation) — every read above goes through the request-scoped
`ResolvedEditorConfig` injected by `Depends(get_editor_config)`, not a process-global.

## .campaigngenerator.local.yaml (writer: PUT /local → PlatformConfigService.update_local)

Typed by `PlatformLocalConfig` (strict `extra="forbid"`, `server/platform_config_shared.py`) —
the pre-Phase-2 untyped `config_models.LocalConfig` is retired. A parse error or unknown key
warns and drops rather than raising (machine-written file, nobody hand-edits it).

| Value | Read by |
|---|---|
| `server.host` / `server.port` | `PlatformLocalConfig` defaults (host `127.0.0.1`, port `5000`); startup |
| `nav.last_page` | frontend nav restore |

## config/wiring.yaml (writer: mneme render)

| Key | Read by |
|---|---|
| `rpg_library_url` | suggest_conversion, rpg_retriever, query_rpg_lib, mcp_server, fivetools_ingest |
| `fivetools_data_root` | resolve_refs (`_DEFAULT_ROOTS`), rpg_retriever |
| `homebrew_private` | resolve_refs (`_DEFAULT_ROOTS`) |
| `fivetools_mcp_index` | launch_5etools_mcp (`DEFAULT_MCP_INDEX`) |
| `pdf_translators` | fivetools_ingest (`_DEFAULT_PDF_TRANSLATORS`) |
| `dgx_endpoint` | scene_editor._backend_flags, grounding._backend_flags, extract_facts (fallback when `session_doc.yaml`'s `backends.dgx.endpoint` is unset) |
| `dgx_model` | extract_facts, campaignlib/api/backends (`DGX_DEFAULT_MODEL`) |

## refs.yaml / refs.local.yaml (writer: human; local seedable via `launch --init-local`)

| Value | Read by |
|---|---|
| `canonical` / `canonical_exclude` | `resolve_refs.resolve_canonical` |
| `refs[].rpglib` (+ `library`, `book_id`, `note`) | `resolve_refs._resolve_rpglib_entry` |
| `refs[].homebrew_private` | `resolve_refs._resolve_homebrew_entry` |
| `refs[].path` | `resolve_refs._resolve_path_entry` |
| `roots.{fivetools_data, rpg_library, homebrew_private}` | `resolve_refs.resolve_roots` (rank 1) |
