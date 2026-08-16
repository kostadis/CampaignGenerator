# Phase 0 Research: Scene Extraction Token Limit from the UI

No `NEEDS CLARIFICATION` markers were left in the Technical Context — the
feature is a narrow parity gap against an existing, working pattern
(`narrate.tokens`), so every "unknown" below was resolved by reading the
pattern itself rather than by evaluating alternatives from scratch.

## D1: Where does the new knob live in the schema?

**Decision**: A new `ExtractKnobs` model (`tokens: int = 8192`), added as a
sibling of `NarrateKnobs`/`ScrubKnobs` on `SessionEditorConfig`, keyed
`extract:` in `session_doc.yaml`.

**Rationale**: `ScrubKnobs` is the closer of the two existing siblings —
`{enabled: bool = False, tokens: int = 16000}` — but Extract has no
"enabled" concept (it always runs when the GM clicks Extract/Re-Extract;
there's no separate opt-in checkbox the way scrub has one), so `ExtractKnobs`
needs only the one field, mirroring `NarrateKnobs.tokens` more closely in
shape (a single `tokens: int` with a tool-matching default) while following
`ScrubKnobs`'s naming (`tokens`, not `max_tokens`) since `tokens` is already
the established grouped-schema field name for "this stage's per-call output
cap" in both siblings.

**Alternatives considered**:
- *Add `tokens` directly onto `EditorPaths` or another existing group* —
  rejected: every other per-stage tuning knob (`narrate.tokens`,
  `scrub.tokens`, `verify.threshold`) lives in its own stage-named group, and
  `EditorPaths` is documented as holding only paths. Breaking that pattern for
  one field would be the kind of drift Constitution VI exists to prevent.
- *Reuse `scrub.tokens` or add a single shared `default_tokens`* — rejected:
  Extract and Scrub are different stages with independently-tunable output
  caps today (`scrub.tokens` already defaults to 16000, distinct from
  Extract's 8192); collapsing them would make one stage's slider silently
  move the other's ceiling.

## D2: What must the default be?

**Decision**: `8192` — the exact value `scene_extract.py`'s own
`--max-tokens` argparse default already uses (`session_doc/scene_extract.py`,
`parser.add_argument("--max-tokens", type=int, default=8192, ...)`).

**Rationale**: Spec FR-004/FR-005 require that a campaign which has never
touched this field sees no behavior change, and that the UI's shown default
matches what actually runs. The only way both hold simultaneously is for the
new field's Pydantic default to equal the CLI's existing default exactly —
otherwise "unset in `session_doc.yaml`" and "the value the CLI has always
used" diverge the moment this ships, silently changing output for every
existing campaign.

**Alternatives considered**: Matching Narrate's 16000 default for visual
consistency — rejected outright; it would silently roughly double every
existing campaign's extraction cap on upgrade, which is exactly the kind of
change-without-consent Constitution X's "no silent blast radius" clause and
spec FR-004 both forbid, just applied to a scalar instead of a selection set.

## D3: How does the value reach `scene_extract`?

**Decision**: `_build_reextract_cmd` (`server/routers/scene_editor.py`)
appends `["--max-tokens", str(cfg.extract.tokens)]` unconditionally (the field
always has a value — either the persisted one or the Pydantic default), the
same shape `_build_narrate_cmd` already uses for
`if cfg.narrate.tokens: cmd += ["--narrate-tokens", str(cfg.narrate.tokens)]`.

**Rationale**: This is Constitution VI's own worked example — "exposing a
flag means adding it to the corresponding `_build_*_cmd()` in the router,
never reimplementing the behavior in the router." `scene_extract.py` needs no
change at all; `--max-tokens` has existed on its parser since before this
feature and is already threaded through to every call site inside that
script (`run_scene_extraction`, `_build_pending_requests` for the batch path).

**Alternatives considered**: Only appending the flag when the value differs
from the CLI default — rejected as needless complexity; always appending it
explicitly is what `_build_narrate_cmd` already does in spirit (its `if`
guards against `0`/`None`, not against "equals the default"), and an explicit
flag makes the actually-issued command fully copyable/debuggable, which
matters more here than saving one CLI token.

## D4: Frontend wiring shape

**Decision**: Mirror `narrateTokens` end-to-end in `SessionDocEditor.vue` —
a new `extractTokens` ref seeded from `ec?.extract?.tokens` in
`loadConfigFields()`, included in the `watch([...])` list that triggers
`scheduleApply()`, added to `buildEditorConfigPayload()` under a new
top-level `extract: { tokens: extractTokens.value || undefined }` key, and
passed to `KnobDrawer` as `:default-extract-tokens`/`v-model:extract-tokens`
the same way `narrateTokens` is today. `KnobDrawer.vue` gets a "Token limit"
`<input type="number">` in its existing (currently knob-less) "② Extract"
section, styled and labelled identically to Stage ④'s.

**Rationale**: This is the same auto-save-on-change, debounced-PUT pattern
every other drawer field already uses; introducing a different pattern for
just this one field would be new surface area for no benefit and would break
the "every stage knob behaves the same way" expectation the drawer currently
holds.

**Alternatives considered**: A dedicated save button for just this field —
rejected, no other drawer field works that way and it would be inconsistent
UX for a single knob.

## D5: Response/serialization surface

**Decision**: `_serialize_resolved` (`server/routers/scene_editor.py`) gains
`"extract": cfg.extract.model_dump()` alongside its existing `"narrate"`/
`"scrub"` entries, so `GET /api/editor/config` and the profile-activate
response (which reuses `_serialize_resolved`) both carry it automatically.

**Rationale**: Single source of truth for the wire shape, exactly as the
function's own docstring states — adding a third stage-knobs entry in the
same dict is the minimal change that keeps both response types in sync.

## D6: Activity-log / knobs-snapshot parity (optional, not required by spec)

**Observation**: `_narrate_knobs_snapshot` stores narrate's knobs alongside
each produced narration file for later review. `api_extract`'s `_done`
callback currently logs only `{"batch": ..., "force": ...}` — no per-run
`extract.tokens` snapshot exists today, and the spec does not require adding
one (its FRs are about the config path, not the activity log). Left out of
scope; noted here only so a future reviewer doesn't mistake the omission for
an oversight — it is symmetric with today's Extract-stage activity logging,
which has never carried the model/backend/token knobs Narrate's does either.
