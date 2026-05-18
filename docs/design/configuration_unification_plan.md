# CampaignGenerator Configuration Unification Plan

## Summary

Unify configuration around campaign-local, git-friendly YAML state. `config.yaml` remains the canonical tracked campaign config, `ui_config.yaml` becomes legacy/migrated, and machine-specific runtime settings move to an ignored per-campaign local file.

This design supports independent campaign evolution, git tags for "after last session" snapshots, desktop/laptop WSL checkouts, and concurrent local instances for different campaigns.

## Key Changes

- Make the campaign directory the source of truth.
  - Server startup must resolve a `campaign_dir` from `--campaign-dir` or CWD containing `config.yaml`.
  - All persistent campaign state is read/written under that campaign directory, never under the tool checkout CWD.
  - Running multiple campaigns concurrently means starting one server per campaign, each with its own port.

- Replace flat UI persistence with typed campaign config.
  - Add `version: 2` to campaign `config.yaml`.
  - Store paths as relative-to-campaign by default: `docs/world_state.md`, `summaries/20260504`, `voice/`.
  - Support `${CG_HOME}` for tool-owned prompt paths when an override is needed; default prompt paths should otherwise come from the running tool checkout.
  - Group former flat UI keys under typed sections such as `ui.session_doc`, `ui.vtt_summary`, `ui.grounding`, `ui.prep`, and `runtime.default_model`.
  - Keep existing `documents` semantics for CLI compatibility, but migrate absolute campaign paths to relative paths.

- Add ignored machine-local config.
  - File: `<campaign>/.campaigngenerator.local.yaml`.
  - Store only machine-specific or non-canonical state: `server.host`, `server.port`, local `campaign_generator_home` override, browser/nav state, and other values that should not move between desktop and laptop.
  - Add this file to the campaign repo `.gitignore`.
  - CLI flags override local config; local config overrides built-in defaults; tracked campaign config overrides tool defaults.

- Introduce a single server-side config service.
  - Replace direct calls to `load_ui_config`, `save_ui_config`, and module-level router config writes with one `CampaignConfigService`.
  - The service loads tracked `config.yaml`, overlays ignored local config, validates/coerces typed values, and exposes resolved runtime config to routers.
  - Writes go through the service with atomic YAML writes and a per-campaign lock file to avoid clobbering when two local instances touch the same campaign.
  - Router in-memory state becomes a cache of resolved config, not an independent authority.

- Preserve compatibility during migration.
  - On first load, if `ui_config.yaml` exists, migrate recognized keys into the new typed sections.
  - Preserve unknown legacy keys under `legacy.ui_config_unmigrated` for review instead of silently dropping them.
  - Do not delete `ui_config.yaml`; write a `.migrated` marker or expose a warning until the user removes it.
  - Existing CLI scripts must continue to accept current `config.yaml` during the transition.

## Public Interfaces

- `GET /api/config/` returns typed merged config plus metadata:
  - `campaign_dir`
  - `config_path`
  - `local_config_path`
  - `schema_version`
  - `resolved`
  - `tracked`
  - `local`
  - `migration_warnings`

- `PUT /api/config/` accepts typed partial updates and writes only tracked campaign-safe fields to `config.yaml`.

- `PUT /api/config/local` accepts machine-local updates and writes only `.campaigngenerator.local.yaml`.

- `GET /api/editor/config` returns resolved editor config from the unified service.

- `PUT /api/editor/config` updates the typed `ui.session_doc` section rather than mutating module-level `CONFIG` only.

## Test Plan

- Unit tests for path resolution:
  - relative campaign paths resolve against `campaign_dir`
  - `${CG_HOME}` resolves to the running tool checkout or local override
  - absolute legacy paths migrate to relative paths when inside the campaign

- Unit tests for migration:
  - `sd_narrate_tokens: '4000'` becomes numeric `4000`
  - empty numeric strings become unset and fall back to defaults
  - legacy `sd_*` and `session_doc_*` keys migrate into one canonical section
  - unknown keys are preserved for review

- API tests:
  - `PUT /api/config/` cannot write machine-local keys
  - `PUT /api/config/local` cannot write tracked campaign state
  - startup from two different campaign directories reads/writes separate config files

- Integration tests:
  - Session Doc Editor loads typed config, applies changes, reloads, and sees the same values.
  - VTT Summary writes generated output paths persistently through the unified service.
  - CLI scripts still load `documents` through `campaignlib.load_config` and `assemble_docs`.

## Assumptions

- Canonical campaign configuration should be git-tracked YAML, not SQLite.
- Machine-specific configuration should live in an ignored per-campaign YAML file.
- The tool remains single-user, but supports multiple local server processes for different campaigns.
- No LLM pipeline behavior changes are part of this plan.
