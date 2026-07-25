# CampaignGenerator Configuration Docs

Repo-specific configuration documentation for CampaignGenerator. Cross-cutting
system/wiring docs live in the `mneme` repo under `docs/architecture/`.

| Doc | What it covers |
|---|---|
| [schema.md](./schema.md) | The config surface at file/section level: the three service documents, `config.yaml` keys, and the `UIState`/`LocalConfig` models |
| [crud.md](./crud.md) | Per-config Create / Read / Update code paths |
| [values.md](./values.md) | Value-level read/write map: each key, who reads it, who updates it (incl. the `scene_editor.CONFIG` mirror) |
| [subsystems.md](./subsystems.md) | The ensemble workflow and the party/campaign_state/world_state grounding-doc subsystems |
| [ensemble-isolation.md](./ensemble-isolation.md) | Ensemble's move out of `ui.ensemble` into its own `ensemble.yaml` + `EnsembleConfigService`; closes the router/model/TypeScript default drift |
| [grounding-isolation.md](./grounding-isolation.md) | The four grounding-doc pages + the PC roster out of `ui_state.yaml` into `grounding.yaml` + `party.yaml`; closes the write-never sections, the dual party.yaml implementations, and the config-location Split-Brain |
| [master.md](./master.md) | Master map stitching all layers together |
| [service-cut.md](./service-cut.md) | CampaignGenerator re-sliced as a multi-service monolith (global vs service-local config) |

All docs are code-verified against source unless a section says otherwise.
