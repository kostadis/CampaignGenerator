#!/usr/bin/env python3
"""MCP server — drive the Kanka CE ⇄ world_state.md sync from Claude.

Exposes the Kanka sync engine (kanka_sync pull + kanka_push push-back) as MCP
tools so a Claude client can refresh grounding and commit post-session canon
changes without dropping to a shell:

  kanka_pull(campaign, output, include_private)
      Kanka CE → world_state.md grounding markdown. Read-only against Kanka.

  kanka_push_preview(campaign, input)        ← safe default
      DRY RUN: parse an edited world_state.md and report the create/update/skip
      plan. Writes nothing.

  kanka_push_apply(campaign, input)          ← explicit, mutates canon
      Commit those creates/updates to Kanka. Never deletes; skip-if-unchanged;
      continue-on-error. Run kanka_push_preview first; only apply on an explicit
      user request.

Design notes:
  - The FastMCP import is guarded (lazy, inside build_server) so the core
    functions below import and unit-test without the `mcp` package installed.
  - The core functions take a KankaClient so they are testable with a fake;
    the tool wrappers construct the real client and surface clean errors
    (missing KANKA_TOKEN, missing input file) instead of stack traces.

Setup:
    pip install -e .   # registers the `kanka_mcp` console script
    # Register via .mcp.json — pass KANKA_TOKEN in the server's `env` block:
    # {
    #   "mcpServers": {
    #     "kanka": {
    #       "command": "kanka_mcp",
    #       "env": {"KANKA_TOKEN": "<token>", "KANKA_BASE_URL": "http://localhost:8081"}
    #     }
    #   }
    # }
"""

import os
from pathlib import Path

from .kanka_client import KankaClient
from .kanka_push import apply_changes, parse_world_state, plan_changes
from .kanka_sync import build_world_state

DEFAULT_BASE_URL = os.environ.get("KANKA_BASE_URL", "http://localhost:8081")


def make_client(base_url: str | None = None) -> KankaClient:
    """Build a KankaClient from env. Raises RuntimeError if KANKA_TOKEN is unset.

    MCP servers don't inherit the shell's `.env`; pass KANKA_TOKEN in the
    server's `env` block in .mcp.json.
    """
    token = os.environ.get("KANKA_TOKEN")
    if not token:
        raise RuntimeError(
            "KANKA_TOKEN not set — add it to the kanka server's `env` block in .mcp.json."
        )
    return KankaClient(token, base_url=base_url or DEFAULT_BASE_URL)


# ── Core (no `mcp` dependency; unit-tested) ────────────────────────────────────

def pull_world_state(client, campaign: int, include_private: bool = False) -> str:
    """Render a Kanka campaign as world_state.md grounding markdown."""
    markdown, _counts = build_world_state(client, campaign, include_private)
    return markdown


def _format_plan(changes: list[dict]) -> str:
    counts = {"create": 0, "update": 0, "skip": 0}
    lines: list[str] = []
    for ch in changes:
        counts[ch["action"]] += 1
        if ch["action"] != "skip":
            lines.append(f"  {ch['action'].upper():6} {ch['entity_type']}/{ch['name']}")
    head = f"create={counts['create']} update={counts['update']} skip={counts['skip']}"
    return head + ("\n" + "\n".join(lines) if lines else "")


def push_preview(client, campaign: int, markdown: str) -> str:
    """Dry-run plan for pushing an edited world_state.md back to Kanka."""
    changes = plan_changes(client, campaign, parse_world_state(markdown))
    return "[DRY RUN] " + _format_plan(changes)


def push_apply(client, campaign: int, markdown: str) -> str:
    """Commit creates/updates from an edited world_state.md to Kanka."""
    changes = plan_changes(client, campaign, parse_world_state(markdown))
    counts = apply_changes(client, campaign, changes, dry_run=False)
    return (f"[APPLIED] create={counts['create']} update={counts['update']} "
            f"skip={counts['skip']} failed={counts['failed']}")


# ── MCP server (FastMCP imported lazily so core stays dependency-free) ──────────

def build_server():
    """Construct the FastMCP server. Imports `mcp` lazily — call only when serving."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "kanka",
        instructions=(
            "Sync a self-hosted Kanka CE campaign with a CampaignGenerator "
            "world_state.md grounding doc. Use kanka_pull to refresh grounding "
            "from Kanka, kanka_push_preview to see what an edited world_state.md "
            "would change in Kanka, and kanka_push_apply ONLY on an explicit user "
            "request to commit those changes. Apply mutates campaign canon "
            "(creates/updates, never deletes); always preview first."
        ),
    )

    @mcp.tool()
    def kanka_pull(campaign: int = 1, output: str = "",
                   include_private: bool = False) -> str:
        """Pull a Kanka campaign into world_state.md grounding markdown.

        Read-only against Kanka. With `output`, write the markdown there and
        return a summary; otherwise return the markdown itself. `include_private`
        folds in GM-secret (is_private) entities — off by default.
        """
        try:
            client = make_client()
        except RuntimeError as exc:
            return f"Error: {exc}"
        markdown = pull_world_state(client, campaign, include_private)
        if output:
            p = Path(output).expanduser().resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(markdown, encoding="utf-8")
            return f"Wrote {p} ({len(markdown)} chars)."
        return markdown

    @mcp.tool()
    def kanka_push_preview(campaign: int = 1, input: str = "") -> str:
        """DRY RUN — show the create/update/skip plan for pushing an edited
        world_state.md back to Kanka. Writes nothing. Run this before apply.
        """
        try:
            client = make_client()
            markdown = Path(input).expanduser().read_text(encoding="utf-8")
        except (RuntimeError, FileNotFoundError) as exc:
            return f"Error: {exc}"
        return push_preview(client, campaign, markdown)

    @mcp.tool()
    def kanka_push_apply(campaign: int = 1, input: str = "") -> str:
        """COMMIT — create/update Kanka entities from an edited world_state.md.

        Mutates campaign canon (never deletes; skips unchanged entities;
        continues past per-entity failures). Run kanka_push_preview first and
        only call this on an explicit user request to write back.
        """
        try:
            client = make_client()
            markdown = Path(input).expanduser().read_text(encoding="utf-8")
        except (RuntimeError, FileNotFoundError) as exc:
            return f"Error: {exc}"
        return push_apply(client, campaign, markdown)

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
