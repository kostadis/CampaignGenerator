# Quickstart: Validate Smoothed-First Narration Input

**Feature**: `018-prefer-smoothed-extractions` | **Date**: 2026-08-28

This guide proves the shared resolver, CLI exact-file handoff, editor API, and
visible UI behavior end to end. See [`data-model.md`](./data-model.md),
[`contracts/cli.md`](./contracts/cli.md), and
[`contracts/editor-api.md`](./contracts/editor-api.md) for the rules; this
guide does not duplicate their full definitions.

## 0. Worktree and baseline gate

Run every command from the user-required feature worktree, never the primary
checkout:

```bash
cd /home/kroussos/src/CampaignGenerator/worktrees/018-prefer-smoothed-extractions
rtk git branch --show-current
rtk git status --short
```

Expected branch: `018-prefer-smoothed-extractions`.

Before the first implementation edit, GPT-5.6 records the baseline:

```bash
rtk pytest tests/test_editor_pipeline.py tests/test_sd_narrate.py tests/test_editor_service_integration.py tests/test_smoothed_claim.py
rtk pytest tests/
```

From the worktree's `frontend/` directory:

```bash
rtk npm run build
```

Any pre-existing full-suite failure is recorded with its exact test name.
Implementation may not add another failure.

## 1. Shared resolver and CLI contract

Run the focused CLI/I/O tests created for the feature:

```bash
rtk pytest tests/test_sd_narrate.py tests/test_smoothed_claim.py tests/test_editor_pipeline.py
rtk proxy python -m session_doc.sd_narrate --help
```

Expected:

- The worktree-local module's `--help` contains exactly one
  `--scene-extraction-file FILE` entry and says
  it requires exactly one `--scene N`.
- Raw-only invocations retain their existing argument shape and behavior.
- A partial smoothed directory can supply the exact requested scene without
  list-position fallback.
- A mismatched, absent, or unreadable exact file refuses before a model call.
- Scaffold-over-plain precedence and ignored sibling artifacts remain green.

The focused tests must cover this matrix:

| Raw scene | Smoothed scene | Expected input |
|---|---|---|
| present | present/readable | exact smoothed file |
| present | absent | raw file |
| absent | present/readable | exact smoothed file |
| absent | absent | refuse; name both checked directories |
| present | present/unreadable | refuse; name smoothed file; no raw fallback |

## 2. Editor API projection

Start the feature-worktree server against a disposable campaign/session. Do
not use a campaign's only copy for the unreadable/missing scenarios below.

With a scene selected in that session:

```bash
rtk curl -s http://localhost:5000/api/editor/extraction/1
```

Format the response with the local JSON tooling if desired:

```bash
rtk summary curl -s http://localhost:5000/api/editor/extraction/1
```

Expected in `narrate_source`:

- `smoothed.directory` is the absolute current-session
  `scene_extractions_smoothed` path even when it does not exist.
- `raw.directory` is the resolved configured raw path, including a custom
  override.
- `active_file`, `active_layer`, `status`, and `available` follow the matrix in
  section 1.
- Existing top-level `exists` and `content` still describe the raw editor
  file; they do not change meaning when smoothed is active.

Run the route/command regressions:

```bash
rtk pytest tests/test_editor_pipeline.py tests/test_editor_service_integration.py
```

Expected: the source path in the response is the exact file forwarded by the
subsequent Narrate command, and no extraction/verify/plan/consistency builder
acquires the exact-file option.

## 3. UI visibility — both layers present

Prepare one disposable scene with distinguishable raw and smoothed content:

```text
<session>/scene_extractions_new/01_scene.md
<session>/scene_extractions_smoothed/01_scene.md
```

1. Open **Session Doc** and select scene 1.
2. Confirm the textarea still shows the configured raw extraction.
3. Confirm the Narrate-source display shows:
   - the resolved smoothed directory;
   - **Smoothed** as active;
   - the exact smoothed file path;
   - an enabled Narrate button.
4. Invoke Narrate using a test backend/fixture suitable for validation.

Expected: the server command uses `--scene 1` and the exact smoothed file. The
result is grounded in the distinguishable smoothed content, while the raw and
smoothed source bytes and mtimes remain unchanged by the invocation itself.

## 4. Partial smoothing and per-scene fallback

Prepare three raw scenes and only smoothed scenes 1 and 3.

1. Select scene 1: active source is **Smoothed**.
2. Select scene 2: active source is **Raw fallback**.
3. Select scene 3: active source is **Smoothed**, even though it is the second
   file in the partial smoothed directory.
4. Invoke or inspect the built command for each scene.

Expected: scenes 1 and 3 forward their exact smoothed files; scene 2 uses the
raw directory. No scene is substituted by compact-list position.

Repeat scene 3 with a plan title whose slug differs from the file slug.
Expected: the shared identity/`NN_` rule still locates scene 3.

## 5. Live disk changes without a page reload

1. Select a raw-fallback scene and leave the browser open.
2. Create its eligible smoothed file outside the UI.
3. Click Reload, or invoke Narrate directly.

Expected: the display changes to **Smoothed** without a page reload or config
edit. Narrate rechecks the same disk state at the server boundary and uses the
new exact file.

Then remove or rename that disposable smoothed file and refresh again.
Expected: the selected scene alone returns to **Raw fallback**.

## 6. Smoothed-only and blocked states

### Smoothed-only

In a disposable fixture, leave the plan and smoothed scene in place but move
the corresponding raw scene aside.

Expected:

- the textarea is disabled because raw `exists` is false;
- Narrate remains enabled because `narrate_source.available` is true;
- the exact smoothed file is used;
- no raw file is created as a side effect.

### Unreadable preferred file

Make a disposable matching smoothed file unreadable or invalid UTF-8 while
leaving raw present.

Expected:

- the source display says **Smoothed unreadable** and names the file;
- Narrate is disabled/refused before a model call;
- raw is not silently selected or rewritten.

### Neither source

Move both disposable scene files aside.

Expected: source display says **Missing**, Narrate is disabled/refused, and
the message names both checked directories. Restore every moved file before
continuing.

## 7. Raw dirty-buffer behavior

### Raw active

1. Select a raw-fallback scene.
2. Edit the raw textarea without pressing Save.
3. Invoke Narrate.

Expected: the dirty raw buffer is saved, source state is refreshed, and the
edited raw file is the run input. This preserves the established raw workflow.

### Smoothed active

1. Select a smoothed scene.
2. Edit the raw textarea without pressing Save.
3. Record raw and smoothed source bytes/mtimes, then invoke Narrate.

Expected: neither source is written as part of Narrate. The smoothed file is
used and the raw buffer remains visibly dirty until the GM explicitly saves or
reloads it.

## 8. Non-Narrate regression boundary

Run the relevant pipeline command-builder tests and inspect the diff:

```bash
rtk pytest tests/test_editor_pipeline.py tests/test_editor_verify_routes.py
rtk git diff -- server/routers/scene_editor.py
```

Expected:

- Re-Extract, Verify Quotes, Plan & Check, consistency, reviewed markers, and
  raw editor routes retain the configured raw extraction directory.
- `--scene-extraction-file` appears only in the `sd_narrate` parser and the
  Narrate builder path.
- No config model or migration file changes.

## 9. Final gates

From the feature worktree root:

```bash
rtk pytest tests/
rtk git diff --check
rtk git status --short
```

From `frontend/`:

```bash
rtk npm run build
```

GPT-5.6 then reviews the complete diff against all thirteen constitution
principles in `plan.md`. Completion requires no new test failure versus the
recorded baseline, a clean frontend build, and successful manual validation of
sections 3–7.
