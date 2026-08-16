# Quickstart: Validating the Scene Extraction Token Limit

Validates spec.md's User Story 1 and its three acceptance scenarios
end-to-end, once the implementation described in `plan.md` is in place.

## Prerequisites

- A campaign workspace with a Session Doc Editor already usable (has a VTT,
  `session-summary.md` with a `## Scenes` section — see
  `docs/cli/session_doc_pipeline.md` if starting from scratch).
- Editable install of this package into the server's venv (see this repo's
  `CLAUDE.md`, "The package MUST be editable-installed into the server's
  venv") so `console_script("scene_extract")` resolves.
- `startup` running (builds the frontend, starts the FastAPI dev server).

## 1. Confirm the default is visible and matches the tool's own default

1. Open the Session Doc Editor for a campaign whose `session_doc.yaml` has
   never set `extract.tokens` (or has no `session_doc.yaml` yet).
2. Open the Config drawer (gear / Config button) → "② Extract" section.
3. **Expect**: a "Token limit" field showing `8192` — the same default
   `python -m session_doc.scene_extract --help` shows for `--max-tokens`.

   Cross-check via the API directly:
   ```bash
   curl -s http://localhost:8000/api/editor/config | jq '.extract'
   # {"tokens": 8192}
   ```

## 2. Change the value and confirm it persists

1. In the drawer, change the Extract token limit to a distinct test value,
   e.g. `12000`.
2. Wait for the debounced auto-save (same ~350ms as every other field) to
   fire — no explicit Save button.
3. Reload the page.
4. **Expect**: the field still shows `12000` (spec Acceptance Scenario 3 /
   SC-003).

   Cross-check on disk:
   ```bash
   grep -A1 "^extract:" <config-dir>/session_doc.yaml
   # extract:
   #   tokens: 12000
   ```

## 3. Confirm the value reaches the extraction run

1. With the token limit still set to a deliberately low value (e.g. `500` —
   low enough to truncate a real scene's extraction), click **Extract** (or
   **Re-Extract**) for a scene with substantial dialogue.
2. **Expect**: the run's own log line / SSE output shows the low cap took
   effect (e.g. a visibly truncated `NN_<slug>.md`, or — if the activity log
   is inspected — the subprocess command line itself, which should read
   `... --max-tokens 500`).
3. Raise the limit back to a normal value (e.g. `8192` or `16000`), re-run
   with `--force` (the UI's Re-Extract always sets this), and confirm the
   scene extracts in full (not truncated).

   Cross-check the exact command issued, without touching the UI:
   ```python
   from server.routers.scene_editor import _build_reextract_cmd
   # cfg.extract.tokens == 500 → cmd includes ["--max-tokens", "500"]
   ```

## 4. Confirm existing campaigns are unaffected (spec FR-004 / SC-002)

1. Pick (or fabricate) a `session_doc.yaml` from before this feature shipped
   — i.e. one with no `extract:` key at all.
2. Load it in the editor; run Extract.
3. **Expect**: the extraction runs exactly as it did before this feature —
   `--max-tokens 8192` on the command line, identical to what
   `scene_extract.py` would default to if the flag were omitted entirely.

## Automated coverage (for reference, not required to hand-verify manually)

- `tests/test_session_editor_config_service.py`: `ExtractKnobs` default
  value, strict-schema rejection of an unknown field under `extract`,
  round-trip persistence through `load_session_editor_config`/
  `save_session_editor_config`.
- `tests/test_editor_pipeline.py`: `_build_reextract_cmd` includes
  `--max-tokens <value>` when `cfg.extract.tokens` is set/default, mirroring
  its existing `_build_narrate_cmd` narrate-tokens assertion.
