# Data Model: Source-Custody Rebase (spec 040)

All records are files on disk (Principle I). New pydantic models use `extra="forbid"` and are **not** subclasses of `StrictPromotionModel`, matching `delta/lineage.py` (R8 of spec 039). Paths are campaign-relative.

## On-disk layout (new)

```
docs/summaries/delta/custody/objects/<sha256>        write-once content-addressed bytes (R2)
docs/summaries/delta/rebase/<rebase_id>/
    inspection.json        StaleCustodyReport  (also printed by `rebase inspect --json`; written only by `rebase prepare`)
    snapshots.json         list[CustodySnapshot]
    impact.json            ImpactSet
    decisions-r<N>.json    RebaseDecisions (revisioned, append-only)
docs/summaries/delta/plans/<plan_id>-r<N>.json       DeltaPlan, now with kind="rebase" for rebase plans
docs/summaries/delta/plans/rebind-<plan_id>-r<N>.json RebindRecord
```

The grounding edits, candidates, lineage, check, review bindings, preview, receipts and staged range all use spec 039's existing locations under the rebase plan's id.

## Entities

### StaleCustodyEntry
| Field | Type | Rule |
|---|---|---|
| chapter | int | from `_custody_rows` |
| path | str | campaign-relative |
| expected_sha256 | sha256 | the pin |
| actual_sha256 | sha256 \| `"missing"` | current bytes |
| pinned_by | str | generation id in the chain that recorded the pin |
| old_bytes | list[{provider, available: bool, detail}] | providers probed, read-only |

### StaleCustodyReport
`generation_ref` (`gid@manifest_sha`), `plan_ref` (optional), `checked` (int), `stale` (list[StaleCustodyEntry]), `integrity_reads` (int). Inspection never writes a file unless it is called through `prepare`.

### CustodySnapshot
`chapter`, `path`, `role: old|current`, `sha256`, `size`, `provider: snapshot|git|file`, `provider_detail` (Git blob id, or the supplied path). Invariant: `objects/<sha256>` exists and hashes to `sha256`.

### ImpactSet (per rebase)
- `sources`: list of
  - `{chapter, old_sha256, new_sha256, entries: [{entry, status: changed|removed|unchanged, old_span, new_span}], diff_ref}`
- `affected_lines`: list of
  - `{line_id, document, line_no, line_sha256, citation, chapter, entry, reason: changed|removed|whole_chapter, origin: baseline|pending}`
- `affected_annotations`: list of
  - `{annotation_id, source_sha256, span}`
- `unknown_members`: list of
  - `{member, reason: cites_selected|no_citations}`
- `followup_consumers`: list of
  - `{path, sha256, chapters}` (published NPC dossiers and others; read-only)
- `impact_sha256`: canonical digest of all of the above

`line_id` = `<document>#<sha256(line bytes)[:12]>@<occurrence>`. This makes it stable against unrelated line-number shifts.

### RebaseDecisions (revisioned)
| Field | Rule |
|---|---|
| rebase_id, revision | append-only `decisions-r<N>.json` |
| reviewer | required, never defaulted |
| sources | `{chapter: adopt-unaffected \| adopt-with-repairs \| reject, reason}`; exactly one per selected chapter |
| unknown_members | `{member: repaired \| held \| attested-unaffected, reason}`; reason required; attested ≠ verified |
| bound | `{snapshots_sha256, impact_sha256, baseline_ref, edits_sha256}` |

**Validation (FR-009):**
- `adopt-unaffected` is refused if the chapter has any `affected_lines` or `affected_annotations`.
- `adopt-with-repairs` is refused while any affected line in that chapter lacks an approved repair or an explicit hold (edit decisions are recorded with `delta grounding decide`).
- Any unruled unknown member blocks everything.
- A `reject`ed chapter is removed from the rebase sources and stays stale.

### DeltaPlan (extended)
New optional `kind: "delta" | "rebase"` (default `"delta"`, omitted from the canonical digest when it is the default, R10). A rebase plan has:

- `products == ("grounding",)`;
- `sources` = the selected corrected summaries at their current digests;
- `rebase_id` set.

### DeltaLineageRecord (extended)
New optional `rebase` block:

```
{rebase_id, decisions_ref, decisions_sha256,
 sources: [{chapter, path, old_sha256, new_sha256, old_snapshot, current_snapshot}],
 repaired_lines, held_lines, attested_members, unchanged_members}
```

It is present only on rebase plans. `kind` stays `"delta"`, so `claims/selection.py:delta_inherited_custody` and `_delta_parent` follow it unchanged (research R1).

### Staged range manifest (rebase)
`{"kind": "custody_rebase", "range": {"since", "until", "gaps": [unselected chapters]}, "files": [selected only, new sha256]}`

### RebindRecord
`plan_id`, `from_revision`, `to_revision`, `old_baseline_ref`, `new_baseline_ref`, `rebase_id`, `npc_carried: [{scope, plan_sha256_from}]`, `npc_projection_sha256`, `invalidated: [artifact paths]`, `stale_edits: [proposal ids]`, `reapplied_edits: [proposal ids]`.

### RebaseReceipt (extends the 039 receipt)
Adds:
- `rebase_id`;
- `sources_and_decisions`;
- `integrity_reads`;
- `parsed_historical`;
- `cached_evidence_reused`;
- `model_input_sources`;
- `model_calls`;
- `unselected_stale_remaining`;
- `followup_consumers`;
- `new_generation_ref`;
- `parent_generation_ref`.

## State transitions (rebase plan)

```
inspected → prepared (snapshots+impact) → [proposed] → decided → checked → previewed(staged)
         → claims+signoffs → applied (new generation active) → [pending plan rebound]
```

Any bound-input change moves the plan back to the earliest stage whose binding broke (exit 3). Apply is journaled by the existing promotion writer, and `delta run status` / `grounding recover` report and repair an interrupted apply.
