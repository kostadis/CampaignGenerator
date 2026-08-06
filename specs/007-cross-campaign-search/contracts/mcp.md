# Contract: `provenance` MCP Server

**Console script**: `provenance_mcp = "provenance.provenance_mcp:main"`
**Server name**: `provenance` · **Transport**: stdio · **Source**: `provenance/provenance_mcp.py`
**Constitution**: V (One Seam per Boundary) — this file is the single outward seam
**Requirements**: FR-001–FR-026, FR-031, FR-033 | **Research**: [D4](../research.md#d4), [D6](../research.md#d6)

## The defining property: this server is **not pinned to a campaign**

Every other server in `~/src/campaigns/.mcp.json` binds a campaign at process start:

```json
"campaign": {"command": "mcp_server",         "args": ["--campaign-dir", ".../out-of-the-abyss"]},
"5etools":  {"command": "launch_5etools_mcp", "args": ["--campaign-dir", ".../out-of-the-abyss"]},
"registry": {"command": "registry_mcp",       "env":  {"CAMPAIGN_DIR": ".../out-of-the-abyss"}}
```

Searching a different campaign today means editing that file and restarting the session —
the spec's "no cross-campaign front door," measured. This server takes **no campaign
argument at all**; scope arrives per call, and it is required on every call.

Why a new sibling rather than unpinning `campaign` (the GM's ruling, confirmed by survey):
`pipelines/rlm/mcp_server.py` resolves `campaign_dir` and loads that campaign's
`config.yaml` at **module import time** (lines 29–46), then builds a doc index from it.
Unpinning it is a rewrite of its bootstrap, not an argument change — and it would give
every one of its *write* tools a scope argument, so a mis-scoped write could land in the
wrong game (research [D6](../research.md#d6)).

## Implementation shape

A thin in-process wrapper over the CLI: each tool calls `provenance.cli.main(argv)` with
`redirect_stdout`/`redirect_stderr`, catches `SystemExit`, and returns the captured output
as a `str`. This is `entity_registry/registry_mcp.py`'s exact pattern, and it is what makes
Constitution VI true rather than aspirational — the MCP surface cannot drift from the CLI,
because it *is* the CLI.

The FastMCP import is lazy (inside `build_server`) so the core functions unit-test without
the `mcp` package installed — same guard as `registry_mcp.py` and `kanka_mcp.py`.

**No tool on this server writes anything.** There is no `notes/` escape hatch as on the
`campaign` server. `test_provenance_readonly.py` enforces this statically over the whole
package — including an allow-list check that the only subprocess the package ever spawns
is `rg` with the pinned read-only flag set (research [D16](../research.md#d16),
[D17](../research.md#d17)).

**Scanner visibility matters more here than at the CLI.** A server is spawned by Claude
Code with an inherited `PATH` that may not match an interactive shell's — `rg` was absent
from this host's Python-visible `PATH` earlier the same day it was installed. Every
`provenance_search` response therefore names the active scanner and its version, so a model
reading the result can see whether it got the 0.01 s path or the 0.63 s fallback. Results
are identical either way (research [D1](../research.md#d1)).

## Registration

`~/src/campaigns/.mcp.json` gains a fourth entry with no campaign binding:

```json
"provenance": {
  "command": "provenance_mcp",
  "args": []
}
```

`configure_mcp` gains a gated block for it, mirroring how `registry` is gated on
`docs/entity_registry.yaml` — here gated on the **workspace manifest** existing. Because
the block is workspace-scoped rather than campaign-scoped, it is emitted once per repo
root, not once per campaign.

## Server `instructions`

Loaded into the model's context with the tool listing, so the scope rule is known before
the first call rather than learned from a refusal:

> Read-only, provenance-labeled search across the D&D campaign workspace at
> `{root}`. Every hit is returned with its trust tier, whether it is
> machine-generated (and by which pipeline stage), the chapter it reflects, and any
> recorded known-stale correction — attached inline.
>
> **Scope is required on every search. There is no "all campaigns".** Name the campaign
> you mean. Call `provenance_capabilities` first if you do not know which campaigns exist
> or whether a backend is live on this machine.
>
> A hit tagged `generated_by: <stage>` **will be clobbered on the next pipeline run and
> may be stale** — verify it against an authoritative hit before treating it as fact.
> An empty result from an unavailable backend is reported as unavailable, never as zero
> hits.
>
> This server never writes. Identity changes (aliasing, merging, marking distinct) belong
> to the `registry` server, behind explicit GM confirmation.

---

## Tools

### `provenance_search`

```python
def provenance_search(
    query: str,
    campaigns: list[str],            # REQUIRED — no default. Empty list is refused.
    tiers: list[str] | None = None,
    horizon: int | None = None,
    expand_aliases: bool = False,
    regex: bool = False,
    case_sensitive: bool = False,
    limit: int = 50,
    context_lines: int = 2,
) -> str
```

`campaigns` is a **required positional-by-schema parameter with no default value**. That is
the mechanical expression of FR-006 and Constitution X: the tool signature offers no way to
express "everything," so no caller can fall into it. An empty list is refused with a message
enumerating the known campaigns.

Naming two or more campaigns **is** the deliberate cross-campaign act (Story 5). Hits stay
labeled with their owning campaign and are never merged or de-duplicated across campaigns
(FR-008).

Equivalent CLI: `provenance search <query> --campaign … [--tier …] […]`

### `provenance_resolve`

```python
def provenance_resolve(surface_form: str, campaign: str) -> str
```

Returns the canonical entity, aliases, recorded known confusions, and the explicit
`known-wrong-variants: not-recorded-by-schema` note. Three distinguishable outcomes:
`resolved` / `not-found` (store exists, form absent) / `no-store` (campaign has none) —
FR-017, FR-018.

Read-only over the existing stores. **Never** mutates identity; that stays with the
`registry` server behind explicit GM confirmation (FR-032).

Equivalent CLI: `provenance resolve <surface-form> --campaign NAME`

### `provenance_capabilities`

```python
def provenance_capabilities() -> str
```

Enumerates every campaign with its manifest / identity-store / corrections status, plus
per-machine backend availability with reasons, plus the resolved workspace root **and which
rule resolved it**. FR-020–FR-023.

The tool a model should call before trusting an empty result.

Equivalent CLI: `provenance capabilities`

### `provenance_check`

```python
def provenance_check(campaigns: list[str] | None = None) -> str
```

Validates the authored manifest and corrections records; reports tier-glob ambiguity,
stale correction entries, unclassified-heavy directories and unattributable chapter files
**for GM review**. Never edits, never auto-resolves.

`campaigns=None` is legal here and means "validate the whole manifest" — this is not a
Principle X violation: `check` reads only the authored YAML documents plus a file-existence
test, spends no tokens, and returns no campaign content. The blast radius the principle
guards is content and token spend, and `check` has neither.

Equivalent CLI: `provenance check [--campaign NAME …]`

---

## Tool-name collisions

Every tool is prefixed `provenance_`. The `campaign` server already exposes
`search_document` and the `registry` server exposes `registry_*`; a bare `search` would
collide in a session where all four servers are wired in — which is the normal
configuration.

## What this server deliberately does **not** expose

| Not exposed | Why |
|---|---|
| Any write tool | FR-031; read-only is what makes Principle X trivially enforceable here |
| Any identity-mutating tool | FR-032 — that is `registry_mcp`'s surface, behind GM confirmation |
| Any LLM-backed ranking or summarization | FR-033; guarded by `test_provenance_no_llm.py` |
| A campaign pin (`--campaign-dir` / `CAMPAIGN_DIR`) | The absence *is* the feature (D4) |
| An "all campaigns" token | Constitution X, SC-003 |
