# Artifact Contract: Persistent Narration Wiki

This contract defines the authoritative files shared by the library, CLI, HTTP adapter, and browser UI. Browser state is never authoritative.

## Common rules

- Every command requires an explicit campaign directory, session directory, and iteration ID.
- Serialized paths are POSIX-style and relative to the selected campaign, session, or iteration root stated by the field.
- Absolute host paths, generated timestamps, random identifiers, mtimes, and unordered collections are forbidden in deterministic read-only artifacts.
- JSON is UTF-8, sorted by key, indented by two spaces, and ends with one newline.
- Content digests are lowercase SHA-256 over exact bytes.
- Stable IDs match `[a-z0-9][a-z0-9._-]{0,63}`.
- Pattern slugs match `[a-z0-9]+(?:-[a-z0-9]+)*` after Unicode normalization and case folding.
- A schema violation is a hard failure. Consumers do not guess missing values or silently upgrade state.
- Read-only operations do not create directories or files.

## Layout

```text
<session>/narration_wiki/<iteration-id>/
├── iteration.json
├── trace-manifest.json
├── measurement-before.json
├── gate1.json
├── conflict-rulings.json
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

~/.claude/narration-wiki/
├── capabilities.yaml
├── index.md
└── patterns/
    └── <slug>.md
```

The campaign wiki directory is created only by a confirmed campaign-tier Gate 1 operation. The portable directory is owned by the companion repository and is always read-only to CampaignGenerator.

## `iteration.json`

This is the disk-derived workflow projection.

Required fields:

| Field | Contract |
|---|---|
| `schema_version` | Integer `1`. |
| `iteration_id` | Stable ID supplied by the operator. |
| `campaign_id` | Configured campaign identity. |
| `session_relative` | Selected session path relative to campaign. |
| `corpus_id` | SHA-256 after collection; null only in `new`. |
| `state` | One lifecycle state from the data model. |
| `pattern_counts` | Counts for pending, accepted, rejected, and pending-portable-sync drafts. |
| `unresolved_conflict_ids` | Sorted stable IDs. |
| `active_proposal_id` | Stable ID or null; at most one proposal awaits Gate 2. |
| `recovery` | Null or the nonterminal transaction and next safe action. |

Status readers derive or validate this projection against surrounding artifacts. They do not trust a browser-submitted state.

## `trace-manifest.json`

Created by `collect` and validated by [manifest.schema.json](manifest.schema.json).

- It inventories only allowlisted artifacts inside the selected session and campaign.
- Every present artifact records its kind, session-relative path, exact SHA-256, byte length, layout generation, and narrator when applicable.
- Expected but absent roles appear in the sorted `missing` list with a reason.
- `measurement_corpus` names the exact narration documents used for both measurements.
- `corpus_id` binds the sorted corpus path/hash/narrator rows.
- Re-running collection for an existing iteration is a conflict and does not rewrite the manifest.

## `measurement-before.json` and `measurement-after.json`

Both validate against [measurement.schema.json](measurement.schema.json).

They record:

- iteration, phase, corpus, and guidance digests;
- exact measured document path/hash/narrator rows;
- structured results for all named D4 checks;
- skipped checks with explicit reasons;
- maximal cross-narrator repeated sequences of three or more words;
- source locations sufficient for the CLI and UI to display evidence.

Measurements never encode a Gate decision. `measurement-after.json` is valid only when its corpus ID equals the baseline corpus ID and the active target bytes equal the proposal's expected comparison hash.

## Baseline binding

Every Gate 1 conflict or pattern ruling embeds:

| Field | Contract |
|---|---|
| `measurement_path` | Exactly `measurement-before.json` relative to the iteration. |
| `measurement_sha256` | Exact bytes of that artifact. |
| `corpus_id` | Equals both manifest and current corpus digest. |
| `guidance_sha256` | Equals current resolved campaign guidance. |
| `profile` | Named measurement profile, initially `d4-v1`. |

If corpus or guidance changes before any Gate 1 ruling, the operator may re-run baseline measurement. After the first conflict or pattern ruling, drift requires a new iteration.

## Pattern drafts and Gate 1

Companion-produced pattern drafts are Markdown files with YAML frontmatter. Required semantic fields are:

- slug, proposed tier, evidence references, and referenced conflict IDs;
- Problem, Root Cause, Corrective Strategy, and Evidence sections;
- explicit campaign-identity marker when named canon appears.

`gate1.json` records one independent human ruling per draft:

- `accepted`, `rejected`, or `pending_portable_sync`;
- selected tier;
- baseline binding;
- referenced durable conflict ruling paths and hashes;
- explicit named-portable override and rationale when required.

A pattern cannot be accepted while any referenced seed conflict is unresolved. Campaign acceptance atomically writes the confirmed page, updates the index, appends a log entry, and records the ruling. Portable acceptance creates only an immutable promotion request; it does not modify the companion deployment.

## Seed conflicts

The companion may write `conflict-drafts/<conflict-id>.json` containing:

- schema version, conflict ID, campaign ID, and affected rule key;
- at least two distinct source reference/hash/statement rows;
- sorted pattern slugs blocked by the disagreement.

No source wins because of repository, path, or list order.

`conflict-rule` writes `<campaign>/wiki/conflicts/<conflict-id>.json`, validated by [conflict-ruling.schema.json](conflict-ruling.schema.json). It contains the copied source set, GM resolution and rationale, iteration provenance, and baseline binding. `conflict-rulings.json` stores only iteration-local path/hash references to those durable rulings.

## Companion capability manifest

CampaignGenerator reads `~/.claude/narration-wiki/capabilities.yaml` and validates the parsed value against [companion-capability.schema.json](companion-capability.schema.json).

The document declares:

- `schema_version: 1`;
- source repository and immutable source revision;
- `narration_wiki_contract: 1`;
- `guidance_source: campaign-resolved`;
- a sorted capability list containing `maintainer` and `proposer`.

Missing, malformed, incompatible, or incomplete metadata produces explicit dependency status. It never triggers a repository write or fallback to copied guidance.

## Proposal bundle

`proposal-stage` validates and persists one proposal directory without changing the target.

`proposal.json` binds:

- proposal and iteration IDs;
- confirmed pattern slugs and affected rule;
- exactly one authorized target kind and campaign-relative path;
- exact before and after hashes;
- full diff and snapshot hashes;
- a deterministic proposal fingerprint;
- either canonical new-evidence bindings or a GM-supplied override rationale.

Each new-evidence binding is:

```json
{
  "source_ref": "relative/source/reference",
  "source_sha256": "64 lowercase hex characters",
  "applies_to_kind": "rule",
  "applies_to_key": "affected-rule"
}
```

The digest must be present in the current manifest, absent from prior equivalent rejected impacts, and bound to the proposal's affected rule or measurement category. Moving identical bytes to a new path is not new evidence. A GM override is supplied only through the staging action; a companion draft cannot authorize itself.

Gate 2 consumes only the staged basis. It cannot add evidence or rationale after comparison.

## Comparison and Gate 2

- `proposal-apply` first requires the live target hash to equal `before_sha256`, then installs exactly `after.snapshot` for comparison.
- `measure --phase after` requires the live target hash to equal `after_sha256` and the corpus to equal the baseline corpus.
- Gate 2 `accept` retains the exact comparison bytes.
- Gate 2 `reject` restores the exact `before.snapshot` bytes.
- Either decision appends exactly one impact record and persists `gate2.json`.
- A stale hash, duplicate proposal ID, invalid state, or unauthorized target refuses without an unjournaled partial mutation.

## `skill-impact.md`

This is the sole durable proposal-impact ledger. Each append-only record includes:

- a machine-recognizable proposal ID and fingerprint;
- iteration, selected session, corpus, patterns, and affected rule;
- target kind/path and before/after hashes;
- complete unified diff;
- before/after measurement references and summaries;
- `Accepted` or `Rejected`;
- the exact staged reconsideration basis, if any.

Equivalent rejected proposals are blocked before staging unless the canonical new-evidence test passes or the GM supplies a non-empty override rationale.

## Transaction journals

Mutations spanning files hold one campaign-wiki process lock and write a hash-bound journal before the first target change. Files are written through sibling temporary files and atomic replacement.

Recovery is idempotent:

- an expected before or after hash determines the next documented step;
- `committed` and `rolled_back` transactions are terminal;
- bytes matching neither expected value produce `needs_attention`;
- recovery never guesses or silently overwrites unknown bytes.

## Acceptance evidence

The post-implementation operator exercise writes `specs/020-narration-wiki/validation/usability-result.json` and validates it against [usability-result.schema.json](usability-result.schema.json).

It records the exact start and end instants, total wall time, separately observed companion-model response time, computed active operator time, the 1280x720 viewport, 320x160 minimum panel size, Gate 1 and Gate 2 artifact references, the persisted ruling path, and the calculated pass result. Passing requires active operator time below 900 seconds.
