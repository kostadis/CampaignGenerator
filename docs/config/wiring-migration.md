# Move external wiring from a source checkout

CampaignGenerator now reads mneme-rendered host wiring from `~/.config/campaigngenerator/wiring.yaml` by default. An explicit `MNEME_WIRING` path can select a shared location when mneme and CampaignGenerator run as different users. The former `<CampaignGenerator checkout>/config/wiring.yaml` is retired. Normal commands never move or read it as a fallback.

This affects operators whose old source checkout still contains `config/wiring.yaml`. Campaign workspace `config/config.yaml` files and local prompt overrides do not move. Complete this migration before using the installed commands: an installed process with no reference to the old checkout cannot discover that file. Checkout startup that sees its own retired wiring refuses to start and prints the command below.

1. Record the absolute path to the old checkout and stop processes that may read wiring.
2. Run `migrate_wiring --source-checkout /absolute/path/to/CampaignGenerator`. For an intentional shared target, add `--target /absolute/shared/path/wiring.yaml`. The command refuses an existing target; inspect both files before deliberately adding `--force`.
3. Check that the command reports its target and any unrecognised keys, and that the old `config/wiring.yaml` is gone. The complete YAML mapping, including unknown keys, is preserved. A failed validation or target write leaves the source intact.
4. Set mneme's `components.CampaignGenerator.config_target` to `~/.config/campaigngenerator/wiring.yaml` or the same explicit shared path. Run `hypostasis apply` and `hypostasis status`; applying alone does not delete the former file.
5. From an unrelated working directory, run an installed CampaignGenerator command that reads a known setting such as `dgx_endpoint`. Set `MNEME_WIRING` for the shared-target case. Compare setting values rather than rendered file bytes, because mneme's source stamp can change when the target changes.

If migration is skipped, the old file remains on disk. Installed commands do not look for arbitrary old checkouts; where the new default is absent, optional wiring reads as empty and features requiring external settings cannot use those old values. A checkout that knows its own retired path refuses with the migration command.
