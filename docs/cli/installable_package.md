# Install CampaignGenerator for CLI use

CampaignGenerator builds a Python wheel. The installed distribution contains its seven Python package trees, shipped prompts, and the gap reviewer page. It does not contain the Vue web build. Run the web UI from a source checkout with `./start`.

## Install the wheel

From a CampaignGenerator source checkout, build a wheel and install it non-editably into an environment with Python 3.10 or newer:

```bash
uv build --wheel --out-dir /tmp/campaigngenerator-dist .
uv venv /tmp/campaigngenerator-env
uv pip install --python /tmp/campaigngenerator-env/bin/python /tmp/campaigngenerator-dist/*.whl
```

From an unrelated working directory, check `registry --help`, `distill --help`, and `sd_verify_quotes --help` using that environment's `bin/` commands. See the [release quickstart](../../specs/030-installable-package/quickstart.md) for the complete wheel smoke.

## Prompts and output

Shipped prompt defaults live in the installed `campaignlib.resources` package and are read only. A campaign can override one by placing a same-name file at `<campaign>/config/agents/<name>.md`; that file wins over the shipped default. An explicitly selected file path that does not exist is an error. Existing logical config values such as `config/system_prompt.md` continue to work when a campaign has no override.

Commands that create files write to the selected campaign workspace or a documented user data path. For example, `new_workspace /path/to/campaign` creates its layout at that path. Installed application files are not an output location.

## External wiring

Mneme renders host settings to `~/.config/campaigngenerator/wiring.yaml` by default. An explicit wiring path or `MNEME_WIRING` takes precedence. If mneme and CampaignGenerator use different accounts, configure one shared target in mneme and set `MNEME_WIRING` for CampaignGenerator. The retired checkout `config/wiring.yaml` is never an installed-mode fallback. If upgrading from an old checkout, follow the [one-shot wiring migration](../config/wiring-migration.md) before using the installed commands.

## Web UI from a checkout

Build the frontend in the source checkout if needed, then run `./start --campaign-dir /path/to/campaign` there. The installed distribution is CLI-only; `./start` serves the existing checkout web UI and its Settings page exposes the same deliberate wiring migration command. If retired checkout wiring blocks normal startup, run `./startup --migration-only` and open `/settings` to move it first.
