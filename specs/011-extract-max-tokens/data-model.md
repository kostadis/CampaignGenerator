# Phase 1 Data Model: Scene Extraction Token Limit from the UI

No new persistent entity is introduced. This feature adds one field, grouped
under one new knob object, to an entity that already exists.

## Entity: `SessionEditorConfig` (per-campaign editor configuration)

Persisted at `<config>/session_doc.yaml`, owned exclusively by
`SessionEditorConfigService` (`server/session_editor_config_service.py`),
strict (`extra="forbid"`, per Constitution VI/VIII — one authority, one file).

### New nested group: `ExtractKnobs`

| Field | Type | Default | Notes |
|---|---|---|---|
| `tokens` | `int` | `8192` | Per-scene output token cap forwarded to `scene_extract --max-tokens`. Default matches `scene_extract.py`'s own argparse default exactly (research D2) so an unset campaign's behavior is unchanged. |

```python
class ExtractKnobs(BaseModel):
    """Stage-② extract knobs."""

    model_config = ConfigDict(extra="forbid")

    tokens: int = 8192
```

Added to `SessionEditorConfig` as:

```python
extract: ExtractKnobs = Field(default_factory=ExtractKnobs)
```

alongside the existing `narrate: NarrateKnobs` and `scrub: ScrubKnobs`
fields. No other field is added — Extract has no `enabled` toggle (unlike
`scrub.enabled`; Extract already runs unconditionally when the GM triggers
Stage 2) and no other tunable surfaced by this feature.

### Validation rules

- `tokens` is a plain `int` field on a Pydantic model — non-numeric input is
  rejected by the schema itself when the config is loaded/updated
  (`SessionEditorConfig.model_validate`), the same as `narrate.tokens` and
  `scrub.tokens` today. Neither of those siblings enforces a minimum/maximum
  at the schema layer either; the *frontend* input element is what enforces a
  sane floor (spec FR-006), mirroring `KnobDrawer.vue`'s existing
  `narrateTokens` field (`min="1000" step="500"` on the `<input>`).
- No cross-field validation is needed — `tokens` has no relationship to any
  other field in `ExtractKnobs` or in the rest of `SessionEditorConfig`.

### State / lifecycle

- **Unset** (field absent from a pre-feature `session_doc.yaml`, or the
  campaign has never opened the drawer's Extract token field): Pydantic's
  `default_factory=ExtractKnobs` supplies `tokens=8192` on load — identical
  in effect to the value `scene_extract.py` has always defaulted to, so this
  state is behaviorally invisible (spec FR-004).
- **Set**: the GM has changed the value in the Config drawer, which triggers
  the existing debounced auto-save to `PUT /api/editor/config`; the value is
  merged into `session_doc.yaml` under `extract.tokens` and persists across
  reloads (spec FR-002/SC-003), the same durability every other drawer field
  already has.
- **Consumed**: on every Stage 2 (Extract / Re-Extract) trigger,
  `_build_reextract_cmd` reads `cfg.extract.tokens` off the request-scoped
  `ResolvedEditorConfig` and forwards it as `scene_extract --max-tokens`
  (spec FR-003). Nothing else reads this field — it is not part of
  `_narrate_knobs_snapshot` or any other narration-specific structure.

### Relationships

`ExtractKnobs` has no relationship to any other entity beyond its containment
in `SessionEditorConfig`, exactly like its `ScrubKnobs`/`VerifyKnobs`
siblings. It is not part of `TYPED_SESSION_DOC_TO_GROUPED` (the flat-legacy →
grouped migration table in `server/session_editor_config_shared.py`) because
there is no legacy flat field to migrate from — `extract.tokens` has no prior
existence anywhere in the system.

### `ResolvedEditorConfig` (request-scoped read view)

Gains one field, populated verbatim from the stored config (no path
resolution needed — unlike `paths.*`, a token count isn't a filesystem path):

```python
extract: ExtractKnobs
```

set in `SessionEditorConfigService.resolved_editor_config()` alongside the
existing `narrate=cfg.narrate, scrub=cfg.scrub` assignments.
