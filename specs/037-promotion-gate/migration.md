# Managed Grounding Bundle Migration

This is the implemented operator contract. Validation uses disposable fixture campaigns; no original campaign was migrated during implementation.

## What changes

The four grounding documents, timeline and generated references move into one managed live generation beneath `docs/grounding/`. Config points to `docs/grounding/current/<document>.md`. The familiar four `docs/<document>.md` paths, timeline and `docs/reference` become explicit relative compatibility links. Source summaries, registry, authority ledger, reviews, NPC dossiers and unrelated documents stay in place.

Each generation retains original published bytes separately from editable live bytes. This storage is campaign data and must travel with Git/backups; link files alone are not a portable publication. Runtime lock files/temporary staging are excluded from publication according to existing repository conventions; manifests, generation content and completed receipts are retained. Promotion itself never commits or pushes.

Affected workspaces are those opting into #548 managed promotion/readers. Existing whole-document v1 approvals remain historical but need new v2 sign-off items binding the expanded support/report context. Authority ledger v2 and #547 review initialization are prerequisites; use their existing explicit migrations first if needed. This migrator does not silently upgrade those schemas.

## Commands

```bash
migrate_grounding_bundle --campaign-dir /path/to/campaign --dry-run --json
migrate_grounding_bundle --campaign-dir /path/to/campaign --plan-sha256 <returned-sha> --json
migrate_grounding_bundle --campaign-dir /path/to/campaign --status --json
migrate_grounding_bundle --campaign-dir /path/to/campaign --verify --json
migrate_grounding_bundle --campaign-dir /path/to/campaign --recover --operation <operation-id> --json
```

Use the same controls in the application's Promotion → Workspace setup panel. There is no --force bypass. Dry-run is read-only; apply is the deliberate layout-changing operation.

## Adoption policy

1. Inventory the current config, the five document/timeline files plus the reference tree, and every nested reference. Resolve existing configured path choices and prove containment/ownership. Disagreeing canonical/config paths, unsafe symlinks, ambiguous generated-versus-handwritten references, partial loose bundles, broken reading contracts or missing required members refuse with exact affected paths.
2. A complete loose bundle must pass its pointer and outline checks before adoption. The receipt labels it `legacy_adoption`: this validates current bytes as a rollback baseline, not historical semantic review or an invented generation provenance. The GM sees its entire inventory and explicitly confirms the digest.
3. A pristine initialized campaign may adopt an explicit absent baseline only if none of the managed outputs exist. Existing incomplete output cannot be silently converted to absent; repair or deliberately relocate it outside this migrator first.
4. Preview shows every config change and all six aliases, plus exact original backups. Unrecognized config keys are preserved/reported, never dropped by parsing through a narrower model; `config.yaml` is edited in place (only the previewed path values change, comments, key order and mode are kept) and the result is re-parsed against the planned mapping. Unrelated files are outside the target set.

## Apply/recovery protocol

- Acquire the existing exclusive authority lock; refuse pending authority/promotion work. Check preview inventory/config hashes again.
- Persist a migration intent and pending marker before changing paths. All upgraded repository readers/writers check it and refuse with the recovery command while migration is pending.
- Copy and synchronize exact original bytes/config/link types into retained migration backups. Create the adopted generation with copied path/run metadata and `published/`/`live/` separation. Preserve original source files until replacement is safely journaled.
- Journal each alias/config transition with expected before/after identities. Replace only the explicitly previewed paths; directory reference replacement is backed up and recorded, never recursive deletion of an unproven tree. Install the current pointer and all aliases, then config. Consumers remain blocked throughout this multi-file migration.
- Verify pointer containment, exact alias/config mappings, source and destination member hashes, outlines, pointer records and preservation of unrelated files. Persist and synchronize the migration receipt and a `legacy_baseline` ActivationRecord binding its digest and adopted generation manifest before clearing the pending marker. This record is a valid parent for the first real promotion; pristine absent initialization has no activation parent.
- If interrupted, explicit recover completes known transitions forward from retained before/after data. Any unexpected bytes require intervention with both copies preserved. Do not guess which state is newer. Repeated successful apply/verify returns the existing result without copying again.

Migration is a recoverable, temporarily unavailable operation. It is not falsely described as one atomic multi-file replacement. Normal publication afterward has the single activation boundary described in [publication.md](contracts/publication.md).

## Behavior without migration

A campaign that has not run the migration has no `docs/grounding/`. Its grounding documents live in exactly one place, the loose `docs/<document>.md` files and `docs/reference/`, and every reader reads them there. The new promote/check workflow refuses with `PROMOTION_MIGRATION_REQUIRED` and the exact dry-run command, and every older single-document publication entry point (the Ensemble `/promote` route, the retired review document prepare/promote routes) refuses with `PROMOTION_WHOLE_BUNDLE_REQUIRED` whether or not the campaign is migrated. No read triggers a migration.

Readers do not refuse the loose layout. That is a recorded decision, not an omission (see the post-merge audit in [validation.md](validation.md)): the location of a grounding document is decided once per campaign by its layout (`docs/grounding/layout.json`), so a reader never consults one location and then falls back to another, and the same fact is never held in two places. After migration the loose paths are compatibility links into the one live generation. Refusing the loose layout would stop every unmigrated campaign's prep and narration to protect a publication path those campaigns cannot use until they migrate anyway.

Prerequisites: the migration takes the authority lock, so a campaign without an authority ledger or review store runs `summary_native authority init --campaign-dir DIR --json` and `summary_native review init --campaign-dir DIR --json` first (`new_workspace` writes these steps into `docs/grounding-migration-required.md`). Re-running the dry run or apply on a migrated campaign returns `PROMOTION_MIGRATION_COMPLETE` with the existing operation.

After an absent baseline, reading a managed member refuses with `PROMOTION_NO_GENERATION` until the first promotion, which installs the six compatibility links; unrelated documents read normally.

## Editing after migration

For ordinary human prose edits, open `docs/grounding/current/world_state.md` (or the corresponding other member), not the final compatibility symlink in `docs/`. An editor may safely replace the regular file inside the live generation; a repository editor must use the managed write lock. Historical published snapshots and receipts remain unchanged.

An editor that overwrites `docs/world_state.md` itself has detached the alias. Status reports the conflict and preserves both the detached file and managed live copy; do not auto-delete either. The operator must inspect and reconcile the intended content at the managed path and restore the exact displayed alias before verification succeeds. Promotion refuses while the conflict exists. Stop concurrent external edits before promotion; external applications do not honor the campaign lock automatically.

## Verification

Verification must show one valid active/absent baseline, all six exact links (when active), config resolving to the same generation, retained originals and migration receipt, complete member hashes, resolving reading-contract links, and unchanged unrelated file hashes. A subsequent read snapshot reports one generation for all requested documents. A subsequent promote dry-run reports exact overwrites, including human edits, without writing.

Implementation also ships these instructions in `docs/cli/grounding_bundle_migration.md` and updates the old manual-copy guidance to link to managed promotion. Installed-wheel tests prove the migrator and status/verify commands work outside a source checkout.
