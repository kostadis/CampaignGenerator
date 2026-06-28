# Phase 1 Data Model: Ensemble Grounding-Doc Workflow UI

This feature's "data" is almost entirely **files on disk** (Principle I) plus a small amount of **UI configuration state**. There is no new database. The entities below describe the conceptual model the UI presents and the on-disk artifacts that back it.

---

## 1. Backend Profile (config + runtime selection)

Represents how an LLM-bearing stage executes. Selectable per stage at run time (FR-006, FR-018).

| Field | Type | Notes |
|---|---|---|
| `backend` | enum `anthropic` \| `dgx` \| `openrouter` | Which seam branch `make_client` takes. Default `anthropic`. |
| `endpoint` | string \| null | For `dgx`: the Spark `--endpoints` URL(s). For `openrouter`: defaults to `https://openrouter.ai/api/v1` (rarely overridden). Null for `anthropic`. |
| `model` | string | Model id. Claude id for `anthropic`; Spark model id for `dgx`; OpenRouter id (e.g. `anthropic/claude-sonnet-4`) for `openrouter`. Free-text. |
| `api_key_source` | derived | `ANTHROPIC_API_KEY` (anthropic), none (dgx), `OPENROUTER_API_KEY` (openrouter). Never stored in tracked config. |

**Validation rules**:
- `backend == "openrouter"` requires `OPENROUTER_API_KEY` to be present in the environment; absence surfaces as an explicit error (FR-009), not a silent fallback.
- `backend == "dgx"` requires a reachable `endpoint`; unreachable surfaces as a fast, explicit error (edge case: local hardware unreachable).
- A synthesis-stage profile whose `model` is not on the synthesis-capable allow-list raises a **warning, not an error** (FR-014, R6).

**Persistence**: backend/endpoint/model selections persist in `ui_state.yaml` under `ui.ensemble` (per-stage). The key (secret) is environment-only.

---

## 2. Pipeline State (derived, not stored)

The campaign's position in the workflow. **Computed from disk on every read** (FR-002, FR-017) — never cached in the browser or written as a manifest (R4).

| Field | Type | Derivation |
|---|---|---|
| `campaign_dir` | path | From the active config (`runtime.session_dir` / campaign root). |
| `stages` | list of Stage | One per pipeline stage (below), each with a computed status. |
| `current_stage` | derived | First stage that is not `complete`. |

There are **no state transitions stored** — the state is a pure function of which artifacts exist. "Transition" happens implicitly when a stage's artifacts appear on disk.

---

## 3. Stage

One step in the ordered workflow. Status is derived from artifact presence (R4).

| Field | Type | Notes |
|---|---|---|
| `id` | enum | `extract` \| `bundle` \| `synthesize` \| `review` |
| `label` | string | Human label for the UI. |
| `status` | enum `not_started` \| `complete` (\| `running` transient) | Derived from artifacts; `running` is an in-flight UI state only. |
| `backend_profile` | Backend Profile \| null | Null for non-LLM stages (e.g. the `review` gate, the deterministic threads/recent-events renders). |
| `artifacts` | list of Artifact | What this stage reads and writes. |
| `gate` | Checkpoint \| null | A blocking human checkpoint attached to this stage, if any. |

**Stage → artifact / gate map** (the concrete pipeline):

| Stage | Backend? | Reads | Writes | Completion predicate | Gate |
|---|---|---|---|---|---|
| `extract` | yes (extract) | `docs/chapters/chapter_*.md` | `docs/ensemble/per_chapter/<stem>/merged.json`, root `merged.json` | per-chapter `merged.json` exist for the glob | — |
| `bundle` | yes (extract) | `merged.json`, `aliases.json`, `--known-names` | `docs/ensemble/state_dossiers/*.md`, `merged_dossiers/*.md` | dossier files exist | **scope review** (`--list`), **alias correction** |
| `synthesize` | yes (synthesis) | `merged_dossiers/*.md`, `threads.md`, `recent_events.md` | `docs/{world_state,campaign_state,party,planning}_draft.md` | `*_draft.md` exist | — |
| `review` | no | `*_draft.md`, live docs | (promotion writes live docs, human-initiated) | live docs updated by operator | **diff-before-promote** |

---

## 4. Checkpoint / Gate

A human-judgment point that blocks automatic advancement (FR-010, FR-011, Principle II). The UI represents it; the *decision* happens in Claude/CLI (Principle IX).

| Field | Type | Notes |
|---|---|---|
| `id` | enum | `scope_review` \| `alias_correction` \| `diff_promote` |
| `stage_id` | enum | The stage it gates. |
| `satisfied` | bool (operator-confirmed) | The UI does not auto-satisfy; the operator confirms after doing the work. |
| `handoff` | description | What to do in Claude/CLI (e.g. "run `--list`, review scope", "edit `aliases.json`", "`diff` draft vs live, then promote"). |
| `interchange_files` | list of path | The files the operator edits/reviews (e.g. `aliases.json`, `*_draft.md`) — the contract between UI, CLI, and chat (FR-012, FR-017). |

**Rule**: a gate is never bypassed by the pipeline; `synthesize` must not consume `bundle` output until `scope_review`/`alias_correction` are operator-confirmed (Principle II — no LLM output feeds another across a precision boundary without a human gate).

---

## 5. Artifact

A file produced or consumed by a stage — the unit of interchange (FR-004, FR-017).

| Field | Type | Notes |
|---|---|---|
| `path` | path | Absolute or campaign-relative; the source of truth. |
| `kind` | enum | `chapter` \| `facts` \| `dossier` \| `threads` \| `recent_events` \| `draft` \| `live_doc` \| `aliases` \| `known_names`. |
| `produced_by` | stage id \| null | Which stage wrote it (null for human-authored inputs). |
| `backend_used` | string \| null | For LLM-produced artifacts: the backend+model recorded with the output (FR-008). |
| `exists` | bool | Drives stage status. |

**Provenance rule (FR-008)**: every LLM-produced artifact records which backend and model produced it (e.g. a frontmatter/comment line). This is how a mixed run (extract on OpenRouter, synthesize on Anthropic) stays auditable.

---

## 6. Grounding Document (draft / live)

The four targets, with a hard draft/live distinction (Principle I, FR-013).

| Field | Type | Notes |
|---|---|---|
| `name` | enum | `world_state` \| `campaign_state` \| `party` \| `planning`. |
| `draft_path` | path | `docs/<name>_draft.md` — what synthesis writes. |
| `live_path` | path | `docs/<name>.md` — only the operator promotes to here. |

**Rule**: the workflow writes drafts only; the UI never auto-overwrites a live doc; promotion is an explicit operator action (SC-005).

---

## Config schema addition (`server/config_models.py`)

A new `EnsembleSection` added to `UISection`, registered in `UI_SECTION_NAMES`:

```
ui.ensemble:
  campaign_dir: str
  chapters_glob: str               # default docs/chapters/chapter_*.md
  extract:    { backend, endpoint, model }   # Backend Profile
  synthesize: { backend, endpoint, model }   # Backend Profile (independent of extract)
  known_names: [str]
  aliases_path: str
```

No secret fields. Mirrors existing `SessionDocSection`'s `backend`/`dgx_endpoint`/`dgx_model` precedent (`config_models.py`).
