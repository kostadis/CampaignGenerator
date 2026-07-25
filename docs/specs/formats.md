# CampaignGenerator File Formats Reference

Generated reference for all input/output file formats used across CampaignGenerator tools.
When debugging or extending any tool, read this file first instead of re-reading source code.

---

## Summary Table

| File Pattern | Reader | Writer | Purpose |
|---|---|---|---|
| `config.yaml` | All scripts | Manual / `pipelines/workspace/new_workspace.py` | Central configuration |
| `docs/campaign_state.md` | `pipelines/session_prep/prep.py`, `pipelines/grounding/planning.py`, `pipelines/grounding/party.py` | `pipelines/grounding/campaign_state.py` P2 | Completed content tracker |
| `docs/world_state.md` | `pipelines/session_prep/prep.py`, all tools | `pipelines/grounding/distill.py` P2 | Living canon reference |
| `docs/planning.md` | `pipelines/session_prep/prep.py` | `pipelines/grounding/planning.py` P2 | NPC/faction prep tracker |
| `docs/party.md` | `sd_*.py` | `pipelines/grounding/party.py` P2 | Character state tracker |
| `summaries.md` | `pipelines/grounding/campaign_state.py`, `pipelines/grounding/distill.py`, `pipelines/grounding/planning.py`, `pipelines/grounding/party.py` | hand (append `session-summary.md`) | Session record |
| `distill_extractions/extract_NNN.md` | `pipelines/grounding/distill.py` P2 | `pipelines/grounding/distill.py` P1 | Lore extraction notes |
| `state_extractions/extract_NNN.md` | `pipelines/grounding/campaign_state.py` P2 | `pipelines/grounding/campaign_state.py` P1 | Campaign state notes |
| `planning_extractions/extract_NNN.md` | `pipelines/grounding/planning.py` P2 | `pipelines/grounding/planning.py` P1 | NPC/faction notes |
| `party_extractions/extract_NNN.md` | `pipelines/grounding/party.py` P2 | `pipelines/grounding/party.py` P1 | Character progression notes |
| `docs/npcs/[slug].md` | `pipelines/grounding/planning.py` P2 | `pipelines/grounding/planning.py --build-dossiers` | Per-NPC dossier |
| `scene_extractions/NN_narrator_scene.md` | `session_doc/sd_narrate.py`, `server/routers/scene_editor.py` | `(deleted in PR #52)` | Scene-specific moments |
| `scene_extractions/plan.md` | `session_doc/sd_plan.py`, `server/routers/scene_editor.py` | `session_doc/sd_plan.py` | Narrator section plan |
| `voice/[character]_voice.md` | `session_doc/sd_narrate.py` | Players (manual) | Player voice guide |
| `logs/YYYY-MM-DD_HHMMSS_*.md` | — | `campaignlib.save_log()` | Archive of all API calls |
| `tracking.txt` | `pipelines/grounding/campaign_state.py` | Manual / `pipelines/grounding/make_tracking.py` | Event tracking list |

---

## config.yaml

**Reader:** All scripts via `campaignlib.load_config()`
**Writer:** Manual or `pipelines/workspace/new_workspace.py`

```yaml
system_prompt: config/system_prompt.md

log_dir: logs/

agents:
  lore_oracle: config/agents/lore_oracle.md
  encounter_architect: config/agents/encounter_architect.md
  voice_keeper: config/agents/voice_keeper.md

documents:
  - label: campaign_state
    path: docs/campaign_state.md
  - label: world_state
    path: docs/world_state.md
  - label: mechanics
    path: docs/mechanics.md
  - label: planning
    path: docs/planning.md
  - label: party
    path: docs/party.md
```

Rules:
- Paths resolved relative to config directory
- `label` names are used by `assemble_docs()` to select which docs to load
- `campaign_state` is listed first so it is the first context `pipelines/session_prep/prep.py` sees

---

## Session Summary (summaries.md)

**Written by:** hand — append each session's `session-summary.md` (produced by `session_doc/enhance_summary.py`)
**Read by:** `pipelines/grounding/campaign_state.py`, `pipelines/grounding/distill.py`, `pipelines/grounding/planning.py`, `pipelines/grounding/party.py`

Multiple sessions are appended; each session starts with a `# Session` heading.

```markdown
# Session — 2026-03-18

## Overview
One paragraph narrative covering what happened this session.

## Session Events
- Key story events in chronological order (bullets)
- Be specific: names, locations, outcomes

## NPC Interactions
- **NPC Name**: What was said or decided, what was revealed

## Open Threads
- Unresolved plot threads and open questions

## Out-of-Character
(skip if none)
- Meta decisions, schedule changes, retcons

## Next Session Setup
One short paragraph: where are PCs, what is immediately at stake
```

---


---

## Grounding Documents

### docs/campaign_state.md

**Written by:** `pipelines/grounding/campaign_state.py` Pass 2
**Read by:** `pipelines/session_prep/prep.py` (first context), `pipelines/grounding/planning.py`, `pipelines/grounding/party.py`

```markdown
## Completed Encounters & Quests
- [Name]: [outcome], session [N]

## Resolved Plot Threads
- [Thread name]: how it ended

## NPC Current States
| NPC | Status | Last Known Location | Disposition |
|-----|--------|---------------------|-------------|
| Name | Alive/Dead/Missing/Imprisoned/Unknown | Location | Friendly/Hostile/Neutral |

## Active Quests & Open Threads
- [Thread name]: [current stakes, last known state]

## Party Current Situation
- Current location
- Active obligations and debts
- Key resources and assets
- Recent developments

## Tracked Items Status
(only present if --track-file was provided)
- Item 1: [status or "NOT FOUND IN SUMMARIES"]
```

**Intermediate: state_extractions/extract_NNN.md**

```markdown
## Completed Encounters & Quests
[list of completed content with outcomes]

## Resolved Plot Threads
[closed plot threads]

## NPC State Changes
[NPC deaths, location changes, alliance shifts]

## Party Accomplishments & Acquisitions
[items earned, secrets learned, allies secured]

## Party Current Situation
[location, immediate situation]

## Tracked Items
(only if tracking file provided)
```

### docs/world_state.md

**Written by:** `pipelines/grounding/distill.py` Pass 2
**Read by:** `pipelines/session_prep/prep.py` and all tools as lore reference

**Intermediate: distill_extractions/extract_NNN.md**

```markdown
## NPCs
- NPC Name: current location, state, recent actions, faction, motivations

## Factions
- Faction Name: goals, recent actions, relationships, key members

## World Events
- Significant events in chronological order

## Locations
- Location Name: what it is, what happened there, current state

## Threads & Mysteries
- Unresolved plot threads, open questions, foreshadowed events
```

**Synthesized format:**

```markdown
# [Campaign Title] — World State

## NPCs
[Current states of all named NPCs by faction/role]

## Factions & Organizations
[Current goals, key members, relationships]

## Locations
[Named places and their current state]

## Active Threats & Arcs
[Ongoing dangers and plot threads]

## Canon Events Timeline
[Chronological list of major events for reference]
```

### docs/planning.md

**Written by:** `pipelines/grounding/planning.py` Pass 2
**Read by:** `pipelines/session_prep/prep.py`

```markdown
## Threat Tracker
| Score Name | NPC/Faction | Current Value | Next Threshold | What Triggers Next |

## NPC Dossiers
### [NPC Name]
- Current location and status
- Active plans and immediate goals
- What party knows vs. what is hidden
- Key relationships and leverage points
- Arc score value (if applicable)

## Faction States
### [Faction Name]
- Current goals and operations
- Key members and roles
- Relationship to party and other factions
- Resources and vulnerabilities

## Active Plots
[Threads in motion by urgency]

## DM Notes
[Foreshadowing opportunities, convergence points]
```

**Intermediate: planning_extractions/extract_NNN.md**

```markdown
## NPC Activity
- NPC names with what they did, where, what they revealed

## Faction Movements
- Faction actions, resource changes, alliance shifts

## Threat Arc Events
- Events triggering arc score increases

## Revealed Information
- Secrets and plans uncovered

## Current Whereabouts
- Last known locations
```

**Per-NPC Dossier: docs/npcs/[slug].md**

```markdown
# [NPC Full Name]

## Identity
- Role, title, faction
- First appearance and how party met them

## Personality & Motivations
- Core goals and drives (2–4 sentences)

## History with the Party
- Chronological summary of significant interactions

## Current Status
- Last known location
- Active plans or operations
- What party knows vs. hidden

## Relationships
- Key relationships with other NPCs, factions, party members

## Arc Score Events
- Events triggering arc score changes
```

### docs/party.md

**Written by:** `pipelines/grounding/party.py` Pass 2
**Read by:** `session_doc/sd_narrate.py` for character voice reference

```markdown
## Party Overview
- Current location
- Active quests
- Collective resources
- Group reputation

## Characters
### [PC Name]
- Class, level, player
- Key personality traits and motivations (2–3 sentences)
- Current arc score tracks: name, value, triggers
- Notable relationships (allies, enemies, obligations)
- Items of significance

## Arc Score Summary
| Character | Arc Name | Current | Next Threshold | Unlocks |

## Party Dynamics
- How characters relate to each other
- Current tensions and shared goals
```

**Intermediate: party_extractions/extract_NNN.md**

```markdown
## Character Progression
- Level changes, new abilities, items

## Arc Score Events
- Character name, what happened, direction (positive/negative)

## Relationships & Decisions
- PC decisions, relationships, oaths, debts, enemies made

## Party State Updates
- Location changes, resources, reputation, obligations
```

---

## Session Narrative (session_doc/sd_narrate.py)

### scene_extractions/plan.md

**Written by:** `session_doc/sd_plan.py`
**Read by:** `session_doc/sd_narrate.py`, `server/routers/scene_editor.py`

**Scene mode:**

```markdown
## Scene 1
narrator: Vukradin
chunks: 1
scene: The Stone Giants
focus: Vukradin's stoic wonder at creatures of living rock

## Scene 2
narrator: Soma
chunks: 1
scene: Crossing the Glacier
focus: Soma's attunement to the wrongness in the ice
```

**Chunk mode:**

```markdown
## Section 1
narrator: Vukradin
chunks: 1
focus: The stone giant encounter and Vukradin's measured respect

## Section 2
narrator: Soma
chunks: 1-2
focus: The glacier crossing and Soma's unease
```

Rules:
- Every character in roster appears exactly once
- All chunks covered by at least one section
- Scene mode: `scene:` field names the scene; `chunks:` is the source chunk(s)
- Chunk ranges can overlap only when a section straddles a boundary

### scene_extractions/NN_narrator_scene.md (Extraction Files)

**Pattern:** `01_vukradin_the_stone_giants.md`, `02_soma_the_glacier.md`
**Written by:** `session_doc/sd_narrate.py`
**Read by:** `session_doc/sd_narrate.py`, edited in `server/routers/scene_editor.py`

```markdown
tokens: 6000
(optional override — only needed if estimate is wrong)

**The Stone Giants**
Stone Giant 1: "Little one with obsidian sword passed through here yesterday."
Stone Giant 2: "King Hekaton's orders — we do not interfere."
The giants were immense, carved from living rock. Their eyes tracked us as we passed, curious but unbothered. We felt the weight of their ancient indifference like a stone wall.

**Crossing the Glacier**
The ice beneath our feet sang with a thin, high note. Soma led, her staff glowing faintly against the white expanse. The cold was wrong — not winter cold, but something older.
```

Rules:
- Chronological order
- Dialogue: full exchanges with attribution (`Speaker: "words"`)
- Copy verbatim; mark paraphrases as `(paraphrase)`
- Include action beats: combat, challenges, struggles
- Include environmental moments: travel, atmosphere
- No mechanical detail (rolls, HP, spell slots)
- Optional `tokens: N` header to override token estimate for UI warning

### voice/[character]_voice.md

**Written by:** Players manually
**Read by:** `session_doc/sd_narrate.py` (injected into that character's narrator prompt only)

```markdown
# Vukradin's Voice

Vukradin is a principled warrior with a dry, measured tone. He speaks in complete sentences
and uses formal address. He is uncomfortable with moral ambiguity and prefers direct action.

## Speech patterns
- Formal address ("You are...") not casual ("You're...")
- Long, considered sentences
- Questions posed as restatements ("So you're saying...")

## Key relationships
- Soma: respects her wildness but worries
- Valphine: frustrated by her moral flexibility

## Emotional notes
- Determined when facing evil
- Sardonic when frustrated
```

---

## Tracking File (tracking.txt)

**Written by:** Manual or `pipelines/grounding/make_tracking.py`
**Read by:** `pipelines/grounding/campaign_state.py --track-file`

```
# Locations
Whispering Woods resolution
Gnomengarde dungeon completion

# NPCs
Cryovain encounter and outcome
Grundar alliance status

# Factions
Kraken Society first contact
```

Rules:
- One item per line; `#` lines are section comments (ignored by parser)
- Blank lines ignored
- Items phrased neutrally (subject + event type, no outcome)
- Missing items flagged as `NOT FOUND IN SUMMARIES` in campaign_state.md

---

## pipelines/session_prep/prep.py User Prompt (Assembled Document)

Built by `assemble_docs()` and passed as the user turn to Claude:

```markdown
## campaign_state

[campaign_state.md content]

---

## world_state

[world_state.md content]

---

## mechanics

[mechanics.md content]

---

## planning

[planning.md content]

---

## Session Beat

[beat text]
```

---

## Log Files

**Pattern:** `YYYY-MM-DD_HHMMSS_[stem].md`
**Location:** `log_dir` from config
**Written by:** `campaignlib.save_log()`

```markdown
# Session Log — 2026-03-18 14:25

---

## System Prompt

[content]

---

## User Prompt

[content]

---

## Response

[content]
```

Stem values: `session_arc` (full session), `session` (single beat), `distill`, `campaign_state`, `planning`, `party`
