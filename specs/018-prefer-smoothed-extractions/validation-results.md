# Validation Results: Prefer Smoothed Scene Extractions for Narration

**Worktree**: `/home/kroussos/src/CampaignGenerator/worktrees/018-prefer-smoothed-extractions`
**Branch**: `018-prefer-smoothed-extractions`
**Baseline date**: 2026-08-29

## T003 — Pre-edit baseline

| Gate | Command | Result |
|---|---|---|
| Focused non-service tests | `rtk pytest tests/test_editor_pipeline.py tests/test_sd_narrate.py tests/test_smoothed_claim.py` | **PASS** — 123 passed. |
| Editor-service integration baseline | `rtk proxy pytest -vv -o faulthandler_timeout=15 tests/test_editor_service_integration.py::TestGetEditorConfig::test_returns_grouped_shape` | **PRE-EXISTING STALL** — request blocks at `client.get("/api/editor/config")`; faulthandler shows Starlette `TestClient` waiting in AnyIO's blocking portal. The run was interrupted after confirming the stall. |
| Required focused set | `rtk proxy pytest -vv tests/test_editor_pipeline.py tests/test_sd_narrate.py tests/test_editor_service_integration.py tests/test_smoothed_claim.py` | **PARTIAL** — all 123 tests preceding the service-integration file passed; the first service-integration test stalled as above. |
| Full backend suite | `rtk proxy timeout --signal=INT 300 pytest -vv tests/` | **PRE-EXISTING COLLECTION ERROR** — 4,520 items collected with one skipped, then `tests/test_mcp_server.py` failed import because optional dependency `mcp` is not installed (`ModuleNotFoundError: No module named 'mcp'`). No tests executed. |
| Frontend build | `rtk npm run build` from `frontend/` | **PASS** — `vue-tsc -b && vite build`; 174 modules transformed. |

The ignored worktree-local `frontend/node_modules` is a symlink to the primary
checkout's existing dependency tree. No package or lockfile changed.

### Baseline comparison rule

Feature completion may add no failure beyond the missing optional `mcp`
collection dependency and may not introduce a new service-integration stall.
Feature-specific API behavior will be exercised with bounded direct route
tests if the pre-existing `TestClient` stall remains.

## T011 — Foundational GPT-5.6 gate

| Check | Result |
|---|---|
| Shared resolver contracts | **PASS** — 4 passed (`tests/test_editor_pipeline.py -k shared_scene_resolver`). |
| Exact-file CLI contracts | **PASS** — 7 passed (`tests/test_sd_narrate.py -k exact_scene_input`). |
| Additive editor-detail source states | **PASS** — 4 passed (`TestExtractionDetailNarrateSource`), using direct route calls to avoid the baseline TestClient stall. |
| CLI help | **PASS** — one canonical `--scene-extraction-file FILE` option entry; help states `single-scene input override` and `exactly one --scene N required`. |
| One authority | **PASS** — graph review shows `resolve_scene_extraction_file()` is the shared caller seam for raw editor lookup, server source candidates, and CLI exact-file validation; it delegates the eligible set and scaffold shadowing to `scene_extraction_files()`. |
| Read-only source handling | **PASS** — resolver/source-state paths use directory scans and UTF-8 reads only; no raw or smoothed write/copy/rename path was added. The only existing source write remains the raw editor PUT route. |
| Command gate | **PASS** — `_build_narrate_cmd()` still has its pre-feature raw-directory command shape and contains no `--scene-extraction-file`; T015 remains test-gated. |
| Diff hygiene | **PASS** — `rtk git diff --check`. |

Foundation is accepted. User-story implementation may begin.

## T018/T023 — User Stories 1 and 2 GPT-5.6 acceptance gate

| Gate | Result |
|---|---|
| US1 command/CLI/API set | **PASS** — 6 focused preference, live re-resolution, exact-content, unchanged-source, and SSE handoff checks; the complete `test_editor_pipeline.py` + `test_sd_narrate.py` set is **124 passed**. |
| Editor API projection | **PASS** — all six `TestExtractionDetailNarrateSource` states plus the API-to-SSE handoff are **7 passed**. Direct route calls remain the bounded workaround for the baseline Starlette `TestClient` stall. |
| Frontend build | **PASS** — `vue-tsc -b && vite build`; 174 modules transformed after the responsive source banner was added. |
| Quickstart sections 2, 3, and 5 | **PASS** — rerun as three disposable acceptance fixtures under `/tmp/cg018-us12-R9wExX5j/pytest`; **3 passed**. |

### Exact source handoff and display evidence

- With both layers present, the API's exact `active_file` was
  `/tmp/cg018-us12-R9wExX5j/pytest/test_narrate_sse_forwards_smoo0/summaries/session1/scene_extractions_smoothed/01_scene_one.md`.
  The source banner renders `narrateSource.smoothed.directory`, its
  present/not-present state, `narrateSource.active_file`, and the server
  message without reconstructing any path in the browser. Long paths wrap at
  desktop and narrow breakpoints rather than being clipped.
- The immediately subsequent Narrate route re-resolved disk and forwarded
  that same absolute path as the value of `--scene-extraction-file`; its base
  `--scene-extractions` value remained the configured raw directory. The
  focused integration assertion compares the command argument directly to
  the API-returned `active_file`.
- The distinguishable CLI fixture used raw
  `/tmp/cg018-us12-R9wExX5j/pytest/test_exact_scene_input_reaches0/scenes/01_scene_one.md`
  and smoothed
  `/tmp/cg018-us12-R9wExX5j/pytest/test_exact_scene_input_reaches0/scenes_smoothed/01_scene_one_smoothed_exact.md`.
  `EXACT_SMOOTHED_BEAT` appeared once in the selected prompt and once in the
  consistency knowledge sources; `RAW_ONLY_BEAT` was absent. Assertions
  confirmed both files' bytes and nanosecond mtimes were unchanged after
  narration.

### Absent/present/live-change evidence

- The live-change fixture began with the fixed expected directory
  `/tmp/cg018-us12-R9wExX5j/pytest/test_projection_re_reads_disk_0/summaries/session1/scene_extractions_smoothed`
  absent and scene 1 on **Raw fallback**.
- Adding eligible `01_scene_one_added.md` changed a fresh detail projection to
  **Smoothed** and that exact file. Renaming it to a non-eligible `.txt`
  changed only scene 1 back to **Raw fallback**; adding and removing another
  eligible file produced the same refreshed fallback. No config edit or
  server restart occurred.
- `SessionDocEditor.vue` refreshes the same projection on scene selection,
  Reload, post-extraction, and immediately before Narrate. Therefore the
  visible banner and the server-boundary command each consume fresh
  server-owned disk state without requiring a page reload.

User Stories 1 and 2 are accepted.

## T029 — User Story 3 GPT-5.6 acceptance gate

| Gate | Result |
|---|---|
| Resolver/command edge matrix | **PASS** — 7 passed (`test_editor_pipeline.py -k t024`). |
| Exact-file CLI/refusal matrix | **PASS** — 10 passed (`test_sd_narrate.py -k exact_scene_input`). |
| Detail and Narrate route states | **PASS** — 13 passed (detail projection, API-to-command handoff, and `TestNarrateRouteUs3SourceEdges`). |
| Frontend build | **PASS** — `vue-tsc -b && vite build`; 174 modules transformed. |

Quickstart sections 4, 6, and 7 were exercised with disposable fixtures; the
partial command fixtures remain inspectable under
`/tmp/cg018-us3-orqy9H3C/pytest`.

### Per-scene and refusal evidence

- In
  `/tmp/cg018-us3-orqy9H3C/pytest/test_t024_partial_smoothed_sce0/20260414`,
  raw scenes 1–3 coexist with only smoothed scenes 1 and 3. Command assertions
  prove scenes 1 and 3 each forward their own exact smoothed file while scene
  2 retains the raw directory and has no `--scene-extraction-file` argument.
- A differing smoothed slug (`12_name_from_an_old_plan.md`) still resolves by
  exact frontmatter scene identity, and a `.scaffold.md` sibling shadows its
  plain source. Empty/artifact-only smoothing retains raw fallback.
- Smoothed-only detail keeps top-level raw `exists=false`/empty content while
  `narrate_source.available=true`; its route uses the smoothed parent as the
  required base plus the exact smoothed file.
- Invalid UTF-8 smoothed input with readable raw present returns
  `Narrate source unreadable: <exact smoothed path>` and launches no
  subprocess. Neither-source returns `No Narrate source found` with both the
  resolved smoothed and configured raw directories and also launches no
  subprocess. CLI validation separately refuses nonexistent, non-file,
  invalid-UTF-8, ineligible, mismatched, missing-scene, and multi-scene exact
  inputs before either model path is called.

### Dirty-buffer and no-write evidence

- The built frontend preserves the raw textarea buffer during source refresh.
  Its Narrate preflight calls `saveExtraction()` only under the explicit
  `source.active_layer === 'raw' && rawExtractionDirty` guard. Smoothed,
  unreadable, and missing states cannot enter that branch; unavailable states
  return before SSE, and smoothed-active state proceeds without a PUT.
- Raw-only compatibility remains intact: a dirty raw buffer is saved and the
  source projection refreshed before a raw Narrate run. Raw editing controls
  remain tied to raw `hasExtraction`, while Narrate is tied independently to
  server-returned source availability, which enables the smoothed-only case.
- The distinguishable exact-input test rechecked both source files after the
  run and found their bytes and nanosecond mtimes unchanged. The server
  resolver, detail route, and command builder add no source write/copy/rename
  operation; live removal simply recomputes to raw fallback.

The T027 server and T028 UI audits required no further edits because their
state transitions were already implemented and locked by T024–T026 plus the
earlier UI slices. User Story 3 is accepted.

## T032 — Targeted cross-cutting regression gate

| Command set | Result |
|---|---|
| `test_smoothed_claim.py`, `test_retrieve_render_isolation.py`, `test_editor_pipeline.py`, `test_editor_verify_routes.py`, `test_sd_narrate.py` | **PASS** — 349 passed. |
| `test_editor_service_integration.py` | **BASELINE-CONSTRAINED** — the first 13 direct source/detail/Narrate tests passed, then the unchanged `TestGetEditorConfig::test_returns_grouped_shape` Starlette `TestClient` call stalled. Faulthandler again showed the main thread in `starlette.testclient`/HTTPX waiting on AnyIO's blocking portal, matching T003 exactly; the bounded run was interrupted. |
| Non-Narrate focused additions | **PASS** — 3 pipeline boundary tests and 1 Verify Quotes raw-path test passed independently. |

No targeted regression failure was added. The only incomplete portion is the
same environment-level `TestClient` stall recorded before implementation;
feature API coverage uses direct route calls and is fully green.

## T033 — Full-suite, build, and diff gate

| Gate | Result |
|---|---|
| `rtk proxy pytest tests/` | **BASELINE-EQUIVALENT COLLECTION ERROR** — 4,562 items collected with one skipped, then the same `tests/test_mcp_server.py` import failed because optional package `mcp` is absent (`ModuleNotFoundError: No module named 'mcp'`). As at T003, no tests execute in the required unmodified full-suite command. |
| Supplemental suite with only `test_mcp_server.py` excluded | **BASELINE-CONSTRAINED** — progressed to the editor-service region, then stopped advancing at the known Starlette `TestClient` stall. A first-failure probe also exposed `test_assemble_audit_comment.py::test_audit_comment_stripped_and_source_unmodified` failing because a directly executed `session_doc/assemble.py` cannot import `campaignlib`; the exact test independently reproduces in the primary `main` checkout, so it is not introduced by this worktree. |
| `rtk npm run build` from `frontend/` | **PASS** — `vue-tsc -b && vite build`; 174 modules transformed. |
| `rtk git diff --check` | **PASS**. |

The required full-suite result has no new failure versus T003. Feature-owned
and adjacent targeted coverage is green (T032), while the two supplemental
environment failures were either recorded before implementation or reproduced
unchanged on `main`.

## T034 — Complete quickstart matrix

| Section | Result and evidence |
|---|---|
| 0. Worktree/baseline | **PASS** — current branch is `018-prefer-smoothed-extractions`; all implementation and validation ran in the required worktree. T003/T033 record the before/after baseline. |
| 1. Resolver/CLI | **PASS** — the worktree-local `python -m session_doc.sd_narrate --help` contains exactly one canonical `--scene-extraction-file FILE` entry and the exactly-one-scene rule. Resolver, smoothed-claim, command, and CLI tests are included in the 349-pass T032 set. |
| 2. Editor API | **PASS** — 13 direct detail/Narrate route cases verify full candidate fields, fixed absent directory, custom raw path, active-file identity, and refusal-before-subprocess behavior. |
| 3. Both layers | **PASS** — the exact smoothed API path equals the subsequent argv path; distinguishable smoothed content reaches the prompt once, raw content does not, and both source byte/mtime pairs remain unchanged. The compiled banner directly renders the same server fields. |
| 4. Partial smoothing | **PASS** — disposable raw scenes 1–3 plus smoothed scenes 1/3 prove exact smoothed selection for 1/3 and raw fallback for 2, including slug drift and scaffold precedence. |
| 5. Live changes | **PASS** — fresh detail reads transition raw → newly added smoothed → raw after rename/removal, and the Narrate builder independently re-resolves the same disk state at invocation. |
| 6. Smoothed-only/blocked | **PASS** — smoothed-only is available while raw editor content is absent; invalid UTF-8 smoothed blocks with raw present; neither-source names both directories; blocked cases never launch a subprocess. |
| 7. Dirty raw | **PASS (compiled state-flow inspection)** — source refresh preserves the raw buffer; only refreshed raw-active + dirty invokes PUT; smoothed-active and blocked paths never auto-save. The exact-input source immutability test supplies the disk byte/mtime proof. |
| 8. Non-Narrate | **PASS** — four T031 tests pin raw builder paths, raw detail/previous reads, raw PUT/reviewed markers, Verify Quotes behavior, and absence of the exact-file flag. |
| 9. Final gates | **PASS WITH BASELINE EXCEPTIONS** — targeted tests and frontend build pass; diff check passes; required full suite stops at the unchanged missing optional `mcp` dependency. |

The repository has no frontend test runner or browser binary, so UI-specific
steps were validated through the production TypeScript/Vite build plus direct
inspection of the compiled source-state branches and their server-backed
route fixtures. No UI claim above relies on a browser-derived path or layer.

The first literal `rtk sd_narrate --help` probe resolved to
`/home/kroussos/.venvs/main/bin/sd_narrate`, an editable entrypoint bound to
the primary checkout, so it correctly lacked this unmerged worktree change.
The quickstart command was corrected to invoke the worktree-local module; that
help output contains the new option and is the relevant branch validation.

## T035 — Final constitution and scope audit

The current worktree was re-indexed after implementation. Graph review finds
`resolve_scene_extraction_file()` as the single scene-association authority
called by the CLI exact-file validator and both raw/source-state server seams.
Production search finds `--scene-extraction-file` in exactly three symbols:
the `sd_narrate` parser, its option-specific refusal helper, and
`_build_narrate_cmd()`. No other command builder contains it.

| # | Principle | Final verdict | Diff evidence |
|---|---|---|---|
| I | Disk is Truth, the Model is a Draft | **PASS / strengthened** | Detail refresh and Narrate invocation each probe current disk; live add/remove tests pass. No active choice is persisted. |
| II | The Human Checkpoint is Non-Negotiable | **PASS** | The GM-created smoothed file and exact server-selected path are visible before Narrate; selection is deterministic and content is not edited. |
| III | Retrieval and Render are Separated | **PASS** | No retrieval implementation changed; `test_retrieve_render_isolation.py` is in the 349-pass targeted gate. |
| IV | Verbatim is Sacred | **PASS** | Resolution and exact loading are read-only; smoothed-claim tests pass; invalid preferred text refuses rather than substituting raw. |
| V | One Seam per Boundary | **PASS** | Shared `session_doc.io` eligibility/resolution feeds CLI and server. Vue renders the server projection and has no path-selection implementation. |
| VI | CLI is the Engine, UI is a Face | **PASS** | `sd_narrate` owns exact-file validation/consumption; the router forwards argv and SSE; the UI performs no prompt/render work. |
| VII | Extract Once, Synthesize Deliberately | **PASS** | No extraction/synthesis stage was added or repeated. Narrate consumes one existing per-scene source. |
| VIII | State is Discoverable | **STRENGTHENED** | Banner exposes expected smoothed directory, directory state, layer/status, exact ready path, and server message, including narrow layouts. |
| IX | The UI Mechanizes; Claude Converses | **PASS** | UI changes are inspection, raw editing, refresh, and invocation mechanics only; smoothing remains external file-backed work. |
| X | Selection is Explicit; There is No Silent “All” | **PASS** | Exact-file mode requires one positive in-range `--scene`; per-scene partial tests prove no compact-list substitution; missing/unreadable refuses. |
| XI | Parity is Bidirectional; Every CLI Capability Has a Face | **PASS** | The canonical CLI option is documented and the Session Doc UI shows/invokes the same server-selected exact path. |
| XII | One Spelling per Option; No Configuration Drift | **PASS** | Help exposes one `--scene-extraction-file`; production search finds no alias or second selector; no stored-config field was added. |
| XIII | Breaking State Changes Migrate Out of Band | **PASS / not applicable** | Changed files contain no config model, schema, migration, workspace-layout, or filename-convention change. No migration is needed. |

### Scope and mutation verdict

- Tracked source changes are limited to the planned three Python modules, two
  Vue components, focused tests, and the CLI guide. Feature artifacts are
  under `specs/018-prefer-smoothed-extractions/`.
- No persisted config, schema, migration, dependency, or lockfile changed.
- No new source-copy, source-rename, source-delete, or source-write operation
  exists. The pre-existing raw editor PUT remains raw-only; narration output
  writes remain output-only. Byte/mtime assertions prove Narrate leaves both
  input layers untouched.
- T031 proves extraction, Verify Quotes, Plan & Check, consistency, raw editor
  reads/PUT, and reviewed markers preserve their raw-configured semantics.
- `git diff --check` and the production frontend build pass. The required full
  suite has only the T003 baseline collection blocker; all feature and adjacent
  targeted tests pass.

**Final audit verdict: PASS.** All thirteen principles hold, no migration or
configuration change is present, and the implementation remains Narrate-only.
