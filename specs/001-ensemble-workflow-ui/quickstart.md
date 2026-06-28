# Quickstart / Validation Guide: Ensemble Grounding-Doc Workflow UI

This guide proves the feature end-to-end. It assumes a campaign workspace with chapter files already prepared (the upstream spelling/known-names pass is out of scope here — see `docs/cli/ensemble_workflow.md`). Details of flags and endpoints live in `contracts/cli.md` and `contracts/api.md`; the data model is in `data-model.md`.

## Prerequisites

- A campaign workspace with `docs/chapters/chapter_*.md`.
- `ANTHROPIC_API_KEY` set (for the Anthropic synthesis path / regression check).
- `OPENROUTER_API_KEY` set (for the OpenRouter path).
- For the DGX path: at least one reachable Spark endpoint (`/spark-status`); optional if validating only Anthropic + OpenRouter.
- Server + frontend running via `./startup`.

---

## Validation 1 — Seam: OpenRouter routes through `make_client` (Principle V)

```bash
python -m pytest tests/test_openrouter_seam.py -q
```

**Expected**: `make_client(backend="openrouter")` returns the OpenRouter client; a missing `OPENROUTER_API_KEY` raises a clear error; no module outside `campaignlib/api` imports the OpenRouter client. (Maps to FR-007, FR-018; R1.)

## Validation 2 — Regression: existing Anthropic path unchanged (FR-015, SC-006)

```bash
# Old per-tool path and the synthesis scripts with NO new flags must be byte-identical.
python -m pytest tests/                       # full suite incl. test_retrieve_render_isolation.py
# Spot check: synthesise_world_state.py with no --backend builds the same command/output as before.
```

**Expected**: full suite green; the isolation guard passes (router added no retrieval/render mixing); default synthesis still hits Anthropic.

## Validation 3 — Stage status is disk-derived (FR-002, FR-017)

```bash
curl -s "http://localhost:8000/api/ensemble/status?campaign_dir=$PWD&chapters=docs/chapters/chapter_*.md" | python -m json.tool
```

**Expected**: with no prior run, `extract` is `current_stage`. After files appear under `docs/ensemble/per_chapter/*/merged.json` (Validation 5), the same call — with no server restart — reports `extract: complete`. Confirms no browser/server-cached state.

## Validation 4 — Walk the pipeline from the UI, no CLI typing (US1, SC-001, SC-002)

1. Open the app → navigate to **Ensemble Workflow** (`/ensemble`). Confirm it is a distinct page from **Grounding Docs** (`/grounding`), which is unchanged (US4).
2. **Setup** step: set chapter glob and pick a backend for *extract* and (independently) for *synthesize* (US2).
3. **Extract** step: Run → watch SSE progress stream → on completion, the page lists per-chapter artifacts.
4. Reload the page → Extract shows **complete** (disk-derived).

**Expected**: an operator who has not read the workflow doc reaches the synthesis stage without typing a command (SC-002).

## Validation 5 — Per-stage backend mix, incl. OpenRouter with local box down (US2, SC-003, SC-008)

```bash
# Simulate local hardware unreachable, then drive extraction via OpenRouter from the UI's Extract step.
# (Equivalent CLI the UI runs — proves CLI-first, FR-016:)
CG_BACKEND=openrouter python ensemble_batch.py \
  --chapters 'docs/chapters/chapter_*.md' --per-chapter-dir docs/ensemble/per_chapter \
  --out docs/ensemble/merged.json --model anthropic/claude-sonnet-4
```

Then synthesize on a *different* backend from the UI's Synthesize step (e.g. Anthropic):

```bash
python synthesise_world_state.py --backend anthropic \
  --dossiers 'docs/ensemble/merged_dossiers/*.md' --dossier-min-facts 10 \
  --output docs/world_state_draft.md
```

**Expected**: extraction completes against OpenRouter with the local box down (SC-003); each artifact records the backend that produced it (FR-008, SC-008); a full refresh is achievable with mixed backends.

## Validation 6 — Human checkpoints block auto-advance (US3, Principle II)

1. After Extract, the UI presents the **scope-review** gate (`bundle --list`) and does **not** auto-run aggregation.
2. Edit `docs/ensemble/aliases.json` from the CLI/chat → return to the UI → the alias-correction gate reflects the edited file **without** re-running any LLM step (FR-012).
3. Proceed to Synthesize → reach the **diff-before-promote** gate.

**Expected**: aggregation never consumes extraction output until the operator confirms scope/alias (Principle II); the gate's interchange files are visible to CLI and chat alike.

## Validation 7 — Drafts only; promotion is explicit (FR-013, SC-005)

```bash
# Synthesis writes a draft, never the live doc.
ls docs/world_state_draft.md          # exists after synthesize
git status docs/world_state.md        # live doc UNCHANGED by synthesis
# Promotion is the single explicit action:
curl -s -X POST http://localhost:8000/api/ensemble/promote \
  -H 'Content-Type: application/json' \
  -d '{"draft":"docs/world_state_draft.md","live":"docs/world_state.md"}'
```

**Expected**: the synthesis step never modifies a live grounding doc; only the explicit promote action does. A `PUT /api/ensemble/file` targeting a live doc is rejected. Zero automatic live-doc overwrites across all runs (SC-005).

## Validation 8 — Sub-Sonnet synthesis warning (FR-014, R6)

Pick a known-weak model (e.g. a small open model id) for the **synthesize** stage and run.

**Expected**: the stream includes a non-fatal warning that the model is below the assumed synthesis capability; the run still proceeds (warn, not block). Extraction with the same weak model produces no such warning.

---

## Done-when

- Validations 1–8 pass.
- `/grounding` behaves identically to before (US4, SC-006).
- A full grounding-doc refresh is completable entirely from `/ensemble` (SC-001), including with the local box unreachable by selecting OpenRouter (SC-003).
