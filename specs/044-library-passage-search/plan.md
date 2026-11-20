# Implementation Plan: Library Passage Search

**Branch**: `044-library-passage-search` | **Date**: 2026-11-20 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/044-library-passage-search/spec.md`

## Summary

This plan turns the 50-book pilot (`pipelines/rpglib_palace/`, #664) into a first-class **library** tier of RLM retrieval. The GM declares a book selection in hypostasis's authority file. CG commands then build and refresh an isolated library palace: one markdown file per section, mined with `mempalace mine`. They also search it, returning whole sections capped per book, and report health through distinct exit codes that hypostasis uses.

The library is wired into the rest of RLM in three places:
- `rpg_retriever` returns library passages as `kind="passage"`, in a documented tier.
- A new MCP tool lets an agent run repeated searches and read whole passages.
- A Prep panel is the UI face.

Bringing the library up on a machine is out of scope (local_machine#1).

## Technical Context

**Language/Version**: Python 3.12+ (repo standard). Vue 3 + TypeScript for the UI face.

**Primary Dependencies**:
- mempalace, reached **only** through `pipelines/rlm/mempalace_client.py` (Principle V)
- `pipelines/content_ingest/fivetools_render.py`
- PyYAML
- FastAPI (`server/`)
- `rpg_library.db`, read-only, through stdlib sqlite3

**Storage**: An isolated mempalace palace, using the turbovec backend and the Ollama `qwen3-embedding:0.6b` embedder (both per hypostasis). Alongside it on disk: a book manifest, a per-book ledger, a section map and an embedder stamp (see data-model.md).

**Testing**: pytest with tmp paths and fakes; tests never touch a live palace or the Drive mount. Vitest for the UI panel.

**Target Platform**: The GM's Linux machines, through hypostasis.

**Project Type**: CLI + module + MCP tool + web UI panel inside the CampaignGenerator monorepo.

**Performance Goals**:
- Search in under 3 s on about 667 books (SC-003).
- Refreshing one book in under 5% of a full build (SC-005).
- The pilot measured about 1 s per search and 186 s to mine 50 books.

**Constraints**:
- Never colocated with a live palace (FR-001).
- No silent "all" (Principle X).
- No LLM calls.
- No direct mempalace imports outside the client.
- Configuration comes only from the authority file (FR-017).

**Scale/Scope**: 667 finished sidecars today. A linear projection from the pilot gives about 95k drawers and about 40 minutes for a first full mine.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How |
|---|---|---|
| I. Disk is truth | PASS | Selection, manifest, ledger, section map and stamp are files. The palace is derived and rebuildable. |
| II. Human checkpoint | PASS | The library feeds nothing automatically. The agent's recommendation is a draft for the GM. |
| III. Retrieval/render separated | PASS | Passages reach campaign docs only through `dossier_proposal.md` approval (FR-016). There are no render calls, and `tests/test_retrieve_render_isolation.py` still guards this. |
| IV. Verbatim | PASS | Passage text is the rendered section, returned verbatim. The MCP tool returns full text so it can be quoted exactly (FR-014). |
| V. One seam per boundary | **ACTION** | The pilot imports `mempalace.searcher` and shells out to `mempalace mine` directly. Both move behind `mempalace_client.py` (research R2). |
| VI. CLI is the engine | PASS | Every capability is a `library` subcommand. The MCP tool and the UI call the same functions. |
| VIII. State discoverable | PASS | `library status` reads its state from disk. "Not built" and "not configured" are explicit states with their own exit codes (FR-018). |
| IX. UI mechanizes | PASS | The panel runs a search and shows the results. Judgement stays in chat or at the CLI. |
| X. Selection explicit | PASS | A build refuses without a declared selection, and "all converted" must be written out (FR-002). |
| XI. Every CLI capability has a face | **ACTION** | The GM has not exempted a UI, so a Library Search panel ships with this feature. It covers `search` and `status`, and shows `build`/`refresh` state together with the exact command to run (R7). |
| XII. One spelling per option | PASS | Reuses RLM's `--limit` and `--json`. `--per-book` is new and documented once. The library location is not a CLI flag. |
| XIII. Breaking state migrates | N/A | This adds a new store and changes no existing state. The pilot's `~/rpglib-palace` is scratch and needs no migration. |

**Gate**: PASS, with the two ACTION items built into the design. The post-design re-check below also passes.

## Project Structure

### Documentation (this feature)

```text
specs/044-library-passage-search/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli.md              # `library` subcommands + exit codes (FR-018)
│   ├── authority-config.md # keys read from hypostasis.yaml (FR-017)
│   ├── retrieval-kind.md   # kind="passage" + tier position (FR-013)
│   └── mcp-tool.md         # library_search tool (FR-012/014)
└── tasks.md                # /speckit-tasks
```

### Source Code (repository root)

```text
pipelines/library/                # git mv of the pilot's pipelines/rpglib_palace/
├── config.py      # authority file → LibraryConfig (FR-017); replaces envcfg.py
├── guard.py       # live-palace refusal (FR-001)
├── select.py      # selection → manifest; version dedupe (FR-002/003)
├── fetch.py       # source → cache (FR-006)
├── render.py      # sections → markdown (FR-004/005)
├── build.py       # build/refresh, diff vs ledger, BuildReport (FR-006/015)
├── search.py      # expansion, per-book cap, unmapped (FR-008/009/010); was query.py
├── status.py      # health → exit codes (FR-007/018)
└── cli.py         # `library {build,refresh,search,status}`
pipelines/rlm/
├── mempalace_client.py   # + mine(), delete-by-room, search on an explicit palace path
├── rpg_retriever.py      # + passage tier; covered books are never expensive candidates
└── mcp_server.py         # + library_search; rpg_search gains include_library/k_library
server/routers/library_routes.py           # GET /api/library/status, POST /api/library/search
frontend/src/views/prep/LibrarySearch.vue  # UI face (XI)
docs/cli/library_search_howto.md
tests/test_library_*.py                    # moved from the pilot's tests and extended
```

**Structure Decision**: The pilot package and its tests are `git mv`-ed to `pipelines/library/` so their history is kept. RLM integration goes into the existing `pipelines/rlm/` modules. The pilot's `query` subcommand becomes `search`, to match RLM wording. `select`, `fetch` and `render` become internal steps of `build`/`refresh`.

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|---|---|---|
| A UI panel for a feature used mostly through the CLI and agents | Principle XI; the GM has not asked for no UI | Omitting it would be an unstated exemption. If the GM rules "no UI", drop the UI tasks and record the ruling here. |
| Mining routed through `mempalace_client` (as a subprocess, not MCP) | Principle V: one seam to MemPalace | A `subprocess.run(["mempalace","mine"…])` call in `pipelines/library` would be a second seam. |

## Decided

- **Build ownership (GM, 2026-11-20): option A.** CG owns `library build` and `library refresh`. Hypostasis decides when to run them: `setup` runs `library build` when no library exists, and `status` runs `library status`. The GM runs `library refresh` directly after fixing a book's JSON.

## Post-design Constitution re-check

- **V**: All palace access goes through `mempalace_client` (contracts/cli.md, R2). PASS.
- **XI**: LibrarySearch.vue covers search and status. Build and refresh are shown, not run (R7). PASS, unless the GM rules otherwise.
- **III**: Passages stay behind the proposal flow, and `library_search` returns data only. PASS.
