# Data Model: Persistent Narration Wiki

## Conventions

- Stable IDs match `[a-z0-9][a-z0-9._-]{0,63}` and are supplied explicitly. Timestamps never create authoritative identity.
- Pattern slugs are Unicode-normalized and case-folded; punctuation and whitespace collapse to `-`; the stored result matches `[a-z0-9]+(?:-[a-z0-9]+)*`.
- Serialized paths are POSIX-style and relative to the resolved campaign or session root. Absolute host paths are runtime-only.
- Content hashes are lowercase SHA-256 over exact raw bytes.
- Canonical JSON is UTF-8 with `ensure_ascii=false`, sorted keys, stable list ordering, two-space indentation, and one final newline.
- Read-only artifacts contain no generated timestamp, mtime, random value, unordered collection, or host-specific path.
- Human rationale is preserved verbatim as data but never interpreted as an automatic ruling.

## Entity relationships

```text
CampaignScope
├── NarrationGuidance 1
├── CompanionCapabilityManifest 0..1 (read-only deployment)
├── CampaignTier 0..1
│   ├── WikiPattern *
│   ├── WikiIndexEntry *
│   ├── ConflictRuling *
│   └── ImpactEntry *
└── SessionScope *
    └── WikiIteration *
        ├── TraceManifest 1
        │   └── TraceArtifact *
        ├── MeasurementSnapshot 1..2
        │   ├── MeasurementCheck *
        │   └── ReuseFinding *
        ├── SeedConflictDraft *
        ├── PatternDraft *
        ├── Gate1Ruling *
        ├── PortablePromotionRequest *
        ├── AtomicProposal 0..*
        │   └── CanonicalEvidenceBinding *
        └── TransactionJournal 0..*

OperatorUsabilityResult 0..1 (feature acceptance evidence, not runtime state)
```

## CampaignScope

| Field | Type | Rules |
|---|---|---|
| `campaign_root` | runtime `Path` | Explicit, existing directory, strictly resolved; never serialized as an absolute path. |
| `campaign_id` | string | Stable configured display/audit identity; not used for containment. |
| `session_root` | runtime `Path` | Explicit existing directory and proper descendant of `campaign_root`; empty, root, outside, or escaping-link values are refused. |
| `session_relative` | relative POSIX path | Serialized selected-session identity. |
| `guidance` | `NarrationGuidance` | Resolved from the selected campaign only. |
| `portable_root` | runtime `Path` | Read-only deployment at `~/.claude/narration-wiki/`; absence is explicit. |

### NarrationGuidance

| Field | Type | Rules |
|---|---|---|
| `rulebook` | relative path + SHA-256 | Required readable regular file for measurement and proposals. |
| `voice_files` | sorted map narrator -> path/hash | Every voice mutation target must be an exact member. |
| `example_files` | sorted map narrator -> path/hash list | Every example mutation target must be an exact member. |
| `checker_source` | relative path + SHA-256 | Rulebook-owned structured checker configuration. |
| `guidance_sha256` | SHA-256 | Digest of canonical sorted path/hash/kind rows for the resolved guidance set. |

Resolution never creates directories, probes legacy paths, or borrows another campaign's guidance. Mutation targets reject every symlink component, even when the final resolution remains inside the campaign.

### CompanionCapabilityManifest

Read-only companion-owned `~/.claude/narration-wiki/capabilities.yaml`, validated after YAML parsing against `contracts/companion-capability.schema.json`.

| Field | Type | Rules |
|---|---|---|
| `schema_version` | integer | `1`. |
| `source_repository` | string | Non-empty companion repository identity. |
| `source_revision` | string | Non-empty version or commit identity. |
| `narration_wiki_contract` | integer | Must equal `1`. |
| `guidance_source` | enum | Must equal `campaign-resolved`. |
| `capabilities` | sorted unique enum list | Must contain both `maintainer` and `proposer`. |
| `manifest_sha256` | runtime SHA-256 | Hash of the exact deployed manifest bytes, included in status/audit results. |

Missing, malformed, incompatible, copied-guidance, or missing-role manifests make the companion dependency incomplete. Campaign-local collection and baseline measurement remain usable.

## WikiIteration

One explicitly selected session's durable accumulation cycle.

| Field | Type | Rules |
|---|---|---|
| `schema_version` | integer | `1`. |
| `iteration_id` | stable ID | Unique under the selected session; duplicate collection refuses without rewriting. |
| `campaign_id` | string | Display/audit identity. |
| `session_relative` | relative POSIX path | Exactly one selected session. |
| `corpus_id` | SHA-256 or null | Set by collection and immutable afterward. |
| `state` | enum | Derived from files; never browser-owned. |
| `pattern_counts` | object | Pending, accepted, rejected, and pending-portable-sync counts, derived. |
| `unresolved_conflict_ids` | sorted stable ID list | Derived from drafts and campaign conflict records. |
| `active_proposal_id` | stable ID or null | At most one comparison proposal awaits Gate 2. |
| `recovery` | object or null | Nonterminal journal identity and next safe action. |

### Iteration states

```text
new
  -> collected
  -> measured_before
  -> gate1_review
  -> ready_for_proposal
  -> proposal_staged
  -> comparison_applied
  -> measured_after
  -> awaiting_gate2
  -> completed_accepted | completed_rejected
```

Rules:

- Companion pattern or conflict drafts may be ruled only in `measured_before` or `gate1_review`.
- Each conflict or pattern receives an independent human ruling.
- Rejected, unreviewed, and pending-portable-sync patterns are excluded from proposal input.
- One proposal may be staged or awaiting Gate 2 at a time.
- A nonterminal transaction journal supersedes nominal state and must recover before another mutation.

## TraceManifest

Immutable deterministic inventory created by `collect` and validated by `contracts/manifest.schema.json`.

| Field | Type | Rules |
|---|---|---|
| `schema_version` | integer | `1`. |
| `iteration_id` | stable ID | Matches the parent iteration. |
| `campaign_id` | string | Contains no absolute path. |
| `session_relative` | relative POSIX path | Matches explicit scope. |
| `layouts` | sorted unique enum list | Detected documented layout generations. |
| `artifacts` | sorted `TraceArtifact[]` | Present allowlisted artifacts only. |
| `missing` | sorted rows | Expected role/pattern/reason; never represented as clean. |
| `measurement_corpus` | sorted relative path list | Exact narration documents used for both phases. |
| `corpus_id` | SHA-256 | Digest of canonical path/hash/narrator rows. |

### TraceArtifact

| Field | Type | Rules |
|---|---|---|
| `kind` | enum | `critique`, `narration`, `scene_extraction`, `gm_assist`, `source_record`, `scrub_manifest`, or `generation_settings`. |
| `path` | session-relative POSIX path | Resolved target remains within session and campaign. |
| `sha256` | SHA-256 | Exact bytes read after containment checks. |
| `bytes` | non-negative integer | Raw byte count. |
| `narrator` | string or null | Required for narrator-attributed narration. |
| `layout` | enum | Layout generation that admitted the artifact. |

## MeasurementSnapshot

Canonical artifact validated by `contracts/measurement.schema.json`.

| Field | Type | Rules |
|---|---|---|
| `schema_version` | integer | `1`. |
| `iteration_id` | stable ID | Matches the iteration. |
| `phase` | enum | `before` or `after`. |
| `proposal_id` | stable ID or null | Null for before; required for after. |
| `corpus_id` | SHA-256 | Must equal the manifest and both phases. |
| `guidance` | object | Rulebook path/hash, checker schema version, named D4 profile. |
| `documents` | sorted rows | Exact measured paths, hashes, and narrators. |
| `checks` | sorted `MeasurementCheck[]` | Mechanical D4 categories. |
| `cross_narrator_reuse` | sorted `ReuseFinding[]` | Maximal 3+ word sequences shared by at least two narrators. |

### MeasurementCheck

| Field | Type | Rules |
|---|---|---|
| `key` | enum | `shape_of`, `portable_portrait`, `taxonomy`, `filing_sections`, `bookkeeping_per_narrator`, or `em_dash`. |
| `scope` | enum | `document`, `corpus`, or `narrator`. |
| `subject` | string or null | Document or narrator identity when applicable. |
| `observed` | integer or null | Null only when skipped. |
| `budget` | object or null | Operator, value, and unit; null only when unconfigured. |
| `verdict` | enum | `ok`, `breach`, or `skipped`; never a Gate decision. |
| `reason` | string or null | Required when skipped. |
| `occurrences` | sorted evidence rows | Relative path, line/section/narrator, and matched text. |

### ReuseFinding

| Field | Type | Rules |
|---|---|---|
| `phrase` | normalized visible text | Maximal repeated span only. |
| `word_count` | integer | At least 3. |
| `narrators` | sorted unique string list | At least 2. |
| `occurrences` | sorted evidence rows | Narrator, relative path, line/section, and visible source text. |

### BaselineBinding

Stored in every Gate 1 conflict or pattern ruling.

| Field | Type | Rules |
|---|---|---|
| `measurement_path` | iteration-relative path | Exactly `measurement-before.json`. |
| `measurement_sha256` | SHA-256 | Exact baseline artifact bytes. |
| `corpus_id` | SHA-256 | Equals manifest and current corpus digest. |
| `guidance_sha256` | SHA-256 | Equals current authoritative guidance digest. |
| `profile` | constant | `d4-v1`. |

Missing or mismatched bindings refuse a ruling without writing. Before the first ruling, a changed corpus/guidance may be remeasured. After any ruling, drift requires a new iteration.

## PatternDraft and durable knowledge

### PatternDraft

| Field | Type | Rules |
|---|---|---|
| `slug` | normalized slug | Unique against drafts and both visible indexes. |
| `title` | string | Human-readable. |
| `problem` | Markdown prose | Non-empty and not only a phrase/error list. |
| `root_cause` | Markdown prose | Non-empty and distinct from problem. |
| `corrective_strategy` | Markdown prose | Non-empty and actionable. |
| `evidence` | reference list | At least one manifest artifact or explicitly approved seed source. |
| `conflict_ids` | sorted stable ID list | Every referenced conflict must be resolved before acceptance. |
| `proposed_tier` | enum | `campaign` or `portable`; named canon defaults to campaign. |
| `mentions_campaign_identity` | boolean | Portable placement requires explicit override confirmation. |
| `status` | enum | `pending`, `accepted`, `rejected`, or `pending_portable_sync`. |

### SeedConflictDraft

Companion-produced immutable JSON under the iteration.

| Field | Type | Rules |
|---|---|---|
| `schema_version` | integer | `1`. |
| `conflict_id` | stable ID | Unique in iteration and campaign conflict store. |
| `campaign_id` | string | Exact selected campaign scope. |
| `rule_key` | stable ID | Rule affected by the disagreement. |
| `sources` | sorted list | At least two distinct `{source_ref, source_sha256, statement}` rows. |
| `pattern_slugs` | sorted slug list | Drafts blocked by this conflict. |

No source is automatically preferred because of order, path, or repository.

### ConflictRuling

Durable campaign-scoped JSON validated by `contracts/conflict-ruling.schema.json`.

| Field | Type | Rules |
|---|---|---|
| `schema_version` | integer | `1`. |
| `conflict_id` | stable ID | Canonical campaign conflict identity. |
| `campaign_id` | string | Exact owning campaign. |
| `rule_key` | stable ID | Matches the draft. |
| `sources` | sorted list | Exact source references/digests copied from the draft. |
| `resolution` | non-empty string | Explicit GM-selected resolution. |
| `rationale` | non-empty string | Required human explanation. |
| `iteration_id` | stable ID | Provenance. |
| `baseline` | `BaselineBinding` | Evidence reviewed before ruling. |

### Gate1Ruling

| Field | Type | Rules |
|---|---|---|
| `gate` | constant | `gate1`. |
| `subject_id` | slug | Exactly one pattern draft. |
| `ruling` | enum | `accepted` or `rejected`. |
| `tier` | enum | Explicit even when rejected. |
| `named_portable_override` | boolean | Required true for named/campaign content placed portable. |
| `rationale` | string or null | Required for named portable override. |
| `iteration_id` | stable ID | Provenance. |
| `baseline` | `BaselineBinding` | Required and current. |
| `conflict_ruling_refs` | sorted path/hash list | Every draft conflict must have a durable resolution. |

### WikiPattern

Confirmed Markdown page with YAML frontmatter containing slug, tier, `status: confirmed`, Gate 1 provenance, baseline hash, conflict references, and evidence references. Its body contains literal `Problem`, `Root Cause`, `Corrective Strategy`, and `Evidence` headings.

### WikiIndexEntry

One normalized slug, one relative page link, and a labeled one- or two-sentence problem/root-cause/fix description. Page and entry agree on slug and tier. Slugs collide across campaign and portable tiers.

### PortablePromotionRequest

Local immutable handoff created after portable Gate 1 acceptance. It contains the validated page, baseline and ruling provenance, conflict references, evidence, and expected portable slug. It is not confirmed proposal input until compatible deployed capability metadata and a matching validated portable page are present.

## AtomicProposal

One companion-proposer candidate bound to one authorized target and one confirmed knowledge set.

| Field | Type | Rules |
|---|---|---|
| `schema_version` | integer | `1`. |
| `proposal_id` | stable ID | Unique within iteration and impact ledger. |
| `iteration_id` | stable ID | Parent iteration. |
| `pattern_slugs` | sorted slug list | All confirmed in a visible compatible tier. |
| `affected_rule` | stable ID | Exact rule/category to which evidence bindings must refer. |
| `target_kind` | enum | `rulebook`, `voice`, `example`, or `checker_config`. |
| `target_path` | campaign-relative POSIX path | Exact configured allowlist member; no symlink component. |
| `before_sha256` | SHA-256 | Hash of `before.snapshot`. |
| `after_sha256` | SHA-256 | Hash of `after.snapshot`; differs from before. |
| `diff_sha256` | SHA-256 | Hash of complete display diff. |
| `proposal_fingerprint` | SHA-256 | Canonical target kind/path, affected rule, and before/after digest identity. |
| `reconsideration` | tagged object or null | Required only when an equivalent Rejected impact exists. |
| `state` | enum | See below. |

### CanonicalEvidenceBinding

| Field | Type | Rules |
|---|---|---|
| `source_ref` | manifest artifact ID/path | Provenance only; changing it does not establish novelty. |
| `source_sha256` | SHA-256 | Must exist in the current manifest and be absent from the prior equivalent impact's evidence digests. |
| `applies_to_kind` | enum | `rule` or `measurement_category`. |
| `applies_to_key` | stable ID | Must equal the proposal's affected rule or an applicable measurement key. |

`reconsideration` is exactly one of:

- `{kind: new_evidence, bindings: CanonicalEvidenceBinding[1..]}`
- `{kind: gm_override, rationale: non-empty human string}`

The companion draft may propose new-evidence bindings. Only the GM supplies an override through the staging CLI/UI action.

### Proposal states

```text
drafted
  -> staged
  -> comparison_applied
  -> measured_after
  -> awaiting_gate2
  -> accepted | rejected
```

Rules:

- Staging creates exact before/after snapshots and a display diff; it changes no target.
- Staging refuses an equivalent prior rejection before comparison unless reconsideration qualifies.
- Comparison application requires current target hash equal to `before_sha256` and writes exact after bytes.
- After measurement requires target hash equal to `after_sha256` and corpus ID equal to the baseline corpus.
- Gate 2 Accept requires the after hash and leaves those bytes in place.
- Gate 2 Reject requires the after hash and restores exact before bytes.
- Stale, unauthorized, duplicate, or invalid-state proposals produce no unjournaled partial state.

## ImpactEntry

Immutable section appended to `<campaign>/wiki/skill-impact.md`.

| Field | Type | Rules |
|---|---|---|
| `proposal_id` | stable ID | Unique ledger key; duplicate append refuses unchanged. |
| `proposal_fingerprint` | SHA-256 | Used for equivalent-rejection lookup. |
| `iteration_id` / `session_relative` | IDs | Selected-session provenance. |
| `corpus_id` | SHA-256 | Same before and after. |
| `pattern_slugs` | sorted slug list | Confirmed inputs. |
| `affected_rule` | stable ID | Matches proposal and evidence bindings. |
| `target_kind/path` | enum/path | One authorized file. |
| `before_sha256` / `after_sha256` | SHA-256 | Exact target states. |
| `diff` | complete unified diff | Embedded display evidence. |
| `before_measurement` / `after_measurement` | artifact path/hash + summaries | Both required. |
| `ruling` | enum | `Accepted` or `Rejected`. |
| `reconsideration` | tagged object or null | Exact staged evidence bindings or GM override; mutually exclusive. |

The Markdown ledger contains a machine-recognizable proposal marker and fenced structured data. There is no second JSON ledger.

## OperatorUsabilityResult

Acceptance-only JSON at `specs/020-narration-wiki/validation/usability-result.json`, validated by `contracts/usability-result.schema.json`.

| Field | Type | Rules |
|---|---|---|
| `schema_version` | integer | `1`. |
| `campaign_id` / `session_relative` / `iteration_id` | IDs | Exact exercised flow. |
| `viewport` | object | Exactly `{width: 1280, height: 720}`. |
| `panel_minimum` | object | Exactly `{width: 320, height: 160}`. |
| `start_condition` | constant string | Page opened with explicit selected session. |
| `end_condition` | constant string | Gate 2 ruling persisted. |
| `total_elapsed_seconds` | non-negative integer | Wall-clock elapsed duration. |
| `excluded_model_response_seconds` | non-negative integer | Separately observed companion-model wait. |
| `active_operator_seconds` | non-negative integer | Exactly total minus excluded; passing requires `< 900`. |
| `gate1_ruling_ref` / `gate2_ruling_ref` | relative path + SHA-256 | Persisted proof of both checkpoints. |
| `persisted_ruling_path` | relative path | Durable impact/ruling location. |
| `passed` | boolean | True only when timing, Gate references, and ruling checks pass. |
| `notes` | string | Optional human context; not used to calculate pass. |

## TransactionJournal

Crash-recovery record for a mutation spanning more than one file.

| Field | Type | Rules |
|---|---|---|
| `transaction_id` | stable ID | Derived from iteration, subject, and operation. |
| `operation` | enum | `conflict_rule`, `gate1_campaign`, `gate1_portable_handoff`, `gate2_accept`, or `gate2_reject`. |
| `state` | enum | `intent`, `target_done`, `ledger_done`, `committed`, `rolled_back`, or `needs_attention`. |
| `preconditions` | sorted file/hash rows | Verified while holding the campaign lock. |
| `writes` | sorted file/before/after rows | Exact intended results. |
| `next_action` | enum/string | Deterministic recovery step. |

Mutations hold a cross-process campaign-wiki lock across read/check/write. Each file uses a sibling temporary file, fsync where supported, and atomic replace. Recovery is idempotent and hash-checked. Actual bytes matching neither expected state become `needs_attention` and are never guessed through.

## Disk layout

```text
<session>/narration_wiki/<iteration-id>/
├── iteration.json
├── trace-manifest.json
├── measurement-before.json
├── gate1.json
├── conflict-rulings.json           # path/hash references to durable rulings
├── drafts/
│   └── <slug>.md
├── conflict-drafts/
│   └── <conflict-id>.json
├── portable-promotions/
│   └── <slug>.md
├── proposals/
│   └── <proposal-id>/
│       ├── draft.yaml
│       ├── candidate
│       ├── proposal.json
│       ├── before.snapshot
│       ├── after.snapshot
│       ├── change.diff
│       ├── measurement-after.json
│       └── gate2.json
└── transactions/
    └── <transaction-id>.json

<campaign>/wiki/
├── index.md
├── patterns/
│   └── <slug>.md
├── conflicts/
│   └── <conflict-id>.json
├── skill-impact.md
└── logs.md

~/.claude/narration-wiki/           # read-only companion deployment
├── capabilities.yaml
├── index.md
└── patterns/
    └── <slug>.md

specs/020-narration-wiki/validation/
└── usability-result.json           # created only by the acceptance exercise
```

Creating `<campaign>/wiki/` is a confirmed mutation, never a read/startup side effect. Existing campaigns without wiki state remain valid.
