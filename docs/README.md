# CampaignGenerator Documentation

Pick a doc by audience or task. The repo root has only the project README, the Claude rules (`CLAUDE.md`), and the backlog (`TODO.md`); everything else lives here.

## Core — start here

- [**Cross-system wiki**](system/index.md) — the *whole* toolchain map: how CampaignGenerator, MemPalace, turbovecdb, mytools rpg-lib, and the campaign/5etools data layer fit together. **Read this when the overall shape (not just CG) is what you've lost.**
- [System architecture](core/architecture.md) — layered system map of CampaignGenerator *internally*, both pipeline data flows, recurring concepts, and a "common task → start here" navigation table. **Read this first for CG itself.**
- [Configuration](core/configuration.md) — `config.yaml`, `platform.yaml`, `.campaigngenerator.local.yaml` and the per-service documents: who owns what, how the server resolves paths, how the CLI auto-detects.

## CLI tools and workflows

- [CLI tool reference](cli/cli_tools.md) — per-script flags and a typical new-campaign workflow.
- [Session-prep workflow](cli/session_prep_workflow.md) — end-to-end pre-session pipeline.
- [Session-doc pipeline](cli/session_doc_pipeline.md) — the 4-stage post-session pipeline (`enhance_summary` → `scene_extract` → `session_doc` → `assemble`) plus the 5-pass internals and design rationale.
- [Quote verification how-to](cli/quote_verification_howto.md) — operator's manual for `sd_verify_quotes` / `sd_agent`: checking that a generated summary or scene extraction actually quotes the tape. **Deterministic, free, calls no model, needs no DGX**, and fixes nothing by itself. Read this for what the three verdicts mean, why `near` is not "safe", and why the `.vtt` you pick moves the finding count 26%.
- [Transcript corrections how-to](cli/transcript_corrections_howto.md) — operator's manual for `sd_corrections`. The `.cleaned.vtt` is now **generated** from the raw tape plus a cue-indexed record (#250 R4); the raw file is never written. Read this before hand-editing a transcript — importing ch46 found **74 substitutions nobody had recorded**, including a surname no player spoke.
- [Post-session umbrella](cli/post_session.md) — short "which entry point matches how I want to work" page.
- [gm-assist anchor](cli/gmassist_anchor.md) — why the gm-assist document is the authoritative event skeleton.
- [Grounding documents](cli/grounding_docs.md) — when and how to refresh `campaign_state`, `world_state`, `planning`, `party`.
- [Ensemble workflow](cli/ensemble_workflow.md) — end-to-end: chapters → `ensemble_batch` → `facts_to_state` → synthesis (API + subscription paths); Phandalin worked example. **Start here for grounding-doc refreshes.**
- [Ensemble extraction](cli/ensemble_extraction.md) — single-file and multi-file `ensemble` deep dive; `--plan` YAML format, key flags, output layout.
- [planning workflow](cli/planning_pipeline.md) — the two-phase build-dossiers → synthesize design.
- [State Projection how-to](cli/state_projection_howto.md) — operator's manual for `event_spine` / `thread_registry` / `grounding_sections` and the State Projection UI page: what to run in what order, what every skip message means. **Read this if the projections page looks empty or errors.**
- [Provenance search how-to](cli/provenance_howto.md) — task-oriented walkthrough: find a fact and know whether to trust it, scope to canon, ask what was true at chapter N, resolve a name, compare two campaigns. **Start here.**
- [Provenance-aware search](cli/provenance_search.md) — the reference behind it: the two hand-authored files (`provenance.yaml`, per-campaign `corrections.yaml`), trust tiers, the corrections matching rule, all ten `check` findings. **Read this before hand-editing either file.**

## MCP servers

- [MCP servers](mcp/mcp_servers.md) — the five servers a campaign can wire into its `.mcp.json` (`campaign`, `5etools`, `registry`, `kanka`, `provenance`): what each is for, what gates it, how to wire one in. `provenance` is the only unpinned one.

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

- [**The extraction contract, as built**](design/ExtractionContract_implementation.md) — **start here for #250.** What shipped (R1–R6), the two axes and why they are not one, the end-to-end workflow, every measurement the build moved, and what it deliberately does not do.
- [Extraction contract for `scene_extractions_*`](design/ExtractionContract_proposal.md) — **ratified and implemented (#250)**: what happens when a scene extraction's two sections carry the same span in conflicting copies. R1 refuse-and-flag (but two verbatim copies are never a conflict), R2 a transcription garble is a ground-truth defect fixed per-cue in the `.cleaned.vtt`, R3 refuse-and-flag on editorial brackets inside a verbatim span — with the measured interruption cost of each, and why the model is not the flagger. Plus R4 (corrections become cue-indexed data; `.cleaned.vtt` becomes generated), R5 (`smoothed/` stops claiming verbatim, so the contract binds `new/`) and R6 — each with the options that lost. **This is the *why*; the build record is the doc above it.**
- [Quote verification handoff](design/QuoteVerification_handoff.md) — **pick-up note**: what 007 shipped, the three findings that outlived it (DeepSeek was not the problem; D1's 64% was measuring a bug; the failure mode is stitching), which corpora are worth re-extracting, and how to start the follow-up feature.
- [Source tree restructure](design/SourceTreeRestructure.md) — splits the 62 flat root scripts into subsystem packages under `pipelines/`, `entity_registry/`, and `session_doc/`, grouped by pipeline; migration complete.
- [RLM paper comparison](design/rlm_paper_comparison.md) — how this system relates to (and diverges from) the published RLM paper.
- [Chapter-extract consolidation (killed)](design/ChapterExtractConsolidation_killed.md) — why consolidating the three extract passes into one per-chapter extract regressed all three grounding docs, and the depth-vs-breadth lesson.
- [Ensemble grounding investigation](design/EnsembleGroundingInvestigation.md) — the "stamped ch62, contains ch61" hunt: four defects sharing one pattern (the pipeline computes a signal, serialises it, then ignores it), what shipped (#194/#197/#200), what is still open (#199/#201/#202), and the measurements + dead-end hypotheses worth not re-deriving.
- [**Narration — what to do next, in order**](design/NarrationNextSteps_handoff.md) — **start here to pick narration work back up.** The ordered plan across all three repos, the one decision that blocks the biggest win (where the genre rulebook lives: #276 fix 2 vs #220), the two tracks that outrank it on importance without blocking it, and a re-verify block because the plan has a shelf life.
- [#245 follow-ups — execution handoff](design/Issue245Followups_handoff.md) — the six work orders that came out of the Fable-vs-Opus narration benchmark, with a 2026-08-11 status table (five landed) and the standing constraints that bind them. **Start here for what the narration pipeline's current shape was built from**; the surviving item is the capstone re-render, never run.
- [Voice-critic alignment](design/VoiceCriticAlignment_proposal.md) — the narration rules live in **five** copies and nothing keeps them in agreement; the checker carries a hand-copied fork of the rulebook. Measures what the narrator receives vs what `/voice-critic` reads, why the critic finds no voice spec at all on the fable-era campaign (pre-#247 lookup), the doc-level budgets a per-scene critique structurally cannot evaluate, and the flattened-`narrate.genre` bug found on the way (#276, kostadis/mytools#125).

## Archive

Shipped plans, deprecated docs, and one-time audits — kept for rationale, not currency. See [`archive/`](archive/).
