# CampaignGenerator

A D&D session-prep and post-session documentation toolkit powered by the [Claude API](https://docs.anthropic.com/). Generate encounter design documents, keep campaign canon consistent, and turn raw session transcripts into polished, multi-voice narrative documents.

---

## What's in the box

| Script | What it does |
|---|---|
| `prep.py` | Session beat and session arc prep — the main planning tool |
| `session_doc.py` | Post-session: five-pass pipeline producing a narrative + structured recap |
| `vtt_summary.py` | Convert a Zoom `.vtt` transcript into a session summary |
| `campaign_state.py` | Generate a grounding doc tracking completed content and NPC states |
| `distill.py` | Synthesize session summaries into a living `world_state.md` |
| `party.py` | Generate `party.md` from character sheets and summaries |
| `planning.py` | Generate `planning.md` from NPC dossiers and arc scores |
| `npc_table.py` | Generate a quick NPC reference table from campaign docs |
| `query.py` | Search session summaries for a specific event, NPC, or topic |
| `make_tracking.py` | Extract a tracking list from an adventure module |
| `dnd_sheet.py` | Convert a D&D Beyond character sheet PDF to markdown |
| `new_workspace.py` | Create a new campaign workspace directory |
| `transform.py` | Convert NotebookLLM dossiers into `prep.py` input |

All scripts share a common library (`campaignlib.py`) for API calls, file I/O, logging, and config loading.

---

## Setup

**Requirements**: Python 3.10+

```bash
pip install anthropic pyyaml pyperclip
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Quick start

### 1. Create a campaign workspace

```bash
python new_workspace.py ~/campaigns/mycamp --name "My Campaign"
cd ~/campaigns/mycamp
```

This generates a `config.yaml` with absolute paths so every script can auto-detect it when run from the workspace directory.

### 2. Session prep (before a session)

```bash
# Single beat — interactive
python ~/CampaignGenerator/prep.py

# Single beat — inline
python ~/CampaignGenerator/prep.py --beat "The party enters Icespire Hold"

# Three-stage pipeline: Lore Oracle → Encounter Architect → Voice Keeper
python ~/CampaignGenerator/prep.py --mode pipeline --beat "The party enters Icespire Hold"

# Full session arc
python ~/CampaignGenerator/prep.py --session "1. Travel to Hold 2. Confront boss 3. Dragon reveal"
```

### 3. Post-session documentation

```bash
# Convert the Zoom transcript to a session summary
python ~/CampaignGenerator/vtt_summary.py session.vtt -o summaries/session_12.md

# Regenerate grounding docs
python ~/CampaignGenerator/campaign_state.py summaries.md -o docs/campaign_state.md
python ~/CampaignGenerator/distill.py summaries.md -o docs/world_state.md

# Generate the session document (see full details below)
python ~/CampaignGenerator/session_doc.py session-recap \
    --roleplay-extract-dir vtt_roleplay_extractions/ \
    --summary-extract-dir  vtt_extractions/ \
    --context docs/campaign_state.md docs/world_state.md docs/party.md \
    --party   docs/party.md \
    --characters "Aldric, Syreth, Mira, Gorvan" \
    --output session-doc.md
```

---

## session_doc.py — Narrative session documents

`session_doc.py` is the post-session centerpiece. It takes a raw recap and turns it into a document that reads like a novel chapter — each player character narrates a chronological slice of the session in their own first-person voice — followed by enhanced structured sections (Memorable Moments, Scenes, NPCs, etc.).

### How it works

Five sequential LLM passes:

```
recap + VTT extractions + context docs
            │
    ┌───────▼────────┐
    │  Pass 1        │  Consistency check (silent)
    │                │  recap vs. campaign_state / world_state / party
    └───────┬────────┘
            │ consistency report
    ┌───────▼────────┐
    │  Pass 2        │  Enhance structured sections
    │                │  Memorable Moments expanded; Scenes/NPCs preserved;
    │                │  Consistency Notes appended. Summary intentionally omitted.
    └───────┬────────┘
            │ structured sections
    ┌───────▼────────┐
    │  Pass 3        │  Narrative plan
    │                │  Assigns each character a chronological chunk range
    │                │  and a one-sentence dramatic focus
    └───────┬────────┘
            │ plan
    ┌───────▼────────┐
    │  Pass 4 × N    │  Per-character extraction (silent)
    │                │  Pulls only that character's moments from their chunks:
    │                │  dialogue exchanges, action beats, environment
    └───────┬────────┘
            │ per-character moment lists
    ┌───────▼────────┐
    │  Pass 5 × N    │  Per-character narration
    │                │  First-person prose, style-matched to examples,
    │                │  with handoff sentence from the previous narrator
    └───────┬────────┘
            │
    narrative sections + structured sections → final document
```

### Usage

```bash
python session_doc.py session-recap \
    --roleplay-extract-dir vtt_roleplay_extractions/ \
    --summary-extract-dir  vtt_extractions/ \
    --context docs/campaign_state.md docs/world_state.md docs/party.md \
    --party   docs/party.md \
    --characters "Aldric, Syreth, Mira, Gorvan" \
    --examples examples/bard_arrival.md \
               examples/cleric_debate.md \
               examples/druid_combat.md \
               examples/barbarian_moment.md \
    --output session-doc.md
```

### Style examples (`--examples`)

The `--examples` flag injects excerpts from earlier, handcrafted session summaries as few-shot style references. One excerpt per character, covering different scene types (travel, combat, political comedy, emotional beat), produces the most reliable voice transfer.

```bash
# Create an examples directory in your workspace
mkdir examples/
# Write one .md file per character — a representative excerpt from a past session
```

The examples are injected into the narration system prompt under a `STYLE REFERENCE` block, with instructions to match voice, structure, and tone — not to copy content.

### Per-character voice files (`--voice-dir`)

Players can write short notes describing their character's inner voice, distinctive phrases, or narrative quirks. These are injected only into that character's narration pass.

```bash
mkdir voice/
# Create one file per character: <name>_voice.md or <name>.md
# e.g. voice/aldric_voice.md
```

```bash
python session_doc.py session-recap \
    --voice-dir voice/ \
    ... (other flags)
```

Voice file example (`aldric_voice.md`):
```markdown
Aldric speaks in short, declarative sentences. He rarely explains his reasoning —
he states what he's going to do and does it. When he reflects on his past, he uses
physical metaphors (stones, weight, iron). He never says "feel" — he says "know."
```

### Flags

| Flag | Effect |
|---|---|
| `--plan-only` | Stop after pass 3 and print the section assignments — verify coverage before committing |
| `--fast` | Use Claude Haiku instead of Sonnet (~4× cheaper, good for iteration) |
| `--no-log` | Skip saving the full log |
| `--session-name` | Override the document title |
| `--model` | Explicit model override |

### Cost

A full Sonnet run costs roughly **$0.25–0.40** depending on session length. `--fast` (Haiku) costs roughly **$0.07**. `max_tokens` is a ceiling, not a cost driver — you pay for what's generated.

For the technical design notes behind this pipeline (narrative bleed, chunk assignment, style transfer), see [SESSION_DOC_PIPELINE.md](SESSION_DOC_PIPELINE.md).

---

## prep.py — Session prep

Generates encounter design documents from a session beat or numbered session outline. Three modes:

- **`single`** (default): one API call, one encounter document
- **`pipeline`**: three sequential calls — Lore Oracle → Encounter Architect → Voice Keeper

The pipeline's Lore Oracle verifies the beat against campaign canon and returns `CLEAR` / `FLAGS` / `GAPS`. If it flags issues, you're prompted before continuing.

```bash
python prep.py --beat "The party enters Icespire Hold"
python prep.py --mode pipeline --beat "The party enters Icespire Hold"
python prep.py --session "1. Arrival 2. Boss fight 3. Reveal"
python prep.py --clipboard --beat "..."   # copy prompt to clipboard instead
```

---

## Other scripts

### vtt_summary.py

Converts a Zoom `.vtt` transcript into a structured session summary using a two-pass extract → synthesize pipeline.

```bash
python vtt_summary.py session.vtt -o summaries/session_12.md
python vtt_summary.py session.vtt --date "2026-03-15" --session-name "Session 12 — Icespire Hold"
python vtt_summary.py --synthesize-only --extract-dir vtt_extractions/ -o out.md
```

### campaign_state.py

Generates a grounding document tracking completed content and current NPC states. Prevents prep tools from hallucinating completed content as still active.

```bash
python campaign_state.py summaries.md --output docs/campaign_state.md

# With a tracking list to ensure specific events are flagged if missing
python campaign_state.py summaries.md \
    --track-file docs/tracking.txt \
    --output docs/campaign_state.md
```

### distill.py

Synthesizes a large session-summary file into a structured `world_state.md` via extract → synthesize.

```bash
python distill.py summaries.md --output docs/world_state.md
python distill.py --synthesize-only --extract-dir docs/distill_extractions --output docs/world_state.md
```

### party.py

Generates `party.md` from character sheets, session summaries, and arc score mechanics.

```bash
python party.py \
    --character docs/characters/soma.md docs/characters/vukradin.md \
    --summaries summaries.md \
    --arc-scores soma_arc.md vukradin_arc.md \
    --output docs/party.md
```

### planning.py

Generates `planning.md` from NPC dossiers and arc score documents.

```bash
# Build per-NPC dossier files from summaries (review and edit before synthesizing)
python planning.py --summaries summaries.md --build-dossiers --dossier-dir docs/npcs/

# Synthesize planning doc from dossiers
python planning.py \
    --npc docs/npcs/*.md \
    --arc-scores arc_scores/*.md \
    --output docs/planning.md
```

### query.py

Ad-hoc search: find whether a specific event, NPC, or detail appears in your session summaries.

```bash
python query.py summaries.md "Did the party clear Gnomengarde?"
python query.py summaries.md "What happened with the stone giants?"
python query.py summaries.md "Xanth" --hits-only   # raw matching extracts only
```

### dnd_sheet.py

Converts a D&D Beyond character sheet PDF to structured markdown using Claude's vision API.

```bash
python dnd_sheet.py Aldric.pdf --output aldric.md
python dnd_sheet.py *.pdf --output-dir docs/characters/
```

### make_tracking.py

Extracts a tracking list from an adventure module markdown for use with `campaign_state.py`.

```bash
python make_tracking.py "adventure.md" --output docs/tracking.txt
# Review the output before use — remove events that haven't happened yet
```

### npc_table.py

Generates a quick NPC reference table (Name / Faction / Current State / Motivations).

```bash
python npc_table.py
python npc_table.py --docs world_state planning
python npc_table.py --output npc_state.md
```

---

## Typical workflow

```bash
# 1. Create workspace
python new_workspace.py ~/campaigns/mycamp --name "My Campaign"
cd ~/campaigns/mycamp

# 2. Convert character sheets
python ~/CampaignGenerator/dnd_sheet.py *.pdf --output-dir docs/characters/

# 3. Extract tracking list from adventure module
python ~/CampaignGenerator/make_tracking.py "adventure.md" --output docs/tracking.txt
# (review and edit tracking.txt)

# 4. Generate grounding docs from session summaries
python ~/CampaignGenerator/campaign_state.py summaries.md \
    --track-file docs/tracking.txt --output docs/campaign_state.md
python ~/CampaignGenerator/distill.py summaries.md --output docs/world_state.md
python ~/CampaignGenerator/party.py \
    --character docs/characters/*.md \
    --summaries summaries.md --output docs/party.md

# 5. Run session prep
python ~/CampaignGenerator/prep.py --beat "The party arrives at Icespire Hold"

# --- After the session ---

# 6. Convert transcript
python ~/CampaignGenerator/vtt_summary.py session.vtt -o summaries/session_12.md

# 7. Regenerate grounding docs
python ~/CampaignGenerator/campaign_state.py summaries.md --output docs/campaign_state.md
python ~/CampaignGenerator/distill.py summaries.md --output docs/world_state.md

# 8. Generate session document
python ~/CampaignGenerator/session_doc.py session-12-recap \
    --roleplay-extract-dir vtt_roleplay_extractions/ \
    --summary-extract-dir  vtt_extractions/ \
    --context docs/campaign_state.md docs/world_state.md docs/party.md \
    --party   docs/party.md \
    --characters "Aldric, Syreth, Mira, Gorvan" \
    --examples examples/*.md \
    --voice-dir voice/ \
    --output docs/session_12.md
```

---

## Config

All scripts auto-detect config: they look for `config.yaml` in the current working directory first, then fall back to `config/config.yaml` in the script directory. Running from a workspace directory is the recommended pattern — no `--config` flag needed.

```bash
cd ~/campaigns/mycamp
python ~/CampaignGenerator/prep.py --beat "..."   # auto-detects config.yaml
```

Override with `--config path/to/config.yaml` if needed.

---

## Running tests

```bash
python -m pytest tests/
```

---

## Model choice

All scripts default to **Claude Sonnet** and accept `--model` for overrides. `session_doc.py` and `narrative.py` also accept `--fast` to use **Claude Haiku** (~4× cheaper), which is useful for iterating on prompts before a final run.

```bash
python session_doc.py ... --fast      # Haiku — iterate quickly
python session_doc.py ... --model claude-opus-4-6   # Opus — highest quality
```

---

## License

MIT
