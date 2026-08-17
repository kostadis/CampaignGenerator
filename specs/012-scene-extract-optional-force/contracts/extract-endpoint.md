# Contract: `GET /api/editor/extract` (Stage 2 re-extraction)

This endpoint already exists (`server/routers/scene_editor.py:1449`,
`api_extract`). This document fixes its `force` behavior as a contract this
feature must not regress, since the whole fix is about the caller finally
exercising the parameter's existing default correctly.

## Request

`GET /api/editor/extract?force={0|1}`

| Param | Type | Required | Default | Meaning |
|---|---|---|---|---|
| `force` | `int` (`0` or `1`) | No | `0` | `0` → skip-existing (resumable) re-extraction. `1` → force-all (redo every scene). |

**Contract obligation of this feature**: the frontend MUST omit `force` or
send `force=0` by default, and MUST send `force=1` only when the GM has
explicitly enabled the Force control for that run. The frontend MUST NOT
hardcode `force=1` unconditionally (the defect being fixed).

## Response (unchanged — SSE stream)

`text/event-stream`, one event per streamed chunk of the underlying
`scene_extract` CLI process's stdout, terminated by a `done` event carrying
the process return code. Per-scene lines already distinguish skip vs.
generate (`"Skipping (already exists): ..."` vs. `"Scene-extracting: ..."` /
`"Re-extracting: ..."`) — this feature does not change the stream format,
only which lines actually appear (skip lines become reachable once
`force=0` is actually sent).

## Side effects by `force` value

| `force` | Per scene with an existing output file | Per scene without an existing output file |
|---|---|---|
| `0` (default) | Untouched — file, `.prev`, and `.reviewed` marker unchanged | Generated: new file written |
| `1` | Regenerated: content overwritten (prior content snapshotted to `.prev` if it differs), `.reviewed` marker cleared | Generated: new file written |

## Observability

The run's `knobs` (recorded alongside every editor run) already include
`"force": bool(force)` (`scene_editor.py:1468`). This feature relies on that
field starting to reflect the GM's actual per-run choice instead of always
being `true`.

## Non-goals of this contract

- No per-scene selection parameter (e.g. `scenes=1,3,5`) is added. Out of
  scope per `spec.md` Assumptions.
- No change to `session_doc/scene_extract.py`'s CLI contract — its
  `--force` flag and skip-if-exists default are already correct and are
  reused as-is via `_build_reextract_cmd`.
