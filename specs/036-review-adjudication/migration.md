# Migration and Adoption Design

These commands are installed. Operator instructions are in `docs/cli/summary_native_review.md`.

## Affected workspaces

- Any campaign with a version 1 `docs/authority.yaml` (every campaign that used `summary_native authority` before #547). Authority and review commands refuse there until `review migrate` runs.
- Any campaign with summary-native range builds whose `manifest.json` has no subject-level `identity_dependencies` (every build made before #547). Only identity merge planning refuses these, naming `review dependencies migrate`; the alternative is `summary_native build --force`.
- A campaign without `docs/authority/` is not affected. Nothing outside the authority and review commands creates that directory: the entity registry commands and `review migrate --dry-run` leave a campaign without it untouched, because its presence is what marks a campaign as review-enabled for every later reader.

## State changes

1. `docs/authority.yaml`: explicit version 1 → 2; preserve existing records/conflicts and add support for audit-only review decisions. No automatic content reclassification.
2. Existing summary-native manifests that use coarse registry hashes: explicit versioned dependency metadata adoption for affected identity-aware outputs. Record source/subject dependencies conservatively; do not claim an artifact is independently fresh when its dependencies cannot be reconstructed.
3. New `docs/reviews/` and private service state: deliberate initialization; no legacy browser decision scraping or silent import.
4. Entity registry remains version 1. `canon.yaml`, transcript corrections, provenance corrections and existing narration-review files retain their current roles.

## Operator sequence

```sh
summary_native review migrate --campaign-dir /path/to/campaign --dry-run --json
summary_native review migrate --campaign-dir /path/to/campaign --plan-sha256 <returned-sha> --json
summary_native review dependencies migrate --campaign-dir /path/to/campaign --dry-run --json
summary_native review dependencies migrate --campaign-dir /path/to/campaign --plan-sha256 <returned-sha> --json
summary_native review init --campaign-dir /path/to/campaign --json
summary_native authority validate --campaign-dir /path/to/campaign --json
summary_native review list --campaign-dir /path/to/campaign --json
```

Dry-run lists every changed path, detected version, unknown field, dependent manifest and before/after hash. Execute refuses changed inputs, pending transactions, unknown data and missing required snapshots. Migration uses the same campaign writer lock and recoverable transaction; it cannot silently drop unknown fields. Existing v1 authority transactions must finish with their original compatible recovery path before upgrading. A campaign without an authority ledger initializes it explicitly through `authority init` on the new version before review initialization.

Keep immutable archived ledger/proposal/receipt bytes as evidence. Historical v1 decoding is explicitly archival; runtime readers never try v2 and then fall back to live v1. Existing approved source proposals whose full-ledger binding changes become stale; applied receipts remain historical facts. A dry-run reports this consequence and required fresh proposals. Existing source records are not changed to review decisions.

Manifest adoption may reconstruct dependencies from pinned inputs without models; inability to prove them marks the artifact stale and lists the exact rebuild needed. It does not regenerate or publish prose during migration. Unrelated bytes and original input evidence are preserved.

## Without migration

A v1 live authority ledger causes new-version authority/review operations to refuse with the exact migration command; `review init` and `npc-publish` relay that command rather than reporting a missing sign-off. Old manifest versions requiring new identity semantics refuse affected merge planning until adopted/rebuilt, and the refusal names `review dependencies migrate`. Range freshness checks (`summary_native extract`, `synth` and the rest) keep reading an old manifest through its whole-registry digest: any registry change marks the range stale, which is conservative, so nothing is reported fresh that is not. A pending v1 transaction journal recovers forward in its own shape; recovery does not rewrite it as v2. The independent v1 entity registry remains readable in its original location. `review init` never upgrades authority as a side effect.

## Verification and recovery

Verify ledger version, record/conflict counts, preserved source/history hashes, new tip event, migrated manifest dependency counts and empty review history after initialization. Rerunning completed migration is an idempotent no-op if expected state matches. Kill at each target boundary and demonstrate forward recovery; changed unexpected bytes must stop without overwrite. Rollback, if needed, requires a deliberately reviewed restoration before further edits, not blind replacement of snapshots over later work.
