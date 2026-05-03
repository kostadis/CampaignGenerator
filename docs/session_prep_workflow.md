# Session-prep workflow (RLM pipeline)

This is the day-to-day GM workflow that the Phase 2 + 3 work was built
to enable: go from "I have a session beat" to an approved encounter
doc, with a human checkpoint between retrieval and rendering.

The pipeline is three steps — generate a proposal, review it, render
from it. Each step has a specific job and a specific thing it's
protecting against; skipping one collapses the architecture.

## The rule this workflow enforces

Global rule (from `~/.claude/CLAUDE.md`):

> LLMs render, humans impose scope. Before planning any LLM call, state
> what decision you are removing from the human. Scope decisions are
> precision decisions and require a human checkpoint.

Retrieval — "which NPCs, locations, stat blocks, encounters are
relevant to this beat?" — is a scope decision. A human has to make it,
or at least review a machine's proposal, before an LLM renders prose
from it. Otherwise early-stage hallucinations amplify through every
downstream call.

`docs/dossier_proposal.md` is the one-bit human-in-the-loop signal
that makes this mechanical: render pipelines refuse to run on a
proposal whose status banner still says `candidates only`.

## Starting state

Before step 1, the campaign workspace looks like:

```
~/campaigns/icespire/
  config.yaml                      ← paths to every grounding doc
  docs/
    world_state.md                 ← living canon
    campaign_state.md              ← completed content + current NPC states
    party.md                       ← roster, arc scores, relationships
    planning.md                    ← synthesized planning doc (NPCs, arcs)
    # no dossier_proposal.md yet
```

Assumptions:

* The MemPalace palace (`/mnt/data/mempalace/palaces/<campaign>` or
  wherever `MEMPALACE_PALACE_PATH` points) already has drawers from the
  books you care about — the ingest workflow (`fivetools_ingest.py`,
  optionally preceded by `pdf_to_5etools_v2.py convert`) ran earlier.
  If not, retrieval will surface cost-tagged candidate suggestions
  (cheap = canonical 5etools JSON ready for one-shot ingest; expensive
  = unconverted PDF that needs pdf-translators first) but nothing else.
* `rpg_library.db` exists and is enriched. Default path
  `~/src/mytools/rpg-lib/rpg_library.db`; override with
  `$RPGLIB_DB` or the `rpglib_db` key in `config.yaml`.
* You, the GM, know the beat you want to prep.

Example beat throughout this doc:

> The party arrives at Icespire Hold and finds the white dragon
> Cryovain absent; Grundar is chained in the main hall.

## Step 1 — generate the proposal

Run:

```bash
cd ~/campaigns/icespire
python ~/src/CampaignGenerator/dossier_proposer.py \
    "party arrives at Icespire Hold, Cryovain absent, Grundar chained in main hall"
```

What happens internally (no Claude call — this is the point):

1. Resolve `campaign_dir` → `~/campaigns/icespire`.
2. Call `rpg_retriever.retrieve(query, palace=..., rpg_library_url=...)`:
   * Query rpg-library over HTTP (`/api/library/nlq` for free-text;
     `/api/library/search` for structured filters). Surfaces candidate
     book rows (Dragon of Icespire Peak, Monster Manual, …) carrying
     `(book_id, filepath, relative_path, product_id)`.
   * Query the canonical 5etools tree via `fivetools_catalog.search()`
     (mtime-cached pickle index). Surfaces named entities and chapter
     records.
   * Spawn `mempalace-mcp` as a subprocess; send
     `mempalace_search_hierarchical(query)`; get drawer hits with
     wing/room/book_id metadata.
   * Merge into a single tiered list: drawers tagged `kind="drawer"`;
     bestiary hits tagged `kind="statblock"`; canonical-5etools hits
     tagged `kind="candidate"` with `cost="cheap"`; rpg-library books
     with no drawers tagged `kind="candidate"` with `cost="expensive"`.
     Each candidate carries `command_argv` + `command` (the ingest
     one-liner). Hard tier order: drawer/statblock > cheap > expensive.
3. `classify()` buckets every hit into one of six slots:
   * **npc** — NPC hint words (townmaster, priestess, captain, …) or a
     multi-token proper noun cluster (e.g. "Grundar Quartzvein").
   * **location** — section-path tail or drawer text contains a
     location noun (hold, keep, temple, forest, …) on a `section` /
     `inset` / `entries` entry type.
   * **encounter** — combat verbs (ambush, fight, assault, strike, …).
   * **statblock** — `kind == "statblock"` (routed at ingest to
     `wing_bestiary`).
   * **conversion** — `kind == "candidate"` (the awareness layer knows
     the source, MemPalace hasn't seen drawers from it). Cheap and
     expensive candidates render as separate ingest blocks in the
     proposal so cost is legible at GM-review time.
   * **lore** — anything else that didn't match a stronger signal.
   * Classifier order: candidate → statblock → encounter → npc →
     location → lore. Encounters and NPCs outrank locations so
     "bandits ambush the party at the narrow pass" doesn't get misfiled
     as a location just because the word "pass" appears.
4. `render()` writes Markdown to `docs/dossier_proposal.md`.

After this step, on disk:

```
~/campaigns/icespire/docs/
  dossier_proposal.md              ← new
```

The file looks roughly like:

```markdown
# Dossier Proposal — party arrives at Icespire Hold…

> **Status:** candidates only. Review, delete, reorder, and edit
> before any render pipeline (prep / session_doc / planning)
> consumes this file.

## Metadata
- generated_at: 2026-04-24T14:02:11
- campaign_dir: `/home/kostadis/campaigns/icespire`
- palace: `/mnt/data/mempalace/palaces/chat`
- raw_hit_count: 18

## NPC Candidates

### 1. Grundar Quartzvein
**book**: Dragon of Icespire Peak  **section**: `… / Icespire Hold`
**page**: 47  **similarity**: 0.84  **drawer**: `drawer_icespire_hold_entry`
**named**: Grundar Quartzvein, Harbin Wester
> The dwarven foreman Grundar Quartzvein was captured during the
> assault on Icespire Hold…

## Locations

### 1. Icespire Hold
…

## Encounters
…

## Stat Blocks

### 1. Cryovain (young white dragon)
**book**: Dragon of Icespire Peak  **page**: 12
**drawer**: `drawer_icespire_cryovain_sb`
> # Cryovain
> tag: creature
> cr: 7
> Young white dragon. Frightful Presence. Ice Walk. Cold breath…

## Conversion Suggestions (unconverted rpglib books)

### 1. Fizban's Treasury of Dragons
**book_id**: 4421
**to convert:**
python3 convert_book.py /mnt/g/Fizbans.pdf
**then ingest:**
python3 fivetools_ingest.py /mnt/g/Fizbans.json --book-id 4421
estimated: ~208,000 tokens  (~$0.17–$0.62)

---

## Approval

Rendering pipelines should refuse to run unless this file is present
and the header line above is edited from the default
`> **Status:** candidates only.` to e.g.
`> **Status:** approved by <name> on <date>.`
```

What this step is protecting against: the "LLM decides scope"
failure mode. The file lists everything retrieval thinks *could* be
relevant; no prose has been rendered; nothing has been committed to
the session plan; you haven't been asked anything yet.

## Step 2 — review and approve

This step has no script. You open `docs/dossier_proposal.md` in your
editor and do three things:

1. **Delete candidates that aren't in scope.** Retrieval will find
   plausible-but-wrong hits on any real query — a drawer about "the
   old keep" in a different campaign, an NPC with a similar name, a
   stat block for a creature the party has already killed. Every
   candidate that survives here is the one you want prose generated
   against.
2. **Reorder or edit.** Promote a specific stat block to the top of
   the bestiary slot; merge two NPC entries if retrieval returned
   both a full-dossier drawer and a passing-mention drawer; delete
   the conversion slot entirely if you don't want to go convert
   anything right now.
3. **Edit the status banner.** Change the line:

   ```markdown
   > **Status:** candidates only. Review, delete, reorder, and edit…
   ```

   to something like:

   ```markdown
   > **Status:** approved by Kostadis on 2026-04-24.
   ```

   The render pipelines check this line mechanically. Any string that
   doesn't start with "candidates only" (case-insensitive) counts as
   approved. The intent is the one-bit signal, not the exact wording.

What this step is protecting against: errors compounding downstream.
If Step 1 returns 18 candidates and two of them are off-topic,
rendering from the raw proposal produces a session doc with two
hallucinated threads woven through it. Catching the mismatch at the
proposal stage is cheap; catching it in a 12,000-token narration pass
is not.

**If the conversion slot has anything in it you want to act on**, this
is the moment to run those commands. They're printed verbatim in the
proposal:

```bash
python convert_book.py /mnt/g/Fizbans.pdf
# review the JSON in adventure_editor
python fivetools_ingest.py /mnt/g/Fizbans.json --book-id 4421
```

Then re-run Step 1 so the new drawers show up in the proposal. The
conversion step is never triggered automatically — that would make
LLM-rendered prose (which is what pdf-translators produces under the
hood) a side effect of querying, which violates the scope rule.

## Step 3 — render with `--require-proposal`

Now prep actually runs. `prep.py` is the primary render pipeline; the
same convention works for `session_doc.py` and `planning.py`.

```bash
cd ~/campaigns/icespire
python ~/src/CampaignGenerator/prep.py \
    --campaign-dir . \
    --require-proposal \
    --mode pipeline \
    --beat "The party arrives at Icespire Hold and finds Cryovain absent…"
```

What happens internally:

1. Argparse runs. Immediately after config load and before any Claude
   call, `proposal_loader.require_approved_proposal(campaign_dir)`
   fires:
   * Missing `docs/dossier_proposal.md` → `parser.error()` with
     "dossier proposal not found" and a hint to run
     `dossier_proposer.py` first. Exit code 2, no tokens spent.
   * Proposal present but status banner still `candidates only` →
     `parser.error()` with "not been approved" and the edit hint.
     Exit code 2, no tokens spent.
   * Approved proposal → pass.
2. `proposal_loader.attach_proposal_to_documents(config, campaign_dir)`
   injects a synthetic entry into `config["documents"]` with label
   `dossier_proposal`. The existing `campaignlib.assemble_docs` picks
   it up automatically — no config-file edits, no changes to the
   prompt-assembly code path.
3. `assemble_user_prompt()` concatenates every config doc
   (`campaign_state`, `world_state`, `planning`, `party`,
   `dossier_proposal`) separated by `\n\n---\n\n`, then appends the
   beat under `## Session Beat`.
4. `make_client()` → `stream_api()` → Claude renders the encounter
   doc to stdout. In pipeline mode (three sequential API calls) the
   proposal flows into Lore Oracle (stage 1), whose output flows into
   Encounter Architect (stage 2), whose output flows into Voice
   Keeper (stage 3). The proposal constrains scope at every stage —
   the LLM isn't being asked to pick NPCs or locations; it's being
   asked to render prose for the ones you approved.

What this step is protecting against: the "LLM structures what a
previous LLM extracted" failure mode. Without the proposal as the
boundary, Claude would see raw retrieval output — drawer IDs,
similarity scores, book metadata — and would have to simultaneously
decide what to include *and* render it. With the proposal as the
boundary, it sees a curated list of verbatim excerpts with citations,
and only has to do the rendering job.

## What gets saved

`prep.py` writes a timestamped log to `logs/` (system prompt + user
prompt + response) unless you pass `--no-log`. The rendered encounter
doc also goes to `--output FILE` if you pass one, or just streams to
stdout otherwise. Nothing in this workflow writes to the MemPalace
palace — that only happens at ingest time, never at render time.

The proposal file itself (`docs/dossier_proposal.md`) is a campaign
artifact; keep it in git alongside `world_state.md` and friends. When
you run next week's session-prep on a different beat, overwrite it
(or keep old proposals under `docs/proposals/` if you want a
history — the filename is configurable via `--output`).

## Troubleshooting

* **`dossier proposal not found`** — run Step 1 first, or drop
  `--require-proposal` if you want to render without a proposal
  (which skips the Phase 3 gate).
* **`proposal has not been approved`** — you edited the proposal but
  forgot to change the status banner. Open the file and change
  `> **Status:** candidates only.` to anything else.
* **`fallback: true` in the proposal metadata** — MemPalace's
  hierarchical indices are empty or stale. Either ingest some books
  (ingest workflow) or rebuild indices explicitly:

  ```python
  from mempalace import recursive_indexer
  recursive_indexer.rebuild_all("/mnt/data/mempalace/palaces/chat")
  ```

* **Retrieval keeps missing a book you know is relevant** — check
  `rpg_library.db` has the book enriched (title, tags, description).
  `rpg_retriever.search_rpglib` does tokenized LIKE matching; if the
  book's title and description don't share any tokens with your
  query, it won't be found. Options: run rpglib's enrichment on the
  book; add synonyms to its tags; or pass explicit filters
  (`--game-system "D&D 5e"`, `--product-type "adventure"`).
* **`rpg_search` / `propose_dossier` / `suggest_conversion` MCP
  tools** — the three live on the CampaignGenerator MCP server
  (`mcp_server.py`). An LLM that's already talking to your campaign
  workspace can drive the retrieval side of this workflow directly;
  the human-review step still has to happen in an editor.

## Related docs

* `docs/archive/rlm_integration_plan.md` — the architectural plan these three
  scripts implement. Phases 1–3 are landed (archived; plan shipped).
* `CLAUDE.md` § "RLM pipeline — rpglib + pdf-translators + MemPalace"
  — reference summary of the tool surface.
* `tests/test_require_proposal_cli.py` — executable spec of the
  Step 3 gate (what passes, what fails, with what messages).
* `tests/test_retrieve_render_isolation.py` — AST-level CI assertion
  that no function body co-locates a retrieval call with a render
  call. Guarantees the `proposal` boundary stays a boundary.
