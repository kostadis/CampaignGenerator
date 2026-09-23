# Quickstart: Validating Bundled Narration

**Feature**: 022-bundle-narration | **Date**: 2026-09-05

Run these checks after implementation. The contracts define exact behavior; this guide proves it end to end without duplicating implementation code.

## Prerequisites

Work from the feature worktree so Python cannot silently import the main checkout:

```bash
cd /home/kostadis/src/CampaignGenerator/workrees/narration-bundle
python -c "import campaignlib, pathlib; print(pathlib.Path(campaignlib.__file__).parent)"
```

The printed path must begin with `/home/kostadis/src/CampaignGenerator/workrees/narration-bundle`.

Install this checkout into the active development environment when exercising the console script or web server:

```bash
uv pip install -e . --python "$VIRTUAL_ENV/bin/python"
```

For a live comparison, choose a session with a human-reviewed `session-summary.md`, `scene_extractions/`, `narration/plan.md`, party/player declarations, voice/examples, and at least two plan scenes. Use a backend/model whose output capacity can hold the projected bundle.

## Scenario 1 — Focused automated verification

```bash
python -m pytest \
  tests/test_narration_bundle_split.py \
  tests/test_narration_bundle_cli.py \
  tests/test_narration_bundle_report.py \
  tests/test_sd_narrate.py \
  tests/test_narrate_input_delivery.py \
  tests/test_narrate_template_contract.py \
  tests/test_editor_pipeline.py \
  tests/test_editor_service_integration.py \
  tests/test_session_editor_config_service.py -q
```

**Expect**: all tests pass. In particular, the bundle tests prove one backend call for N scenes, exact prompt delivery, deterministic reconciliation, safe partial writes, mixed raw/smoothed inputs, and run-report-driven sidecars.

## Scenario 2 — Existing narration remains unchanged

Run the existing regression subset:

```bash
python -m pytest tests/test_sd_narrate.py tests/test_narrate_input_delivery.py -q
```

Required assertions:

- an unadorned N-scene run still makes N ordered live calls;
- provider `--batch` without `--batch-scenes` still makes N ordered one-item batch calls;
- `--scene N` still writes only scene N;
- sequential `--narrator NAME` keeps its current filter-then-index behavior, while combining it with `--batch-scenes` refuses before client creation and directs the user to full-plan `--scene` indices;
- the generated final line still becomes the next sequential scene's handoff;
- existing filenames, frontmatter, warnings, and narration settings are unchanged.

## Scenario 3 — One explicit bundle, one model exchange

Use absolute campaign paths while invoking the feature worktree's installed CLI:

```bash
sd_narrate /absolute/session/session-summary.md \
  --plan /absolute/session/narration/plan.md \
  --scene-extractions /absolute/session/scene_extractions \
  --per-scene-output /tmp/cg-narration-bundle \
  --party /absolute/campaign/docs/party.md \
  --party-config /absolute/campaign/config/party.yaml \
  --players-config /absolute/campaign/config/players.yaml \
  --voice-dir /absolute/campaign/voice \
  --examples /absolute/campaign/examples \
  --batch-scenes --batch-max-tokens 32000 \
  --backend claude-code
```

**Expect before generation**: the banner lists every selected index/name/narrator, source, destination, replacement state, projected output, ceiling, content mode `bundle`, provider Batch state, and `Model exchanges: 1`.

**Expect after generation**: one individual `session_doc_scene_NN_<slug>.md` per selected scene; the report says `exchange_count: 1`; no combined canonical narration file; no automatic assembly or approval.

Repeat with an explicit subset:

```bash
sd_narrate /absolute/session/session-summary.md \
  --plan /absolute/session/narration/plan.md \
  --scene-extractions /absolute/session/scene_extractions \
  --per-scene-output /tmp/cg-narration-subset \
  --batch-scenes --scene 2 5 --batch-max-tokens 32000 \
  --backend claude-code
```

**Expect**: exactly scenes 2 and 5 are requested and written, with original plan indices. No other narration file is touched.

## Scenario 4 — Content bundling and provider Batch remain distinct

Automated fake-backend tests must demonstrate this matrix:

| Invocation | Expected call path |
|---|---|
| sequential, no `--batch` | N `stream_api` calls |
| sequential + `--batch` | N `run_single_batch` calls |
| `--batch-scenes` | one `stream_api` call |
| `--batch-scenes --batch` | one `run_single_batch` call |

The CLI banner and JSON report must show content mode and provider pricing mode as separate fields in every row.

## Scenario 5 — Capacity refusal is honest

Run a fixture whose summed estimate exceeds a deliberately low ceiling:

```bash
python -m pytest tests/test_narration_bundle_cli.py -q -k 'bundle and ceiling'
```

**Expect**: exit `1`, zero client construction/calls, zero narration writes, and guidance to raise the ceiling, select fewer scenes, or use sequential mode. No automatic grouping or fallback is permitted.

## Scenario 6 — Partial and unreconcilable responses

```bash
python -m pytest tests/test_narration_bundle_split.py tests/test_narration_bundle_cli.py -q -k 'partial or incomplete or absent or unreconcilable or order or mismatched_end'
```

**Expect for a valid truncated response**: K closed non-empty scenes are written, incomplete/absent scenes are untouched and named, report status is `partial`, and exit is `3`.

**Expect for unknown, duplicate, nested, mismatched-BEGIN/END, name-mismatched, or out-of-order markers**: no scene from the exchange is written, report status is `unreconcilable`, and exit is `4`.

**Expect for a structurally valid zero-write response**: every empty/incomplete/absent scene is named, existing files remain untouched, report status is `partial`, and exit is `3`.

Then rerun only the missing indices with `--batch-scenes --scene ...` or use the existing current-scene Narrate button. Already successful files remain untouched.

## Scenario 7 — Mixed raw and smoothed editor sources

```bash
python -m pytest tests/test_editor_pipeline.py tests/test_editor_service_integration.py -q -k 'narrate and bundle and source'
```

Use a fixture where scenes 1 and 3 have preferred smoothed files and scene 2 has only raw input.

**Expect**: the copyable command contains all three explicit indices, repeated exact-file overrides for scenes 1 and 3, and the raw directory for scene 2. Bundle preflight refuses before subprocess start if any chosen source becomes missing or unreadable.

The JSON report labels these sources `override`, `base`, and `override`; raw/smoothed labels stay in editor-owned presentation because the general CLI accepts arbitrary eligible paths.

## Scenario 8 — Editor interaction

```bash
cd frontend
npm run build
npm run test:e2e -- session-narration-bundle.spec.ts
```

In the Session Doc Editor:

1. Confirm the current-scene `Narrate` button still works.
2. Open `Narrate all in one call…`.
3. Confirm the dialog lists every plan index, name, narrator, count, and `new`/`will replace` state.
4. Cancel and verify no request starts.
5. Reopen and run; inspect the first SSE command event for `--batch-scenes --scene 1 2 ...` and repeated source overrides.
6. Confirm success refreshes all scene statuses.
7. Feed the e2e fixture exit `3`; confirm the page says partial, names missing scenes, refreshes all statuses, and retains the current-scene recovery action.

## Scenario 9 — Representative quality gate

Generate the same reviewed session twice into separate temporary directories, once sequentially and once bundled, with identical backend, model, and narration settings.

Compare:

- identical filename and YAML-frontmatter sets;
- each file's plan index, scene name, and narrator assignment;
- quoted speech against that scene's extracted source, with no invented or cross-scene quote;
- narrator-specific voice and examples, especially across a narrator change;
- continuity between adjacent section endings/openings;
- coverage and prose depth in the final two scenes versus the early scenes;
- absence of protocol markers and absence of automatic assembly/approval.

This is a human release gate. A visible voice-flattening, quote-attribution, scene-leakage, or tail-compression regression blocks release even when structural tests pass.

## Structural and full regression

```bash
cd /home/kostadis/src/CampaignGenerator/workrees/narration-bundle
python -m pytest \
  tests/test_retrieve_render_isolation.py \
  tests/test_no_prefix_identity.py \
  tests/test_layering.py \
  tests/test_backend_seam_guardrails.py -q

python -m pytest tests/ -q
cd frontend && npm run build
```

**Expect**: all checks pass. The structural guards confirm that bundling did not move model calls outside the existing boundary or mix retrieval into narration rendering.
