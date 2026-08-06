"""Shared constants for CampaignGenerator.

Module-level so every script and submodule reads the same default.
"""

import os
from pathlib import Path

# Unified default Claude model for every CLI script. Override per-environment
# with the CAMPAIGN_MODEL env var; the server forwards the UI's sidebar pick
# as an explicit --model, which takes precedence over this default.
DEFAULT_MODEL = os.environ.get("CAMPAIGN_MODEL") or "claude-sonnet-4-6"

# The one directory a campaign's config files live in, relative to the campaign
# root. THE location, not a preferred one: there are no fallback probes for
# older layouts (docs/config/grounding-isolation.md Track 0, GM directive
# 2026-07-24 — "one place for config files, in config"). A config file left
# outside this directory is simply not found; `./migrate_config.sh <campaign>`
# moves it.
#
# The server can override the name per-process via `--config-dir`
# (PlatformConfigService.config_path_base). CLIs have no such flag, so they
# read CAMPAIGN_CONFIG_DIR to stay consistent with a server started that way.
CONFIG_DIR_NAME = os.environ.get("CAMPAIGN_CONFIG_DIR") or "config"


# The multi-campaign workspace root — the directory that holds one subdirectory
# per campaign. THE location, resolved once here rather than re-spelled at each
# call site: this literal previously lived only in
# `pipelines/workspace/configure_mcp.py`, and the provenance seam needs the same
# answer. Two literals are two answers waiting to drift.
#
# Override per-environment with $CAMPAIGNS_ROOT. A CLI may additionally accept
# an explicit `--campaigns-root`, which takes precedence over both; the
# resolution order is then (flag -> env -> this constant), and
# `provenance capabilities` reports which rule fired.
CAMPAIGNS_ROOT = Path(
    os.environ.get("CAMPAIGNS_ROOT") or "~/src/campaigns"
).expanduser()


def config_path(campaign_dir: Path | str, filename: str) -> Path:
    """``<campaign_dir>/<config dir>/<filename>`` — the declared location.

    Use this instead of probing a list of candidate locations. Four such probes
    used to exist for ``party.yaml`` alone, disagreeing on both the candidate
    set and the precedence, which left the obelisk campaign's roster visible to
    PC-name filtering and invisible to the Party page simultaneously.
    """
    return Path(campaign_dir) / CONFIG_DIR_NAME / filename

