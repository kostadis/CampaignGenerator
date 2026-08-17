# Research: Optional Force for Scene Re-Extraction

All items below were resolved during spec authoring by reading the actual
call chain (`SessionDocEditor.vue` → `scene_editor.py` → `campaignlib/scenes.py`
→ `scene_extract.py`) before `/speckit-specify` wrote the spec. No
`NEEDS CLARIFICATION` markers were carried into this plan, so this document
records the findings rather than open questions.

## D1: Where does the hardcoded force actually live?

**Decision**: The bug is entirely in one frontend call site.
`frontend/src/views/session/SessionDocEditor.vue:473` (`runExtract()`) calls
`connectSSE('/api/editor/extract?force=1', ...)` unconditionally.

**Rationale**: Traced every layer down from the button:
- `server/routers/scene_editor.py:1449` `api_extract(request, force: int = 0, ...)`
  — the query param **already defaults to `0`**. The route does not force
  anything; it forwards whatever the caller sent.
- `server/routers/scene_editor.py:1014` `_build_reextract_cmd(..., force: bool = False)`
  — already appends `--force` to the CLI invocation *only* when `force=True`
  is passed in; the default path already omits it.
- `campaignlib/scenes.py:266` `run_scene_extraction()` — already skips a
  scene whose output file exists unless `force=True` (`if out_file.exists()
  and not force: ... continue`), already snapshots to `.prev` and clears the
  reviewed marker only in the force branch.
- `session_doc/scene_extract.py` — the CLI's `--force` flag
  (`parser.add_argument("--force", ...)`, line ~303) and its own
  skip-if-exists default (line ~106) are already correct and match the
  engine.

So every layer from the FastAPI route down to the CLI already implements
"default = skip existing, `--force` = redo everything" — exactly the
behavior issue #323 asks for. The only place that behavior is short-circuited
is the frontend hardcoding the query string to `force=1` on every click.

**Alternatives considered**:
- *Add a new backend flag or CLI mode* — rejected, nothing is missing at
  that layer; adding one would violate Constitution VI (CLI is the Engine)
  by growing a second implementation of behavior the engine already has.
- *Add per-scene selection* (checkboxes per scene, `--only`/`--scenes` CLI
  flag) — rejected as out of scope; issue #323's agreed fix direction is a
  session-wide Force toggle, and `spec.md`'s Assumptions section already
  records per-scene selection as a separate, larger feature.

## D2: Does `--force`/skip-if-exists already report per-scene outcome?

**Decision**: Yes — reuse the existing print statements verbatim; no new
reporting mechanism is needed to satisfy spec FR-005.

**Rationale**: `campaignlib/scenes.py` already prints
`"  [{i}/{total}] Skipping (already exists): {out_file.name}"` on the skip
path and `"  [{i}/{total}] {action}: {name}"` (`action` = "Re-extracting" or
"Scene-extracting") on the generate path. Both are streamed to the frontend
today via the existing SSE pipe (`narrationOutput.value += text`), so the
GM already sees this — it's just been meaningless while `force=1` was
hardcoded, because every scene always took the "generate" path.

**Alternatives considered**: A structured per-scene JSON summary appended
after the run — rejected as unnecessary scope; the existing streamed text
already satisfies FR-005 once the default path is actually reachable.

## D3: Is the "run knobs" record (for observability) already force-aware?

**Decision**: Yes. `api_extract` already builds
`knobs={"batch": _editor_resolved_batch(request, cfg), "force": bool(force)}`
(scene_editor.py:1468) before kicking off the run. Once the frontend stops
hardcoding `force=1`, this record starts reflecting the GM's actual choice
with no further change.

**Rationale**: Confirms FR-006/FR-007 (force is a fresh, visible, per-run
choice) has a place to be recorded for later inspection without new backend
work.

## D4: What UI convention already exists for "toggle next to an action button"?

**Decision**: Follow the existing `replace-toggle` pattern in
`frontend/src/views/prep/ConnectionGraph.vue:387-390`:
```html
<label class="replace-toggle" title="If unchecked, results merge into existing connections.json">
  <input type="checkbox" v-model="replaceExisting" />
  Replace cache (don't merge)
</label>
```
A checkbox `<label>` immediately after the action button, with a `title`
tooltip stating what the *unchecked* (default/safe) state does.

**Rationale**: This is the same shape of decision — "the default merges/
skips; checking this box makes the action destructive/total" — already
solved once in this codebase. Reusing it satisfies spec FR-002 (visible,
distinct control) and FR-007 (the interface states what a Force-enabled run
will do) without inventing new UI vocabulary. It's a plain reactive
`ref<boolean>`, not a `v-model` into `EditorConfigDrawer`'s persisted config
props — matching spec Assumption "not a persistent session or user
preference."

**Alternatives considered**: A confirmation modal on click when Force is on
— rejected per spec Assumptions (matches the no-extra-confirmation pattern
already used elsewhere in the editor); the checkbox's own persistent visible
state plus its label/tooltip is the confirmation.

## D5: Any other call site or test hardcoding `force=1`/`--force`?

**Decision**: No. `grep -rn "force=1\|editor/extract"` across `frontend/src`
and `server/routers/scene_editor.py` turns up exactly the one call site in
`runExtract()`, plus the doc comment describing it. No test in
`tests/test_editor_pipeline.py` or elsewhere pins the `force=1` default, so
none needs updating for the default flip — but the default's absence of
coverage means Phase 2 should add one.

**Rationale**: Confirms scope: this is a single-file frontend fix (plus a
one-line template addition for the checkbox) with a backend test gap to
close, not a multi-site migration.

## Technology summary (no NEEDS CLARIFICATION remaining)

| Aspect | Resolution |
|---|---|
| Language/Version | Python ≥3.9 (backend/CLI, per `pyproject.toml`); TypeScript + Vue 3.5 / Vite 8 (frontend) |
| Primary Dependencies | FastAPI (existing `/api/editor/extract` SSE route); Vue 3 reactive `ref` + existing `connectSSE` helper — no new dependency |
| Storage | Filesystem only — per-scene `.md` files, `.prev` snapshots, `.reviewed` markers under `scene_extractions_dir`; on-disk semantics unchanged |
| Testing | pytest (`tests/test_editor_pipeline.py` et al.) for the backend query-param default and knob recording; frontend has no automated test harness in this repo (no `*.test.*`/`*.spec.*` files, no test script in `package.json`) — verified manually via dev server per `CLAUDE.md`'s UI-change rule |
| Target Platform | Existing local FastAPI + Vue SPA (Session Doc Editor), served via `startup` |
| Project Type | Web application (existing `frontend/` + `server/` pair) |
| Performance Goals | N/A — the feature *reduces* LLM calls; no new performance target |
| Constraints | Do not modify `campaignlib/scenes.py::run_scene_extraction` or `session_doc/scene_extract.py`'s force/skip logic — already correct (Constitution VI); the fix only changes what value the UI sends for the already-optional `force` parameter |
| Scale/Scope | One frontend call site + one new checkbox control; zero required backend logic changes; one backend test addition for the default-off path |
