# Migration and Adoption Design

These are planned commands, not an already-installed migration. Implementation must also publish operator instructions under `docs/cli/summary_native_review.md`.

## State changes

1. `docs/authority.yaml`: explicit version 1 → 2; preserve existing records/conflicts and add support for audit-only review decisions. No automatic content reclassification.
2. Existing summary-native manifests that use coarse registry hashes: explicit versioned dependency metadata adoption for affected identity-aware outputs. Record source/subject dependencies conservatively; do not claim an artifact is independently fresh when its dependencies cannot be reconstructed.
3. New `docs/reviews/` and private service state: deliberate initialization; no legacy browser decision scraping or silent import.
4. Entity registry remains version 1. `canon.yaml`, transcript corrections, provenance corrections and existing narration-review files retain their current roles.

## Operator sequence

```sh
summary_native review migrate --campaign-dir /path/to/campaign --dry-run --json
summary_native review migrate --campaign-dir /path/to/campaign --plan-sha256 <returned-sha> --json
summary_native review init --campaign-dir /path/to/campaign --json
summary_native authority validate --campaign-dir /path/to/campaign --json
summary_native review list --campaign-dir /path/to/campaign --json
```

Dry-run lists every changed path, detected version, unknown field, dependent manifest and before/after hash. Execute refuses changed inputs, pending transactions, unknown data and missing required snapshots. Migration uses the same campaign writer lock and recoverable transaction; it cannot silently drop unknown fields. Existing v1 authority transactions must finish with their original compatible recovery path before upgrading. A campaign without an authority ledger initializes it explicitly through `authority init` on the new version before review initialization.

Keep immutable archived ledger/proposal/receipt bytes as evidence. Historical v1 decoding is explicitly archival; runtime readers never try v2 and then fall back to live v1. Existing approved source proposals whose full-ledger binding changes become stale; applied receipts remain historical facts. A dry-run reports this consequence and required fresh proposals. Existing source records are not changed to review decisions.

Manifest adoption may reconstruct dependencies from pinned inputs without models; inability to prove them marks the artifact stale and lists the exact rebuild needed. It does not regenerate or publish prose during migration. Unrelated bytes and original input evidence are preserved.

## Without migration

A v1 live authority ledger causes new-version authority/review operations to refuse with the exact migration command. Old manifest versions requiring new identity semantics refuse affected merge planning until adopted/rebuilt. The independent v1 entity registry remains readable in its original location. `review init` never upgrades authority as a side effect.

## Verification and recovery

Verify ledger version, record/conflict counts, preserved source/history hashes, new tip event, migrated manifest dependency counts and empty review history after initialization. Rerunning completed migration is an idempotent no-op if expected state matches. Kill at each target boundary and demonstrate forward recovery; changed unexpected bytes must stop without overwrite. Rollback, if needed, requires a deliberately reviewed restoration before further edits, not blind replacement of snapshots over later work.
