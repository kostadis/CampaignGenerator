# Migration: external wiring leaves the checkout

**Status**: Implemented migration procedure for issue #494. Verify the installed command and coordinated mneme render target before applying it to a real checkout.

## What changes

Mneme currently renders CampaignGenerator's host wiring to `<CampaignGenerator checkout>/config/wiring.yaml`. Installed CampaignGenerator will default to `~/.config/campaigngenerator/wiring.yaml` for the user running it. The former checkout location becomes retired; normal application startup does not move or silently read it. The wiring value mapping stays the same.

## Who is affected

Operators with a rendered `config/wiring.yaml` in a CampaignGenerator checkout, including mneme/hypostasis installs that point `components.CampaignGenerator.config_target` there. Campaign-local `<campaign>/config/config.yaml` files and prompt overrides do not move. If mneme and CampaignGenerator run under different users, choose one explicit shared target and set `MNEME_WIRING` to it for CampaignGenerator.

## Deliberate migration sequence

1. Before using an installed copy, record the old checkout path and choose the destination. Stop processes that may read wiring while it moves. An installed process without that checkout path cannot detect its retired file.
2. Run `migrate_wiring --source-checkout /absolute/path/to/CampaignGenerator`. The default destination is `~/.config/campaigngenerator/wiring.yaml`; use `--target /absolute/shared/path/wiring.yaml` only for a deliberate shared-user deployment. The command refuses to replace an existing target unless `--force` is supplied explicitly.
3. Confirm the command reports the destination and that the old checkout `config/wiring.yaml` is gone. Review any reported unrecognised keys; the migration preserves them.
4. Set mneme's CampaignGenerator `config_target` to the same destination, then run `hypostasis apply` and `hypostasis status` using mneme's normal operator workflow. Applying alone does not delete the former file.
5. Run an installed CampaignGenerator command with the chosen wiring visible and verify at least one rendered value, such as `dgx_endpoint`. Resume normal processes.

The source-stamp text may change when mneme renders at a new target. Verify setting values and the `status` result rather than expecting byte-identical rendered files.

## If migration is not run

An installed copy does not use the retired checkout path as a fallback. Checkout startup that knows its own path refuses retired wiring and reports the migration command. Where an installed process has no reference to that checkout and no default wiring file exists, optional wiring reads as empty; it cannot detect that upgrade state. Migrate the old checkout before installed use. The old file remains on disk until the operator migrates it.

## Verify and recover

- Verify the target is a readable YAML mapping and the former checkout file is absent.
- Verify mneme `hypostasis status` reports the new target current.
- Verify the installed application reads the chosen values from an unrelated working directory, using `MNEME_WIRING` if an explicit shared target was selected.
- If migration refuses because a target exists, inspect both files. Re-run with `--force` only after choosing which content should replace the target. A failed validation or write must leave the source untouched.

The operator-facing procedure is also published at `docs/config/wiring-migration.md`. Mneme's example config and architecture guide name the new target.
