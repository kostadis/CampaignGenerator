---
description: "Task list for Library Passage Search"
---

# Tasks: Library Passage Search

**Input**: Design documents from `/specs/044-library-passage-search/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (cli, authority-config, retrieval-kind, mcp-tool), quickstart.md

**Tests**: Included. The repo works test-first, and the pilot code is already tested. Every test uses tmp paths and fakes. No test may touch `~/.mempalace`, `~/src/campaigns`, or the `/mnt/g` mount.

**Organization**: Tasks are grouped by user story.
- Search, build and config are shared engine pieces, so they sit in Foundational.
- The stories add their surfaces on top: agent (US1), CLI (US2), RLM tier (US3), refresh (US4).
- No UI: the GM exempted this feature from Principle XI on 2026-11-20.

**Execution rule (GM)**:
- All tasks run in the single worktree `~/src/CampaignGenerator-rpglib-palace`, branch `044-library-passage-search`.
- Sonnet subagents write the code; Opus orchestrates and reviews.
- There is one code-review pass at the end. Leftovers become sub-issues of #664.
- Tests run with `PYTHONPATH=<worktree>`. The editable install shadows the worktree, so one test asserts that the package `__file__` is inside the worktree.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup

- [X] T001 `git mv pipelines/rpglib_palace pipelines/library` and `git mv tests/test_rpglib_palace_*.py tests/test_library_*.py`. Update imports. Run `python -m pytest tests/test_library_*.py` to confirm the 49 pilot tests still pass. Update the worktree-import assertion in tests/test_library_select.py to `pipelines.library`.
- [X] T002 Rename the pilot `query.py` to `pipelines/library/search.py` and `run_query` to `search_library`. Change the CLI from `query` to `search`. Replace the `rpglib_palace` entry in `pyproject.toml [project.scripts]` with `library = "pipelines.library.cli:main"`.

## Phase 2: Foundational (blocks all stories)

**Config and guard (FR-001, FR-017)**

- [X] T003 [P] Write tests in tests/test_library_config.py for each of the following:
  - a `library:` block is read correctly;
  - the `env:` merge never overrides variables already set;
  - a missing block, a missing selection, and a selection using more than one form each raise `NotConfigured`;
  - `~` paths are expanded;
  - `rpg_library_db` is read from `data_roots.rpg_library_db`.
- [X] T004 Implement `load_library_config(path=~/.config/hypostasis/hypostasis.yaml, environ) -> LibraryConfig` in pipelines/library/config.py, following contracts/authority-config.md and data-model.md LibraryConfig. Delete `pipelines/library/envcfg.py` and move its tests into tests/test_library_config.py.
- [X] T005 [P] Extend the guard tests in tests/test_library_guard.py: `~/.mempalace/palaces/x`, a campaign palace, and a symlink into either all raise `PalaceRefused`. Exit code 6 is mapped in T012.

**Mempalace seam (Principle V, research R2)**

- [X] T006 [P] Write tests in tests/test_mempalace_client_library.py:
  - `mine(render_root, palace, wing, env)` builds `mempalace mine <root> --direct --wing <wing>`, passes the merged env, and raises `MempalaceProcessError` on a non-zero exit (with subprocess mocked);
  - `delete_room(palace, wing, room)` calls the MCP delete path (fake transport);
  - `search(..., palace=<path>)` passes `--palace <path>`.
- [X] T007 **First**, decide research R10: probe the mempalace MCP tool list for delete-by-room or delete-by-source, record the answer in research.md R10, and stop and tell the GM if only the rebuild fallback exists. Then implement `mine()`, `delete_room()` (or the R10 fallback) and explicit-palace search in pipelines/rlm/mempalace_client.py.
  - Check the real MCP search hit shape for `source_path`, `room` and `source_file`, and record the finding in a docstring.
  - If no delete-by-room tool exists, implement the R5 fallback and note which one was used.
- [X] T008 Remove every `mempalace` import and `mempalace` subprocess call from pipelines/library/ and route them through `mempalace_client`. Add tests/test_library_seam.py, an AST check that fails if `pipelines/library/*.py` imports `mempalace` or calls `subprocess` with `mempalace`.

**Selection and dedupe (FR-002, FR-003)**

- [X] T009 [P] Add tests to tests/test_library_select.py:
  - each of `product_types`, `book_ids` and `all_converted` selects the right books;
  - `exclude_book_ids` is honoured;
  - print-friendly twins are deduped in favour of the non-print-friendly title, with `is_printer_friendly` as the tiebreaker;
  - an explicit `book_ids` entry bypasses dedupe.
- [X] T010 Implement `select_books(config: LibraryConfig) -> list[LibraryBook]` in pipelines/library/select.py, using the rules in research R4.

**Build engine and state (FR-004, FR-005, FR-007, FR-015)**

- [X] T011 [P] Write tests in tests/test_library_build.py for `build(config, *, client)`:
  - it writes `manifest.json`, `library_ledger.json`, `rendered/`, `sections.json` and `embedder.json` under `work_dir`;
  - books whose sidecar is missing or unreadable are skipped with a reason, and the other books still build;
  - an unreadable `source_root` raises `SourceUnavailable`, and no empty library is written;
  - the returned BuildReport has the fields from data-model.md.
  Use a fake client.
- [X] T012 Implement `build()` in pipelines/library/build.py, reusing fetch.py and render.py. Write the EmbedderStamp from config env. Define the exit-code enum `ExitCode` (0, 1, 2, 3, 4, 5, 6 per contracts/cli.md) in pipelines/library/__init__.py.

**Search engine with the embedder check (FR-007 to FR-010)**

- [X] T013 [P] Add tests to tests/test_library_search.py:
  - a library that was never built raises `NotBuilt`;
  - a stamp/config mismatch raises `EmbedderMismatch` with a message naming both models;
  - when search runs through the fake `mempalace_client`, expansion, dedupe, the per-book cap and the unmapped list still pass.
- [X] T014 Update `search_library(config, query, *, limit=10, per_book=2, client) -> SearchResultSet` in pipelines/library/search.py so it uses the client and the stamp check.

**Checkpoint**: the engine builds and searches entirely through the client.

## Phase 3: User Story 1 — Ask the agent to find something (P1) 🎯 MVP

**Goal**: An agent can iterate over library searches and recommend passages with citations.

**Independent Test**: In a Claude session with the campaign MCP server, ask "use the library to find me a statblock for a tavern keeper". The answer cites `title (book id) — section`, and every quoted detail appears in that passage.

- [X] T015 [P] [US1] Write tests in tests/test_mcp_library_search.py:
  - `library_search` returns SearchResultSet JSON with full passage text;
  - NotConfigured, NotBuilt, EmbedderMismatch and Refused each come back as `{"error": code, "message": ...}`, and nothing raises;
  - the docstring contains the four guidance points from contracts/mcp-tool.md.
- [X] T016 [US1] In pipelines/rlm/mcp_server.py, add the `library_search(query, limit=10, per_book=2)` MCP tool, calling `search_library`, and the `library_verify_citation(file, quote)` tool (contracts/mcp-tool.md "Companion tool"). The `library_search` docstring requires the agent to verify every quote (SC-002). It depends on T018a's `verify_citation`.
- [X] T017 [US1] Run tests/test_retrieve_render_isolation.py and confirm `library_search` and pipelines/library never mix retrieval with render calls.

## Phase 4: User Story 2 — Command-line search (P2)

**Goal**: `library search` gives whole passages, with distinct-book count, cap count and unmapped hits.

**Independent Test**: `library search "tavern keeper statblock" --json` returns whole sections, no more than 2 per book, with a summary.

- [X] T018 [P] [US2] Write tests in tests/test_library_cli.py:
  - `library search` produces the human-readable format and the `--json` format;
  - exit codes are 3 when not configured, 4 when not built, 5 on an embedder mismatch, and 6 when refused;
  - each refusal message names its fix, and exit 4 names the hypostasis step;
  - `library status --json` produces the fields listed in contracts/cli.md.
- [X] T018a [P] [US2] Write tests in tests/test_library_verify.py for `verify_citation(work_dir, file, quote)`:
  - an exact span is found and its offset is returned;
  - a span that differs only in whitespace is found;
  - a single changed word is not found;
  - a file outside `rendered/` is refused.
- [X] T019 [US2] Implement `library build | search | status | verify-citation` in pipelines/library/cli.py and `status(config) -> dict` in pipelines/library/status.py, mapping exceptions to `ExitCode`.

## Phase 5: User Story 3 — Library hits in RLM retrieval (P2)

**Goal**: `kind="passage"` sits in tier 2, and books it covers are no longer offered as expensive candidates.

**Independent Test**: `rpg_retriever "tavern keeper"` shows passages after drawers and before candidates. With `--no-library`, the output is identical to before.

- [X] T020 [P] [US3] Add tests to tests/test_rpg_retriever.py:
  - `reconcile(..., library_result=...)` places passages after drawers and before cheap candidates, in their search order, truncated to `k_library`;
  - books with passages are excluded from the expensive tier;
  - `library_status` is set for ok, not_configured, not_built and embedder_mismatch;
  - with `include_library=False`, the output equals the pre-feature output on the existing fixtures.
- [X] T021 [US3] Implement the passage tier in pipelines/rlm/rpg_retriever.py:
  - add `library_result` to `reconcile()`;
  - add `include_library` and `k_library` to `retrieve()`, `retrieve_scoped()` and the CLI (`--no-library`, `--k-library`);
  - add `library_status` to `RetrievalResult`, following contracts/retrieval-kind.md.
- [X] T022 [US3] Thread `include_library` and `k_library` through `rpg_search` and `propose_dossier` in pipelines/rlm/mcp_server.py. Passages render into `dossier_proposal.md` labelled `passage`. Update tests/test_mcp_server.py.

## Phase 6: User Story 4 — Declare and refresh (P3)

**Goal**: Only changed, added or removed books are re-processed.

**Independent Test**: Build; then change one sidecar; then `library refresh`. `changed` lists only that book, and search shows the change.

- [X] T023 [P] [US4] Write tests in tests/test_library_refresh.py with a fake client (the R10 decision from T007 must already be recorded):
  - **no stale drawers**: after refreshing a changed book, no palace `source_path` is missing from the new `sections.json` (R10 guard);
  - for a changed book, the client gets `delete_room(b<id>)` and then a mine of only that book;
  - for a removed book, the client gets `delete_room` and the book's ledger entry is dropped;
  - an unchanged book gets no client call;
  - the ledger is updated;
  - refreshing before any build gives `NotBuilt`.
- [X] T024 [US4] Implement `refresh(config, *, client) -> BuildReport` in pipelines/library/build.py, then add `library refresh` to pipelines/library/cli.py.

## Phase 7: Polish & Cross-Cutting

- [X] T027 [P] Write the operator how-to in docs/cli/library_search_howto.md: the authority keys, every exit code and refusal, the agent workflow, and refresh after fixing a book's JSON. Add it to the CLAUDE.md doc table and docs/README.md. Add a passage-tier note to docs/rlm/rlm_pipeline.md.
- [ ] T028 (DEFERRED by GM 2026-11-20, see #669) Install the package into the server venv with `uv pip install -e . --python ~/.venv/bin/python` (the CLAUDE.md rule), then confirm `library --help` resolves.
- [ ] T029a (DEFERRED by GM 2026-11-20, see #669) Run the scale check (SC-003, SC-005):
  - Build a scratch library with `selection: {all_converted: true}`; that is 667 books today.
  - Record the build time, the drawer count and the index size, and note any chunk-cap skips.
  - Measure search latency (median and maximum over 10 queries) and the time to refresh one book.
  - Record the results in experiments/20261120-rpglib-palace-pilot/FINDINGS.md.
  - If SC-003 or SC-005 is missed, tell the GM. Do not change the targets.
- [ ] T029 (DEFERRED by GM 2026-11-20, see #669) Run quickstart.md scenarios 1–7 against a scratch `library:` config of about 50 books.
  - Record the time, size and latency, and confirm the live palaces are unchanged (SC-006).
  - Scenario 8 (the agent test) is run by the GM.
- [X] T030 Run one `/code-review` pass on the branch. Fix confirmed findings, and file the rest, plus any deferred gaps, as sub-issues of #664.

## Dependencies & Execution Order

- **Order**: Setup (T001–T002), then Foundational (T003–T014), then the stories.
  - US1 (T015–T017), US2 (T018–T019), US3 (T020–T022) and US4 (T023–T024) depend only on Foundational, so they can proceed in parallel.
  - T029 needs everything. T030 comes last.
- **Within Foundational**:
  - T003 → T004 → (T005, T006 → T007 → T008).
  - T009 → T010.
  - T011 → T012 needs T004, T007 and T010.
  - T013 → T014 needs T007 and T012.
- **Shared files**:
  - mcp_server.py is touched by T016 and T022, so run them sequentially.
  - cli.py is touched by T019 and T024, so run them sequentially.

## Parallel Examples

- **Foundational tests**: T003, T005, T006 and T009 together (different files).
- **After Foundational**: T015 [US1], T018 [US2], T020 [US3] and T023 [US4] tests together.


## Implementation Strategy

1. **MVP**: Setup, then Foundational, then US1 (the agent tool). This delivers the use case the pilot proved.
2. Add US2 (the CLI surface the hypostasis contract relies on), then US3 (RLM integration), then US4 (refresh).
3. Polish brings docs, install and the end-to-end quickstart. Stop and validate after each story with its Independent Test.
