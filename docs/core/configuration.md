# Configuration architecture

How CampaignGenerator's configuration is stored, loaded, and saved after the unification refactor. Read this when you need to answer "where does the value of X come from?" or "what file should I edit to change Y?"

The pre-refactor design had five overlapping layers (CLI config, UI persistence, server boot dict, per-router in-memory dict, frontend store) where the same logical setting could have different shapes. The worked example `sd_narrate_tokens: '4000'` shadowing an in-code default of `16000` was the canonical bug — see [git history of this file](../docs/configuration_unification_plan.md) for the original analysis.

This document describes the new design. A small amount of legacy scaffolding is still in place during the in-progress frontend sweep (see [What's still legacy](#whats-still-legacy)).

## Three files, one service

| File | Tracked? | Writer | Reader | Purpose |
|---|---|---|---|---|
| `<campaign>/config.yaml` | yes | **human only** | CLI scripts + server (read-only) | `documents:`, prompt paths, model defaults. Server never opens for write — comments and ordering are protected by virtue of no writer existing. |
| `<campaign>/ui_state.yaml` | yes | **server only** (atomic-rename) | server + migration | Typed sections under `version: 2`: `ui.session_doc`, `ui.vtt_summary`, `ui.grounding`, `ui.prep`, `ui.npc`, `ui.distill`, `ui.party`, `ui.connections`, `ui.experimental`, `ui.workflow`, `runtime.default_model`, `runtime.session_dir`, `legacy.unmigrated`. |
| `<campaign>/.campaigngenerator.local.yaml` | gitignored | server | server | `server.host`, `server.port`, transient `nav.*` browser state, anything machine-specific. |

All three are owned end-to-end by [`server/config_service.py:CampaignConfigService`](../server/config_service.py). Routers receive the service through `request.app.state.config_service` and never touch YAML files directly.

## Hard rules (enforced in code or tests)

1. **`config.yaml` is never written.** [`tests/test_config_service.py::TestConfigYamlNeverWritten`](../tests/test_config_service.py) freezes this at the file level. Hand-edit it freely; comments survive forever.
2. **All paths in `config.yaml` and `ui_state.yaml` resolve against `campaign_dir`.** Absolute paths and `~`-expansion pass through. The service exposes only resolved (absolute) paths to routers via `service.resolved()`.
3. **Boot CLI flags do NOT persist to disk.** They flow through `CampaignConfigService(boot_overrides=...)` and override the resolved view for the process lifetime only. A second instance of the service against the same campaign sees only what's on disk.
4. **CLI subprocesses get plain command-line flags.** When the server runs `session_doc.py` etc. it passes flags built from `service.resolved`. CLI scripts continue to read their own `config.yaml` for `documents:`/prompts. CLI scripts never read `ui_state.yaml`. (Per [CLAUDE.md](../CLAUDE.md): "the subprocess should look the same as if a human had typed it.")
5. **Atomic writes.** Every persisting write goes through `_atomic_write` (temp file + `os.replace`). A crash mid-write leaves the existing file untouched.

## What's in each typed section

`ui_state.yaml` v2 layout:

```yaml
version: 2
ui:
  session_doc:    # Session Doc Editor (post-session narrative)
  vtt_summary:    # VTT Summary page
  grounding:      # summaries pointer
  campaign_state: # campaign_state.py UI page
  distill:        # distill.py UI page
  party:          # party.py UI page
  planning:       # planning.py UI page
  prep:           # prep.py UI page
  npc:            # npc_table.py UI page
  query:          # query.py UI page
  workflow:       # session-workflow wizard
  connections:    # connection-graph page
  experimental:
    narrative:    # narr_*
    enhance_recap:# er_*
    dnd_sheet:    # dnd_*
    make_tracking:# mt_*
runtime:
  default_model: claude-sonnet-4-6
  session_dir: summaries/20260318    # relative to campaign_dir
legacy:
  unmigrated: {}                      # quarantined keys from migration
```

[`server/config_models.py`](../server/config_models.py) defines the pydantic v2 models. `SessionDocSection` and `VttSummarySection` are fully typed; the rest are loose-extras (untyped fields) so pages can grow without model edits during the transition.

## Migration from legacy `ui_config.yaml`

Runs lazily on `CampaignConfigService.__init__` when:
- `<campaign>/ui_config.yaml` exists, AND
- `<campaign>/ui_state.yaml` does NOT exist

The pure migrator [`server/config_migration.py:migrate_ui_config`](../server/config_migration.py) does:

- **Type coercion** — `'4000'` → `4000` via pydantic. The worked-example bug is now structurally impossible.
- **Duplicate collapse** — `sd_*` and `session_doc_*` aliases for the same field map to one canonical key in `ui.session_doc`. `sd_*` wins.
- **Prefix routing** — every prefix from the old `_SAVE_KEY_PREFIXES` registry has a typed home. See `_PREFIX_TO_SECTION` and `_PREFIX_TO_EXPERIMENTAL` in `config_migration.py`.
- **Top-level routing** — `session_dir` → `runtime.session_dir`, `summaries` → `ui.grounding.summaries`, `global_model` → `runtime.default_model`. `campaign_dir` is dropped (comes from CLI/CWD discovery only).
- **Quarantine** — anything the migrator can't place lands in `legacy.unmigrated` with a warning, never silently dropped.
- **Idempotent** — re-running on a v2 dict is a no-op.

After a successful migration:
- `ui_state.yaml` is written.
- A zero-byte `ui_config.yaml.migrated` marker is dropped next to the legacy file.
- `ui_config.yaml` is left **untouched** on disk.
- Migration warnings surface through `GET /api/config/.migration_warnings` and are rendered as a banner in `Settings.vue`.

## API surface

All under `/api/config/`. Defined in [`server/routers/config_routes.py`](../server/routers/config_routes.py).

| Method + path | Purpose |
|---|---|
| `GET /api/config/` | Returns `{campaign_dir, config_path, ui_state_path, local_config_path, schema_version, resolved, tracked, local, migration_warnings, ...legacy_overlay}`. The `resolved` view has paths absolute against `campaign_dir` and boot overrides applied. The legacy flat-key overlay is merged in at the top level for un-migrated frontend views. |
| `PUT /api/config/section/{name}` | Merges `{values: {...}}` into `ui.<name>` and persists atomically. Validates that `name` is a real `UISection` field; rejects unknown sections with 404. |
| `PUT /api/config/local` | Merges `{values: {...}}` into `.campaigngenerator.local.yaml`. |
| `PUT /api/config/` | **Legacy bulk merge.** Still present for `SessionConfig.vue`'s top-level `campaign_dir`/`session_dir` saves. Removed once the full frontend sweep finishes. |
| `GET /api/config/campaign-paths`, `/session-paths`, `/path-status`, `/party-yaml`, `PUT /party-yaml`, `/models`, `/status` | Path discovery + party YAML editing — unchanged by the refactor. |

The pre-refactor `GET/PUT /api/config/raw` endpoints (raw YAML editor) **have been removed**. `Settings.vue` now shows a read-only collapsible JSON view of `resolved`, `tracked`, and `local` plus the migration banner.

## Frontend store

[`frontend/src/stores/config.ts`](../frontend/src/stores/config.ts) — Pinia store with:

| Field / method | Purpose |
|---|---|
| `resolved` | Typed read-only view from `service.resolved()`. New views read `config.resolved.ui.session_doc.narrate_tokens` etc. |
| `values` | **Legacy flat-key mirror** (sd_*, vtt_*, …). Still populated from the `GET /` legacy overlay so unmigrated views keep working. |
| `migrationWarnings` | List of strings to render as a dismissible banner. |
| `loaded`, `loadPromise` | Race guard from commit `c253d56` — prevents double-fetch and prevents `save()` from racing the initial fetch. **Preserve verbatim** when reshaping the store further. |
| `updateSection(name, partial)` | `PUT /api/config/section/<name>` then `refresh()`. Use this from migrated views. |
| `updateLocal(partial)` | `PUT /api/config/local` then `refresh()`. |
| `save()` | Legacy bulk save. Used only by `SessionConfig.vue` for top-level keys. |

The two anti-pattern bugs from the original `configuration.md` are fixed:
- `VttSummary.vue` after a successful run now calls `config.updateSection('vtt_summary', {session_summary, roleplay_summary})` so the produced paths survive a restart.
- `SessionDocEditor.vue`'s Batch toggle persists via `updateSection('session_doc', {batch})` instead of mutating `config.values` and bulk-saving.

## What's still legacy (in-progress sweep)

These are deliberately left in place during the transition. They can be removed in a follow-up PR once every view consumes `config.resolved`:

- **`PUT /api/config/`** (bulk merge) — `SessionConfig.vue` uses it for `campaign_dir`/`session_dir` (top-level keys without typed homes).
- **`load_ui_config` / `save_ui_config` / `_SAVE_KEY_PREFIXES`** in [`server/config.py`](../server/config.py) — used by `PUT /api/config/`.
- **`legacy_values` overlay** in `GET /api/config/` — computed by `flatten_resolved_to_legacy()`. Read by 11 frontend views that haven't been converted to `config.resolved` yet:
  - `prep/ConnectionGraph.vue`, `prep/QuerySummaries.vue`
  - `session/SceneExtraction.vue`
  - `grounding/PlanningDocument.vue`, `DistillWorldState.vue`, `CampaignState.vue`
  - `setup/MakeTracking.vue`
  - `experimental/SessionNarrative.vue`
  - `utils/paths.ts` (helper that reads `campaign_dir` / `session_dir`)

Search with `grep -rn 'config\.values' frontend/src` to track sweep progress.

## When you're touching this code

- **Adding a typed field** — add it to the appropriate model in `server/config_models.py`. If it's a path, list it in `_PATH_FIELDS` in `server/config_service.py` so the resolved view absolutizes it.
- **Adding a new UI section** — add an attribute on `UISection` (in `config_models.py`); the migrator and `UI_SECTION_NAMES` pick it up automatically.
- **Reading config in a router handler** — use `request.app.state.config_service.resolved`. For routers that need the legacy `CONFIG` dict (`scene_editor`, `ledger`), the `_refresh_config_from_service` router dependency keeps it in sync before every request.
- **Reading config in a CLI subprocess** — DON'T. Pass values via command-line flags. CLI scripts are independent of the web server's config layer.
- **Persisting a value from the frontend** — call `config.updateSection('<name>', {...})` for typed sections, `config.updateLocal({...})` for machine-only. Don't mutate `config.values` and walk away.

## Reference

| File | Role |
|---|---|
| [`server/config_models.py`](../server/config_models.py) | Pydantic v2 models for `UIState`, `LocalConfig`, all sections |
| [`server/config_migration.py`](../server/config_migration.py) | Pure migration `legacy → typed`; reverse `typed → legacy_overlay` |
| [`server/config_service.py`](../server/config_service.py) | `CampaignConfigService` — the single authority |
| [`server/config.py`](../server/config.py) | Path-derivation helpers (`derive_campaign_paths`); legacy `load_ui_config` / `save_ui_config` (still used by `PUT /api/config/`) |
| [`server/routers/config_routes.py`](../server/routers/config_routes.py) | `/api/config/*` endpoints |
| [`server/routers/scene_editor.py`](../server/routers/scene_editor.py) | Uses `_refresh_config_from_service` router dependency |
| [`server/routers/ledger.py`](../server/routers/ledger.py) | Same; reads `CONFIG` populated by the dependency |
| [`server/main.py`](../server/main.py) | Constructs the service at boot; `_boot_overrides_from_args` builds the dotted-key map |
| [`frontend/src/stores/config.ts`](../frontend/src/stores/config.ts) | Pinia store with `resolved`, `updateSection`, `updateLocal`, plus legacy `values` mirror |
| [`tests/test_config_models.py`](../tests/test_config_models.py) | Coercion / defaults / extras |
| [`tests/test_config_migration.py`](../tests/test_config_migration.py) | Worked example, prefix routing, idempotence, quarantine |
| [`tests/test_config_service.py`](../tests/test_config_service.py) | `config.yaml` never written, atomic writes, boot-overrides-don't-persist, concurrent updates |
| [`tests/test_config_routes.py`](../tests/test_config_routes.py) | `GET /` shape, typed-section PUT, local PUT, removed raw endpoints |
| [`tests/test_editor_service_integration.py`](../tests/test_editor_service_integration.py) | `PUT /api/editor/config` round-trips through the service; field-name translation |
