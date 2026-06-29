#!/usr/bin/env python3
"""Write .mcp.json files for campaign directories.

Configures three MCP servers from CampaignGenerator into one or more campaign
workspace directories:

  campaign   — mcp_server.py       (all campaigns that have config.yaml)
  5etools    — launch_5etools_mcp.py  (campaigns that have refs.yaml)
  kanka      — kanka_mcp.py        (only when --kanka-token is given)

Usage
-----
  # Configure all campaigns under ~/src/campaigns/
  python configure_mcp.py

  # Specific campaign(s)
  python configure_mcp.py ~/src/campaigns/Phandalin ~/src/campaigns/toee

  # Include the Kanka server (needs KANKA_TOKEN)
  python configure_mcp.py --kanka-token <token>

  # Preview without writing
  python configure_mcp.py --dry-run

  # Overwrite existing entries (default: merge, preserving extra servers)
  python configure_mcp.py --force
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CAMPAIGNS_ROOT = Path("~/src/campaigns").expanduser()
SCRIPT_DIR = Path(__file__).resolve().parent

MCP_SERVER = str(SCRIPT_DIR / "mcp_server.py")
FIVETOOLS_SERVER = str(SCRIPT_DIR / "launch_5etools_mcp.py")
KANKA_SERVER = str(SCRIPT_DIR / "kanka_mcp.py")


def find_campaigns(roots: list[Path]) -> list[Path]:
    """Return subdirs of each root that look like campaign workspaces."""
    result = []
    for root in roots:
        if (root / "config.yaml").exists():
            result.append(root)
        else:
            for child in sorted(root.iterdir()):
                if child.is_dir() and (child / "config.yaml").exists():
                    result.append(child)
    return result


def build_server_block(campaign_dir: Path, kanka_token: str, kanka_url: str) -> dict:
    """Build the mcpServers dict for one campaign directory."""
    servers: dict = {}

    servers["campaign"] = {
        "command": "python3",
        "args": [MCP_SERVER, "--campaign-dir", str(campaign_dir)],
    }

    if (campaign_dir / "refs.yaml").exists():
        servers["5etools"] = {
            "command": "python3",
            "args": [FIVETOOLS_SERVER, "--campaign-dir", str(campaign_dir)],
        }

    if kanka_token:
        servers["kanka"] = {
            "command": "python3",
            "args": [KANKA_SERVER],
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
) -> None:
    mcp_path = campaign_dir / ".mcp.json"
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
    print(f"  [{action}] {mcp_path}  servers: {server_names}")

    if not dry_run:
        mcp_path.write_text(json.dumps(payload, indent=2) + "\n")


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

    for campaign_dir in campaigns:
        print(f"\n{campaign_dir.name}/")
        configure_campaign(
            campaign_dir,
            kanka_token=args.kanka_token,
            kanka_url=args.kanka_url,
            dry_run=args.dry_run,
            force=args.force,
        )

    print("\nDone." if not args.dry_run else "\n(dry run complete)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
