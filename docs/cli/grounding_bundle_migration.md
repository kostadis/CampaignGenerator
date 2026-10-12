# Grounding bundle migration

Managed promotion stores the four grounding documents, the canon timeline,
and the complete generated reference tree as one generation under
`docs/grounding/`. Run this migration once before the first promotion.

## Preview, apply, and verify

The migration takes the campaign's authority lock, so the authority ledger and
review store must exist first. On a campaign that has never used them (a fresh
`new_workspace`, for one) run these once; skip either that already exists:

```bash
summary_native authority init --campaign-dir /path/to/campaign --json
summary_native review init --campaign-dir /path/to/campaign --json
```

Then run from any directory and name the campaign explicitly:

```bash
migrate_grounding_bundle --campaign-dir /path/to/campaign --dry-run --json
migrate_grounding_bundle --campaign-dir /path/to/campaign --plan-sha256 <preview-sha256> --json
migrate_grounding_bundle --campaign-dir /path/to/campaign --verify --json
migrate_grounding_bundle --campaign-dir /path/to/campaign --status --json
```

Preview is read only. Inspect every owned member, retained original, alias, and
configuration change before applying its digest. There is no force option.
Unknown files, incomplete bundles, unsafe links, foreign paths, or changed
preview inputs refuse rather than being adopted.

A valid legacy bundle becomes an attributed `legacy_adoption` baseline. A
campaign with none of the managed outputs may establish an explicit absent
baseline. The migration does not claim historical semantic review for either
case.

`config.yaml` is edited in place: only the previewed document paths change, so
comments, key order and the file's mode are kept (the plan lists each change and
the resulting file's digest). Copied generation members keep their source's mode.

Running the dry run or the apply again on a migrated campaign reports
`PROMOTION_MIGRATION_COMPLETE` with the existing operation; it never starts a
second migration.

## After an absent baseline

An absent baseline has no published generation yet. Unrelated documents read as
before; reading a grounding document (`docs/world_state.md` and the rest)
refuses with `PROMOTION_NO_GENERATION` until the first `summary_native promote`
publishes one. That first promotion installs the six compatibility links, and
`--verify` then reports them. A generator that tries to write a loose grounding
document refuses rather than creating one beside the managed layout.

## A campaign that never migrates

It keeps working: its grounding documents live in one place, the loose
`docs/<document>.md` files, and every reader reads them there. What it cannot do
is publish. `summary_native promote` and the claims workflow refuse with
`PROMOTION_MIGRATION_REQUIRED` and this page's dry-run command, and the old
single-document promote (the Ensemble page's Promote button, the retired review
document routes) refuses with `PROMOTION_WHOLE_BUNDLE_REQUIRED` on every
campaign, migrated or not.

## Interrupted migration

While a migration is pending, managed readers and writers refuse. Inspect the
operation ID returned by status, then recover it explicitly:

```bash
migrate_grounding_bundle --campaign-dir /path/to/campaign \
  --recover --operation <operation-id> --json
```

Recovery resumes only journaled before and after identities. Unexpected bytes
produce an intervention state and retain both copies. Repeating a completed
apply or recovery is idempotent.

## Files and editing

`docs/grounding/current` selects one complete generation. Compatibility links
at `docs/world_state.md`, `docs/campaign_state.md`, `docs/party.md`,
`docs/planning.md`, `docs/canon_events_timeline.md`, and `docs/reference` point
into it. Retained manifests, receipts, published bytes, and editable live bytes
belong in campaign backups and version control.

Edit prose through `docs/grounding/current/<document>.md`. Replacing a top
level compatibility link creates a conflict that status reports and promotion
refuses. Inspect both copies, reconcile the managed file, and restore the exact
link. External editors do not participate in the campaign lock, so stop them
before migration or promotion.

Migration and promotion never run Git commands.
