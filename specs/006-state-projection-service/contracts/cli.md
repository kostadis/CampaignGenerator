# Contract: CLI surface

**Feature**: 006-state-projection-service | **Date**: 2026-08-01

The three State Projection console scripts after sentinel conversion, plus the one cross-service
dependency this feature declares. Registered entry points in `pyproject.toml` are unchanged.

## Resolution rule (all three tools)

1. Load `config_path(Path.cwd(), "projections.yaml")` once at the top of `main()`.
   Missing/empty → all-defaults; malformed → exit non-zero naming the file.
2. Every path-valued flag defaults to `None`. Where `None`, the resolved config value is used.
3. An explicit flag always wins over config.
4. Resolution completes **before** any work begins, so `--help` and the echoed command stay explicit.

This mirrors the router-sentinel rule `test_ensemble_config_defaults.py` enforces for
`server/routers/ensemble.py`, applied one layer down.

## `event_spine`

```
event_spine update --corpus GLOB [GLOB ...] [--store PATH]
event_spine render [--window N] [--output PATH] [--store PATH]
```

| Flag | Before | After |
|---|---|---|
| `--corpus` | `required=True, nargs="+"` | **unchanged — required** (research D6). No config default exists or may be added. |
| `--store` | `default=DEFAULT_STORE` literal | `default=None` → `stores.events` |
| `--output` | `docs/recent_events.md` literal | `default=None` → `output.recent_events` |

## `build_recent_events` — moves to this service (research D15)

```
build_recent_events --corpus GLOB [GLOB ...] [--output PATH] [--window N] [--store PATH] [--campaign LABEL]
```

A wrapper over `event_spine.update()` + `render()`. Because `--store` now resolves from
`projections.yaml`, leaving its route on the ensemble side would make a Dossier Synthesis route read
this service's config document — the cross-service read FR-003 forbids. So it moves with its
settings:

| Was | Now |
|---|---|
| `--output` default from `ensemble.yaml`'s `paths.recent_events_out` | `output.recent_events` |
| `--window` default from `ensemble.yaml`'s `tuning.recent_events_window` | `output.recent_events_window` |
| `--store` default `event_spine.DEFAULT_STORE` | `stores.events` |
| route `GET /api/ensemble/run/recent-events` | `GET /api/projections/run/recent-events` |

`paths.recent_events_out` and `tuning.recent_events_window` are **deleted from `EnsembleConfig`, no
shim**. Both live campaigns carry `recent_events_out`, so their ensemble page returns `400` until
the key is hand-removed; the error must name the key. `dossier_recent_window` is a different field
and stays with the shared service.

## `thread_registry`

```
thread_registry propose --corpus GLOB [GLOB ...] [--out PATH] [--registry PATH]
thread_registry add|log|set-status|alias  [--registry PATH] ...
thread_registry render --output PATH [--registry PATH]
thread_registry check [--registry PATH]
thread_registry speculate --backend ... --model ... [--registry PATH]
```

| Flag | Before | After |
|---|---|---|
| `--corpus` | `required=True, nargs="+"` | **unchanged — required** |
| `--registry` | `DEFAULT_REGISTRY` literal | `default=None` → `stores.thread_registry` |
| `--out` (propose) | `DEFAULT_PROPOSALS` literal | `default=None` → `stores.thread_proposals` |

Invariants: every write runs `check`; `set-status resolved` requires `--chapter`; rulings survive
re-proposal; `speculate` writes only to `notes/` and is never read by a pipeline.

**`render --output` became required** rather than gaining a config field. Its old default,
`docs/ensemble/threads_registry.md`, has **no consumer** anywhere in the tree — the `threads` section
in `grounding_sections.py` renders from the registry inline rather than shelling out to this
subcommand — so declaring a config field for a file nothing reads would be a recurring tax for
nothing. Requiring the path is also the more explicit of the two options. `speculate --output`
resolves from `inputs.speculations`, which already existed and which the `speculations` copy-section
reads, closing a duplicate declaration.

## `grounding_sections`

```
grounding_sections list  --doc DOC [--sections a,b] [--npcs a,b] [--json]
grounding_sections build --doc DOC [--sections a,b] [--force] [--no-assemble]
                         [--backend B] [--endpoint URL] [--model M] [--max-tokens N]
                         [--dossiers-dir PATH] [--registry PATH] [--window N] [--npcs a,b]
```

### `list --json` (NEW — required by the UI)

`list` today prints a fixed-width text table ending in `N file(s)`; it emits neither the input paths
nor the provenance the staleness view needs. Screen-scraping it from the router would put parsing
logic in the server, which Constitution VI and FR-023 forbid. So `list` gains a `--json` mode:

```json
{"doc": "campaign_state",
 "sections": [{"name": "recent_events", "mode": "spine", "state": "stale",
               "inputs": ["docs/ensemble/events.jsonl"],
               "provenance": {"dossier_set": null, "importance_list": null}}]}
```

`state ∈ {fresh, stale, unbuilt, no-input, optional, per-npc}` — `per-npc` is what the text table
prints as `-` for the outlook section, whose freshness is tracked per NPC block rather than per
section. `provenance` carries FR-024a's read-only attribution and is `null` for sections that
consume neither a dossier set nor the importance list.

The human-readable table is unchanged and stays the default.

| Flag / literal | Before | After |
|---|---|---|
| `--dossiers-dir` | default `docs/ensemble/merged_dossiers` | `default=None` → `inputs.dossiers`, falling back to `inputs.dossiers_fallback` **and reporting which was used** |
| `SECTIONS_DIR` module constant | `docs/grounding_sections` | `output.sections_dir` |
| draft path (inline in `main`) | `docs/{doc}_draft.md` | `output.draft` |
| `events.jsonl` ×3 (`:116`, `:150`, `:355`) | three literals | one resolved `stores.events`, threaded through |
| `docs/thread_registry.yaml` | literal | `stores.thread_registry` |
| `docs/tracking*.txt` | literal glob | `stores.tracking` |
| `narrative_importance.yaml` | literal | `inputs.narrative_importance` |
| `SPECS` `source=` paths | literals | `inputs.{party,planning_notes,speculations}` |
| `SPECS` section list | code | **stays code** (FR-014) |

### Behaviour the conversion must preserve

- A build without `--backend` skips every LLM section and spends nothing (FR-019).
- Zero matching dossiers → clean skip with a reason, not an error.
- Missing required input → loud error naming the path.
- `--sections` with an unknown name → `argparse` error listing valid names.
- Freshness stays `inputs-sha` over input bytes; `--force` overrides.

### New behaviour

**Legacy-draft gate (FR-007b)**: before writing a draft for `DOC`, if `output.legacy_draft` resolved
for `DOC` exists, exit non-zero:

```
error: a pre-move draft still exists at docs/planning_draft.md
       This service now writes docs/projections/planning_draft.md.
       Move or delete the old file to continue; nothing will be moved for you.
```

Never moves or deletes. Once cleared, one `stat` per run and never fires again.

## Cross-service dependency (research D12)

`grounding_sections.render_synthesis` invokes Dossier Synthesis's engine as a subprocess. The
mechanism (`sys.executable` + repo-relative path) is unchanged — `console_script()` lives in the
server layer and `test_layering.py` forbids importing it from the engine.

**The contract State Projection depends on** — `synthesise_world_state` must continue to accept:

| Flag | Cardinality | Purpose |
|---|---|---|
| `--dossiers` | 1..n paths | the type-scoped subset for this section |
| `--output` | 1 path | where the rendered section body lands |
| `--registry` | 0..1 | entity registry passed through |
| `--backend`, `--endpoint`, `--model`, `--max-tokens` | 0..1 each | forwarded selection |

A change to any of these breaks State Projection at runtime. `test_fact_record_contract.py` covers
the data half of the boundary; this flag surface is pinned alongside it.
