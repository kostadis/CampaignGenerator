# Source Change Transaction Contract

## V1 target boundary

V1 source changes target maintained summary Markdown only. The adapter refuses:

- VTT and claimed-verbatim spans;
- generated `<range>/state/` artifacts;
- entity and thread registry edits, which use their existing authority workflows;
- arbitrary YAML or config edits;
- external planning-note mutation.

## Proposal guarantees

A proposal contains exact before and after bytes, whole-file and span digests, the stable ruling/source/anchor, post-`propose` ledger revision and digest, affected projections, and a canonical proposal digest. The proposed ledger references only `proposal_id`, so computing the proposal digest does not invalidate its own ledger binding. The proposal is immutable after display. Any edit creates a new proposal revision requiring review.

The target span must match exactly once at proposal time and again at apply time. The after document must pass the summary validator. V1 supports exact replacement only; it defines no source-annotation grammar. The immutable proposal digest is calculated without its own digest field. Explicit approval creates a separate immutable event binding the displayed proposal digest, reviewer, timestamp, and current source/ledger digests.

## Apply protocol

1. Acquire the campaign authority writer lock.
2. Refuse if any nonterminal authority transaction exists.
3. Re-read ledger and target; verify campaign, proposal digest, ledger digest/revision, source digest, unique span, allowed target, and audience/source compatibility.
4. Validate complete proposed target and ledger bytes.
5. Persist and sync source/ledger before-and-after snapshots, the approval event, and a `prepared` journal.
6. Advance journal to `writing`; replace each target using durable per-file atomic write; record and verify each resulting digest.
7. Write immutable receipt and ledger `applied` transition through the same journal.
8. Verify every after digest; mark `committed`; release lock.

The operation is recoverable and fail closed. It is not described as filesystem-atomic across files.

## Reader contract

Build, extract, synth, freshness, preview, and mutation input loading acquire the campaign authority shared/read lock while constructing one coherent AuthorityInputManifest and filtered input snapshot. They refuse a nonterminal journal with transaction ID and the exact recovery command. The lock is released before any model call. Before publishing a model result as current, the command reacquires the read lock and compares the authority/source generation and complete manifest; a change leaves the result incomplete/stale rather than current. Apply/recover takes the exclusive/write lock. A check without this lock is insufficient because a writer could start between the check and the reads.

## Recovery protocol

Recovery is idempotent and takes the same writer lock.

| Observed target digests | Action |
|---|---|
| All approved `after` | Verify/write missing receipt and ledger transition, then commit. |
| All approved `before` | Resume the exact approved proposal. |
| Mixture of approved `before`/`after` | Resume forward from stored approved bytes after all targets validate. |
| Any unexpected digest | Mark `attention_required`; display target and expected/actual digests; write nothing. |

Recovery never blindly restores snapshots over unexpected current bytes.

The applied ledger stores the predetermined receipt ID, not the receipt digest. The immutable receipt can therefore record the verified final ledger digest without a content-digest cycle.

## Withdrawal protocol

Withdrawal creates a new reversal proposal. It may derive an inverse only when the exact applied passage remains identifiable in the current source and unrelated current edits can be retained. Otherwise it requires a newly authored replacement. Approval binds the current digest. The original record, proposal, and receipt remain history.

## Failure codes

- `AUTH_PENDING_TRANSACTION`
- `AUTH_STALE_PROPOSAL`
- `AUTH_TARGET_NOT_ALLOWED`
- `AUTH_SPAN_NOT_UNIQUE`
- `AUTH_VERBATIM_TARGET`
- `AUTH_SOURCE_INVALID`
- `AUTH_UNEXPECTED_RECOVERY_BYTES`
- `AUTH_AUDIENCE_SOURCE_UNSAFE`

`--force` never bypasses these gates.
