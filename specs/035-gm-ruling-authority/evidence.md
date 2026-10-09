# Baseline Evidence for Issue #546

This note records the existing seams used while specifying the feature. Code discovery was performed through codebase-memory-mcp against the indexed CampaignGenerator project.

- `campaignlib/planning_config.py`: the planning configuration currently selects NPC and faction dossiers and arc scores; first-class campaign-note selection is not present.
- `pipelines/summary_native/synth.py`: planning synthesis already writes per-run records and receives checked notes, which makes selected-note provenance and digesting an extension of an existing run concept.
- `pipelines/summary_native/freshness.py`: freshness checks already hash core inputs; its documentation explicitly says `canon.yaml` affects validation findings rather than corpus content.
- `pipelines/summary_native/duplicates.py`: `docs/summary_native/canon.yaml` is strict and limited to not-a-duplicate and link rulings. It is not a general campaign-fact correction store.
- `provenance/corrections.py`: `docs/corrections.yaml` records known-stale provenance context. Its stale wording is not used for attachment, so it cannot be reinterpreted as an executable claim replacement without changing its meaning.
- `campaignlib/transcript_corrections.py`: `transcript_corrections.yaml` belongs to transcript repair and remains separate from campaign-fact authority.

Issues #516 and #518 map into one feature as follows:

- #518 supplies approved, replayable corrections, effective scope, affected projections, withdrawal behavior, and conflict reporting.
- #516 supplies selected notes, the six classifications, planning precedence, knowledge audiences, digests, freshness, and stale-future-prep warnings.
- The shared authority ledger, audience model, provenance, and run history prevent the two workflows from inventing incompatible meanings for the same decision.
