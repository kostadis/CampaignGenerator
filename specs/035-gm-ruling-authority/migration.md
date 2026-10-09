# Migration and Adoption: GM Rulings and Authority Tiers

## Shape changes

This feature adds `docs/authority.yaml`, immutable artifacts under `docs/authority/`, optional `notes` selectors in `config/planning.yaml`, an authority/audience policy version in checked-note caches, and an authority input manifest in run records.

It does not retire or reinterpret `docs/summary_native/canon.yaml`, `docs/corrections.yaml`, or `transcript_corrections.yaml`.

There is no prior general-authority ledger schema, so V1 has no authored state to mass-convert and defines no invented migration command.

## Affected workspaces

- Workspaces that do not adopt classified notes/rulings continue summary-only planning and need no authored-state migration.
- Adopting workspaces deliberately initialize an empty ledger and add explicit note selectors/records.
- Old checked-note caches and run records must be regenerated before an authority-aware run can accept them.
- Corrections that exist only as edits to generated state Markdown cannot be inferred. The GM must review a source correction against the maintained summary.

## Exact adoption commands

```bash
summary_native authority init --campaign-dir /absolute/path/to/campaign
summary_native authority validate --config /absolute/path/to/campaign/config/config.yaml
summary_native authority status --json --config /absolute/path/to/campaign/config/config.yaml
```

Then stage records and add selectors using [the CLI contract](contracts/cli.md). No command scans legacy stores and guesses tiers, audiences, reviewers, identities, or intervals.

## Unmigrated behavior

- Missing `docs/authority.yaml` means authority features are unconfigured; legacy stores are not merged or inferred.
- `planning.yaml` without `notes` preserves summary-only planning.
- Once `notes` is present, empty or missing/unreadable/zero-match selectors refuse.
- Authority-aware extract/synth refuses cache entries or run records lacking the new policy/manifest version and instructs regeneration. It neither upgrades them in place nor falls back to their schema.
- An unsupported future/retired authored ledger version refuses. Before a version is retired, that release must ship a defined one-shot migrator and exact refusal command.

Old cache/run metadata is derived output, so regeneration is the transition. Historical files may remain, but freshness cannot accept them for authority-aware runs.

## Verification

1. `authority validate` succeeds with no inferred records.
2. `authority status --json` reports expected schema/policy, ledger digest, and no pending transaction.
3. `authority notes preview --audience gm --json` returns exactly intended files/sections and a selection digest.
4. External paths are marked and no selector silently resolves to zero.
5. A new extract/synth records the authority manifest and policy-aware cache key.
6. Existing narrow stores remain byte-identical and continue their original workflows.
7. UI refresh reconstructs the same ledger, selection, status, and digests.

## Rollback

Before any applied source correction, an unused empty ledger/selectors can be removed to return to summary-only behavior. Once records exist, preserve them for audit. After source apply, rollback is the reviewed withdrawal/reversal workflow; never delete the ledger or blindly restore a snapshot.

## Future breaking versions

Any future authored-shape replacement must ship a separate one-shot migrator with `--campaign-dir`, preview/apply phases, original-byte preservation, unknown-field reporting, collision refusal, affected-workspace documentation, exact invocation, unmigrated behavior, and verification. Readers must refuse the retired shape with that command. Lazy write-on-read upgrades and dual-shape fallback readers are prohibited.
