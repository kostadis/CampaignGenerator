# Data Model: Batched Scene Extraction

**Feature**: 013-batched-scene-extraction | **Date**: 2026-08-22

Entities, their states and the validation rules the requirements imply. No
storage schema changes — extraction files keep their existing on-disk shape
(FR-002); the only persisted additions are two config fields (D7).

---

## 1. ScenePlanEntry *(existing — reused unchanged)*

Produced by `plan_scene_extraction` (`campaignlib/scenes.py:334`). The batched
engine consumes it as-is; this is what keeps the two modes from drifting on
naming and force semantics (D1).

| Field | Type | Meaning |
|---|---|---|
| `i` | int | 1-based request index. **The attribution key** for the wire protocol (D5). |
| `name` | str | Scene name from the human-reviewed summary. Not guaranteed unique. |
| `body` | str | gm-assist bullets. Defines scope, and is the projection input (D4). |
| `slug` | str | Filename slug. |
| `custom_id` | str | Batch-API identifier (metered path only; unused here). |
| `path` | Path | Destination extraction file. |
| `exists` | bool | Whether `path` is already on disk. |

**Rule DM-1**: `i` is assigned over the **full** scene list, before any
filtering, and never renumbered. A scene keeps its index whether or not other
scenes are skipped, so a partial run and a full run agree on what "scene 03" is.

---

## 2. ExtractionRequestSet

The scenes a run will actually send. Derived, never persisted.

| Field | Type | Meaning |
|---|---|---|
| `entries` | list[ScenePlanEntry] | Scenes to extract, in plan order. |
| `force` | bool | Whether existing files are being overwritten. |
| `skipped` | list[ScenePlanEntry] | Scenes excluded because they already exist. |

**Rule DM-2** (FR-008a): `entries = plan if force else [p for p in plan if not
p.exists]`. This filter runs **before** projection and grouping. Skipped scenes
never appear in a request, never contribute to a projection, and never influence
group sizing.

**Rule DM-3** (FR-008b): `entries == []` → the run makes **zero** calls and
reports that everything is already extracted. It is not an error.

**Rule DM-4** (FR-008d): `exists` is the sole criterion, and it is the same one
the per-scene mode uses — so a session started in one mode and finished in the
other converges on the same set.

Convergence puts one requirement on the OTHER mode, which it did not originally
meet: `run_scene_extraction` wrote a file even when the model returned nothing,
so an empty result retired that scene permanently — while the batched path
(FR-006, status `"empty"`) left no file and asked again. Both now decline to
write an empty scene, so `exists` means the same thing on both paths. Under
`--force` this also stops an empty response from overwriting a good prior
extraction.

---

## 3. OutputProjection

An estimate of generated output size, made before any response exists (D4).

| Field | Type | Meaning |
|---|---|---|
| `scene_index` | int | The `i` this projects. |
| `estimated_chars` | int | `len(entry.body.strip()) × OUTPUT_CHARS_PER_BODY_CHAR` |
| `estimated_tokens` | float | `estimated_chars ÷ CHARS_PER_TOKEN` |

**Constants** (declared once, named, not inlined):

| Constant | Value | Provenance |
|---|---|---|
| `OUTPUT_CHARS_PER_BODY_CHAR` | `4.2` | Median over 15 measured scenes (range 2.4–6.5, r = 0.784) — research D4 |
| `CHARS_PER_TOKEN` | `4.0` | Prose/markdown estimate; the transcript's own ~7.4 ch/tok does **not** apply to generated prose |

**Rule DM-5**: the projection is an estimate and nothing downstream may treat it
as authoritative. It selects a grouping and is then discarded. Correctness comes
from the response split (§5) and the short-response path (§6), neither of which
consults it.

**Rule DM-6**: the multiplier is deliberately the **median**, not a conservative
bound. Over- and under-estimating each cost one extra transcript transmission
(D4), so the central estimate minimises expected cost.

---

## 4. SceneGroup

A contiguous run of scenes answered by one exchange.

| Field | Type | Meaning |
|---|---|---|
| `index` | int | 1-based group number, for the run report. |
| `entries` | list[ScenePlanEntry] | Scenes in this group, in plan order. |
| `projected_tokens` | float | Sum of member projections. |

**Rule DM-7** (FR-006a): if the whole request set's projection ≤ ceiling, there
is exactly **one** group.

**Rule DM-8** (FR-006b): otherwise, pack greedily in plan order into the fewest
groups whose individual projections each fit the ceiling.

**Rule DM-9** (FR-006b): a group is never empty. A single scene whose own
projection exceeds the ceiling forms a group **alone** and the run says the
projection was exceeded — it is not refused, and it is not merged.

**Rule DM-10** (FR-006c): grouping is a pure function of
`(entries, ceiling, constants)`. Same inputs → same grouping, always.

**Rule DM-11**: groups are contiguous in plan order. Scenes are never reordered.

---

## 5. BatchedExchange & the wire protocol

One request/response pair per group. Full syntax in
[contracts/wire-protocol.md](./contracts/wire-protocol.md).

**Request**: the shared system prompt (batched prefix + full VTT + NPC roster,
via the existing `build_scene_extraction_system_prompt`) plus a user prompt
rendering each group member as an indexed block.

**Response**: for each scene, a sentinel-delimited section:

```
<<<CG-SCENE {i:02d} BEGIN: {name}>>>
{moments}
<<<CG-SCENE {i:02d} END>>>
```

### SceneSection states

| State | Condition | Action |
|---|---|---|
| `complete` | BEGIN and END both present, in order, indices agree | Write via `format_scene_output` + `snapshot_scene_for_rerun` |
| `empty` | Complete, but `moments` is blank after stripping | **Do not write** (FR-006). Report "no moments returned" |
| `incomplete` | BEGIN present, END absent | **Do not write** (FR-011). Report as not extracted |
| `absent` | No BEGIN for a requested index | Report as not extracted (FR-012) |
| `unreconcilable` | Index not in the group, duplicated, or echoed name mismatches | **Fail the group; write nothing from it** (FR-005) |

**Rule DM-12** (FR-004): the split is textual and deterministic. No model call,
no similarity matching, no fuzzy name resolution.

**Rule DM-13**: attribution is by **index**. The echoed name is verified and a
mismatch is a hard failure — never a re-assignment. Duplicate scene names are
therefore harmless.

**Rule DM-14**: `unreconcilable` fails the whole group, not one scene. A
response that cannot be trusted to say which scene it is talking about cannot be
trusted for any scene in it.

**Rule DM-15**: an `incomplete` section is the expected consequence of a
short response, not an error. It is the signal FR-010/FR-011 are built on —
everything before it is kept, it and everything after are re-requested.

---

## 6. RunReport

Emitted at the end of every run (FR-018). Read by the GM; also what makes the
projection constants re-tunable from evidence later.

| Field | Type | Meaning |
|---|---|---|
| `scenes_total` | int | Scenes in the summary. |
| `scenes_skipped` | int | Already on disk, Force off. |
| `scenes_requested` | int | `len(request_set.entries)`. |
| `projected_tokens_total` | float | Sum of every group's `projected_tokens` (§3) — printed next to the group count so the constant is re-tunable from evidence (T050). |
| `scenes_written` | int | Sections that were `complete` and non-empty. |
| `scenes_empty` | list[str] | Complete but returned no moments. |
| `scenes_missing` | list[str] | `incomplete` or `absent` — named, per FR-012. |
| `groups_used` | int | Number of exchanges. |
| `transcript_transmissions` | int | Equals `groups_used`. |
| `ceiling_exceeded` | bool | Whether the projection forced a split (FR-006d). |

**Rule DM-16** (FR-012): `scenes_missing` non-empty → the run exits marking
itself incomplete. Partial success is reported as partial, never as success.

---

## 7. Config additions

`ExtractKnobs` in `server/session_editor_config_shared.py` (D7). The model is
`extra="forbid"`, so both fields must be declared.

| Field | Type | Default | Notes |
|---|---|---|---|
| `tokens` | int | `8192` | **Unchanged.** Per-scene ceiling; pinned to the CLI default by an existing test (FR-017b, SC-008) |
| `batch_scenes` | bool \| None | `None` | `None` = "follow the backend default" (§8). `True`/`False` = the GM pinned it |
| `batch_tokens` | int | `32000` | Batched ceiling (FR-017). GM-adjustable; raising it above a session's projection collapses the run to one call (SC-009) |

**Rule DM-17**: `batch_tokens` and `tokens` are independent. Changing one never
changes the other.

---

## 8. Activation resolution

**Rule DM-18** (FR-007a), in order:

1. An explicit per-run choice from the GM (CLI flag, or the editor checkbox as
   sent) wins.
2. Otherwise `ExtractKnobs.batch_scenes` if it is not `None`.
3. Otherwise the backend default: `True` when `cfg.backends.active ==
   "claude-code"`, `False` otherwise.

**Rule DM-19**: the resolved value is always rendered as an explicit CLI flag, so
the subprocess command is fully explicit and copyable — the resolution happens
before argv is built, matching the repo's existing ensemble-config precedent.

**Rule DM-20**: the UI must show the resolved default in its initial checkbox
state. A default the GM cannot see is the invisible behaviour change FR-007a
forbids.
