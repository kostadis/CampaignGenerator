# Implementation Plan: Cross-Campaign Provenance-Aware Search Seam

**Branch**: `007-cross-campaign-search` | **Date**: 2026-08-05 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-cross-campaign-search/spec.md`

## Summary

A read-only, unpinned MCP server plus a CLI that search the six-campaign workspace at
`~/src/campaigns` and return **every hit wrapped in a provenance envelope**: owning
campaign, repo-relative path, trust tier, machine-generated status and generating stage,
chapter/date, provenance range, and any recorded known-stale correction — attached
inline. Scope is mandatory on every query; there is no input that means "all campaigns."

Technically this is small and deliberately dumb: a new top-level `provenance/` package
holding two strict pydantic document models (the workspace manifest, the per-campaign
corrections record), a **ripgrep-backed scanner with a stdlib Python fallback**, a thin
read-only adapter over the **existing** `campaignlib.registry` loader for identity, a
`provenance` CLI, and a `provenance_mcp` server that wraps that CLI in-process — the same
shape `entity_registry/registry_mcp.py` already uses. **No index, no daemon, no cache, no
LLM call, no writes.** Measured: **0.01 s** for the full six-campaign corpus via `rg`,
0.63 s for the largest single campaign via the Python fallback, against a 2 s budget
(research [D1](./research.md#d1)) — so the first increment earns its speed by not building
anything.

The two hand-authored data files (FR-027 manifest, FR-028 corrections × 6 campaigns)
ship in the `~/src/campaigns` workspace, not in this repo, and are a first-class part of
the deliverable.

**Increment 1 = User Stories 1 and 2** per the spec's GM ruling. Stories 3–5 are designed
into the contracts here (the response shapes carry their fields from day one) but land in
later phases.

## Technical Context

**Language/Version**: Python 3.14.4 (`pyproject.toml` declares `requires-python = ">=3.9"`;
nothing in this feature needs newer syntax than 3.9 supports)

**Primary Dependencies**: `pyyaml`, `pydantic` 2.13.4 (**must be added explicitly** to
`[project.dependencies]` — today it arrives only transitively via `fastapi`, and this
package does not import fastapi), `mcp` (FastMCP, lazily imported so the core functions
unit-test without it). **Deliberately no new *Python* dependency**: no search engine, no
vector store, no `anthropic`.

**`ripgrep` is an optional external binary, not a dependency.** `rg` 15.1.0 is installed at
`/usr/bin/rg` and resolves from a spawned Python process. It is used when present and the
stdlib scanner runs when it is not; **the active scanner and its version are reported in
every search response and by `capabilities`**, so the difference is observable rather than
invisible (research [D1](./research.md#d1)). Nothing in the feature hard-fails on rg's
absence.

**Storage**: Files on disk, read-only. Two hand-authored YAML documents:
`~/src/campaigns/provenance.yaml` (workspace manifest) and
`<campaign>/docs/corrections.yaml` (per campaign). Existing identity stores
(`docs/entity_registry.yaml`, `docs/aliases.json`) are read as-is and never written.
No database, no index, no cache.

**Testing**: `pytest` (`python -m pytest tests/`). Three test classes: contract tests over
pinned fixtures in `tests/fixtures/provenance/`; live-corpus tests against
`~/src/campaigns`, skipped when the workspace is absent; and AST guard tests
(read-only, no-LLM, layering).

**Target Platform**: Linux CLI + stdio MCP server. Must behave identically on the WSL2
desktop, where MemPalace *is* installed — which is why backend availability is probed and
reported per-machine rather than assumed (research [D15](./research.md#d15)).

**Project Type**: Single Python package with a console-script CLI and an MCP server. No
frontend, no FastAPI route, no `server/` involvement.

**Performance Goals**: Single-campaign search p95 < 2 s (SC-007). Measured today:

| | out-of-the-abyss (largest) | all six campaigns |
|---|---|---|
| `rg` 15.1.0 | **0.01 s** | **0.01 s** |
| Python fallback | 0.63 s | 1.49 s |

Both paths clear the budget; rg clears it by three orders of magnitude and collapses the
gap between one campaign and six, which is what makes Story 5's cross-campaign search (P5)
cheap rather than the slowest thing in the feature. Every response reports its own
`elapsed_ms` **and which scanner produced it**, so the spec's "degraded-latency condition
the caller can observe" is a number the caller reads, not an inference.

**Constraints**: Zero writes to campaign content (FR-031, SC-010 — statically and
behaviourally enforced). Zero LLM calls (FR-033 — statically enforced). No implicit
"all campaigns" (FR-006, SC-003). Failure on a malformed manifest is loud and total, never
partial (FR-030).

**Scale/Scope**: 6 campaigns, 9,273 markdown files, 408 MB on disk / 131 MB of searchable
text across five extensions. 243 chapter files, 1,079 NPC dossiers, 72 VTTs, 175 notes
files. Identity stores present for 4 of 6 campaigns.

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1. Result both times:
**PASS**, no violations, Complexity Tracking empty.*

Checked by name against all ten principles, as Governance requires.

| # | Principle | Verdict | How this plan satisfies it |
|---|---|---|---|
| I | Disk is Truth, the Model is a Draft | **PASS** | The feature builds no index, no cache and no database — there is nothing to rebuild disk from. Its entire purpose is to make "this file is a draft" machine-readable at query time. SC-009 is satisfied vacuously and the plan says so rather than claiming a rebuild test it doesn't need (research [D1](./research.md#d1)). |
| II | The Human Checkpoint is Non-Negotiable | **PASS** | **What decision does this remove from the human? None.** It labels and retrieves. No LLM call exists to cross a precision boundary (FR-033, guarded by `test_provenance_no_llm.py`). The one place a scope decision could leak in — tier filtering silently dropping hits — is closed by reporting suppressed counts (FR-011/FR-012). Tier-glob ambiguity is *reported* to the GM, not auto-resolved (research [D8](./research.md#d8)). |
| III | Retrieval and Render are Separated | **PASS** | Pure retrieval; no render path exists. `tests/test_retrieve_render_isolation.py` passes vacuously because no module in `provenance/` imports `campaignlib.api`, and `test_provenance_no_llm.py` makes that permanent. |
| IV | Verbatim is Sacred | **PASS** | Excerpts are sliced from bytes read off disk and decoded — never paraphrased, summarized or normalized. The contract fixes an exact excerpt shape (line + N context lines) so no component can "improve" it. |
| V | One Seam per Boundary | **PASS** | One new file is the outward seam: `provenance/provenance_mcp.py`. It wraps the CLI in-process rather than duplicating logic — `entity_registry/registry_mcp.py`'s exact pattern. Identity is read through the **existing** `campaignlib.registry` loader; no second registry parser is written (research [D10](./research.md#d10)). The GM's ruling for a new sibling server over unpinning `campaign` is confirmed by the survey: `pipelines/rlm/mcp_server.py` binds its campaign at *module import time*, so unpinning it is a rewrite, not an argument change (research [D6](./research.md#d6)). |
| VI | CLI is the Engine, UI is a Face | **PASS** | The `provenance` CLI is the engine and ships first; the MCP server is a face over it, calling `main(argv)` in-process. Every MCP tool has an exactly equivalent CLI invocation, documented in [contracts/cli.md](./contracts/cli.md). |
| VII | Extract Once, Synthesize Deliberately | **N/A** | No extraction or synthesis passes exist in this feature. |
| VIII | State is Discoverable | **PASS** | `provenance capabilities` reports the resolved workspace root **and which rule resolved it**, per-campaign manifest/identity-store/corrections presence, per-machine backend status, and **which scanner is active with its version**. The `CAMPAIGNS_ROOT` literal currently duplicated in `configure_mcp.py` moves to `campaignlib/constants.py` so there is one answer (research [D5](./research.md#d5)). Adopting rg made scanner reporting load-bearing rather than decorative: a 60× latency difference that varies by host is exactly the tribal state this principle forbids (research [D1](./research.md#d1)). |
| IX | The UI Mechanizes; Claude Converses | **N/A** | No UI surface. Files remain the interchange: the manifest and corrections records are hand-edited YAML equally visible to CLI, chat and any future UI. |
| X | Selection is Explicit; There is No Silent "All" | **PASS** | Scope is a required, non-empty argument. There is **no `all` token in increment 1** — a scopeless call is refused with a message enumerating the known campaigns, so the caller re-issues explicitly (research [D4](./research.md#d4), SC-003). Naming N≥2 campaigns is itself the deliberate cross-campaign act (Story 5). The inverse also holds after adopting rg: `--no-ignore --hidden` is mandatory so that **`.gitignore` never silently narrows scope** — the manifest's `exclude` list is the single authority on what is not searched (research [D17](./research.md#d17)). |

**Two spec statements corrected by the survey, both recorded rather than quietly fixed:**

1. The spec's rationale for a workspace-level manifest — *"campaigns that do not share a
   commit history"* — is factually wrong: `~/src/campaigns/.git` is the only repo in the
   tree. Both of the spec's **conclusions** survive on better grounds; the shared repo
   makes per-campaign corrections *more* necessary, because `~/src/campaigns/CLAUDE.md`
   forbids cross-campaign commits and a shared corrections file would violate that on
   every edit (research [D3](./research.md#d3)).
2. Two of Story 2's acceptance *Givens* are false on disk today: obelisk's registry has no
   Veyra entry, and no registry anywhere contains Kazneporium/Kostadinious. Entering them
   is a `registry alias` / `registry mark-distinct` act that FR-032 explicitly forbids this
   feature from performing. Handled by splitting contract tests (pinned fixtures, prove the
   mechanism) from live-corpus tests (assert the honest `not-found-in-identity-store`
   answer), with the GM action item recorded (research [D11](./research.md#d11)).

**Revision, same day — ripgrep adopted at the GM's direction.** D1 originally rejected rg
because `shutil.which("rg")` returned `None`; rg 15.1.0 is now installed and resolves. The
plan now uses rg as the primary scanner with the Python scanner retained as fallback and
parity oracle. The change surfaced one finding worth reading before implementation:
**rg's default `.gitignore` behaviour silently hides 230 files in this workspace**, 217 of
them working-reference-tier content the manifest explicitly declares in-scope. `--no-ignore
--hidden` is therefore mandatory, and the flag set is pinned and test-guarded (research
[D17](./research.md#d17), [D18](./research.md#d18)).

## Project Structure

### Documentation (this feature)

```text
specs/007-cross-campaign-search/
├── plan.md              # This file
├── spec.md              # Feature specification (input)
├── research.md          # Phase 0 output — D1–D16 corpus + codebase survey
├── data-model.md        # Phase 1 output — entities, fields, validation, states
├── quickstart.md        # Phase 1 output — runnable validation guide
├── contracts/
│   ├── manifest.md      # ~/src/campaigns/provenance.yaml schema
│   ├── corrections.md   # <campaign>/docs/corrections.yaml schema
│   ├── cli.md           # `provenance` CLI surface
│   └── mcp.md           # `provenance` MCP server tool surface
├── checklists/
│   └── requirements.md  # Spec quality checklist (pre-existing)
└── tasks.md             # Phase 2 — created by /speckit-tasks, NOT by this command
```

### Source Code (repository root)

```text
provenance/                      # NEW top-level package (added to ENGINE_PACKAGES)
├── __init__.py
├── manifest.py                  # ProvenanceManifest models + loader (strict pydantic)
├── corrections.py               # CorrectionsRecord models + loader (strict pydantic)
├── tiers.py                     # Glob → tier classification; ambiguity detection (D8)
├── scan.py                      # Scanner interface + selection; reports which ran (D1)
│   ├── (scan_rg)                #   rg --json, pinned flag set (D1, D17, D18)
│   └── (scan_python)            #   stdlib bytes fallback + the parity oracle (D1)
├── identity.py                  # Read-only adapter over campaignlib.registry (D10)
├── backends.py                  # Backend roster + per-machine probes (D15)
├── envelope.py                  # ProvenanceEnvelope assembly + deterministic ranking (D9)
├── search.py                    # Orchestration: scope → scan → classify → annotate → rank
├── cli.py                       # `provenance` console script: search/resolve/capabilities/check
└── provenance_mcp.py            # `provenance_mcp` console script: THE outward seam (V)

campaignlib/
└── constants.py                 # MODIFIED: + CAMPAIGNS_ROOT (D5)

pipelines/workspace/
└── configure_mcp.py             # MODIFIED: import CAMPAIGNS_ROOT; emit `provenance` block (D4)

tests/
├── fixtures/provenance/         # NEW pinned mini-workspace (2 campaigns, all tiers, D11/D12)
├── test_provenance_manifest.py      # Schema, strictness, loud failure (FR-030)
├── test_provenance_corrections.py   # Schema; 4-state consultation status (D13)
├── test_provenance_tiers.py         # Precedence, ambiguity reporting, unclassified (D8)
├── test_provenance_scan.py          # Excerpt fidelity; latency + scanner reporting
├── test_provenance_scanner_parity.py # rg and Python return an IDENTICAL hit set (D1)
├── test_provenance_rg_flags.py      # The pinned flag set; .gitignore never scopes (D17)
├── test_provenance_identity.py      # Aliases, distinct/rejected, 4 no-store states (D10)
├── test_provenance_search.py        # Envelope completeness; ranking; suppression counts
├── test_provenance_scope.py         # SC-003: no input searches everything
├── test_provenance_capabilities.py  # SC-004: unavailable ≠ zero hits (US3)
├── test_provenance_horizon.py       # Chapter attribution, refusal, disposition (US4)
├── test_provenance_cross_campaign.py # Labeled, never merged across campaigns (US5)
├── test_provenance_incidents.py     # SC-002: incidents 1–4 (D12); incident 5 is identity
├── test_provenance_readonly.py      # FR-031/SC-010: AST guard + before/after hash sweep
├── test_provenance_no_llm.py        # FR-033: AST guard
├── test_provenance_mcp.py           # Tool surface; CLI/MCP equivalence (VI)
├── test_configure_mcp.py            # MODIFIED: + `provenance` block gating (T067)
└── test_layering.py                 # MODIFIED: + "provenance" in ENGINE_PACKAGES

pyproject.toml                   # MODIFIED: + pydantic dep; + 2 console scripts;
                                 #           + "provenance" to hatch wheel packages

docs/mcp/mcp_servers.md          # MODIFIED: four servers → five
docs/                            # NEW: docs/provenance/provenance_search.md
```

**Authored data (ships in `~/src/campaigns`, not this repo — FR-027/FR-028):**

```text
~/src/campaigns/
├── provenance.yaml                    # NEW workspace manifest, all 6 campaigns
├── .mcp.json                          # MODIFIED: + unpinned `provenance` server (D4)
├── Phandalin/docs/corrections.yaml    # NEW  ┐
├── out-of-the-abyss/docs/corrections.yaml  # │ one per campaign, hand-authored,
├── stormgiants/docs/corrections.yaml       # │ seeded from the 5 documented
├── toee/docs/corrections.yaml              # │ incidents; committed one campaign
├── Hillsfar/docs/corrections.yaml          # │ per commit (workspace CLAUDE.md)
└── obelisk/docs/corrections.yaml           # ┘
```

**Structure Decision**: A new top-level `provenance/` package, mirroring
`entity_registry/` — the existing precedent for "owns an on-disk document + has a CLI +
has an MCP server." Not `pipelines/`, which is for token-spending render pipelines and
would invite someone to add an LLM call to a feature that forbids them. Not
`campaignlib/`, whose `projection_config.py` precedent applies only when both a CLI engine
and `server/` need the shape — nothing in `server/` consumes this. Rationale and rejected
alternatives in research [D6](./research.md#d6).

## Phasing

Phases map to the spec's story priorities; each is independently shippable and testable.

| Phase | Delivers | Stories | Exit criteria |
|---|---|---|---|
| **0** | `provenance.yaml` manifest for all 6 campaigns + 6 `corrections.yaml` files, hand-authored; `manifest.py`, `corrections.py`, `provenance check` | FR-027–FR-030 | `provenance check` clean on all 6; malformed input fails loudly; tier-glob ambiguity reported |
| **1** | Both scanners (rg + Python fallback), tier classification, envelope, ranking, `provenance search`, refusals | **US1 (P1)** | SC-001, SC-002, SC-003, SC-005, SC-007, SC-008, SC-010; **scanner parity test green**; `.gitignore` proven not to scope (D17) |
| **2** | Identity adapter, `provenance resolve`, alias expansion in search | **US2 (P2)** | SC-006; four distinguishable identity states (D10) |
| **3** | `provenance_mcp` server + `.mcp.json` + `configure_mcp` block; docs | US1+US2 exposed | Every MCP tool has an equivalent CLI call; server starts unpinned |
| **4** | `provenance capabilities`, backend probes, `backends_consulted` | **US3 (P3)** | SC-004 |
| **5** | Horizon filter, provenance ranges, unattributable disposition | **US4 (P4)** | FR-024–FR-026 |
| **6** | Multi-campaign scope | **US5 (P5)** | Cross-campaign labeled, never merged |

Increment 1 (the GM's ruling) is **Phases 0–3**. Phases 4–6 follow; their response fields
are present in the contracts from Phase 1 so adding them is filling in values, not
reshaping the envelope.

## Complexity Tracking

> No Constitution Check violations. This table is intentionally empty.
