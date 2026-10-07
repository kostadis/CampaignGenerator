# HTTP Contract: summary-native routes (Principle XI parity)

All routes live in `server/routers/summary_native.py` (prefix unchanged) and stream the CLI's output over SSE via `subprocess_runner`. They build argv only; no pipeline logic lives in the router (Principle VI).

**Defaults**: resolved from `grounding.yaml summary_native` through `GroundingConfigService` at the route edge. Route parameters are sentinels (`""`, or `None` for ints where 0 is meaningful). No default literal appears in the router, and a guard test asserts that.

| Route | CLI | Parameters → flags |
|---|---|---|
| `GET /run/extract` | `extract` | `summaries_dir since until` (as 031); `endpoints: list[str]` (repeated query parameter; blank entries dropped) → one `--endpoints A B …` flag, never `--endpoint` beside it, 400 for a non-dgx backend; `parallel` (at least 1, else 400) → `--parallel` (calls per endpoint). Endpoints are machine wiring and never stored in config (the strict model refuses an `endpoints` key); `chunk_chars` → `--chunk-chars`; `max_tokens`; `dump_only`; `force`; `model` / backend selection via `resolve_selection(... service="summary_native.extract")` → `--backend --model --endpoint` |
| `GET /run/synth/{doc}` *(changed for world_state / campaign_state)* | `synth <doc>` | as 031, plus `fallback_npc_lines: bool` → `--fallback-npc-lines` (world_state only; refused for other docs). Prose backend/model via `resolve_selection(... service="summary_native.prose")`; `claude_code_effort` (`low|medium|high|xhigh|max`) → `--claude-code-effort`, sent only when given. `parts` and `audit` are rejected (400) for these two docs, with the CLI's message |
| `GET /run/annotate/{doc}` | `annotate <doc>` | `summaries_dir since until`; `dry_run` → `--dry-run` |
| `GET /run/audit` | `audit` | `summaries_dir since until`; `track_file: list[str]` (repeated) → one `--track-file` each, or none to let the CLI read `grounding.yaml campaign_state.track_files` (400 before spawning when neither the request nor the config names a file); `candidates` (at least 1, else 400) → `--candidates`, sent only when given; `max_tokens`; `dump_only`; `force`; `endpoints` / `parallel` exactly as `/run/extract`; backend and model via `resolve_selection(... service="summary_native.extract")`, since the judge runs on the extraction backend family |
| `GET /state` *(extended)* | — (reads files) | adds an `extract` block (chunks, kept/dropped, outlier chunks, freshness), an `audit` block (below), and per-doc `annotations` counts and `missing_dossiers`, all read from `state/` |
| `GET /drafts` *(extended)* | — | lists the timeline file, `reference/*.md`, `annotations.md`, `npc_status_report.md`, `notes/drops.md` and `audit/audit.md` alongside the drafts |

## Page

`frontend/src/views/grounding/SummaryNative.vue` gains:

- **An "Extract" step:** endpoints list (multi-entry), parallel requests per endpoint, chunk size, extraction model; Run / Dump-only / Force. It shows kept and dropped counts per chunk, flags outlier chunks, and links `drops.md`.
- **On the world_state / campaign_state synth steps:** the prose model and effort, and a **"Write fallback lines for NPCs without a published dossier"** checkbox. It is unchecked on every page load, never persisted, and world_state only. A refusal for missing dossiers is shown as its list of NPCs and states, with a link to the NPC dossiers page.
- **An "Audit" step:** track files (prefilled from config, editable per run), candidates per item, max tokens, model, endpoints and workers per endpoint; Run / Dump-only / Force. It shows the counts (supported; not found split into no candidate chapters / not shown / unverified; not judged), staleness and a link to `audit.md`.
- **An "Annotate" action** per draft, with a dry-run preview.
- **Links** to the timeline, reference files, annotations report and NPC status report.

The page mechanizes; reviewing drafts and promoting them stays in files and chat (Principle IX).

## Config routes

The new `summary_native.extract` and `summary_native.prose` blocks are read and written through the existing `GET`/`PUT` grounding config routes. The model is strict (`extra="forbid"`): unknown keys are refused, and `endpoints` and `fallback_npc_lines` are not config keys.

## The `audit` block of `GET /state`

Read from `state/audit/` only; no model, no CLI. Shape: `{present, complete, stale, stale_reason, counts, summary, backend, model, candidates, audit_file, track_files_run, track_files}`.

- `counts` are `audit.json`'s (`items, supported, not_found, no_candidates, not_shown, unverified, not_judged`); `summary` is the CLI's `audit: … items — …` line.
- `complete` is false while any item is `NOT JUDGED`.
- `stale` is `freshness.check_audit_fresh` against the **configured** track files (`grounding.yaml campaign_state.track_files`), the same comparison `synth campaign_state` makes; `stale_reason` is its message.
- `track_files` is the configured list, which the page uses to prefill its box. It is present (possibly empty) even before any audit has run.
- Before any audit, `present` is false and `counts` is `null`.
