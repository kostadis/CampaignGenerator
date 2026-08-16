# Contract: `/api/editor/config` — `extract` group

This feature extends two existing endpoints (`server/routers/scene_editor.py`)
with one new grouped key. No new route is added; no existing route's URL,
method, or error semantics change.

## `GET /api/editor/config`

Response gains one top-level key, `extract`, alongside the existing `paths`,
`narrate`, `scrub`, `backends`, etc. (see `_serialize_resolved`).

**Before** (excerpt):
```json
{
  "paths": { "...": "..." },
  "narrate": { "tokens": 16000, "prose_mode": false, "reflections": false, "context": [] },
  "scrub": { "enabled": false, "tokens": 16000 },
  "...": "..."
}
```

**After** (excerpt):
```json
{
  "paths": { "...": "..." },
  "narrate": { "tokens": 16000, "prose_mode": false, "reflections": false, "context": [] },
  "extract": { "tokens": 8192 },
  "scrub": { "enabled": false, "tokens": 16000 },
  "...": "..."
}
```

A campaign with no `extract:` block in its on-disk `session_doc.yaml` still
returns `"extract": {"tokens": 8192}` — the Pydantic default, not an absent
key — matching how `narrate`/`scrub` already behave for a field that was
never explicitly set.

## `PUT /api/editor/config`

Request body MAY now include an `extract` key, as a partial merged the same
way every other group already is (`SessionEditorConfigService.update_config`,
deep-merged into the stored `SessionEditorConfig` then re-validated):

```json
{ "extract": { "tokens": 12000 } }
```

- Unknown keys under `extract` are rejected the same way an unknown key under
  `narrate` is today — `ExtractKnobs`'s `extra="forbid"` surfaces as the
  existing `update_config` error path (400-class response with an
  unrecognised-field message), not a new error shape.
- Omitting `extract` from the PUT body leaves the stored value untouched
  (partial-merge semantics, identical to every other group).
- The response contract for `PUT` is unchanged (whatever `api_put_config`
  already returns on success/failure); only the accepted request shape grows.

## Activated profiles (`_PROFILE_KNOB_TO_GROUPED`)

Out of scope for this feature. A profile's `knobs` dict does not gain an
`extract_tokens` mapping — activating a profile continues to affect only the
knobs it already affects (`narrate_tokens`, `prose_mode`, `reflections`,
`narration_genre_file`, `backend`). The new field is set directly via the
drawer/PUT path described above, the same way `scrub.tokens` is today (also
absent from the profile-knob table).

## `scene_extract` CLI surface

No contract change. `--max-tokens` (`session_doc/scene_extract.py`) already
exists, already defaults to `8192`, and already flows to every extraction
call site inside that script. This feature only changes who calls it with
which value — a new caller (`_build_reextract_cmd`) starts passing it
explicitly instead of leaving it unset.
