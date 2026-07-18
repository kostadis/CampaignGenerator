#!/usr/bin/env python3
"""MCP server for the campaign entity registry (docs/entity_registry.yaml).

Exposes every ``registry`` CLI subcommand (``entity_registry/registry.py``)
as an MCP tool, so a Claude session gets the CLI's full surface — subcommand
names, flags, ordering rules, guard semantics — from the tool listing itself
instead of re-reading ``registry.py``'s module docstring or ``--help`` output
each session.

Design notes:
  - The FastMCP import is guarded (lazy, inside build_server) so the core
    functions below import and unit-test without the `mcp` package installed
    — same shape as kanka_mcp.py.
  - Every tool is a thin wrapper that calls ``entity_registry.registry.main()``
    in-process (not a subprocess — this is the exact code path
    ``tests/test_registry_cli.py`` already exercises) and returns its
    captured stdout/stderr as a formatted string, matching the plain-``str``
    tool convention used throughout this codebase's other MCP servers
    (pipelines/rlm/mcp_server.py, kanka_mcp.py).
  - ``add`` is the one CLI subcommand with an interactive prompt (the
    near-miss "[1] same entity / [2] new / [3] abort" choice). An MCP tool
    call has no terminal on the other end — the server process's stdin is
    the MCP transport channel, not a real prompt — so ``_run_main`` never
    lets ``input()`` block: it's patched to raise unless the caller
    (``registry_add``) explicitly supplies a canned answer. ``registry_add``
    itself never risks the interactive branch: on a near-miss it always
    supplies "3" (abort — nothing written) and returns the CLI's own
    near-miss table plus next-step guidance (call again with
    ``confirm_new=true``, or use ``registry_alias`` instead) rather than
    guessing an answer on the GM's behalf.
  - Identity is a precision decision (this project's own LLM Pipeline Design
    Rule): registry_add / registry_alias / registry_merge /
    registry_mark_distinct / registry_mark_rejected all mutate entity
    identity and should only be called once the GM has explicitly confirmed
    the specific mapping in conversation — see the server `instructions`
    below and each tool's docstring. registry_check and
    registry_triage_candidates are read-only surfacing tools; run those
    first.

Setup:
    pip install -e .   # registers the `registry_mcp` console script
    # Register via .mcp.json (one server instance per campaign directory):
    # {
    #   "mcpServers": {
    #     "registry": {
    #       "command": "registry_mcp",
    #       "env": {"CAMPAIGN_DIR": "/path/to/your/campaign"}
    #     }
    #   }
    # }
"""

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from . import registry

# ── campaign_dir resolution (env var → CLI arg → cwd) ───────────────────────


def resolve_campaign_dir(argv: list[str] | None = None) -> Path:
    argv = sys.argv if argv is None else argv
    campaign_dir_arg = ""
    for i, arg in enumerate(argv):
        if arg == "--campaign-dir" and i + 1 < len(argv):
            campaign_dir_arg = argv[i + 1]
            break
    campaign_dir_str = os.environ.get("CAMPAIGN_DIR", "") or campaign_dir_arg or str(Path.cwd())
    return Path(campaign_dir_str).expanduser().resolve()


# ── core: in-process CLI runner ──────────────────────────────────────────────


def _run_main(argv: list[str], input_response: str | None = None) -> tuple[str, str, int]:
    """Run ``entity_registry.registry.main(argv)`` in-process, capturing output.

    Returns (stdout, stderr, exit_code). Two hazards this guards against:

    - argparse validation errors (missing/bad flags) call ``sys.exit(2)``
      internally, which raises ``SystemExit`` — left uncaught, that would
      kill the whole MCP server process on the very first malformed call.
      Caught here and converted to a normal (stdout, stderr, code) return.
    - No registry subcommand should ever block on real interactive input
      inside a tool call. ``input_response`` supplies a canned answer for
      the one CLI path that prompts (``add``'s near-miss disambiguation —
      see registry_add below); any other, unexpected ``input()`` call is a
      bug in this wrapper, not a real prompt to answer, so it fails loud
      instead of hanging the server on the transport-channel stdin.
    """

    def _guard(prompt: str = "") -> str:
        if input_response is not None:
            return input_response
        raise RuntimeError(
            f"registry CLI unexpectedly prompted for input ({prompt!r}) — "
            "this MCP wrapper does not support interactive prompts"
        )

    out, err = io.StringIO(), io.StringIO()
    try:
        with mock.patch("builtins.input", side_effect=_guard), redirect_stdout(out), redirect_stderr(err):
            code = registry.main(argv)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 2
    return out.getvalue(), err.getvalue(), code


def _format(out: str, err: str, code: int) -> str:
    """Fold captured stdout/stderr into one message, success or failure alike."""
    parts = [p.strip() for p in (out, err) if p.strip()]
    text = "\n".join(parts) if parts else ("(no output)" if code == 0 else "(failed, no output)")
    return text if code == 0 else f"FAILED (exit {code}):\n{text}"


# ── core: one function per CLI subcommand ────────────────────────────────────


def registry_init(campaign_dir: Path, campaign: str | None = None) -> str:
    argv = ["init", str(campaign_dir)]
    if campaign:
        argv += ["--campaign", campaign]
    return _format(*_run_main(argv))


def registry_add(
    campaign_dir: Path,
    name: str,
    type: str,
    aliases: list[str] | None = None,
    note: str | None = None,
    provenance: str | None = None,
    source: str | None = None,
    scope: str | None = None,
    confirm_new: bool = False,
) -> str:
    argv = ["add", str(campaign_dir), "--name", name, "--type", type]
    if aliases:
        argv += ["--aliases", *aliases]
    if note:
        argv += ["--note", note]
    if provenance:
        argv += ["--provenance", provenance]
    if source:
        argv += ["--source", source]
    if scope:
        argv += ["--scope", scope]
    if confirm_new:
        argv.append("--yes")

    # confirm_new=True passes --yes, so args.yes is truthy and cmd_add's
    # near-miss branch (`if near and not args.yes`) never runs regardless of
    # input_response — "3" here is a pure safety net, not the live answer.
    out, err, code = _run_main(argv, input_response="3")
    if code == 0:
        return out.strip()
    if "looks similar to existing name" in out:
        return (
            out.strip()
            + "\n\nNot added — a similar name already exists (shown above), and no GM confirmation "
            "was given for either reading. Ask the GM which is correct, then either call registry_add "
            "again with confirm_new=true to register this as a genuinely distinct new entity, or call "
            "registry_alias to attach this name as an alias of the existing entity instead."
        )
    return _format(out, err, code)


def registry_alias(campaign_dir: Path, to: str, variants: list[str]) -> str:
    return _format(*_run_main(["alias", str(campaign_dir), "--to", to, *variants]))


def registry_merge(campaign_dir: Path, into: str, others: list[str]) -> str:
    return _format(*_run_main(["merge", str(campaign_dir), "--into", into, *others]))


def registry_mark_distinct(campaign_dir: Path, name_a: str, name_b: str) -> str:
    return _format(*_run_main(["mark-distinct", str(campaign_dir), name_a, name_b]))


def registry_mark_rejected(campaign_dir: Path, names: list[str]) -> str:
    return _format(*_run_main(["mark-rejected", str(campaign_dir), *names]))


def registry_project(campaign_dir: Path) -> str:
    return _format(*_run_main(["project", str(campaign_dir)]))


def registry_check(campaign_dir: Path) -> str:
    out, err, code = _run_main(["check", str(campaign_dir)])
    # code == 1 here means "findings exist", not a tool failure — the report
    # itself (in stdout) is the useful payload either way.
    parts = [p.strip() for p in (out, err) if p.strip()]
    return "\n".join(parts) if parts else "(no output)"


def registry_triage_candidates(
    campaign_dir: Path,
    bible: str | None = None,
    min_len: int | None = None,
    min_count: int | None = None,
) -> str:
    argv = ["triage-candidates", str(campaign_dir)]
    if bible:
        argv += ["--bible", bible]
    if min_len is not None:
        argv += ["--min-len", str(min_len)]
    if min_count is not None:
        argv += ["--min-count", str(min_count)]
    out, err, code = _run_main(argv)
    if code != 0:
        return _format(out, err, code)
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        return _format(out, err, code)
    summary = err.strip()  # "triage-candidates: N candidate(s), M with near-miss hint(s)"
    return json.dumps(payload, indent=2, ensure_ascii=False) + (f"\n\n{summary}" if summary else "")


def registry_import_inventory(
    campaign_dir: Path,
    md: str,
    provenance: str | None = None,
    source: str | None = None,
    heading_type: list[str] | None = None,
) -> str:
    argv = ["import-inventory", str(campaign_dir), md]
    if provenance:
        argv += ["--provenance", provenance]
    if source:
        argv += ["--source", source]
    if heading_type:
        for item in heading_type:
            argv += ["--heading-type", item]
    return _format(*_run_main(argv))


def registry_import_dedup(campaign_dir: Path, json_path: str) -> str:
    return _format(*_run_main(["import-dedup", str(campaign_dir), json_path]))


def registry_import_frontmatter(campaign_dir: Path, dossier_dir: str) -> str:
    return _format(*_run_main(["import-frontmatter", str(campaign_dir), dossier_dir]))


def registry_import_alias_decisions(campaign_dir: Path, json_path: str) -> str:
    return _format(*_run_main(["import-alias-decisions", str(campaign_dir), json_path]))


# ── MCP server (FastMCP imported lazily so core stays dependency-free) ──────


def build_server(campaign_dir: Path):
    """Construct the FastMCP server bound to one fixed campaign directory.

    Imports `mcp` lazily — call only when actually serving (or testing
    against a live FastMCP instance); every core function above works
    without it.
    """
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        "registry",
        instructions=(
            f"Entity registry for the campaign at {campaign_dir} "
            f"({campaign_dir}/docs/entity_registry.yaml) — the single authority for entity "
            "identity: canonical spelling, aliases, and anti-merge guards (distinct pairs, "
            "rejected-alias groups).\n\n"
            "Start with registry_check (drift between the registry and legacy stores) and "
            "registry_triage_candidates (unregistered proper nouns from session output) — both "
            "read-only, both surface work without deciding anything.\n\n"
            "registry_add, registry_alias, registry_merge, registry_mark_distinct, and "
            "registry_mark_rejected all mutate entity identity. Identity is a precision "
            "decision, not a rendering one: only call these once the GM has explicitly "
            "confirmed the specific mapping in this conversation — do not infer a match from "
            "string similarity or context and call these unprompted. registry_add returns a "
            "near-miss warning (not an error) when a similar name already exists; that is the "
            "cue to ask the GM before proceeding, not to guess.\n\n"
            "Import order for the one-time bulk migration commands, when starting a registry "
            "from legacy scattered stores: registry_init -> registry_import_inventory -> "
            "registry_import_dedup -> registry_import_frontmatter -> "
            "registry_import_alias_decisions -> registry_check -> [GM resolves via alias / "
            "merge / mark_distinct / mark_rejected] -> registry_project. Order matters — see "
            "each import tool's own docstring for why."
        ),
    )

    @mcp.tool()
    def registry_init_tool(campaign: str | None = None) -> str:
        """Create an empty entity registry at docs/entity_registry.yaml.

        campaign — campaign name to record (default: the campaign directory's basename).
        Fails if a registry already exists there.
        """
        return registry_init(campaign_dir, campaign)

    @mcp.tool()
    def registry_add_tool(
        name: str,
        type: str,
        aliases: list[str] | None = None,
        note: str | None = None,
        provenance: str | None = None,
        source: str | None = None,
        scope: str | None = None,
        confirm_new: bool = False,
    ) -> str:
        """Register a new entity. IDENTITY DECISION — only call after the GM has
        confirmed this is genuinely a new entity, not a variant spelling of one
        already registered.

        type — npc | location | faction | item | deity | event | concept.
        If a similar existing name is found, nothing is written and the response
        is a near-miss warning, not an error: show it to the GM, then either call
        this again with confirm_new=true (register as distinct), or call
        registry_alias_tool instead (attach as a variant of the existing entity).
        An exact-normalized collision (not just "similar") always fails outright —
        that always means the same entity, never a new one.
        """
        return registry_add(campaign_dir, name, type, aliases, note, provenance, source, scope, confirm_new)

    @mcp.tool()
    def registry_alias_tool(to: str, variants: list[str]) -> str:
        """Attach one or more surface forms as aliases of an EXISTING entity.
        IDENTITY DECISION — only call after the GM has confirmed each variant
        really is the same entity as `to`.

        to — the target entity's canonical name, or any of its existing aliases.
        All variants are pre-checked before anything is written: if any variant
        already belongs to a DIFFERENT entity, the whole call is refused (use
        registry_merge_tool if the GM rules those two entities are actually the
        same, or leave it alone if they're genuinely different — see
        registry_mark_distinct_tool).
        """
        return registry_alias(campaign_dir, to, variants)

    @mcp.tool()
    def registry_merge_tool(into: str, others: list[str]) -> str:
        """Fold one or more EXISTING registered entities into `into` — they are
        the same thing. DESTRUCTIVE and an IDENTITY DECISION: removes the folded
        entities, only call after explicit GM confirmation.

        Refuses if any pair is already marked distinct or shares a
        rejected-aliases group (remove that guard first if the GM has changed
        their ruling). All targets are pre-checked, so the call lands
        completely or writes nothing.
        """
        return registry_merge(campaign_dir, into, others)

    @mcp.tool()
    def registry_mark_distinct_tool(name_a: str, name_b: str) -> str:
        """Record name_a and name_b as DIFFERENT entities — a standing guard that
        blocks any future registry_merge_tool call between them. IDENTITY
        DECISION — only call after the GM has explicitly ruled these apart
        (e.g. two NPCs who happen to share a name or a phoneme).
        """
        return registry_mark_distinct(campaign_dir, name_a, name_b)

    @mcp.tool()
    def registry_mark_rejected_tool(names: list[str]) -> str:
        """Record `names` as a rejected (never auto-merge) alias group — the GM
        looked at this cluster of similar-looking names and ruled that at least
        one of them is NOT the others. IDENTITY DECISION.

        Note this means "not ALL of these are one entity," not "every pair is
        distinct" — a subset may still be the same entity via a separate
        registry_alias_tool/registry_merge_tool call.
        """
        return registry_mark_rejected(campaign_dir, names)

    @mcp.tool()
    def registry_project_tool() -> str:
        """Regenerate docs/aliases.json and docs/entity_inventory.md from the
        current registry. Safe, idempotent, read-derived — call this after any
        registry_add/alias/merge/mark_* call so the projected files consumed by
        the ensemble pipeline stay in sync.
        """
        return registry_project(campaign_dir)

    @mcp.tool()
    def registry_check_tool() -> str:
        """Read-only. Surface drift between the registry and the legacy scattered
        stores it's meant to replace (.dedup_state.json, inventory markdown,
        .alias_decisions.json, dossier frontmatter, aliases.json): grouping
        drift (primary, high-confidence), fuzzy near-duplicates (secondary,
        review — do not assume), and presence drift (informational). Never
        writes anything. Run this before deciding whether any alias/merge/
        mark_* call is warranted.
        """
        return registry_check(campaign_dir)

    @mcp.tool()
    def registry_triage_candidates_tool(
        bible: str | None = None,
        min_len: int | None = None,
        min_count: int | None = None,
    ) -> str:
        """Read-only. Diff proper nouns found in session output (or an optional
        bible file) against the registry and return the UNKNOWN-surface-form
        queue as JSON: candidates not yet registered, each with a near-miss
        hint when one clears the similarity threshold (a hint, not a verdict —
        still confirm with the GM before calling registry_alias_tool).

        bible — also scan this bible file's text, in addition to the ensemble
        fact corpus (or raw summaries, for a campaign with no ensemble yet).
        """
        return registry_triage_candidates(campaign_dir, bible, min_len, min_count)

    @mcp.tool()
    def registry_import_inventory_tool(
        md: str,
        provenance: str | None = None,
        source: str | None = None,
        heading_type: list[str] | None = None,
    ) -> str:
        """Bulk-migration tool: merge entities from an inventory markdown file
        (## Heading sections of "- **Name** / **Alias** — note" bullets), e.g.
        a module inventory or entity_inventory.md. Run FIRST among the import-*
        tools — it carries real entity types and authoritative spellings that
        later imports (which default everything to type=npc) must not clobber.

        heading_type — override the type inferred for a heading, e.g.
        "Outside Candlekeep=location" (repeatable).
        """
        return registry_import_inventory(campaign_dir, md, provenance, source, heading_type)

    @mcp.tool()
    def registry_import_dedup_tool(json_path: str) -> str:
        """Bulk-migration tool: merge NPC entities + anti-merge guards from a
        .dedup_state.json file. Run AFTER registry_import_inventory_tool (it
        blanket-types everything npc, which would clobber an inventory-sourced
        type) and BEFORE registry_import_frontmatter_tool.
        """
        return registry_import_dedup(campaign_dir, json_path)

    @mcp.tool()
    def registry_import_frontmatter_tool(dossier_dir: str) -> str:
        """Bulk-migration tool: merge NPC entities from dossier frontmatter (e.g.
        docs/npcs/). Run AFTER registry_import_dedup_tool — it only fills gaps
        (singleton dossiers no dedup cluster ever grouped) rather than fighting
        dedup's merge decisions.
        """
        return registry_import_frontmatter(campaign_dir, dossier_dir)

    @mcp.tool()
    def registry_import_alias_decisions_tool(json_path: str) -> str:
        """Bulk-migration tool, ENRICH-ONLY: add aliases to entities that are
        ALREADY registered, from an approved .alias_decisions.json file — never
        creates a new entity (approved canonicals in that file are often
        generic/garbage strings with no reliable type). Run LAST among the
        import-* tools, after registry_check_tool.
        """
        return registry_import_alias_decisions(campaign_dir, json_path)

    return mcp


def main() -> None:
    """Console-script entry point (`registry_mcp` — [project.scripts])."""
    campaign_dir = resolve_campaign_dir()
    build_server(campaign_dir).run()


if __name__ == "__main__":
    main()
