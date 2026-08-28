#!/usr/bin/env python3
"""Write CampaignGenerator MCP servers into OpenClaw configuration.

Mirror of ``configure_mcp.py``, but instead of writing a campaign-local
``.mcp.json`` for Claude Code, it registers the CampaignGenerator MCP servers
into OpenClaw's ``mcp.servers`` (in ``~/.openclaw/openclaw.json``) so OpenClaw's
own agent runtimes can use them.

OpenClaw stdio MCP servers take a ``command`` (absolute path — OpenClaw does
not inherit the CampaignGenerator venv's PATH) plus ``args`` and optionally
``env``. Each server's config dependency differs:

  campaign   — mcp_server console script. Loads <campaign>/config/config.yaml.
               Must pass --campaign-dir (or set env CAMPAIGN_DIR). Always added.
  5etools    — launch_5etools_mcp console script. Resolves refs.yaml +
               refs.local.yaml via resolve_refs, builds a symlink farm, execs
               node. Requires the fivetools_data root to resolve (refs.local.yaml,
               FIVETOOLS_DATA_ROOT env, or mneme wiring.yaml) AND a real
               refs.yaml + refs.local.yaml in the campaign's config dir —
               WITHOUT refs.local.yaml the server fails at resolve time.
               Added only when the campaign has config/refs.yaml AND a
               resolvable fivetools_data root is detectable.
  registry   — registry_mcp console script. Reads CAMPAIGN_DIR env only.
               Added only when docs/entity_registry.yaml exists.
  kanka      — kanka_mcp console script. Needs KANKA_TOKEN + KANKA_BASE_URL env.
               Added only when --kanka-token is given.

Usage
-----
  # Register all campaigns under ~/src/campaigns/ (merge, keep existing)
  configure_openclaw_mcp

  # Specific campaign(s)
  configure_openclaw_mcp ~/src/campaigns/Phandalin

  # Name servers by campaign, e.g. campaign-phandalin / 5etools-phandalin
  configure_openclaw_mcp --prefix campaign

  # Include kanka (needs KANKA_TOKEN)
  configure_openclaw_mcp --kanka-token <token>

  # Show what would be written without writing
  configure_openclaw_mcp --dry-run

  # Remove / enable / disable
  configure_openclaw_mcp --unset
  configure_openclaw_mcp --disable
  configure_openclaw_mcp --enable

  # Alternative config file
  configure_openclaw_mcp --config /path/to/openclaw.json

  # Config subdir holding refs.yaml / refs.local.yaml (default 'config')
  configure_openclaw_mcp --config-dir cfg        # reads <campaign>/cfg/refs.yaml
  configure_openclaw_mcp --config-dir cfg --dry-run

Install the console script (from the CampaignGenerator repo):
  pip install -e .   (adds configure_openclaw_mcp to .venv/bin next to configure_mcp)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

CAMPAIGNS_ROOT = Path("~/src/campaigns").expanduser()
DEFAULT_OPENCLAW_CONFIG = Path("~/.openclaw/openclaw.json").expanduser()
# The .venv that holds the CampaignGenerator console scripts. OpenClaw does not
# put .venv/bin on PATH, so every command is emitted as its absolute path here.
DEFAULT_VENV_BIN = Path("~/.venv/bin").expanduser()

# The root names launch_5etools_mcp needs to resolve from refs.local.yaml.
FIVETOOLS_ENV = "FIVETOOLS_DATA_ROOT"


# ── Campaign discovery (identical logic to configure_mcp.py) ────────────


def find_campaigns(roots: list[Path], config_dir_name: str = "config") -> list[Path]:
    """Return subdirs of each root that look like campaign workspaces
    (a dir with its own ``<config_dir>/config.yaml``), or the root itself if it
    is one. Mirrors configure_mcp.find_campaigns, but honors a non-default
    config subdir (``--config-dir`` / CAMPAIGN_CONFIG_DIR) when locating
    ``config.yaml``."""
    result = []
    for root in roots:
        if (root / config_dir_name / "config.yaml").exists():
            result.append(root)
        else:
            for child in sorted(root.iterdir()):
                if child.is_dir() and (child / config_dir_name / "config.yaml").exists():
                    result.append(child)
    return result


# ── Per-server config dependency checks ──────────────────────────────────


def _resolvable_fivetools_root(campaign_dir: Path, config_dir: Path) -> Path | None:
    """Best-effort detect whether the 5etools data root resolves for a campaign.

    launch_5etools_mcp resolves roots with precedence:
      refs.local.yaml > FIVETOOLS_DATA_ROOT env > mneme wiring.yaml.
    We cannot run the full resolver cheaply for every server, so we mirror the
    precedence here: check the campaign's refs.local.yaml roots.fivetools_data,
    then the env var, then mneme wiring.yaml. Any hit that points at a real
    dir (with a sibling mcp/index.js) counts as resolvable.

    ``config_dir`` is the per-campaign directory holding refs.yaml /
    refs.local.yaml (default ``<campaign>/config``; overridable with
    ``--config-dir`` or the CAMPAIGN_CONFIG_DIR env). Return the resolved
    root Path, or None if unconfigured.
    """
    # 1. refs.local.yaml in the campaign's config dir
    local = config_dir / "refs.local.yaml"
    if local.is_file():
        try:
            import yaml  # noqa: PLC0415
            raw = yaml.safe_load(local.read_text(encoding="utf-8")) or {}
            roots = raw.get("roots") or {}
            val = roots.get("fivetools_data")
            if isinstance(val, str) and val.strip():
                p = Path(val).expanduser().resolve()
                if p.is_dir():
                    return p
        except Exception:  # noqa: BLE001 - mirroring resolver leniency
            pass
    # 2. env var
    env = os.environ.get(FIVETOOLS_ENV)
    if env:
        p = Path(env).expanduser().resolve()
        if p.is_dir():
            return p
    # 3. mneme wiring.yaml (campaignlib.wiring_path)
    try:
        from campaignlib.wiring import wiring_path  # noqa: PLC0415
        wired = wiring_path("fivetools_data_root")
        if wired and wired.is_dir():
            return wired.resolve()
    except Exception:  # noqa: BLE001
        pass
    return None


def _5etools_data_root_has_mcp_index(root: Path) -> bool:
    """The MCP server index.js ships beside the data tree:
    ``<fivetools_data>/../mcp/index.js`` (fivetools_data is `<repo>/data`)."""
    return (root.parent / "mcp" / "index.js").is_file()


# ── Server block construction ───────────────────────────────────────────


def build_server_block(
    campaign_dir: Path,
    venv_bin: Path,
    config_dir: Path,
    kanka_token: str,
    kanka_url: str,
    prefix: str,
) -> tuple[dict, list[str]]:
    """Build servers keyed by name for one campaign.

    ``config_dir`` is the per-campaign directory holding refs.yaml /
    refs.local.yaml (default ``<campaign>/config``). It is baked into every
    server's env as CAMPAIGN_CONFIG_DIR so the launched server resolves its
    config from the same place this script validated (the campaign/dirs and
    resolve_refs honor that env var via campaignlib.constants.CONFIG_DIR_NAME).

    Returns ``(servers, warnings)`` where warnings lists config gaps found
    (e.g. 5etools skipped because refs.local.yaml is missing)."""
    servers: dict = {}
    warnings: list[str] = []

    def _cmd(name: str) -> str:
        p = venv_bin / name
        return str(p) if p.is_file() else str(venv_bin / name)  # keep path anyway

    # Key naming: no prefix -> "campaign", "5etools", ...  With prefix ->
    # "<prefix><campaign>__campaign", "<prefix><campaign>__5etools", ... so
    # multiple campaigns can coexist in one OpenClaw config without collision.
    def _key(server: str) -> str:
        return f"{prefix}{campaign_dir.name}__{server}" if prefix else server

    def _env(base: dict | None = None) -> dict:
        env = dict(base or {})
        env["CAMPAIGN_DIR"] = str(campaign_dir)
        # If the campaign's config lives in a non-default subdir (not
        # "config"), tell every launched server where it is. campaignlib reads
        # CAMPAIGN_CONFIG_DIR as the config *subdir name* under the campaign
        # root (CONFIG_DIR_NAME), so we emit exactly that name; each server then
        # resolves config/<file> via `<campaign>/<CAMPAIGN_CONFIG_DIR>/<file>`.
        if config_dir.name != "config":
            env["CAMPAIGN_CONFIG_DIR"] = config_dir.name
        return env

    servers[_key("campaign")] = {
        "enabled": True,
        "command": _cmd("mcp_server"),
        "args": ["--campaign-dir", str(campaign_dir)],
        "env": _env(),
    }

    # 5etools — the one that depends most heavily on baked config.
    refs_path = config_dir / "refs.yaml"
    if refs_path.is_file():
        root = _resolvable_fivetools_root(campaign_dir, config_dir)
        if root is None:
            warnings.append(
                f"5etools: {campaign_dir.name} has refs.yaml but no resolvable "
                f"fivetools_data root (no refs.local.yaml / {FIVETOOLS_ENV} env / "
                f"wiring.yaml). launch_5etools_mcp would fail at resolve time. "
                f"Skipped."
            )
        elif not _5etools_data_root_has_mcp_index(root):
            warnings.append(
                f"5etools: {campaign_dir.name} fivetools_data root {root} has no "
                f"sibling mcp/index.js. launch_5etools_mcp would fail to exec. Skipped."
            )
        else:
            key = _key("5etools")
            servers[key] = {
                "enabled": True,
                "command": _cmd("launch_5etools_mcp"),
                "args": ["--campaign-dir", str(campaign_dir)],
                "env": _env(),
            }
    else:
        warnings.append(
            f"5etools: {campaign_dir.name} has no {config_dir.name}/refs.yaml — skipped."
        )

    # registry — CAMPAIGN_DIR env only.
    if (campaign_dir / "docs" / "entity_registry.yaml").is_file():
        key = _key("registry")
        servers[key] = {
            "enabled": True,
            "command": _cmd("registry_mcp"),
            "args": [],
            "env": _env(),
        }

    # kanka — token required.
    if kanka_token:
        key = _key("kanka")
        servers[key] = {
            "enabled": True,
            "command": _cmd("kanka_mcp"),
            "args": [],
            "env": _env({
                "KANKA_TOKEN": kanka_token,
                "KANKA_BASE_URL": kanka_url,
            }),
        }

    return servers, warnings


# ── OpenClaw config load/save ───────────────────────────────────────────


def load_openclaw_config(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text())
    return {}


def save_openclaw_config(path: Path, cfg: dict) -> None:
    path.write_text(json.dumps(cfg, indent=2) + "\n")


# ── Action handlers ──────────────────────────────────────────────────────


def cmd_configure(  # noqa: C901
    cfg_path: Path,
    campaigns: list[Path],
    venv_bin: Path,
    config_dir_name: str,
    kanka_token: str,
    kanka_url: str,
    prefix: str,
    force: bool,
    dry_run: bool,
) -> int:
    cfg = load_openclaw_config(cfg_path)
    servers = cfg.setdefault("mcp", {}).setdefault("servers", {})

    all_warnings: list[str] = []
    for campaign_dir in campaigns:
        print(f"\n{campaign_dir.name}/")
        config_dir = campaign_dir / config_dir_name
        block, warnings = build_server_block(
            campaign_dir, venv_bin, config_dir, kanka_token, kanka_url, prefix
        )
        all_warnings.extend(warnings)
        for w in warnings:
            print(f"  WARN  {w}")

        for name, spec in block.items():
            servers[name] = spec
            print(f"  [set]  {name}: {spec['command']} {spec.get('args', [])}")

    if not dry_run:
        save_openclaw_config(cfg_path, cfg)
        print(f"\nWrote {cfg_path}  (mcp.servers keys: {list(servers.keys())})")
        print(
            "NOTE: active OpenClaw processes may need `openclaw mcp reload` or a "
            "Gateway restart to pick up new servers."
        )
    else:
        print(f"\n[dry-run] would write {cfg_path}")

    if not force:
        print(
            "\nNOTE: merged into existing mcp.servers (existing entries preserved). "
            "Use --force to drop previously-registered CampaignGenerator servers "
            "you no longer want."
        )
    return 0


def cmd_toggle(
    cfg_path: Path,
    campaigns: list[Path],
    venv_bin: Path,
    config_dir_name: str,
    kanka_token: str,
    kanka_url: str,
    prefix: str,
    mode: str,  # "enable" | "disable" | "unset"
    dry_run: bool,
) -> int:
    cfg = load_openclaw_config(cfg_path)
    servers = cfg.setdefault("mcp", {}).setdefault("servers", {})
    changed = 0
    for campaign_dir in campaigns:
        config_dir = campaign_dir / config_dir_name
        meresult, _ = build_server_block(
            campaign_dir, venv_bin, config_dir, kanka_token, kanka_url, prefix
        )
        for name in meresult:
            if name not in servers:
                continue
            if mode == "unset":
                if not dry_run:
                    del servers[name]
                print(f"  [unset]  {name}")
            else:
                want = mode == "enable"
                if not dry_run:
                    servers[name]["enabled"] = want
                print(f"  [{mode}]    {name}")
            changed += 1
    if changed == 0:
        print(f"No registered CampaignGenerator servers matched under cfg={cfg_path}.")
        return 1
    if not dry_run:
        save_openclaw_config(cfg_path, cfg)
        print(f"\nWrote {cfg_path}")
    else:
        print(f"\n[dry-run] would write {cfg_path}")
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "campaign_dirs",
        nargs="*",
        type=Path,
        metavar="DIR",
        help="Campaign workspace dirs (default: all under ~/src/campaigns/)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_OPENCLAW_CONFIG,
        help="OpenClaw config file (default: ~/.openclaw/openclaw.json)",
    )
    parser.add_argument(
        "--venv-bin",
        type=Path,
        default=DEFAULT_VENV_BIN,
        help="Dir holding the CampaignGenerator console scripts (default: ~/.venv/bin)",
    )
    parser.add_argument(
        "--config-dir",
        default="",
        metavar="NAME",
        help="Per-campaign config subdir holding refs.yaml / refs.local.yaml. "
        "Default: 'config' (or $CAMPAIGN_CONFIG_DIR). Passed to each server as "
        "CAMPAIGN_CONFIG_DIR so it resolves refs from the same place. Must be a "
        "subdir name under the campaign dir, e.g. --config-dir cfg.",
    )
    parser.add_argument(
        "--kanka-token",
        default="",
        metavar="TOKEN",
        help="KANKA_TOKEN for the kanka MCP server (omit to skip kanka)",
    )
    parser.add_argument(
        "--kanka-url",
        default="http://localhost:8081",
        metavar="URL",
        help="KANKA_BASE_URL (default: http://localhost:8081)",
    )
    parser.add_argument(
        "--prefix",
        default="",
        metavar="STR",
        help='Prefix server names per-campaign, e.g. "campaign" -> '
        "campaign-phandalin / 5etools-phandalin (avoids collisions when "
        "registering multiple campaigns into one OpenClaw config)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Set/overwrite without the merge note (still merges into existing config)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without writing",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--unset",
        action="store_true",
        help="Remove these campaigns' servers from OpenClaw config",
    )
    group.add_argument(
        "--disable",
        action="store_true",
        help="Set enabled:false on these campaigns' servers (keep definition)",
    )
    group.add_argument(
        "--enable",
        action="store_true",
        help="Set enabled:true on these campaigns' servers",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.venv_bin.is_dir():
        print(
            f"Venv bin dir not found: {args.venv_bin}. Use --venv-bin.",
            file=sys.stderr,
        )
        return 1

    # Per-campaign config subdir: --config-dir > CAMPAIGN_CONFIG_DIR env > "config".
    # Computed early because campaign discovery also depends on it.
    config_dir_name = args.config_dir or os.environ.get("CAMPAIGN_CONFIG_DIR") or "config"

    roots = args.campaign_dirs if args.campaign_dirs else [CAMPAIGNS_ROOT]
    # Resolve user-supplied paths: absolute stays; relative paths are tried
    # against CWD first, then against CAMPAIGNS_ROOT (so bare names like
    # `Phandalin` work even when CWD is elsewhere).
    resolved_roots: list[Path] = []
    for r in roots:
        p = Path(r).expanduser()
        if p.is_absolute():
            resolved_roots.append(p)
            continue
        cand_cwd = (Path.cwd() / p).resolve()
        cand_root = (CAMPAIGNS_ROOT / p).resolve()
        if cand_cwd.exists():
            resolved_roots.append(cand_cwd)
        elif cand_root.is_dir():
            resolved_roots.append(cand_root)
        else:
            resolved_roots.append(cand_cwd)  # let find_campaigns fail clearly
    campaigns = find_campaigns([p.resolve() for p in resolved_roots], config_dir_name)
    if not campaigns:
        print("No campaign directories found.", file=sys.stderr)
        return 1

    if args.dry_run:
        print("-- dry run, no files will be written --")

    if args.unset or args.disable or args.enable:
        mode = "unset" if args.unset else ("disable" if args.disable else "enable")
        return cmd_toggle(
            args.config.expanduser().resolve(),
            campaigns,
            args.venv_bin.expanduser().resolve(),
            config_dir_name,
            args.kanka_token,
            args.kanka_url,
            args.prefix,
            mode,
            args.dry_run,
        )

    return cmd_configure(
        args.config.expanduser().resolve(),
        campaigns,
        args.venv_bin.expanduser().resolve(),
        config_dir_name,
        args.kanka_token,
        args.kanka_url,
        args.prefix,
        args.force,
        args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
