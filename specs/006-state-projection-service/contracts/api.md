# Contract: HTTP surface

**Feature**: 006-state-projection-service | **Date**: 2026-08-01

Router `server/routers/projections.py`, mounted at `/api/projections` by `server/main.py`. Shaped
after `server/routers/grounding.py` and owned by `ProjectionConfigService`
(`server/projection_config_service.py`), which mirrors `GroundingConfigService`: constructed from a
config directory, `_deep_merge` for grouped partial writes, `resolved()` as the single read seam.

**Release scope** (spec Q2): staleness and per-section rebuild. There is deliberately **no** route
for thread triage, summary-map approval, the lineage report, or promotion — those stay CLI/skill
driven, and adding a write route for proposals would move a judgment checkpoint into the interface.

## `GET /api/projections/config` → `ProjectionConfig`

Returns the stored document. A missing file returns all-defaults, not 404 — an all-defaults config is
a legitimate state for a campaign that has never opened the page.

## `PUT /api/projections/config` → `ProjectionConfig`

Body: a grouped **partial** (e.g. `{"stores": {"events": "docs/alt/events.jsonl"}}`). Deep-merged;
lists are replaced wholesale, never concatenated. Returns the merged document.

- `400` on an unknown key, naming it (FR-011)
- `400` on `output.draft` missing `{doc}`
- Writes are atomic; the file is created lazily on first write
- A write here cannot touch `grounding.yaml`, `ensemble.yaml` or `platform.yaml`
  (regression-tested, mirroring `test_ui_section_write_cannot_touch_platform_yaml`)

## `GET /api/projections/sections?doc=<doc>` → staleness table

Read-only. Shells out to `grounding_sections list --doc <doc>` and returns one row per section:

```json
{
  "doc": "campaign_state",
  "sections": [
    {
      "name": "recent_events",
      "mode": "spine",
      "state": "stale",
      "inputs": ["docs/ensemble/events.jsonl"],
      "provenance": null
    },
    {
      "name": "npc_outlook",
      "mode": "npc_outlook",
      "state": "fresh",
      "inputs": ["docs/ensemble/state_dossiers/npc_grazilaxx.md"],
      "provenance": {"dossier_set": "fallback", "importance_list": "docs/ensemble/narrative_importance.yaml"}
    }
  ]
}
```

`state ∈ {fresh, stale, unbuilt, no-input, optional, per-npc}` — `per-npc` is the outlook section, whose freshness is tracked per NPC block; the page renders it as a count rather than a single state. `provenance` carries FR-024a's read-only
attribution — which dossier set fed the section (`curated` / `fallback`) and which importance list
applied. It is **display-only**; no route writes it.

## `GET /api/projections/run/build` → SSE stream

Query: `doc` (required), `sections` (required, repeated), `force` (bool), plus the selection
sentinels `model` / `backend` / `endpoint` / `max_tokens`.

- **`sections` MUST be non-empty.** Declare it *optional* in the signature and reject emptiness explicitly, so the response is a `400` naming the problem rather than FastAPI's generic `422` for a missing required param. Never "all sections" —
  Constitution X, mirroring `test_ensemble_chapters.py`. "Rebuild all" is the page materialising the
  full set as the chosen set.
- Selection resolves through `platform_config_service.resolve_selection` (request → service →
  platform), with `ProjectionConfigService` supplying the service tier. An override that cannot run
  on the resolved backend returns `409`, matching feature 003.
- Every other path comes from `resolved()` at the route edge; the route contains **no**
  `docs/`-shaped literal (guarded, mirroring `test_ensemble_config_defaults.py`).
- Streams stdout as SSE via `stream_subprocess(cmd, cwd=str(Path.cwd()))`; each run is logged under
  `<cwd>/logs/`.
- The legacy-draft gate surfaces as a non-zero exit with its message in the stream — the server adds
  no gate logic of its own.

## `GET /api/projections/run/recent-events` → SSE stream

**Moved from `/api/ensemble/run/recent-events`** (research D15). Query: `corpus` (required, repeated
— Constitution X), plus `output` / `window` / `store` sentinels resolved from
`output.recent_events`, `output.recent_events_window` and `stores.events`.

It has to move with the store: `build_recent_events` wraps the event spine, so once `--store`
resolves from `projections.yaml`, an ensemble-side route invoking it would be reading this service's
config document. Deterministic, no model call, so no selection resolution applies.

The corresponding ensemble route and its Vue control are deleted, and `EnsembleConfig` loses
`paths.recent_events_out` and `tuning.recent_events_window` with no compatibility shim — both live
campaigns' ensemble pages return `400` until the retired key is hand-removed, and the message must
name it.

## What the router must not do

- No default literals in signatures — sentinels only, resolved from `resolved()`.
- No generation logic; argv construction and streaming only (FR-023, Constitution VI).
- No read of another service's config document (FR-003).
- No write route for proposals, rulings, or promotion in this release.

## Frontend contract

`frontend/src/views/grounding/ProjectionSections.vue`, one nested route under `/grounding`. Uses the
existing `api/client.ts` + `api/sse.ts` and the shared `stores/process.ts` for run output. Renders
the staleness table, a per-section rebuild control, the `provenance` column, and the standard
selection panel so the cost-bearing choice is explicit before a build starts (FR-019). Holds no
pipeline state of its own — every result is a file on disk (FR-022a).
