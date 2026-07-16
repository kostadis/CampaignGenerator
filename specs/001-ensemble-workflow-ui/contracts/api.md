# API Contract: `/api/ensemble`

New FastAPI router `server/routers/ensemble.py`, mounted at `/api/ensemble`, registered in `server/main.py` alongside the existing routers. It mirrors `server/routers/grounding.py`: stage runners return SSE streams from `stream_subprocess()`; status/file endpoints return JSON. **The router builds CLI commands and shells out — it contains no pipeline logic and issues no retrieval/render calls** (Principles VI, III).

All run endpoints accept a per-stage backend selection: `backend` ∈ {`anthropic`, `dgx`, `openrouter`}, plus optional `endpoint` and `model`. These map to CLI flags (see `cli.md`). The `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` are injected into the subprocess via `env_extra`, never passed as query params.

---

## Stage runners (SSE)

### `GET /api/ensemble/run/extract`
Runs `ensemble_batch.py` over the chapter glob.

Query params: `chapters` (glob), `per_chapter_dir`, `out`, `plan`, `endpoint`/`endpoints[]`, `model`, `backend`, `chapter_parallel`, `chunk_parallel`, `embed_endpoint`, `embed_model`, `embed_threshold`, `unit_timeout`, `no_speculative` (bool).

Response: `text/event-stream` — `data:` chunks of stdout/stderr; terminal `event: done` with `{"returncode": N}`.

Behavior: resumable (chapters with existing `merged.json` are skipped by the CLI). On a backend/endpoint failure, the stream surfaces the error and ends with non-zero `returncode` (FR-009); prior chapters' outputs persist.

### `GET /api/ensemble/run/bundle`
Runs `facts_to_state.py` (aggregation). Supports `--list` mode (no model call) for the scope-review gate.

Query params: `corpus` (glob), `aliases`, `known_names[]`, `min_facts`, `known_only` (bool), `out_dir`, `list` (bool → `--list`), `types[]`, `render_only`, `endpoint`/`endpoints[]`, `model`, `backend`, `entity_parallel`.

Response: SSE as above. When `list=true`, the stream is the entity/scope table only.

### `GET /api/ensemble/run/recent-events`  *(deterministic, no model)*
Runs `build_recent_events.py`. Query params: `corpus`, `output`, `window`. SSE.

### `GET /api/ensemble/run/synthesize`
Runs one of the four synthesis scripts depending on `doc`.

Query params: `doc` ∈ {`world_state`, `campaign_state`, `party`, `planning`} (selects the script), the doc-specific inputs (e.g. `dossiers`, `dossier_min_facts`, `threads`, `party`, `planning_config`, `npc[]`, `arc_scores[]`, `context[]`, `extract_dir`, `synthesize_only`), `output` (must be a `*_draft.md` path), `backend`, `endpoint`, `model`.

For `doc=planning`, `planning_config` (falling back to an auto-detected `config/planning.yaml`/`planning.yaml`, mirroring `party`) takes precedence and is passed as `--planning-config`; only when no config is found or given do `npc[]`/`arc_scores[]` get passed directly. The tracked (arc-scored) NPC/faction subset inside the config is a human-curated decision (`docs/cli/ensemble_workflow.md` §3e). Everything else — every `docs/ensemble/merged_dossiers/npc_*.md` not already bound as a config entry's `dossier` — is auto-included as `--npc` pass-through (planning.py's own docstring: config entries are the arc-scored minority, `--npc` extras are "the majority"), unless `npc[]` is supplied explicitly.

Response: SSE.

Behavior:
- `output` MUST resolve to a draft path; the router rejects (HTTP 400) an `output` that targets a live grounding doc (`docs/<name>.md`) to enforce FR-013.
- If `doc` ∈ {`campaign_state`, `party`} and `backend` resolves to the subscription `claude-code` path, the router disables agent tools so output goes to stdout (the documented `claude -p` clobber gotcha) — but the default synthesis path here is direct API/OpenRouter, so this is an edge guard.
- If the synthesis `model`/`backend` is below the capability bar, the response includes a non-fatal warning line in the stream (FR-014).

---

## Status & file endpoints (JSON)

### `GET /api/ensemble/status?campaign_dir=…&chapters=…`
Returns disk-derived pipeline state (R4, FR-002). No model call, no caching.

```json
{
  "campaign_dir": "/abs/path",
  "stages": [
    {"id": "extract",    "status": "complete",    "artifacts": 45},
    {"id": "bundle",     "status": "not_started", "artifacts": 0},
    {"id": "synthesize", "status": "not_started", "drafts": []},
    {"id": "review",     "status": "not_started"}
  ],
  "current_stage": "bundle"
}
```

Completion predicates: `extract` ⇔ `per_chapter/*/merged.json` exist; `bundle` ⇔ `state_dossiers/*.md` exist; `synthesize` ⇔ `*_draft.md` exist; `review` ⇔ operator-promoted (best-effort: live doc newer than draft).

### `GET /api/ensemble/files?dir=…&pattern=…`
Lists artifacts in an ensemble subdir (dossiers, drafts, per_chapter outputs) for review. Mirrors `grounding.py:/extracts`. Returns `{dir, exists, files:[{name,size}]}`.

### `GET /api/ensemble/file?path=…`  /  `PUT /api/ensemble/file?path=…`
Read / write a single interchange file (e.g. `aliases.json`, a draft) so the operator can preview and the alias-correction gate is satisfiable from the UI *or* the CLI/chat (FR-012). Write is path-validated and confined to the campaign workspace. **PUT to a live grounding doc is rejected** (promotion is a deliberate, separate action).

### `GET /api/ensemble/diff?draft=…&live=…`
Returns a unified diff between a `*_draft.md` and its live counterpart for the diff-before-promote gate. Read-only; never writes.

### `POST /api/ensemble/promote`
Body `{draft, live}`. Copies a reviewed draft over the live doc — the single explicit promotion action (FR-013, SC-005). The router refuses any `live` outside the four known grounding docs.

---

## Cross-cutting contract rules

1. Every run endpoint records the backend+model into the produced artifact's provenance (FR-008) — implemented in the CLI, surfaced here.
2. No endpoint stores pipeline state server-side; status is always recomputed from disk (FR-017).
3. Secrets travel only via `env_extra` to the subprocess, never as query params or in logs.
4. The router never imports `anthropic`/`openai` and never calls `stream_api`/`call_api`/`retrieve` — it only spawns CLI processes (Principles III, V, VI).
