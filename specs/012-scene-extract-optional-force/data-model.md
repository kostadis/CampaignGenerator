# Data Model: Optional Force for Scene Re-Extraction

No new persisted schema, database, or config field is introduced. Both
entities named in `spec.md`'s Key Entities section already exist as on-disk
state or transient UI state; this document records their shape as consumed
by this feature, not new structure.

## Scene extraction file

Already on disk, one per scene, under the session's `scene_extractions_dir`
(`campaignlib/scenes.py`, `filename_template="{i:02d}_{slug}.md"`).

| Field | Type | Source | Notes |
|---|---|---|---|
| `out_file` (path) | file existence | on disk | Presence/absence is the sole input to the skip decision (`out_file.exists() and not force`) |
| content | markdown | on disk | Overwritten only on the force path, and only after being snapshotted |
| `<file>.prev` | markdown | on disk | Written by `snapshot_scene_for_rerun()` when force overwrites a scene whose content actually differs |
| `<file>.reviewed` marker | file existence | on disk | Cleared only on the force path, per scene, when that scene is regenerated |

No change to this shape. This feature only changes which scenes the run is
*allowed* to touch (all vs. missing-only), not how a touched scene's file,
`.prev`, or reviewed marker behave once touched.

## Force selection

Transient, per-run UI state — not persisted.

| Field | Type | Scope | Default |
|---|---|---|---|
| `forceReextract` (proposed ref name) | `boolean` | Component-local reactive state in `SessionDocEditor.vue`, mirrored into the `force` query param of `GET /api/editor/extract` and the `force: int = 0` FastAPI param, and finally the CLI's `--force` flag | `false` |

Explicitly **not**: a field in `EditorConfigDrawer`'s config props, a key in
`session_doc.yaml`, or anything else routed through the editor's persisted
per-service config (per Constitution's "per-service config files" rule and
this feature's own Assumption that Force is not a remembered preference).
It resets to `false` on every page load, matching Constitution Principle X
(no silent default expansion to "everything").

The existing `knobs.force` field already recorded per-run in
`server/routers/scene_editor.py:1468` is where this choice becomes durable
observability data (which run did what), which is different from *config*
that would change next run's default.
