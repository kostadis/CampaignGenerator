# planning.py — How the NPC Synthesize Workflow Works

`planning.py` produces `planning.md` — the GM reference for active threats, NPC
intentions, and plot threads. It runs in two separate phases that are designed to
be done on different days:

1. **Build dossiers** — extract per-NPC information from session summaries into
   individual files, one per NPC, for review and editing
2. **Synthesize** — combine the edited dossier files with arc score mechanics into
   a finished `planning.md`

Keeping these phases separate is intentional. The dossier files are the human
checkpoint: you review and correct them before the synthesis runs, so errors in the
extraction don't silently propagate into your planning document.

---

## Phase 1: Build Dossiers

```bash
python planning.py \
    --summaries summaries.md \
    --build-dossiers \
    --dossier-dir docs/npcs/
```

### What it does internally

**Step 1 — Extract NPC mentions from each chunk**

The summaries file is split into chunks (by character count, or by session prefix
with `--split-chapters "# Session"`). Each chunk is sent to Claude with a prompt
that extracts every named NPC as a separate `## NPC Name` section containing what
they did, said, revealed, and where they were.

Intermediate extraction files are saved to `docs/planning_extractions/`
(`dossier_extract_001.md`, `dossier_extract_002.md`, etc.). If you re-run,
existing files are skipped — only new chunks are processed.

**Step 2 — Aggregate by NPC name**

All `dossier_extract_*.md` files are scanned. Every `## Heading` is treated as an
NPC name; all sections with the same name are grouped together. A single NPC
appearing across 20 sessions produces one aggregated block of raw notes.

**Step 3 — Synthesize each NPC into a dossier file**

Each NPC's aggregated notes are sent to Claude with a prompt that produces a clean
single-NPC dossier:

```
# NPC Full Name
## Identity
## Personality & Motivations
## History with the Party
## Current Status
## Relationships
## Arc Score Events (if applicable)
```

Output files are named by slug: `grundar_quartzvein.md`, `xalvosh.md`, etc.
Existing files are skipped.

### Default directories

| What | Default |
|---|---|
| Per-chunk extractions | `<dossier-dir>/../planning_extractions/` |
| Dossier output files | `--dossier-dir` (required) |

If `--dossier-dir docs/npcs/`, extractions go to `docs/planning_extractions/`.

### Splitting by session instead of chunk size

For large summaries where sessions are separated by a heading, splitting on that
heading gives cleaner per-session extractions and avoids cutting mid-scene:

```bash
python planning.py \
    --summaries summaries.md \
    --build-dossiers \
    --dossier-dir docs/npcs/ \
    --split-chapters "# Session"
```

---

## Review the dossier files

After Phase 1, open the files in `docs/npcs/` and:

- **Correct factual errors** — the extraction model sometimes misattributes actions
  or conflates two NPCs with similar names
- **Fill in what's missing** — motivations and secrets the model couldn't infer from
  session notes alone (things only you know as GM)
- **Prune noise** — remove minor one-time NPCs you don't need in `planning.md`
- **Add arc score values** — the extraction tracks *events* but not the running total;
  add the current numeric value yourself

These files are yours. The synthesize pass only reads them; it never overwrites them.

---

## Phase 2: Synthesize

```bash
python planning.py \
    --npc docs/npcs/grundar_quartzvein.md docs/npcs/xalvosh.md \
    --arc-scores docs/arc_scores/brundar_echo.md docs/arc_scores/kraken_echoes.md \
    --summaries summaries.md \
    --output docs/planning.md
```

Or, if you want to skip re-extracting summaries (they were already extracted in
Phase 1 or a prior run):

```bash
python planning.py \
    --npc docs/npcs/grundar_quartzvein.md docs/npcs/xalvosh.md \
    --arc-scores docs/arc_scores/brundar_echo.md \
    --synthesize-only \
    --extract-dir docs/planning_extractions \
    --output docs/planning.md
```

### What it does internally

All NPC dossiers, arc score documents, session extractions, and any `--context`
files are assembled into a single prompt and sent to Claude, which produces
`planning.md` with:

- **Threat Tracker** — table of all arc scores (current value, next threshold, trigger)
- **NPC Dossiers** — one subsection per NPC with current plans, what party knows vs.
  what's hidden, and arc score state
- **Faction States** — goals, resources, and relationship to the party
- **Active Plots** — threads currently in motion, ordered by urgency
- **DM Notes** — foreshadowing and NPC convergence points

**Source priority:**
- NPC dossier files take precedence for identity and definitive facts
- Session extractions take precedence for current emotional state and recent actions
- Arc score documents define the mechanics; session notes set the current value

### Default directories

| What | Default |
|---|---|
| Session extractions | `<output>/../planning_extractions/` |
| Output | `--output` (required) |

If `--output docs/planning.md`, extractions are loaded from `docs/planning_extractions/`.

---

## Full example workflow

```bash
# Step 1: extract dossiers from the full summaries file
python planning.py \
    --summaries summaries.md \
    --build-dossiers \
    --dossier-dir docs/npcs/ \
    --split-chapters "# Session"

# Step 2: review and edit docs/npcs/*.md
#   - fix errors, add motivations, fill arc score values

# Step 3: synthesize planning.md from edited dossiers
python planning.py \
    --npc docs/npcs/grundar_quartzvein.md docs/npcs/xalvosh.md docs/npcs/jena_roscoe.md \
    --arc-scores docs/arc_scores/brundar_echo.md docs/arc_scores/kraken_echoes.md \
    --context docs/campaign_state.md \
    --output docs/planning.md

# Step 4 (later): re-synthesize after editing dossiers without re-extracting
python planning.py \
    --npc docs/npcs/*.md \
    --arc-scores docs/arc_scores/*.md \
    --synthesize-only \
    --extract-dir docs/planning_extractions \
    --output docs/planning.md
```

---

## Which NPCs to include in --arc-scores

Pass only the arc score mechanic files for NPCs and factions the party is actively
tracking. The arc score file defines the full list of thresholds and what unlocks at
each one — Claude uses this to populate the Threat Tracker table and the arc score
sections in each dossier.

You don't need an arc score file for every NPC. Minor NPCs with no arc score
mechanics are handled entirely by their dossier file.

---

## Re-running efficiently

| Situation | Command |
|---|---|
| New sessions added to summaries | Delete `docs/planning_extractions/dossier_extract_*.md`, re-run Phase 1 |
| Edited a dossier, want updated planning.md | Phase 2 with `--synthesize-only` |
| New NPC appeared, want their dossier | Re-run Phase 1 (existing dossier files are skipped) |
| Deleted a dossier file (pruned NPC) | Phase 2 with `--synthesize-only`, omit that `--npc` arg |
