# MCP servers

CampaignGenerator ships four MCP servers a campaign workspace can register in its
`.mcp.json`. They're independent — a campaign wires in whichever it needs — but
easy to forget exist, since nothing lists them in one place. This page does.

For the *actual* mechanics of wiring one in, see [Wiring one in](#wiring-one-in)
below. For what each server is *for*, read its section.

| Server | Console script | Gated on | What it's for |
|---|---|---|---|
| [`campaign`](#campaign) | `mcp_server` | `config.yaml` (every campaign) | Read campaign docs/notes; RLM retrieval search; write to `notes/` |
| [`5etools`](#5etools) | `launch_5etools_mcp` | `refs.yaml` | Published-module reference lookups (monsters, spells, items, book/adventure sections), scoped to what the campaign owns |
| [`registry`](#registry) | `registry_mcp` | `docs/entity_registry.yaml` | Entity identity — canonical names, aliases, anti-merge guards |
| [`kanka`](#kanka) | `kanka_mcp` | `KANKA_TOKEN` passed to `configure_mcp` | Pull/push campaign canon to/from a Kanka CE workspace |

A fifth server, **mempalace** (semantic search over a campaign's mined content),
is related but not owned by CampaignGenerator — it's a separate package with its
own CLI (`mempalace`) and its own setup guide, `MEMPALACE_HOWTO.md` at the
workspace root. `configure_mcp` does not wire it; the `mempalace-campaign` skill
does.

## `campaign`

The general-purpose campaign server — almost always wired in. Resolves a fixed
`CAMPAIGN_DIR` at startup (env var / `--campaign-dir` / cwd) and exposes:

**Resources** — the five grounding docs as read-only MCP resources:
`campaign_state`, `world_state`, `planning`, `mechanics`, `party`.

**Read tools:**
- `read_document(label_or_path)` — any doc by config label or relative path
- `search_document(pattern, scope)` — regex search over `docs/` / `summaries/` / `notes/` / everything
- `list_sessions()`, `list_files(subdir)`, `list_notes()`

**Write tools (notes/ only — everything else stays read-only):**
- `write_note(filename, content)`, `append_note(filename, content, separator)`

**RLM retrieval tools** (need a mined MemPalace index; see
[`docs/rlm/rlm_architecture.md`](../rlm/rlm_architecture.md) for the three-pile
model these implement):
- `quick_search(query, limit, room)` — fast path over the maintained MemPalace index
- `grounded_search(query, limit)` — verify a claim against canonical session narrative
- `rpg_search(query, ...)` — tiered search across MemPalace + 5etools-canonical + rpg-library, surfacing cheap/expensive ingest candidates for anything not yet indexed
- `propose_dossier(query, output, ...)` — run `rpg_search` and write a slotted proposal to `docs/dossier_proposal.md`
- `suggest_conversion(book_id, filepath)` — build a convert+ingest command pair for an unconverted rpg-library book

Source: `pipelines/rlm/mcp_server.py`.

## `5etools`

A per-campaign *launcher*, not a Python MCP server itself: it resolves the
campaign's `refs.yaml` + `refs.local.yaml`, builds a filtered runtime data tree
at `~/.5etools-mcp-runtime/<slug>/` (canonical 5etools content minus anything
`canonical_exclude`s, plus the campaign's homebrew/purchased content), then
`exec`s the **external** node-based 5etools MCP server against that scoped
tree. The actual tools it exposes (`get_section`, `search`, `get_monster`, …)
come from that external server, not from this repo.

Requires a `refs.yaml` in the campaign directory and a working
`5e-tools-kostadis` checkout (`--mcp-index` or the `fivetools_mcp_index` wiring
default). `--status` shows the resolved scope without building anything;
`--init-local` writes a starter `refs.local.yaml`.

**Why this exists instead of mining published-module text into MemPalace:**
published modules stay outside the palace on purpose (see each campaign's own
`CLAUDE.md`) — this server is the substitute lookup path.

Source: `pipelines/rlm/launch_5etools_mcp.py`.

## `registry`

Wraps every `entity_registry/registry.py` CLI subcommand as an MCP tool — the
full surface (subcommand names, ordering rules, guard semantics) is in the
server's own `instructions` and each tool's docstring, visible in the tool
listing itself, so it doesn't need to be re-derived from `registry.py`'s module
docstring every session. Read-only: `registry_check_tool`,
`registry_triage_candidates_tool`. Identity-mutating (only call after explicit
GM confirmation): `registry_add_tool`, `registry_alias_tool`,
`registry_merge_tool`, `registry_mark_distinct_tool`,
`registry_mark_rejected_tool`. Plus `registry_project_tool` and the one-time
bulk-migration `registry_import_*_tool`s.

Requires `docs/entity_registry.yaml` to already exist (`registry_init_tool` if
not — or run `registry init` from the CLI once, then wire this in).

Source: `entity_registry/registry_mcp.py`. See also the
[entity registry section of the root `CLAUDE.md`](../../CLAUDE.md).

## `kanka`

Drives a Kanka CE ⇄ `world_state.md` sync without dropping to a shell:
- `kanka_pull(campaign, output, include_private)` — Kanka CE → grounding markdown (read-only against Kanka)
- `kanka_push_preview(campaign, input)` — dry run: parse an edited `world_state.md`, report the create/update/skip plan, write nothing to Kanka
- `kanka_push_apply(campaign, input)` — commit that plan (never deletes; skip-if-unchanged; continue-on-error)

Always run `kanka_push_preview` before `kanka_push_apply`; only apply on an
explicit user request — same precision-decision principle as the registry's
identity-mutating tools, applied to an external system instead of local
identity.

Needs `KANKA_TOKEN` (and optionally `KANKA_BASE_URL`, default
`http://localhost:8081`). Source: `pipelines/integrations/kanka/kanka_mcp.py`.

## Wiring one in

**Automatic, per campaign or all of them:**

```bash
configure_mcp                          # all campaigns under ~/src/campaigns/
configure_mcp ~/src/campaigns/Phandalin ~/src/campaigns/toee
configure_mcp --kanka-token <token>    # also wire in kanka
configure_mcp --dry-run                # preview without writing
```

`configure_mcp` writes each campaign's `.mcp.json`, merging into any existing
file by default (`--force` to overwrite entirely instead). `campaign` is
always added; `5etools` is gated on `refs.yaml` existing; `registry` is gated
on `docs/entity_registry.yaml` existing; `kanka` only appears when
`--kanka-token` is passed. Source: `pipelines/workspace/configure_mcp.py`.

**Manual:** copy the relevant block from
[`.mcp.json.template`](../../.mcp.json.template) at the repo root into the
campaign's own `.mcp.json`, under `mcpServers`. Every server here resolves its
campaign directory the same way: `CAMPAIGN_DIR` env var first, then
`--campaign-dir <path>` in `args`, then falls back to cwd — so pick one
consistently rather than mixing both across servers in the same file.

A server only being *gated in* (the file it needs exists) doesn't mean it's
*wired in* — `configure_mcp` has to actually run (or you edit `.mcp.json` by
hand) before Claude sees the new tools in a session. Re-run `configure_mcp`
after a campaign gains a `refs.yaml` or `entity_registry.yaml` it didn't have
before, or the newly-eligible server won't show up until you do.
