#!/usr/bin/env python3
"""Write .mcp.json files for campaign directories.

Configures MCP servers from CampaignGenerator into one or more campaign
workspace directories:

  campaign   — mcp_server console script          (all campaigns that have config/config.yaml)
  5etools    — launch_5etools_mcp console script   (campaigns that have refs.yaml)
  registry   — registry_mcp console script         (campaigns that have docs/entity_registry.yaml)
  kanka      — kanka_mcp console script             (only when --kanka-token is given)

Usage
-----
  # Configure all campaigns under ~/src/campaigns/
  configure_mcp

  # Specific campaign(s)
  configure_mcp ~/src/campaigns/Phandalin ~/src/campaigns/toee

  # Include the Kanka server (needs KANKA_TOKEN)
  configure_mcp --kanka-token <token>

  # Preview without writing
  configure_mcp --dry-run

  # Overwrite existing entries (default: merge, preserving extra servers)
  configure_mcp --force

.mcp.json is written at the campaign's git repo root (see git_root), not
necessarily inside the campaign directory itself — a campaign can be its own
repo (~/src/campaigns/<name>/, one repo per campaign) or a subdirectory of a
larger monorepo (a multi-campaign workspace with one shared repo), and Claude
Code only looks for .mcp.json at the repo root. If two campaigns configured
in the same run share a repo root, the later one's servers overwrite the
earlier one's in that shared file — main() prints a NOTE when this happens.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CAMPAIGNS_ROOT = Path("~/src/campaigns").expanduser()
# mcp_server.py and launch_5etools_mcp.py have moved to pipelines/rlm/ and
# gained `mcp_server` / `launch_5etools_mcp` console-script entry points (see
# pyproject.toml), same as kanka_mcp.py's own move to
# pipelines/integrations/kanka/ — all three are invoked by their bare command
# name below instead of a `python3 <path>` invocation.


def find_campaigns(roots: list[Path]) -> list[Path]:
    """Return subdirs of each root that look like campaign workspaces.

    A campaign workspace is a directory with its own ``config/config.yaml``
    (the per-campaign config location — moved under a ``config/`` subdir
    rather than living at the campaign root). ``root`` itself is checked
    first (so pointing directly at one campaign works), then, if that
    misses, each child of ``root`` (so pointing at a container of many
    campaigns, e.g. ``~/src/campaigns/``, also works).
    """
    result = []
    for root in roots:
        if (root / "config" / "config.yaml").exists():
            result.append(root)
        else:
            for child in sorted(root.iterdir()):
                if child.is_dir() and (child / "config" / "config.yaml").exists():
                    result.append(child)
    return result


def git_root(path: Path) -> Path:
    """Return the git repository root containing ``path``, or ``path`` itself
    if none is found.

    A campaign directory can be its own repo root (the
    ``~/src/campaigns/<name>/`` layout, one git repo per campaign) or a
    subdirectory of a larger monorepo (a multi-campaign workspace with one
    shared repo). Either way, ``.mcp.json`` belongs at the repo root, since
    that's where Claude Code looks for it — not necessarily inside the
    campaign directory itself. Walks up from ``path`` looking for a ``.git``
    entry (a directory normally, a file for worktrees — either marks a repo
    root, so no need to distinguish them here).
    """
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return path


def build_server_block(campaign_dir: Path, kanka_token: str, kanka_url: str) -> dict:
    """Build the mcpServers dict for one campaign directory."""
    servers: dict = {}

    servers["campaign"] = {
        "command": "mcp_server",
        "args": ["--campaign-dir", str(campaign_dir)],
    }

    if (campaign_dir / "refs.yaml").exists():
        servers["5etools"] = {
            "command": "launch_5etools_mcp",
            "args": ["--campaign-dir", str(campaign_dir)],
        }

    if (campaign_dir / "docs" / "entity_registry.yaml").exists():
        servers["registry"] = {
            "command": "registry_mcp",
            "args": [],
            "env": {"CAMPAIGN_DIR": str(campaign_dir)},
        }

    if kanka_token:
        servers["kanka"] = {
            "command": "kanka_mcp",
            "args": [],
            "env": {
                "KANKA_TOKEN": kanka_token,
                "KANKA_BASE_URL": kanka_url,
            },
        }

    return servers


def configure_campaign(
    campaign_dir: Path,
    kanka_token: str,
    kanka_url: str,
    dry_run: bool,
    force: bool,
) -> Path:
    """Write (or merge into) the .mcp.json for one campaign. Returns the path
    written to, so callers can detect two campaigns sharing one repo root
    (and therefore one .mcp.json — see git_root)."""
    mcp_dir = git_root(campaign_dir)
    mcp_path = mcp_dir / ".mcp.json"
    new_servers = build_server_block(campaign_dir, kanka_token, kanka_url)

    if mcp_path.exists() and not force:
        existing = json.loads(mcp_path.read_text())
        merged = existing.get("mcpServers", {})
        merged.update(new_servers)
        payload = {**existing, "mcpServers": merged}
        action = "merge"
    else:
        payload = {"mcpServers": new_servers}
        action = "overwrite" if mcp_path.exists() else "create"

    server_names = list(payload["mcpServers"].keys())
    location_note = "" if mcp_dir == campaign_dir else " (repo root, not the campaign dir itself)"
    print(f"  [{action}] {mcp_path}{location_note}  servers: {server_names}")

    if not dry_run:
        mcp_path.write_text(json.dumps(payload, indent=2) + "\n")

    return mcp_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write .mcp.json files for CampaignGenerator MCP servers.",
    )
    parser.add_argument(
        "campaign_dirs",
        nargs="*",
        type=Path,
        metavar="DIR",
        help="Campaign workspace directories (default: all under ~/src/campaigns/)",
    )
    parser.add_argument(
        "--kanka-token",
        default="",
        metavar="TOKEN",
        help="KANKA_TOKEN for the Kanka MCP server (omit to skip kanka)",
    )
    parser.add_argument(
        "--kanka-url",
        default="http://localhost:8081",
        metavar="URL",
        help="KANKA_BASE_URL (default: http://localhost:8081)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without writing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .mcp.json entirely (default: merge)",
    )
    args = parser.parse_args(argv)

    roots = args.campaign_dirs if args.campaign_dirs else [CAMPAIGNS_ROOT]
    campaigns = find_campaigns([p.expanduser().resolve() for p in roots])

    if not campaigns:
        print("No campaign directories found.", file=sys.stderr)
        return 1

    if args.dry_run:
        print("-- dry run, no files will be written --")

    written_to: dict[Path, str] = {}
    for campaign_dir in campaigns:
        print(f"\n{campaign_dir.name}/")
        mcp_path = configure_campaign(
            campaign_dir,
            kanka_token=args.kanka_token,
            kanka_url=args.kanka_url,
            dry_run=args.dry_run,
            force=args.force,
        )
        if mcp_path in written_to:
            print(
                f"  NOTE: {mcp_path} was already configured for "
                f"{written_to[mcp_path]!r} earlier in this run — {campaign_dir.name!r}'s "
                "servers just overwrote those. Only one campaign's servers can be active "
                "in a shared .mcp.json at a time; re-run configure_mcp for whichever "
                "campaign you actually want active before starting a session there."
            )
        written_to[mcp_path] = campaign_dir.name

    print("\nDone." if not args.dry_run else "\n(dry run complete)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
