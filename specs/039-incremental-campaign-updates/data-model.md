# Data Model: Incremental Campaign Grounding and NPC Updates (039)

All records are JSON (machine state) or Markdown (human-facing), stored on disk under the campaign (Principle I). Each record carries `schema_version`. None of them modifies a `StrictPromotionModel` subclass (research R8). Digests are sha256 over exact bytes.

## DeltaPlan

| Field | Notes |
|---|---|
| `plan_id`, `operation_version` | Stable identity; a plan is immutable once created |
| `campaign_identity` | Existing canonical campaign identity; never rewritten (FR-022) |
| `products` | Subset of {`grounding`, `npc`} |
| `stopping_point` | One of: plan, prepare, propose, verify, review, preview, apply |
| `sources` | Explicit list of `{path, sha256, chapter, kind: new}`. Empty list is refused. |
| `models` | Backend, model and effort for generation and consistency (FR-010) |
| `grounding_baseline_ref`, `npc_baselines` | Refs to the bindings below |
| `census` | Per-subject disposition (see NpcCensusEntry) |
| `created_at`, `revision` | Plan revisions are explicit; a changed plan invalidates downstream checks |

## SourceSelection

Each entry records parse versus custody.

| Field | Notes |
|---|---|
| `path`, `sha256` | Exact bytes |
| `role` | `parsed_new`, `parsed_historical`, `reused_artifact`, `integrity_only`, `model_input` |
| `read_count` | Count of reads, separately per role (SC-001) |

## GroundingBaseline

| Field | Notes |
|---|---|
| `generation_id`, `manifest_sha256` | Active immutable generation |
| `documents` | Four entries: `{name, origin_sha256, live_sha256, origin_ref, approval_ref}` |
| `adoption` | Present only after explicit adoption; `{adopted_at, drift: [{hunk, disposition}]}`. Unreviewed drift blocks use. |
| `members` | Timeline, reference tree, reading-contract records: `{name, sha256, coverage_through, gaps[], audience}` |
| `coverage` | Per member. Live prose through 74 does not raise the coverage of an inherited timeline through 72. |

**States**: `unadopted` → `adopted` (explicit) → `superseded` (new generation adopted). Unreviewed drift keeps the baseline in `unadopted`.

## NpcBaseline

| Field | Notes |
|---|---|
| `subject` | Canonical name (registry) |
| `publication` | Entry from `publish_log.json`: `{published_sha256, body_sha256, horizon}` |
| `draft`, `evidence`, `composition` | Digests of the reviewed draft, the cached evidence and the composed authored file |
| `horizon` | Actual last horizon, which may differ per subject |
| `attestations` | Later unchanged attestations, each with its own id |
| `status` | `ok`, or `repair_required: <named reason>` (broken lineage, hand-edited target, missing evidence) |

A newer unpublished draft is never a baseline.

## EvidenceContext

| Field | Notes |
|---|---|
| `kind` | `full` or `sparse`. Sparse can never be presented as full. |
| `targets` | Exact available targets: `{chapter, kind: scene|entry|moment, id, span}` |
| `inherited_targets` / `new_targets` | Distinguishes baseline evidence from selected-source evidence |
| `digests` | Per artifact |
| `associations` | Reviewed associations only (see Association) |
| `authority_rules` | Authority, audience and rule-version digests |
| `missing_scope`, `unexamined_scope` | Kept separate. Missing required support blocks; unexamined is disclosed. |

## NpcCensusEntry

`disposition` is one of: `changed`, `new`, `mentioned_unchanged`, `absent_from_selected`, `deferred`, `excluded`, `unresolved`. Each entry records its evidence spans and the ruling that produced it. An unregistered name and a deliberate exclusion are different dispositions.

## Association

| Field | Notes |
|---|---|
| `canonical_id` | From the registry. An association never creates an alias. |
| `source` | Exact revision, scene and span |
| `relationship_support` | Quoted support |
| `rationale`, `scope`, `audience` | Scope is exact (for example, "faction offer", not "deployed") |
| `decision` | `approved`, `rejected`, `discuss`, `unresolved`. Only `approved` can enter drafting evidence. |
| `reviewer`, `decision_revision` | Explicit |

## EditProposal (grounding)

| Field | Notes |
|---|---|
| `target_id` | Stable line identifier assigned by the host to the bound baseline |
| `before_sha256` | Host-computed from the baseline line; the model never supplies before-text |
| `after_text` | Proposed bytes |
| `category` | `new_information`, `superseded_state`, `resolved_thread`, `historical_event`, `no_material_change` |
| `rationale`, `support` | Exact selected-source span |
| `dependent_checks` | Required follow-up (heading, table, citation, consistency) |
| `decision` | Per proposal: `approved`, `rejected`, `discuss`, unset. Unset or discuss blocks reconstruction. |

**Validation**: unknown, duplicate or overlapping `target_id` is rejected. A stale `before_sha256` is rejected. An empty proposal set needs an explicit justification.

## ReviewBinding

Exact hashes of the candidate, plan, evidence and rules; item and document decisions; reviewer; decision revision; approval scope (`draft`, `attestation`, `association`, `publication`, kept distinct); inherited and outstanding findings. A change to any bound hash makes the binding stale.

## Attestation

| Field | Notes |
|---|---|
| `publication_sha256` | The exact published dossier it attests to |
| `added_sources`, `added_evidence`, `links` | Exact identities |
| `rulings` | Identity, authority and rule digests in force |
| `reason` | The GM's reason, required |
| `scope` | The horizon it covers |

An attestation never edits the dossier. The original bytes and their horizon are kept.

## RunState

| Field | Notes |
|---|---|
| `run_id`, `schema_version`, `plan_ref` | |
| `stages` | Ordered list: `{name, status, artifacts[{path, sha256}], started_at, finished_at}` |
| `status` | `running`, `failed`, `stale`, `awaiting_review`, `partial`, `recovery_required`, `complete` (complete means the stopping point is reached for every required member) |
| `members` | `{subject, outcome, receipt_ref}` per member. Outcome is `published`, `held`, `rejected`, `unchanged`, `failed`. |
| `counts` | Parsed-source and integrity-read counts; model calls; checks |

**Transitions**: a stage may be retried by digest. A completed stage whose inputs have not changed is reused without a model call. A failed or incomplete output is never a success. Restart reads this file, not browser state.

## Receipt

`selected_chapters`, `inherited_coverage_and_gaps`, `changed/new/carried/held` lists, `publication_hashes` (exact output digests), `checks`, `decisions` (with revisions), `read_counts`, `call_counts`, `recovery_state`. It contains no capability URLs or access tokens (FR-023).
