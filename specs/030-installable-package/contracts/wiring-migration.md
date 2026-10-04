# Contract: host wiring and one-shot migration

## Runtime read contract

`campaignlib/wiring.py` is the only CampaignGenerator accessor for mneme-rendered external wiring. Selection order:

1. Non-empty explicit `load_wiring(path)` argument.
2. Non-empty `MNEME_WIRING` environment value.
3. `~/.config/campaigngenerator/wiring.yaml` for the current user.

The selected explicit or environment path is authoritative. Missing or malformed content there raises a path-specific error; it does not fall through to a different file. Missing default content returns `{}` where external wiring is optional. Present content must be a YAML mapping. Callers that cache values must see the selected file for that process; tests that vary selection must use a fresh process or clear the cache.

The retired checkout `config/wiring.yaml` and CWD `config/wiring.yaml` are not default fallbacks. When checkout startup knows its source path and finds retired wiring there, refuse it with `migrate_wiring --source-checkout DIR` in the error; do not read or move it during normal startup. An installed process with no checkout reference cannot search arbitrary old checkouts. Its missing optional default remains `{}`; the upgrade instructions therefore require the operator to identify and migrate the old checkout before installed use. A genuinely fresh installation with no wiring retains optional behavior.

## Producer contract with mneme

Mneme's `components.CampaignGenerator.config_target` is `~/.config/campaigngenerator/wiring.yaml` when both programs run as the same user. Operators using different users set a deliberate shared target in mneme and `MNEME_WIRING` for CampaignGenerator. Mneme `apply` renders the file, creates parent directories, and may change its source stamp when the target changes. Mneme `status` must report the new target as current after apply. The old checkout target is removed by migration; apply alone does not remove it.

## One-shot CLI

```text
migrate_wiring --source-checkout DIR [--target PATH] [--force]
```

- `--source-checkout` is required and names the checkout holding retired `config/wiring.yaml`. No implicit scan or silent choice of a campaign.
- `--target` defaults to the single runtime default. It supports an intentionally shared target for deployments with different users.
- Without `--force`, an existing destination refuses the move and leaves source and target unchanged. `--force` deliberately replaces the target only after the source has been read and validated.
- The source is read raw as a YAML mapping. Preserve all keys and values, report keys outside the currently known wiring set, and do not discard them.
- Safely write the target, then remove the source. A failed write or validation leaves the source intact and returns nonzero. A successful run reports source, target, and completion.
- The CLI is installable and runnable from an unrelated CWD. Host-global wiring is why this migrator uses `--source-checkout`, not the campaign migrators' `--campaign-dir`.

## Checkout UI invocation

The source-checkout Settings page shows the retired source and selected target, lets the operator supply both paths and choose overwrite deliberately, and displays the command result. It calls `POST /api/config/wiring/migrate` with a JSON body:

```json
{
  "source_checkout": "/absolute/path/to/CampaignGenerator",
  "target": "/absolute/path/to/wiring.yaml",
  "force": false
}
```

`target` may be omitted to use the runtime default. The route passes only these values to the same `server.migrate_wiring` CLI through the active interpreter and existing subprocess runner, so a checkout UI does not depend on an editable-install console script. It returns exit status and command output; it contains no copy, parse, write, or fallback logic of its own. An empty source selection is refused. The UI does not auto-run migration on page load.

## Operator sequence

1. Run the one-shot migration against the old checkout before rerendering, or explicitly resolve a destination conflict.
2. Change mneme's render target to the chosen location and run `hypostasis apply`.
3. Verify `hypostasis status`, read the same values through installed CampaignGenerator, and verify the old checkout file is gone.

The final render may differ byte-for-byte because mneme's stamp includes the target; the value mapping is what migration verification preserves.
