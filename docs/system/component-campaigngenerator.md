# Component: CampaignGenerator

> The hub. The only thing you launch directly. Everything else feeds it or is
> called by it. [↑ index](index.md)

**Repo:** `~/src/CampaignGenerator` · **Deep docs:** [`docs/core/architecture.md`](../core/architecture.md)

---

## What it is

A D&D session-prep and post-session toolkit. It assembles campaign documents,
calls an LLM to draft encounter/narration content, and runs a retrieval
pipeline over a local RPG library. Three faces:

- **CLI scripts** — `pipelines/session_prep/prep.py`, `sd_*.py`, `pipelines/grounding/distill.py`, `pipelines/grounding/planning.py`, … (one per task)
- **Web UI** — FastAPI backend + Vue 3 frontend that *shells out to the same CLI scripts*
- **MCP server** — exposes campaign docs/tools to a Claude Code session

**Core invariant:** Markdown/YAML files on disk are the source of truth. The LLM
drafts between human checkpoints. All LLM calls funnel through one module.

---

## The four layers (+ one boundary)

```
Layer 4   CLI pipelines        pipelines/session_prep/prep.py, sd_consistency/plan/narrate, pipelines/grounding/distill.py,
          (extract→review→     pipelines/grounding/planning.py, pipelines/grounding/party.py, pipelines/grounding/campaign_state.py,
           synthesize/render)  session_doc/enhance_summary.py, session_doc/scene_extract.py, ...
              │
Layer 3   Frontend             frontend/  (Vue 3 + Pinia + Vue Router)
              │   HTTP + SSE
Layer 2   Web server           server/  (FastAPI; routers shell out to CLI via
              │                  subprocess_runner.py, stream stdout as SSE)
              │
Layer 1   Core library         campaignlib/  (ALL file I/O, config, LLM calls,
          THE API SURFACE       batch orchestration, chunking)
              │
boundary  MCP server           pipelines/rlm/mcp_server.py  (read campaign docs; write notes/ only)
```

### Layer 1 — `campaignlib/` (the thing everything imports)

Refactored from a 1749-line god-module into a package. Public surface re-exported from `__init__.py`:

| Submodule | Owns |
|---|---|
| `api/client.py` | `make_client`, `call_api`, `stream_api`, `call_api_with_tools` — the **only** place `anthropic` is imported. Retry loop built in. |
| `api/backends.py` | Existing HTTP/Claude adapters: Anthropic (default), `_OpenAICompatClient` (DGX/vLLM), `_OpenRouterClient`, and `_ClaudeCodeClient` (claude CLI headless). |
| `api/codex_cli.py` | Sole Codex boundary: strict single-turn text facade plus isolated, subscription-authenticated `codex exec` process policy. |
| `api/batch.py` | Anthropic Message Batches orchestration (build → submit → poll → collect; sidecar `.batch.json`). |
| `config.py` | `find_default_config`, `load_config`, `load_file`, `assemble_docs`, `load_agent_prompt`. |
| `npc.py` / `scenes.py` / `textproc.py` / `pipelines.py` | Alias normalization, scene helpers, chunking/POV, the extract→synthesize two-pass pattern. |

> **Rule:** never `import anthropic` in a script; always go through `campaignlib`.
> `stream_api`/`call_api` already handle retries — don't add your own.

### LLM backends — picking where a call runs

`make_client()` chooses a backend by environment / flags:

- default → **Anthropic** (`anthropic.Anthropic()`)
- `CG_BACKEND=claude-code` → **Claude Code** CLI headless (bills Pro/Max, not metered API)
- `CG_BACKEND=codex-cli` → **Codex CLI** non-interactive execution using the saved ChatGPT login; supported across the canonical 30-command family, including brokered polish
- `DGX_ENDPOINT` set (or `--dgx-endpoint`) → **`_OpenAICompatClient`** pointed at vLLM on the Spark

The DGX backend is an *anthropic-SDK facade* over the `openai` SDK (so the whole
pipeline runs unchanged), and it pulls per-model behavior — thinking on/off,
read timeout — from **`dgxlib.resolve_model_config()`**. A `thinking: bool|None`
knob threads from `stream_api`/`call_api` down to the request `extra_body`, and
is stripped for non-DGX clients so Anthropic never sees it. Swapping the served
model is a one-line edit to `dgxlib/models.yaml`, not code surgery here. See
`tests/test_dgx_registry.py`.

### Canonical command family and Codex boundary

The backend selector is shared by 30 model-bearing or dispatching commands:

| Family | Commands |
|---|---|
| Session document (8) | `check_consistency`, `enhance_summary`, `scene_extract`, `sd_agent`, `sd_consistency`, `sd_plan`, `sd_narrate`, `vtt_voice_compare` |
| Prep, ingest, search, integration (5) | `prep`, `transform`, `dnd_sheet`, `query`, `scabard_sync` |
| Grounding (8) | `planning`, `party`, `make_tracking`, `distill`, `campaign_state`, `npc_table`, `grounding_sections`, `thread_registry` |
| Ensemble (9) | `synthesise_world_state`, `synthesise_polish`, `extract_facts`, `facts_to_state`, `narrate_chapter`, `polish`, `ensemble`, `ensemble_batch`, `ensemble_extract` |

Codex requires an installed compatible CLI and `codex login`; it uses the saved
ChatGPT subscription login in a fresh ephemeral, tool-free child. Metered API
keys are stripped from that environment and no provider fallback is attempted.
Omitted model intent reaches `CG_CODEX_MODEL`, then the subscription default;
explicit compatible models are forwarded and explicit `claude-*` models are
refused. Provider `--batch` is Anthropic-only and fails before Codex work, while
application grouping (`--batch-scenes`), local ensemble fan-out, resume, and
review remain independent. The `polish` loop is brokered: the parent owns tool
validation and document mutation, and Codex supplies only typed turn results.

Seven new UI faces expose consistency audit, transform, voice comparison,
Scabard sync, synthesis polish, per-chapter narration, and post-assemble polish;
other commands remain available through existing workflow faces. Scabard's
access key is passed only as a child-environment override and never appears in
argv, previews, logs, or diagnostics.

### Layer 2/3 — Web server & frontend

The UI **never reimplements logic**. A router takes an HTTP request, calls
`subprocess_runner.stream_subprocess()` to run the matching CLI script, and
streams stdout back as Server-Sent Events. State lives in `config.yaml` /
per-service server-owned YAML documents (`platform.yaml`, `session_doc.yaml`, `ensemble.yaml`, `grounding.yaml`, …; each strict pydantic) and Pinia stores. See [`docs/web/web_ui.md`](../web/web_ui.md).

### Boundary — `pipelines/rlm/mcp_server.py`

A FastMCP stdio server registered per-campaign via `.mcp.json`. Read/write
**asymmetric**: it can read any campaign doc and run retrieval/prep tools, but
writes only into `notes/`. MemPalace I/O from here still goes through
`pipelines/rlm/mempalace_client.py`.

---

## Major subsystems at a glance

| Subsystem | Key files | Page / doc |
|---|---|---|
| Session prep | `pipelines/session_prep/prep.py`, `pipelines/rlm/proposal_loader.py` | [flow-session-prep](flow-session-prep.md) |
| Post-session | `session_doc/enhance_summary.py`, `session_doc/scene_extract.py`, `sd_consistency/plan/narrate.py`, `session_doc/assemble.py`, `pipelines/ensemble/polish.py` | [flow-post-session](flow-post-session.md) |
| Ensemble grounding docs (with a Spark) | `pipelines/ensemble/ensemble.py`, `pipelines/ensemble/ensemble_batch.py`, `pipelines/ensemble/facts_to_state.py`, `pipelines/grounding/build_recent_events.py`, `pipelines/ensemble/synthesise_world_state.py` (+ `--synthesize-only` on `campaign_state/party/planning`) | [flow-ensemble](flow-ensemble.md) |
| Grounding docs (no-Spark / API-only fallback) | `pipelines/grounding/distill.py`, `pipelines/grounding/campaign_state.py`, `pipelines/grounding/party.py`, `pipelines/grounding/planning.py`, `pipelines/grounding/make_tracking.py` | [`docs/cli/grounding_docs.md`](../cli/grounding_docs.md) |
| RLM retrieval | `pipelines/rlm/rpg_retriever.py`, `pipelines/rlm/fivetools_catalog.py`, `pipelines/rlm/dossier_proposer.py`, `pipelines/rlm/proposal_loader.py` | [flow-rlm-retrieval](flow-rlm-retrieval.md) |
| MemPalace client | `pipelines/rlm/mempalace_client.py` | [component-mempalace](component-mempalace.md) |
| 5etools scoping | `pipelines/rlm/launch_5etools_mcp.py`, `pipelines/rlm/resolve_refs.py` | [component-campaign-data](component-campaign-data.md) |

---

## On-disk state it owns

Per-campaign, inside the workspace dir — see
[component-campaign-data](component-campaign-data.md) for the full tree. The
headline files CG reads/writes: `docs/*.md` (grounding), `docs/dossier_proposal.md`
(the human checkpoint), `docs/npcs/*.md`, `summaries/{session}/…`,
`logs/`, `notes/`.

---

## How it reaches the other components

| To | How | File |
|---|---|---|
| Anthropic / DGX / OpenRouter / Claude Code | existing adapters above | `campaignlib/api/backends.py` |
| Codex CLI | isolated `codex exec`, no API keys or provider fallback | `campaignlib/api/codex_cli.py` |
| MemPalace | subprocess stdio JSON-RPC | `pipelines/rlm/mempalace_client.py` |
| turbovecdb | **never directly** — only via MemPalace | — |
| 5etools JSON | filesystem, mtime-cached index | `pipelines/rlm/fivetools_catalog.py`, `pipelines/content_ingest/fivetools_ingest.py` |
| 5etools MCP (per campaign) | scoped symlink farm + Node server | `pipelines/rlm/launch_5etools_mcp.py` |
| mytools | data only (5etools JSON + `rpg_library.db`) | `pipelines/content_ingest/fivetools_ingest.py`, `pipelines/content_ingest/convert_book.py` |
| dgxlib | installed package | `campaignlib/api/backends.py` |
