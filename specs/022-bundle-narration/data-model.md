# Data Model: Bundled Narration Generation

**Feature**: 022-bundle-narration | **Date**: 2026-09-05

The design adds no database and does not replace existing narration files. These records are runtime or report shapes around the current disk-backed workflow.

## 1. NarrationScene

One selected section from the human-reviewed plan, fully prepared before a bundle call.

| Field | Type | Meaning |
|---|---|---|
| `index` | positive integer | Stable 1-based position in the complete plan; response attribution key. |
| `scene_name` | string | Exact plan scene name; may be duplicated across different indices. |
| `narrator` | string | Assigned point-of-view character from the plan. |
| `focus` | string | Human-reviewed focus for this narration section. |
| `source_path` | path | Exact eligible extraction chosen for this scene. |
| `source_kind` | `base` or `override` | Whether `source_path` came from `--scene-extractions` or `--scene-extraction-file`; it does not guess raw/smoothed semantics. |
| `scene_events` | string | Authoritative scene account used as structural scope. |
| `moments` | string | Extracted moments and verbatim quotes for this scene. |
| `voice_note` | string or null | Guidance declared for this narrator. |
| `character_examples` | string or null | Narrator-specific examples. |
| `previous_narrator` | string or null | Plan narrator immediately before this full-plan index. |
| `previous_voice_sample` | string or null | Contrast sample when the prior narrator differs. |
| `estimated_output_tokens` | positive integer | Existing scene narration estimate used for bundle preflight. |
| `output_path` | path | Existing per-scene narration destination. |
| `output_existed` | boolean | Whether the explicit bundle will replace an existing artifact. |

**DM-1**: `index` is assigned from the full plan before filtering. A subset such as scenes 2 and 5 remains `[2, 5]`, never `[1, 2]`.

**DM-2**: Every selected index resolves to exactly one source. A supplied exact-file override wins for its matching scene; otherwise the configured extraction directory supplies it.

**DM-3**: All selected scenes must be valid and fully prepared before client creation. One invalid record invalidates the whole request set.

## 2. BundleSelection

The operator's explicit, ordered narration scope and run-wide choices. Derived for each run; not persisted as a default selection.

| Field | Type | Meaning |
|---|---|---|
| `scenes` | non-empty list of `NarrationScene` | Selected scenes in full-plan order. |
| `replacement_scenes` | list of `NarrationScene` | Selected scenes whose output already exists. |
| `backend` | string | Effective text backend. |
| `model` | string or null | Effective model selection. |
| `provider_batch` | boolean | Whether Message Batches submission is selected. |
| `bundle_ceiling` | positive integer | Maximum output tokens requested for the single exchange. |
| `projected_output_tokens` | positive integer | Sum of scene estimates plus protocol overhead. |
| `prose_mode` | boolean | Shared narration setting. |
| `reflections` | boolean | Whether shared campaign history is included. |

**DM-4**: `scenes` must be non-empty, unique by index, in full-plan order, and exactly equal to the scene identities reported before the call.

**DM-5**: `projected_output_tokens > bundle_ceiling` is a refusal. Bundling never silently becomes two or more model exchanges.

**DM-6**: `replacement_scenes` is informational and auditable. Existing output does not imply skip; current narration reruns replace explicitly selected files.

**DM-6a**: `--narrator` is not a `BundleSelection` field. Combining it with `--batch-scenes` is refused because existing sequential narrator filtering changes index interpretation; explicit `--scene` is the bundled subset mechanism.

## 3. SharedNarrationContext

Run-wide input emitted once in the bundle prompt.

| Field | Type | Meaning |
|---|---|---|
| `base_rules` | string | General first-person, ordering, expansion, and prohibited-move rules. |
| `genre` | string or null | Campaign genre/register guidance. |
| `shared_examples` | string or null | Campaign-wide style examples. |
| `party` | string or null | Party document. |
| `class_roster` | string | Definitive character roles/classes. |
| `npc_roster` | string | Canonical spellings for narration outside quotes. |
| `campaign_context` | list of strings | Optional history used for reflections. |
| `prose_rules` | string or null | Mechanical-language and table-speech rules. |

**DM-7**: Each shared field appears at most once in the constructed request, regardless of scene count.

**DM-8**: Narrator-private voice notes and examples do not belong in this entity; they stay scoped to their `NarrationScene` packet.

## 4. BundleExchange

The single model request and raw response.

| Field | Type | Meaning |
|---|---|---|
| `selection` | `BundleSelection` | Exact run scope and settings. |
| `system_prompt` | string | Shared rules and context. |
| `user_prompt` | string | Ordered scene packets and response protocol. |
| `raw_response` | string | Accumulated response returned by the existing backend seam. |
| `exchange_count` | literal `1` | Contractual model-exchange count for any started bundle. |

**DM-9**: Provider batching changes submission of this exchange, not its contents or count.

**DM-10**: Scene packets appear in `selection.scenes` order, and the response contract requires the same order.

## 5. BundleSceneSection

The deterministic parse result for one requested plan index.

| State | Condition | Write behavior |
|---|---|---|
| `complete` | One matching BEGIN/END pair in request order with a non-empty body. | Atomically write the ordinary per-scene narration file. |
| `empty` | Matching closed pair whose body is blank after trimming. | Do not write; report missing output. |
| `incomplete` | BEGIN exists but matching END is absent. | Do not write; report incomplete. |
| `absent` | No BEGIN exists for a requested index. | Do not write; report absent. |

An exchange-level `unreconcilable` result occurs for an unknown index, duplicate index, nested marker, mismatched name, mismatched BEGIN/END index, out-of-order section, or response with no recognized section. These marker-shape rules are checked against the raw response before `split_batched_response`, because the shared splitter's normalized result cannot reveal a stray mismatched END or original encounter order.

**DM-11**: Attribution uses `index`. `scene_name` is an exact checksum after whitespace normalization; it is never a fuzzy lookup key.

**DM-12**: Marker lines are transport syntax and never appear in written narration bodies.

**DM-13**: `unreconcilable` writes no scene from the exchange. A valid partial may write its closed complete sections.

## 6. NarrationBundleRunReport

Atomic JSON written for every bundle attempt after its report destination is initialized. CLI users inspect it directly; the editor route validates its nonce-scoped report after `stream_subprocess(..., emit_done=False)` finishes and before emitting its own terminal event. Full schema: [contracts/run-report.md](./contracts/run-report.md).

| Field | Type | Meaning |
|---|---|---|
| `version` | integer | Report schema version, initially `1`. |
| `run_id` | string | Invocation nonce; unique for editor runs and echoed in the nonce-scoped report. |
| `mode` | literal `bundle` | Distinguishes this result from sequential narration. |
| `status` | enum | `success`, `partial`, `unreconcilable`, `refused`, or `failed`. |
| `exit_code` | integer | CLI result corresponding to status. |
| `requested` | list of scene summaries | Exact explicit selection. |
| `replaced` | list of scene summaries | Requested outputs that existed before the run. |
| `written` | list of scene summaries | Files written by this run. |
| `missing` | list of scene summaries | Empty, incomplete, or absent responses. |
| `rejected` | list of issue objects | Protocol or preflight problems. |
| `provider_batch` | boolean | Effective pricing/submission mode. |
| `exchange_count` | integer | `0` for refusal before a call; otherwise `1`. |
| `projected_output_tokens` | integer | Preflight projection. |
| `bundle_ceiling` | integer | Requested single-exchange output ceiling. |
| `report_path` | path | Location of this report. |

**DM-14**: `written` names only files produced by this invocation. Pre-existing files for missing scenes never appear there.

**DM-15**: Status transitions are terminal:

```text
prepared ──preflight refusal──────────────► refused (exit 1, exchanges 0)
prepared ──call error─────────────────────► failed (exit 1, exchanges 1)
prepared ──unreconcilable response────────► unreconcilable (exit 4, no writes)
prepared ──fewer than all complete────────► partial (exit 3, including zero writes)
prepared ──all complete───────────────────► success (exit 0)
```

**DM-16**: Once the report destination is initialized, every terminal path writes it atomically before process exit, including preflight refusal, backend failure, zero-write partial, and protocol failure. The editor accepts only its nonce-scoped path with the expected `run_id` and requested selection.

## 7. NarrateKnobs addition

One additive persisted field in `server/session_editor_config_shared.py`:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `batch_tokens` | positive integer | `32000` | Output ceiling for one bundled narration exchange. |

**DM-17**: Bundle activation is not persisted here. It is an explicit run action in the CLI or editor.

**DM-18**: `batch_tokens` and existing `tokens` are independent. `tokens` remains the sequential per-scene cap; changing either never changes the other.

## 8. Editor activity entry

The existing `.cg/activity.jsonl` row keeps `stage: "narrate"` and extends its details for bundled runs:

| Field | Type | Meaning |
|---|---|---|
| `scene` | integer or absent | Existing single-scene identity; absent for a bundle. |
| `run_id` | string or absent | Nonce linking a bundled activity row to its unique run report. |
| `scenes` | list of integers or absent | Exact bundled selection. |
| `outputs` | list of paths | Report-derived files written by the run. |
| `knobs.mode` | `sequential` or `bundle` | Content-generation mode. |
| `knobs.provider_batch` | boolean | Separate provider submission state. |
| `knobs.batch_tokens` | integer or absent | Bundle ceiling. |
| `knobs.exchange_count` | integer or absent | Report-derived count. |

**DM-19**: Per-scene knob sidecars are updated only for entries in the run report's `written` list, including a partial run. This prevents old files from acquiring false provenance.
