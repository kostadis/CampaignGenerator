# CampaignGenerator Documentation

Pick a doc by audience or task. The repo root has only the project README, the Claude rules (`CLAUDE.md`), and the backlog (`TODO.md`); everything else lives here.

## Core — start here

- [System architecture](core/architecture.md) — layered system map, both pipeline data flows, recurring concepts, and a "common task → start here" navigation table. **Read this first.**
- [Configuration](core/configuration.md) — `config.yaml`, `ui_state.yaml`, `.campaigngenerator.local.yaml`: who owns what, how the server resolves paths, how the CLI auto-detects.

## CLI tools and workflows

- [CLI tool reference](cli/cli_tools.md) — per-script flags and a typical new-campaign workflow.
- [Session-prep workflow](cli/session_prep_workflow.md) — end-to-end pre-session pipeline.
- [Session-doc pipeline](cli/session_doc_pipeline.md) — the 4-stage post-session pipeline (`enhance_summary` → `scene_extract` → `session_doc` → `assemble`) plus the 5-pass internals and design rationale.
- [Post-session umbrella](cli/post_session.md) — short "which entry point matches how I want to work" page.
- [gm-assist anchor](cli/gmassist_anchor.md) — why the gm-assist document is the authoritative event skeleton.
- [Grounding documents](cli/grounding_docs.md) — when and how to refresh `campaign_state`, `world_state`, `planning`, `party`.
- [Ensemble workflow](cli/ensemble_workflow.md) — end-to-end: chapters → `ensemble_batch.py` → `facts_to_state.py` → synthesis (API + subscription paths); Phandalin worked example. **Start here for grounding-doc refreshes.**
- [Ensemble extraction](cli/ensemble_extraction.md) — single-file and multi-file `ensemble.py` deep dive; `--plan` YAML format, key flags, output layout.
- [planning.py workflow](cli/planning_pipeline.md) — the two-phase build-dossiers → synthesize design.

## Web UI

- [Web UI overview](web/web_ui.md) — pages, stores, dev workflow.
- [UI configuration & persistence](web/web_ui_config_persistence.md) — `ui_config.yaml` model and the in-progress unification.
- [Session Doc Editor walkthrough](web/session_doc_editor.md) — button-by-button operator flow for the post-session pipeline in the browser.

## RLM (retrieval) pipeline

- [RLM architecture](rlm/rlm_architecture.md) — three-pile model, MCP surface, retrieval contract.
- [RLM pipeline](rlm/rlm_pipeline.md) — how retrieval feeds approved proposals into the render pipelines.
- [Retrieval architecture](rlm/retrieval_architecture.md) — palace internals, hierarchical descent, dirty-flag index lifecycle.
- [Dossier aliases](rlm/dossier_aliases.md) — dossier merge rules and cross-pipeline alias propagation.
- [refs.yaml reference](rlm/refs_yaml_reference.md) — full field reference for refs.yaml and refs.local.yaml (5etools MCP scope).

## For players

- [Voice guide](player/voice_guide.md) — how to write a per-character voice file the narrator will use.

## Specs

- [File formats](specs/formats.md) — input/output shapes for the major tools.

## Design notes

- [RLM paper comparison](design/rlm_paper_comparison.md) — how this system relates to (and diverges from) the published RLM paper.
- [Chapter-extract consolidation (killed)](design/ChapterExtractConsolidation_killed.md) — why consolidating the three extract passes into one per-chapter extract regressed all three grounding docs, and the depth-vs-breadth lesson.

## Archive

Shipped plans, deprecated docs, and one-time audits — kept for rationale, not currency. See [`archive/`](archive/).
