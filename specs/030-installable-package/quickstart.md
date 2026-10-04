# Quickstart: validate the installable package

These are release validation steps for the completed feature. Run them from the CampaignGenerator checkout after implementation. They intentionally install a built wheel and then leave the checkout, matching issue #494. See [resource contract](contracts/resources.md), [wiring contract](contracts/wiring-migration.md), and [migration guide](migration.md) for the expected behavior.

## Prerequisites

- Python 3.14 and `uv` available for the local steps below. Release CI must repeat the wheel import, packaged-resource, and command checks on Python 3.10, the oldest declared version.
- Ability to install declared runtime dependencies into a temporary environment.
- A checkout with this feature's implementation and a built frontend for the separate `./start` check.
- A temporary directory that can be deleted after validation. No real wiring file is changed in the local smoke below.

## 1. Build and inspect the wheel

```bash
cd /home/kostadis/src/CampaignGenerator
smoke_root=$(mktemp -d)
uv build --wheel --out-dir "$smoke_root/dist" .
unzip -l "$smoke_root"/dist/*.whl | rg 'citation_rules_extract.md|session_doc/narrate/base.md|reviewer.html'
```

Expected: all three files appear in the wheel. The implementation's release test must inspect the full shipped-resource inventory, not only these examples.

## 2. Install non-editably and run away from the checkout

```bash
uv venv --python 3.14 "$smoke_root/venv"
uv pip install --python "$smoke_root/venv/bin/python" "$smoke_root"/dist/*.whl
uv pip check --python "$smoke_root/venv/bin/python"
mkdir -p "$smoke_root/away"
cd "$smoke_root/away"
env -u PYTHONPATH "$smoke_root/venv/bin/python" -c 'import campaignlib, session_doc, pipelines, entity_registry, provenance'
env -u PYTHONPATH "$smoke_root/venv/bin/registry" --help
env -u PYTHONPATH "$smoke_root/venv/bin/distill" --help
env -u PYTHONPATH "$smoke_root/venv/bin/sd_verify_quotes" --help
```

Expected: dependency check, five imports, and three help commands succeed without a source-tree path or missing-resource error.

Run the installed write-producing command from the same unrelated directory:

```bash
env -u PYTHONPATH "$smoke_root/venv/bin/new_workspace" "$smoke_root/away/workspace"
test -f "$smoke_root/away/workspace/config/config.yaml"
```

Expected: workspace output appears under the temporary directory. The automated wheel test compares installed package contents before and after this command and fails if they change.

## 3. Check local prompt priority and shipped fallback

```bash
mkdir -p "$smoke_root/away/config/agents"
printf 'LOCAL OVERRIDE\n' > "$smoke_root/away/config/agents/citation_rules_extract.md"
env -u PYTHONPATH "$smoke_root/venv/bin/python" -c 'from campaignlib import load_agent_prompt; assert load_agent_prompt("citation_rules_extract") == "LOCAL OVERRIDE\n"'
rm "$smoke_root/away/config/agents/citation_rules_extract.md"
env -u PYTHONPATH "$smoke_root/venv/bin/python" -c 'from campaignlib import load_agent_prompt; assert load_agent_prompt("citation_rules_extract").strip()'
```

Expected: the local text wins first; after removal, the shipped prompt loads. These are separate processes so prompt caching cannot mask a source change.

## 4. Check wiring and deliberate migration without touching real settings

```bash
mkdir -p "$smoke_root/old-checkout/config" "$smoke_root/new-config"
printf 'dgx_endpoint: http://example.invalid:8000\n' > "$smoke_root/old-checkout/config/wiring.yaml"
env -u PYTHONPATH "$smoke_root/venv/bin/migrate_wiring" --source-checkout "$smoke_root/old-checkout" --target "$smoke_root/new-config/wiring.yaml"
test ! -e "$smoke_root/old-checkout/config/wiring.yaml"
env -u PYTHONPATH MNEME_WIRING="$smoke_root/new-config/wiring.yaml" "$smoke_root/venv/bin/python" -c 'from campaignlib import wiring_get; assert wiring_get("dgx_endpoint") == "http://example.invalid:8000"'
```

Expected: the one-shot command reports a move, the old file is gone, and the installed copy reads the same setting from the explicit location. Repeat with an existing destination: without `--force`, migration must refuse and leave both files unchanged. Confirm the checkout Settings page offers the same explicit operation and displays the CLI result.

## 5. Check mneme and source-checkout mode

After changing mneme's CampaignGenerator `config_target` to `~/.config/campaigngenerator/wiring.yaml` in the coordinated change, run its normal `hypostasis apply` and `hypostasis status` in a safe operator environment. Confirm that CampaignGenerator reads the rendered values and that the retired checkout file is absent. If mneme and CampaignGenerator run as different users, set the same explicit shared path in mneme and `MNEME_WIRING`.

From a checkout, run `./start --campaign-dir <existing-campaign>` and open its normal interface. Check the Settings migration control and then stop the server. Installed mode remains CLI-only; the wheel need not contain `frontend/dist`.

## Release gate

Automate steps 1–4 in the repository's test suite using temporary paths and a fresh process. Run the wheel import, packaged-resource, and command checks on both Python 3.10 and 3.14 in release CI. Keep the checkout smoke and mneme render/status check in the integration release checklist. The acceptance target is zero missing-resource errors, workspace output created outside the installation, zero writes to installed code, and successful startup of the named commands from outside the checkout.
