# Component: Campaign workspace + 5etools data

> The data layer. What's per-campaign vs. machine-global, and how a campaign
> declares which books are in scope. [↑ index](index.md)

**Repos / trees:** `~/src/campaigns-test/<Campaign>/`, `~/src/5etools-kostadis/`,
`~/src/5etools-img/` · **Deep docs:** [`docs/rlm/refs_yaml_reference.md`](../rlm/refs_yaml_reference.md), [`docs/core/configuration.md`](../core/configuration.md)

---

## Anatomy of one campaign workspace

A workspace is a directory (e.g. `campaigns-test/Phandalin/`). CG scripts run
from inside it and auto-detect `config.yaml` in the CWD.

| Path | What it is |
|---|---|
| `config.yaml` | CLI config — absolute paths to prompts and the grounding docs. Bootstrap for every script. |
| `ui_config.yaml` | Web-UI runtime settings (`campaign_dir`, `session_dir`). |
| `.mcp.json` | Registers `pipelines/rlm/mcp_server.py` for this campaign (with `CAMPAIGN_DIR`). |
| `docs/campaign_state.md` | DONE/TODO state synthesized from summaries (`pipelines/grounding/campaign_state.py`). |
| `docs/world_state.md` | Lore, factions, geography (`pipelines/grounding/distill.py`). |
| `docs/planning.md` | Threat/forward-planning, from NPC dossiers + arc scores (`pipelines/grounding/planning.py --synthesize`). |
| `docs/party.md` | Party roster, character arcs (`pipelines/grounding/party.py`). |
| `docs/mechanics.md` | Arc-score systems, house rules (manual). |
| `docs/npcs/<npc>.md` | Per-NPC dossiers — directory created on-demand by `pipelines/grounding/planning.py --build-dossiers`, not by `pipelines/workspace/new_workspace.py`; frontmatter holds canonical name + aliases. |
| `docs/tracking/<arc>.md` | Quantified quest/threat/relationship trackers (also populated on-demand). |
| `docs/dossier_proposal.md` | **The RLM human checkpoint** (on-demand, not scaffolded) — retrieval results; render pipelines refuse to run until its `**Status:**` banner is set to approved. |
| `voice/<char>_voice.md` | Per-character speech/tone — read by `session_doc/sd_narrate.py`. |
| `examples/` | Handcrafted prose style exemplars (optional). |
| `summaries/<date>/` | Session inputs: `session.vtt`, `gm-assist.md`, then pipeline outputs (`scene_extractions/`, `narration/`, …). |
| `planning.yaml` | Binds `docs/npcs/*` ↔ `docs/tracking/*` for `pipelines/grounding/planning.py`. |
| `mempalace.yaml` | Declares this campaign's palace wing/room schema. |
| `refs.yaml` (+ `refs.local.yaml`) | Declares which 5etools books/PDFs/homebrew are in scope (next section). |
| `logs/`, `notes/` | Run logs, MCP write-only scratch. |

> **Scaffold vs. on-demand.** `pipelines/workspace/new_workspace.py` creates `config.yaml`,
> `ui_config.yaml`, and the `docs/ logs/ voice/ examples/ summaries/` skeleton
> (plus placeholder grounding docs). Everything else above — `docs/npcs/`,
> `docs/tracking/`, `dossier_proposal.md`, `characters/` — is
> created on-demand by the tool that owns it (`pipelines/grounding/planning.py`, the RLM pipeline,
> `pipelines/content_ingest/dnd_sheet.py`). So a fresh workspace is smaller than the
> full table; the table is the *mature* shape.

**Creating one:** `pipelines/workspace/new_workspace.py <dir> --name … [--world-state … --party … ]`
scaffolds the tree, writes `config.yaml`/`ui_config.yaml`, and creates
placeholder docs for anything not supplied. See [`docs/cli/cli_tools.md`](../cli/cli_tools.md).

---

## refs.yaml — scoping the per-campaign 5etools MCP

A campaign declares which sources it can navigate; a launcher turns that into a
dedicated 5etools MCP server that sees **only** those sources. This is the
**navigation** layer (browse/read whole books, look up a monster), distinct from
MemPalace's **retrieval** layer (semantic drawer search).

**`refs.yaml`** (git-tracked, portable):

```yaml
canonical: all                 # or a whitelist ["MM","PHB","OotA"]
canonical_exclude: [VRGtR]     # only valid when canonical: all
refs:
  - rpglib: "WotC/Adventures/T14.pdf"   # a purchased PDF
    library: drivethrurpg               # picks roots.rpg_library_drivethrurpg
    book_id: 7421                        # used by fivetools_ingest metadata
  - homebrew_private: "setting_bible/"   # a directory of *.json
  - path: "./converted/icespire.json"    # an explicit path
```

**`refs.local.yaml`** (git-ignored, per-machine) maps the named roots to real
paths:

```yaml
roots:
  fivetools_data: ~/src/5etools-kostadis/data/
  rpg_library_drivethrurpg: /mnt/g/DriveThru/
  homebrew_private: ~/src/homebrew-private/
```

Root resolution precedence: `refs.local.yaml` → env var
(`FIVETOOLS_DATA_ROOT`, …) → built-in default.

**Launch flow** — `pipelines/rlm/launch_5etools_mcp.py --campaign-dir .`:

1. `pipelines/rlm/resolve_refs.py` parses both files → a `ResolvedScope` (canonical sources in
   scope, excluded codes, concrete ref paths, resolved roots).
2. Builds an idempotent symlink farm at `~/.5etools-mcp-runtime/<slug>/`
   (`data/` + `homebrew/`, with generated indices). A `.sources.sha256` sidecar
   skips rebuilds when refs are unchanged.
3. `exec`s the Node MCP server (`~/src/5etools-kostadis/mcp/index.js`) with
   `DATA_DIRS` pointed at that farm — so it sees only in-scope content.

Full field reference: [`docs/rlm/refs_yaml_reference.md`](../rlm/refs_yaml_reference.md).

---

## The 5etools trees

| Tree | Size | Role | Consumed by |
|---|---|---|---|
| `~/src/5etools-kostadis/` | ~6 GB tree | The fork. `data/` (~108 MB) is the canonical 5etools JSON (adventures, bestiary, spells, classes…); `mcp/` is the **sibling** Node MCP server that `pipelines/rlm/launch_5etools_mcp.py` execs. | `pipelines/rlm/fivetools_catalog.py` reads `data/` (in-process index, cached as `.fivetools_catalog.pkl`); `pipelines/rlm/launch_5etools_mcp.py` execs `mcp/index.js` |
| `~/src/5etools-img/` | ~12 GB | Image assets (adventure art, monster tokens). | Manual GM use — **not** in the core pipeline |
| `~/src/5etools-src/` | ~772 MB | The 5etools web-UI source. | Reference/customization base — not consumed by CG |

---

## Local vs. global — the table that prevents mistakes

| Per-campaign (workspace dir) | Machine-global (shared) |
|---|---|
| `docs/*.md`, `voice/`, `examples/`, `summaries/` | `~/src/5etools-kostadis/data/` (canonical JSON) |
| `refs.yaml` (+ `refs.local.yaml`) | `~/.mempalace/palaces/<name>/` (one palace per campaign, shared root) |
| `config.yaml`, `ui_config.yaml`, `.mcp.json`, `planning.yaml`, `mempalace.yaml` | `~/src/mytools/rpg-lib/rpg_library.db` (enriched PDF index) |
| `logs/`, `notes/` | `~/src/homebrew-private/`, `~/src/5etools-img/`, `dgxlib` model registry, `~/.5etools-mcp-runtime/<slug>/` |

**Why the split:** game-world state is campaign-specific and git-tracked per
campaign; bulk reference data and the model registry are deduplicated once per
machine. The palace is *named per campaign* but lives under the shared
`~/.mempalace` root — so each campaign has its own memory without re-ingesting
shared books elsewhere.
