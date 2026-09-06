# Contract: Session Doc Editor Bundled Narration

**Feature**: 022-bundle-narration | Governs FR-003, FR-004, FR-014, FR-016, FR-018, FR-019

## 1. Existing current-scene route

```http
GET /api/editor/narrate/{n}
Accept: text/event-stream
```

This route and the existing `Narrate` button retain their current behavior: one selected scene, its resolved raw/smoothed source, existing prompt/handoff behavior, one per-scene output, one knob sidecar, and one activity row.

## 2. New bundle route

```http
GET /api/editor/narrate-bundle?scene=1&scene=2&scene=3
Accept: text/event-stream
```

`scene` is required and repeatable. There is no absent-means-all interpretation.

The server validates before starting the subprocess:

- at least one index is present;
- indices are positive, unique, in range, and in reviewed plan order;
- route indices correspond to the current on-disk plan;
- every selected scene has an available preferred source under the existing smoothed-first/raw-fallback rule;
- every common narration prerequisite is ready;
- the route has generated a unique run nonce and its nonce-scoped bundle report path is session-local and writable.

The copyable command has this shape:

```text
sd_narrate <summary> --plan <plan> --scene-extractions <raw-dir> \
  --per-scene-output <narration-dir> \
  --batch-scenes --batch-max-tokens <configured-total> \
  --scene 1 2 3 \
  --scene-extraction-file <preferred-smoothed-scene-1> \
  --scene-extraction-file <preferred-smoothed-scene-3> \
  --run-report <session>/.cg/narrate-bundle/<run-id>.json \
  <existing selection, party, player, voice, genre, and reflection arguments>
```

Raw fallback scenes require no exact override because `--scene-extractions` already names their base directory. The report records sources as `base` or `override`; raw/smoothed labels remain editor presentation data because the general CLI cannot infer those semantics from arbitrary paths.

## 3. SSE behavior

The route wraps the existing subprocess contract with `stream_subprocess(..., emit_done=False)`:

- a command event arrives first;
- stdout/stderr progress follows as data events;
- after the subprocess generator finishes, the route reads the nonce-scoped report and validates its version, run ID, return code, and requested selection;
- report-derived sidecars and activity are committed;
- one route-specific terminal `done` event carries `returncode`, `status`, `run_id`, `written_count`, `requested_count`, `missing`, `rejected`, and a bounded validation error when applicable;
- disconnect terminates the subprocess group under existing cleanup behavior.

Return codes are presented as:

| Code | UI state |
|---|---|
| `0` | “Bundled narration complete — N/N scenes written.” |
| `3` | “Bundled narration partial — K/N written”; missing scene names and the current-scene recovery action remain visible. |
| `4` | “Bundled response could not be reconciled — no bundle output was written.” |
| other | Existing failed/aborted presentation with the streamed reason. |

Every route-specific terminal result triggers a full scene-list and pipeline-status reload. The UI derives K/N and missing-scene copy from the terminal payload rather than parsing stdout or inspecting existing files.

## 4. Scope dialog

The editor exposes `Narrate all in one call…` while retaining the current `Narrate` action. Opening it uses the already loaded plan scene list and displays, in order:

| Display | Source |
|---|---|
| Full-plan index | `scene.index` |
| Scene name | `scene.scene` |
| Narrator | `scene.narrator` |
| Output state | `scene.has_output` shown as `new` or `will replace` |

The dialog shows the total count and the configured bundled output ceiling. Its Run button is disabled for an empty list or while another editor pipeline action is active. Cancel makes no request. Run materializes every displayed index into repeated `scene` query parameters.

If the current raw extraction has unsaved edits, the editor saves it before launching or reports why it cannot; it never starts a bundle against stale disk content.

## 5. Settings and language

The Narrate section of the configuration drawer adds `Batched token limit`, bound to `narrate.batch_tokens`. Help text states:

- current `Token limit` is per scene in sequential mode;
- `Batched token limit` is the total ceiling for the one bundled exchange;
- raising the bundled ceiling can make a larger explicit set eligible;
- the run refuses rather than silently splitting.

Provider Batch remains inherited from the app/service backend selection. The existing unconditional statement that provider batching always narrates one scene at a time is replaced with wording that distinguishes:

- sequential content + provider Batch: ordered one-item submissions;
- bundled content + provider Batch: one bundled item;
- bundled content without provider Batch: one live exchange.

## 6. Completion audit

The route reads the validated nonce-scoped run report described in [run-report.md](./run-report.md). Knob sidecars are written for report `written` entries even when the overall exit is partial. The activity row keeps `stage: narrate`, stores `run_id`, `scenes: [1,2,3]`, and records bundle/provider modes, ceiling, exchange count, result counts, and actual output paths.

Review and assembly continue to consume the ordinary per-scene narration files. The bundle route never marks review complete and never invokes assembly.
