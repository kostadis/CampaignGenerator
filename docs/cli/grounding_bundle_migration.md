# Grounding bundle migration

Managed promotion stores the four grounding documents, the canon timeline,
and the complete generated reference tree as one generation under
`docs/grounding/`. Run this migration once before the first promotion.

## Preview, apply, and verify

Run from any directory and name the campaign explicitly:

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
