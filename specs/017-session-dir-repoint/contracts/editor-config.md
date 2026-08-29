# Contract: Session-Editor Config Wire Shape

**Feature**: `017-session-dir-repoint` | **Date**: 2026-08-28

Covers the HTTP surface between the Vue SPA and the FastAPI server that this
feature changes. All changes are **additive**: no existing key changes name,
type, or meaning, so no client that ignores the new keys breaks.

Producer for both endpoints below is `_serialize_resolved`
(`server/routers/scene_editor.py:106`), deliberately the single source of the
wire shape for `GET /api/editor/config` *and* the profile-activate response, so
the two cannot drift.

---

## `GET /api/editor/config`

Returns the resolved editor config, grouped.

### Added keys

```jsonc
{
  // ... every existing key unchanged: paths, extract, narrate, backends,
  // session_name, profiles, active_profile, model, work_dir, campaign_dir,
  // config_dir, vtt, session_dir, genre, batch_scenes_effective

  "paths_stored": {
    "session_recap":        "gm-assist.md",          // relative to session_dir
    "session_summary":      "session-summary.md",
    "scene_extractions_dir":"scene_extractions",
    "narration_dir":        "narration",
    "output_dir":           null,
    "party":                "docs/party.md",         // relative to campaign_dir
    "voice_dir":            "voice",
    "examples_dir":         "examples",
    "genre_file":           "voice/_genre.md"
  },

  "warnings": [
    "session_doc.yaml paths.scene_extractions_dir pointed into a different session directory (/…/summaries/20260811/scene_extractions); re-pointed to /…/summaries/20260825/scene_extractions. The corrected value will be stored on the next save."
  ]
}
```

### Contract guarantees

| ID | Guarantee |
|---|---|
| C-01 | `paths` keeps its existing meaning: every field absolute, or `null`. It is now resolved **from the healed values**. |
| C-02 | `paths_stored` has exactly the same keys as `paths`. For every key, `paths[k] == resolve(paths_stored[k])`. |
| C-03 | `paths_stored` is what a client MUST echo back in `PUT /api/editor/config`. Sending `paths` back is what this feature exists to stop. |
| C-04 | `warnings` is always present and always a list. Empty on a healthy config. |
| C-05 | Each `warnings` entry names the field, the stored value, and the value now in use (FR-006). |
| C-06 | A `GET` never writes to disk. Two consecutive `GET`s produce identical bodies and leave `session_doc.yaml` mtime unchanged (FR-007, FR-012). |
| C-07 | `session_dir` (existing key) reflects any `--session-dir` boot override, and the classification in `paths_stored` is computed against that same value (FR-011). |
| C-08 | A field whose resolved target does not exist is still returned. Existence is reported by `GET /api/config/path-status`, not by omission (FR-008). |

### Unchanged

`GET /api/editor/config` remains the only read door for the editor slice, and
every `_build_*_cmd()` in `server/routers/scene_editor.py` keeps reading
`ResolvedEditorConfig.paths` server-side. **No run route gains a path
parameter.** The diff for those functions must be empty.

---

## `PUT /api/editor/config`

Unchanged endpoint, unchanged body shape (a grouped `SessionEditorConfig`
partial), unchanged response (`{"ok": true}`).

What changes is the client's obligation:

| ID | Obligation |
|---|---|
| C-09 | The client sends the values it received in `paths_stored`, not `paths`. |
| C-10 | The server's write-time relativization (`_relativized_paths`) is retained unmodified. With C-09 honoured it is a no-op for relative values; it still collapses a hand-authored or CLI-supplied absolute. |
| C-11 | A `PUT` that arrives while `runtime.session_dir` has already advanced MUST NOT be able to pin the previous session — guaranteed by C-09, since a relative name carries no session identity. |

---

## `PUT /api/config/runtime`

Unchanged endpoint and body (`{"values": {...}}`), unchanged response
(`{"ok": true}`).

| ID | Obligation |
|---|---|
| C-12 | When the partial contains `session_dir`, the **client** additionally refetches `GET /api/editor/config` before rendering any editor path. (Client-side obligation — the endpoint itself is untouched.) |
| C-13 | Session Config commits `session_dir` **before** `PUT /api/editor/config`, so path fields in the same save are interpreted against the new session (FR-002 scenario 2). |

---

## `GET /api/config/path-status?path=<abs>`

**Unchanged.** Already implemented (`server/routers/config_routes.py:127`,
`{"exists": bool}`) and already consumed by `PathField.vue:43`. Listed here
because User Story 4's acceptance depends on it and the contract must not
regress.

| ID | Guarantee |
|---|---|
| C-14 | Called with the **resolved** path. After this feature the editor holds relative values, so the caller resolves first — which `PathField.resolvedPath` already does. |

---

## Frontend internal contract (not HTTP, but binding)

| ID | Rule |
|---|---|
| C-15 | `frontend/src/utils/paths.ts` resolves **for display only** and MUST NOT gain an inverse. Relativization has exactly one implementation, server-side (Principle XII, FR-010). |
| C-16 | `configStore.editorConfig` is the single source the editor hydrates from. A component MUST NOT derive a session path from `resolved.runtime.session_dir` independently. |
