# Security review: managed grounding promotion

Reviewed 2026-10-10 against the implemented migration, promotion, claims, shared-review, HTTP, and private capability paths. Tests and probes use disposable synthetic campaigns only.

## Filesystem boundaries

- Managed roots, operation IDs, generation IDs, source selections, and report IDs are strict typed relative identifiers. Empty/dot paths, NUL, absolute paths, lexical traversal, and foreign campaign identities refuse before filesystem mutation.
- Path walking checks every raw component before canonicalization. Reads and private writes use component-wise directory file descriptors, `O_NOFOLLOW`, bounded/nonblocking opens, and regular-file checks. Parent and leaf symlinks, FIFOs, devices, and escaped aliases refuse.
- The exact source manifest, full nested reference inventory, retained records, destination identity, and current activation chain are hashed. Mandatory missing files do not disappear from a manifest. Managed snapshots bind one reconciled generation and refuse migration pending, commit unknown, corrupt pointer/manifest/receipt/history, cycles, or detached aliases.
- Immutable selections, runs, reports, receipts, and decisions use atomic no-replace installation. Concurrent different writers yield one winner and one conflict. Temporary files and directories are owner only and synchronized before visibility.

Evidence: `test_grounding_bundle_contracts.py`, `test_grounding_bundle_readers.py`, `test_migrate_grounding_bundle.py`, `test_summary_native_promotion_recovery.py`, `test_summary_native_claims_privacy.py`, and `test_summary_native_review_security_regressions.py` cover traversal, symlink/special-file attacks, partial-copy recovery, concurrent publication/private saves, and corrupt evidence chains.

## Freshness and activation

- Preview is read only. Commit reacquires the authority lock and recomputes source custody, current candidates/extraction revision, report analysis/resolution, four review contexts, live destination identity, parent activation, and staged bytes immediately before the pointer swap.
- Review JSON is evidence, not authority: publication reconstructs current mappings, resolutions, source corrections, and sign-offs from the immutable shared-review history. New candidates, failed later selected runs, withdrawals, changed semantic meaning, rules, audience, authority records, support, report, source, or destination produce a stale/blocked result.
- Activation intent is durable before the swap. Every exception after swap is `commit_unknown` with an operation ID until recovery proves the activation or retains an intervention state. Completed request replay verifies the original intent and returns its historical receipt without moving current.
- Migration resumes per member and verifies complete before/after hashes before removing originals or clearing pending state. Unknown ownership or unexpected bytes require intervention.

Fault tests inject failures at file write, sync, rename, pointer swap, receipt, and activation boundaries, plus process death. These are Python/process durability tests; they do not simulate physical device failure.

## Claims and review authority

- Model output and imported candidates are untrusted candidates. They cannot create authority, resolve registry ambiguity, waive a mechanical or GM-confirmed false finding, or publish. Only exact current typed actions can be approved.
- Mapping approval binds the complete normalized meaning: subject identity kind and resolution, predicate, value, certainty, scope, audience, evidence span/context, authority record payloads, and revision. Same bytes with changed meaning require a new approval.
- Required source closure binds each source's role, audience, authority class, applicability, record identity, and content hash. The model receives only explicitly selected chunks; zero chunks is an explicit disclosed no-model path.
- Prepared dismissal/uncertainty actions bind the finding, evidence, rationale, expected decision revision, and required disposition. Source correction is accepted only for the exact prepared correction action. All CLI, imported-decision, local HTTP, and private HTTP transports share store-level validation.

## Private capability and HTTP surface

- Capability grants are review scoped, expiring, revocable, and stored owner only. The authorized issuance response returns its access URL; later logs and error bodies do not expose the token. Host, origin, CSRF, content type, request/response size, note length, batch size, audience, review, item, revision, and digest are checked.
- The private service exposes read and review-save operations only. It has no promotion, migration, source selection, arbitrary file, model extraction, or recovery route. Static assets are a packaged allowlist; missing assets fail closed.
- Local application routes construct fixed installed CLI argument vectors, send bounded canonical stdin, preserve structured domain codes, and do not duplicate domain policy. Mutating transport loss reports an unknown outcome and operation/request context; it is never described as a safe rollback or automatically retried.
- Claim packets and reports are GM-private owner-only artifacts. Private capability access remains bound to the review audience and never returns private filesystem paths or raw transport exceptions.

Independent Python 3.10 review/privacy/HTTP/installation validation passed 25 tests with loopback permission. The route parity matrix separately proves private capability absence for publish, promote, migrate, model, and extract operations.

## Platform limits and residual risk

Publication requires a local POSIX filesystem with working `flock`, symlinks, `O_NOFOLLOW`, same-filesystem atomic rename/link installation, and directory `fsync`. Network, multi-host, and filesystems that cannot provide these primitives are unsupported and must refuse. External editors do not honor the campaign lock; a last-moment edit is detected by the preactivation hashes, but operators should stop external writers during migration/publication. Git commit/push and backup transport remain operator responsibilities.

The reviewed security suites have no unresolved defect. Revised sign-off, configuration parity, and UI workflow regressions passed the focused release gates recorded in `validation.md`.
