#!/usr/bin/env python3
"""MCP server for provenance-aware cross-campaign search — the outward seam.

Constitution V: this file is the *single* boundary between a Claude session and
the provenance engine. Every tool below is a thin wrapper that calls
``provenance.cli.main(argv)`` in-process and returns the captured output. That
is not laziness — it is what makes Constitution VI true rather than aspirational.
The MCP surface cannot drift from the CLI, because it **is** the CLI. Every tool
here has an exactly equivalent shell invocation, and both go through the same
refusals, the same envelope assembly and the same ranking.

## The defining property: this server is not pinned to a campaign

Every other server in ``~/src/campaigns/.mcp.json`` binds one campaign at process
start — ``mcp_server --campaign-dir …``, ``launch_5etools_mcp --campaign-dir …``,
``registry_mcp`` with ``CAMPAIGN_DIR``. Searching a different game today means
editing that file and restarting the session. **This server takes no campaign
argument at all.** Scope arrives per call, and it is required on every call.

The absence *is* the feature (research D4). ``provenance_search`` therefore
declares ``campaigns: list[str]`` with **no default**: the signature offers no
way to express "everything", so no caller can fall into it (FR-006,
Constitution X). Naming two or more campaigns is itself the deliberate
cross-campaign act.

## Nothing here writes

There is no ``notes/`` escape hatch as on the ``campaign`` server, and no
identity-mutating tool — aliasing, merging and marking-distinct stay with
``registry_mcp``, behind explicit GM confirmation (FR-032).
``tests/test_provenance_readonly.py`` enforces that statically over the whole
package, including an allow-list on the one subprocess it spawns.

## Scanner visibility matters more here than at the CLI

A server is spawned by Claude Code with an inherited ``PATH`` that may not match
an interactive shell's — ``rg`` was absent from this host's Python-visible
``PATH`` earlier the same day it was installed. Every search response names the
active scanner and its version, so a model reading the result can tell whether
it got the 0.01 s path or the 0.63 s fallback. Results are identical either way
(research D1).

Setup:
    pip install -e .   # registers the `provenance_mcp` console script
    # Register via .mcp.json — note the empty args, and no campaign anywhere:
    # {"mcpServers": {"provenance": {"command": "provenance_mcp", "args": []}}}
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

from . import cli
from .manifest import resolve_workspace_root

#: Loaded into the model's context with the tool listing, so the scope rule is
#: known before the first call rather than learned from a refusal.
INSTRUCTIONS = """\
Read-only, provenance-labeled search across the D&D campaign workspace at {root}.
Every hit is returned with its trust tier, whether it is machine-generated (and by
which pipeline stage), the chapter it reflects, and any recorded known-stale
correction — attached inline.

Scope is required on every search. There is no "all campaigns". Name the campaign
you mean. Call provenance_capabilities first if you do not know which campaigns
exist or whether a backend is live on this machine.

A hit tagged `generated_by: <stage>` will be clobbered on the next pipeline run and
may be stale — verify it against an authoritative hit before treating it as fact.
An empty result from an unavailable backend is reported as unavailable, never as
zero hits.

This server never writes. Identity changes (aliasing, merging, marking distinct)
belong to the `registry` server, behind explicit GM confirmation.\
"""


def _run(argv: list[str]) -> str:
    """Call the CLI in-process and fold its output into one string.

    ``SystemExit`` is caught rather than allowed to propagate: argparse exits the
    process on a malformed invocation, and an MCP server that dies on the first
    bad call is worse than one that reports the error.
    """
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2

    parts = [p.strip() for p in (out.getvalue(), err.getvalue()) if p.strip()]
    text = "\n".join(parts) if parts else ("(no output)" if code == 0 else "(failed)")
    # Exit 1 from `search`/`check` is a refusal or a findings report, and the
    # text IS the payload — but the caller must still be able to see that the
    # tool did not simply find nothing.
    return text if code == 0 else f"EXIT {code}:\n{text}"


# ── core functions (unit-testable without the `mcp` package) ─────────────────


def provenance_search(
    query: str,
    campaigns: list[str],
    tiers: list[str] | None = None,
    horizon: int | None = None,
    expand_aliases: bool = False,
    regex: bool = False,
    case_sensitive: bool = False,
    limit: int = 50,
    context_lines: int = 2,
) -> str:
    """Equivalent CLI: ``provenance search <query> --campaign … [--tier …] […]``."""
    argv = ["search", query]
    for name in campaigns or ():
        argv += ["--campaign", name]
    for tier in tiers or ():
        argv += ["--tier", tier]
    if horizon is not None:
        argv += ["--horizon", str(horizon)]
    if expand_aliases:
        argv.append("--expand-aliases")
    if regex:
        argv.append("--regex")
    if case_sensitive:
        argv.append("--case-sensitive")
    argv += ["--limit", str(limit), "--context-lines", str(context_lines)]
    return _run(argv)


def provenance_resolve(surface_form: str, campaign: str) -> str:
    """Equivalent CLI: ``provenance resolve <surface-form> --campaign NAME``."""
    return _run(["resolve", surface_form, "--campaign", campaign])


def provenance_capabilities() -> str:
    """Equivalent CLI: ``provenance capabilities``."""
    return _run(["capabilities"])


def provenance_check(campaigns: list[str] | None = None) -> str:
    """Equivalent CLI: ``provenance check [--campaign NAME …]``.

    ``campaigns=None`` is legal here and means "validate the whole manifest".
    That is not a Constitution X violation: ``check`` reads only the authored
    YAML plus a file-existence test, spends no tokens, and returns no campaign
    content. The blast radius the principle guards is content and token spend,
    and ``check`` has neither.
    """
    argv = ["check"]
    for name in campaigns or ():
        argv += ["--campaign", name]
    return _run(argv)


# ── the server ───────────────────────────────────────────────────────────────


def build_server():
    """Construct the FastMCP server. Bound to no campaign — that is the point.

    Imports ``mcp`` lazily so every core function above imports and unit-tests
    without the package installed — the same guard ``registry_mcp`` and
    ``kanka_mcp`` use.
    """
    from mcp.server.fastmcp import FastMCP

    workspace = resolve_workspace_root(None)
    mcp = FastMCP("provenance", instructions=INSTRUCTIONS.format(root=workspace.path))

    @mcp.tool()
    def provenance_search_tool(
        query: str,
        campaigns: list[str],
        tiers: list[str] | None = None,
        horizon: int | None = None,
        expand_aliases: bool = False,
        regex: bool = False,
        case_sensitive: bool = False,
        limit: int = 50,
        context_lines: int = 2,
    ) -> str:
        """Search named campaigns; every hit comes back provenance-labeled.

        campaigns — REQUIRED, no default. Name the campaign(s) you mean; there is
        no "all campaigns" token and an empty list is refused with the list of
        known campaigns. Naming two or more IS the deliberate cross-campaign act,
        and hits stay labeled by owning campaign — never merged across games.

        tiers — filter to authoritative / search_accelerator / working_reference /
        staging / unclassified. Suppressed hits are COUNTED in the response, never
        silently dropped.

        horizon — chapter number; refused for a campaign that declares no marker
        rather than served unfiltered.

        A hit tagged `generated_by` will be clobbered on the next pipeline run.
        Prefer an authoritative-tier hit when the two disagree.
        """
        return provenance_search(
            query,
            campaigns,
            tiers,
            horizon,
            expand_aliases,
            regex,
            case_sensitive,
            limit,
            context_lines,
        )

    @mcp.tool()
    def provenance_resolve_tool(surface_form: str, campaign: str) -> str:
        """Resolve a surface form to its canonical entity within ONE campaign.

        Three distinguishable outcomes, never collapsed: resolved / not-found
        (the store exists and no link is recorded) / no-store (the campaign has
        none). Name similarity is never treated as evidence of identity.

        Read-only. Identity changes belong to the `registry` server.
        """
        return provenance_resolve(surface_form, campaign)

    @mcp.tool()
    def provenance_capabilities_tool() -> str:
        """Which campaigns exist, and which backends are live ON THIS MACHINE.

        Call this before trusting an empty result. An unavailable backend is
        reported as unavailable with a reason — never as zero hits.
        """
        return provenance_capabilities()

    @mcp.tool()
    def provenance_check_tool(campaigns: list[str] | None = None) -> str:
        """Validate the authored manifest and corrections records for GM review.

        Reports tier-glob ambiguity, stale correction entries, unclassified-heavy
        directories and unattributable chapter files. Never edits, never
        auto-resolves an ambiguity.
        """
        return provenance_check(campaigns)

    return mcp


def main() -> None:
    """Console-script entry point (``provenance_mcp`` — [project.scripts])."""
    build_server().run()


if __name__ == "__main__":  # pragma: no cover
    main()
