# CLI Contract: `narration_wiki`

The console script is the complete deterministic engine. The FastAPI router only validates transport inputs, constructs this fixed argument vocabulary, and executes it through the shared subprocess boundary.

## Invocation

```text
narration_wiki COMMAND
  --campaign-dir PATH
  --session-dir PATH
  --iteration-id ID
  [COMMAND OPTIONS]
  [--json]
```

The three scope options are required on every command. Empty values are invalid. `session-dir` must resolve to a proper descendant of `campaign-dir` without traversing a symlink outside the campaign.

`--json` changes the final result to one compact JSON object. Workflow commands may emit progress lines before the final object; the server transports those lines as SSE. Status emits exactly one JSON object.

## Commands

### `status`

```text
narration_wiki status SCOPE --json
```

Read-only. Returns a bounded projection derived from files:

```json
{
  "ok": true,
  "iteration_id": "iter-001",
  "state": "measured_before",
  "corpus_id": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "pattern_counts": {
    "pending": 2,
    "accepted": 0,
    "rejected": 0,
    "pending_portable_sync": 0
  },
  "unresolved_conflict_ids": ["seed-voice"],
  "active_proposal_id": null,
  "dependency": {
    "present": true,
    "compatible": true,
    "source_revision": "companion-revision",
    "capabilities": ["maintainer", "proposer"]
  },
  "recovery": null
}
```

It creates no directory, file, or log.

### `collect`

```text
narration_wiki collect SCOPE --json
```

Read-only with respect to source artifacts; writes a new iteration manifest and iteration projection. It refuses an existing iteration rather than replacing it. The final result includes the manifest path/hash, corpus ID, present counts by kind, and explicit missing roles.

### `measure`

```text
narration_wiki measure SCOPE
  --phase before|after
  [--proposal-id ID]
  --json
```

- `before` is valid after collection and before Gate 1.
- Before the first Gate 1 ruling, source or guidance drift allows replacement of the baseline measurement.
- After any Gate 1 ruling, drift requires a new iteration.
- `after` requires `--proposal-id`, an applied comparison, matching after-target hash, and the original corpus ID.

The command writes one canonical measurement artifact and never decides a Gate.

### `index-check`

```text
narration_wiki index-check SCOPE --json
```

Read-only validation of campaign and compatible portable wiki indexes. It reports duplicate slugs, broken links, tier/page mismatches, malformed pages, unresolved promotion state, and portable capability status. It does not repair anything.

### `conflict-rule`

```text
narration_wiki conflict-rule SCOPE
  --conflict-id ID
  --resolution TEXT
  --rationale TEXT
  --json
```

Persists one explicit GM ruling for a companion-produced seed conflict. Resolution and rationale must be non-empty. The command:

1. verifies the conflict draft and current baseline binding;
2. atomically writes the durable campaign conflict record;
3. records its iteration-local path/hash reference;
4. refreshes derived unresolved-conflict status.

It never accepts a pattern implicitly.

### `pattern-rule`

```text
narration_wiki pattern-rule SCOPE
  --pattern-slug SLUG
  --decision accept|reject
  [--tier campaign|portable]
  [--named-portable-override]
  [--rationale TEXT]
  --json
```

Records one Gate 1 decision.

- `--tier` is required for `accept` and forbidden for `reject`.
- Every referenced seed conflict must already have a durable compatible ruling before acceptance.
- Campaign-named content defaults to the campaign tier.
- Portable placement of named content requires `--named-portable-override` and non-empty `--rationale`.
- Campaign acceptance atomically writes or validates the page, index, log, and ruling.
- Portable acceptance creates a promotion handoff and `pending_portable_sync` state only.
- Rejection records the ruling without publishing the draft.

### `proposal-stage`

```text
narration_wiki proposal-stage SCOPE
  --proposal-id ID
  --draft PATH
  [--evidence-binding-json JSON ...]
  [--override-rationale TEXT]
  --json
```

Validates one companion-produced proposal and stages immutable before/after snapshots plus a complete unified diff. It does not modify the target.

Exactly one reconsideration form may be supplied:

- one or more `--evidence-binding-json` values, each containing `source_ref`, `source_sha256`, `applies_to_kind`, and `applies_to_key`; or
- one non-empty GM `--override-rationale`.

The engine validates canonical evidence bindings before writing the proposal bundle. New paths for previously seen identical bytes do not qualify. If an equivalent rejected proposal exists and neither valid form is supplied, staging fails without creating a bundle.

`--draft` must resolve inside the selected iteration. The proposal itself must name exactly one target that is a configured campaign rulebook, voice file, example file, or checker configuration.

### `proposal-apply`

```text
narration_wiki proposal-apply SCOPE
  --proposal-id ID
  --json
```

Applies the staged after snapshot for comparison. It requires the live target hash to equal the staged before hash, records a transaction journal, atomically writes exact bytes, and verifies the after hash. It does not record a Gate 2 decision.

### `proposal-rule`

```text
narration_wiki proposal-rule SCOPE
  --proposal-id ID
  --decision accept|reject
  --json
```

Records Gate 2.

- `accept` verifies and retains the exact comparison bytes.
- `reject` verifies the comparison hash and restores the exact before snapshot.
- Both decisions require a valid after measurement and append exactly one impact entry.
- Evidence bindings and override rationale are forbidden here; Gate 2 consumes only the staged basis.
- Repeating a completed decision is idempotent only when every requested and persisted value agrees.

## Mutation boundaries

| Command | Source reads | Intended writes |
|---|---|---|
| `status` | iteration, wiki, capability files | none |
| `collect` | selected-session allowlist | new iteration + manifest |
| `measure` | manifest, guidance, corpus, optional proposal | one measurement + iteration projection |
| `index-check` | indexes, pages, capability files | none |
| `conflict-rule` | conflict draft, baseline, campaign conflict state | conflict record + reference + journal |
| `pattern-rule` | draft, baseline, conflict rulings, wiki state | Gate 1 + campaign publication or portable handoff + journal |
| `proposal-stage` | proposal draft, guidance, ledger, evidence | immutable proposal bundle |
| `proposal-apply` | proposal bundle, target | target comparison bytes + journal |
| `proposal-rule` | proposal, measurements, target, ledger | Gate 2 + target restore when rejected + impact + journal |

No command writes the companion repository. No command reads or writes narration renderer output beyond the explicitly collected source corpus.

## Progress and final output

Workflow commands emit UTF-8 lines suitable for terminal use:

```text
Validating selected campaign and session
Reading trace manifest
{"ok":true,"command":"measure","phase":"before","artifact":"narration_wiki/iter-001/measurement-before.json"}
```

The final non-empty stdout line under `--json` is the result object. Diagnostics go to stderr. Paths in result objects are relative; no absolute host paths are exposed.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Success. |
| `2` | Invalid command-line syntax or empty required value. |
| `3` | Scope, containment, symlink, or companion-dependency refusal. |
| `4` | Lifecycle, stale-hash, duplicate, unresolved-conflict, or idempotency conflict. |
| `5` | Draft, schema, manifest, measurement, index, or evidence validation failure. |
| `6` | Mutation or recovery failure; inspect persisted recovery status. |
| `70` | Unexpected internal failure. |

Failures must be nonzero, name the failed precondition, and avoid a success-shaped result. Known refusals do not emit tracebacks unless diagnostic mode is explicitly enabled for development.

## Determinism and parity

- Repeating a read-only command against unchanged bytes produces byte-identical JSON.
- CLI and UI expose every command and option with the same spelling and semantics.
- The server never synthesizes a decision, target, evidence binding, or override rationale.
- Cancellation terminates the CLI process group; authoritative state is determined by a subsequent `status` call.
- Server-owned diagnostic run logs are disabled for this workflow so CLI and UI create the same persisted feature artifacts.
