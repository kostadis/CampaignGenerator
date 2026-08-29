# Editor API Contract: Narrate Source Projection

**Feature**: `018-prefer-smoothed-extractions`

The contract is additive. Existing extraction editor and Narrate SSE routes
retain their paths and current fields.

## `GET /api/editor/extraction/{n}`

### Existing fields (unchanged)

```json
{
  "exists": true,
  "content": "raw editor content",
  "scene_label": "Narrator — Scene",
  "estimated_tokens": 1200
}
```

`exists` and `content` continue to describe the configured **raw extraction**
owned by the editor. They do not switch meaning when smoothing is present.

### Additive fields

The raw editor also reports whether its existing file could be decoded safely:

```json
{
  "editor_readable": true,
  "editor_error": null
}
```

`editor_readable` is null when the raw file is absent, true when `content` was
loaded, and false when the file exists but cannot be read as UTF-8 (or another
filesystem read fails). In the false case, `content` is empty and
`editor_error` names the file and reason. The UI must not expose that empty
buffer as editable, because saving it would overwrite the unreadable file.

Every successful selected-scene response adds `narrate_source`:

```json
{
  "narrate_source": {
    "scene_index": 3,
    "scene_name": "The Statue Returned",
    "smoothed": {
      "layer": "smoothed",
      "directory": "/campaign/summaries/20260825/scene_extractions_smoothed",
      "directory_exists": true,
      "path": "/campaign/summaries/20260825/scene_extractions_smoothed/03_the_statue_returned.md",
      "filename": "03_the_statue_returned.md",
      "exists": true,
      "readable": true,
      "reason": null
    },
    "raw": {
      "layer": "raw",
      "directory": "/campaign/summaries/20260825/scene_extractions_new",
      "directory_exists": true,
      "path": "/campaign/summaries/20260825/scene_extractions_new/03_the_statue.md",
      "filename": "03_the_statue.md",
      "exists": true,
      "readable": true,
      "reason": null
    },
    "active_layer": "smoothed",
    "active_file": "/campaign/summaries/20260825/scene_extractions_smoothed/03_the_statue_returned.md",
    "status": "ready",
    "available": true,
    "fallback_to_raw": false,
    "message": "Narrate will use the smoothed scene extraction."
  }
}
```

### Candidate field rules

| Field | Type | Rule |
|---|---|---|
| `layer` | `"smoothed" | "raw"` | Fixed for the candidate. |
| `directory` | string or null | Absolute resolved directory. Raw may be null when not configured. |
| `directory_exists` | boolean | Current disk state. |
| `path` | string or null | Exact eligible candidate, after scaffold precedence. |
| `filename` | string or null | Basename of `path`. |
| `exists` | boolean | Candidate file exists now. |
| `readable` | boolean or null | Null when no file; otherwise UTF-8 read probe result. |
| `reason` | string or null | Absence/readability explanation. |

### Active field rules

| State | `active_layer` | `status` | `available` | `fallback_to_raw` |
|---|---|---|---|---|
| Readable smoothed candidate | `smoothed` | `ready` | `true` | `false` |
| Smoothed absent, readable raw candidate | `raw` | `ready` | `true` | `true` |
| Preferred candidate exists but is unreadable | `null` | `unreadable` | `false` | `false` |
| Neither eligible candidate exists | `null` | `missing` | `false` | `false` |

For `unreadable`, `message` names the failing file. For `missing`, `message`
names both directories checked. The smoothed directory path is returned even
when `directory_exists` is false, so the UI can show where smoothing output is
expected.

An out-of-range scene retains the existing 404 behavior. No source is selected
for an invalid scene number.

## `PUT /api/editor/extraction/{n}`

Unchanged. It saves the configured raw editor file only. It never redirects a
write into the active smoothed source.

## `GET /api/editor/narrate/{n}` (SSE)

Path and transport are unchanged. Before starting the subprocess, the server
recomputes `NarrateSourceState` from disk:

- `ready/smoothed`: forward the exact file through the CLI contract.
- `ready/raw`: use the existing raw directory invocation.
- `missing` or `unreadable`: return the existing SSE error form before any
  model call, using `narrate_source.message`.

The command builder does not accept a browser-selected path or layer. The
frontend preflight refresh exists to update what the GM sees; the server's
fresh resolution remains authoritative.

## Frontend rendering contract

`ExtractionEditor` renders all of the following from `narrate_source`:

1. Expected smoothed directory and present/not-present state.
2. Active label: **Smoothed**, **Raw fallback**, **Missing**, or
   **Smoothed unreadable**.
3. Exact active path when ready.
4. Blocking message when not ready.

Save/Edit/Reload/Diff require raw `exists` and `editor_readable != false`.
Narrate is controlled independently by `narrate_source.available`, so a valid
smoothed source remains usable when the raw editor file is unreadable. Before
opening the SSE connection, the parent view refetches the extraction detail so
these displayed fields reflect current disk state.
