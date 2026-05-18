# The CampaignGenerator Pipeline: How gmassistant Drives Narration

## The Core Principle

The gmassistant document is the authoritative source of truth for what happened in a session. Everything else — VTT transcripts, voice files, verbatim player quotes — is color layered on top of that skeleton.

Without the gmassistant skeleton, the narration LLM has to reconstruct events from extracted character moments alone. Those moments are fragmentary by nature: they're the beats that made it through Pass 4's character filter. Structurally important events — an NPC's decision, a failed persuasion attempt, the exact moment a plan pivoted — may not appear in a character's extracted moments at all. The narration would miss them, or get the order wrong, or invent connective tissue that contradicts what actually happened.

With the gmassistant skeleton, the LLM knows the shape of the scene before it reads a single extracted moment. The extracted moments become what they actually are: the character's lens on events the LLM already understands.

---

## What gmassistant Produces

The gmassistant document is a structured GM recap organized by scene:

```
### The Deception Completed
#### Daz convinces Asha Vandree to ally against Ilvara by abandoning his claim to divine status.
- Daz recalls the bat familiar to his hand, uses Dancing Lights to establish presence
- Asha is skeptical: a drow cleric knows Lolth does not speak through male magic users
- Daz pivots: presents himself as a delusional wizard, not a divine herald
- Asha rolls Insight, sees through the divine claim but accepts the reframing
- Alliance formed on the premise that Daz is useful, not holy
```

Each scene entry contains:
- **Scene name** — the anchor for all downstream processing
- **One-sentence dramatic summary** — what this scene accomplished narratively
- **Bullet-point actions** — the actual sequence: decisions, NPC reactions, pivots, outcomes

This is not flavor. This is the record.

---

## The Five-Pass Pipeline

### Pass 1 — Consistency (gmassistant)
The VTT transcript is chunked and fed to Claude with the **current gmassistant document** as context. Claude identifies continuity errors, contradictions, and missing outcomes. The result is a consistency report — not a new document, but a set of corrections the GM reviews before moving on.

**gmassistant role:** reference standard. What the transcript is checked against.

### Pass 2 — Enhancement
The transcript chunks are enhanced for clarity: filler words trimmed, incomplete sentences completed, obvious transcription errors fixed. No narrative added.

**gmassistant role:** none directly. The enhanced transcript feeds into later passes.

### Pass 3 — Planning (plan.md)
Claude reads the gmassistant document and produces a scene plan: scene names, narrators, focus, and chunk ranges. This plan drives scene-level processing in Passes 4 and 5.

**gmassistant role:** the scene structure comes from here. Chunk ranges map transcript positions to named scenes.

### Pass 4 — Character Extraction
For each scene, Claude reads the enhanced transcript chunks falling within that scene's chunk range and extracts character-specific moments: dialogue, action beats, internal states. The scene name from the plan scopes which chunks are included.

**gmassistant role:** scope boundary. The scene name determines which chunks get processed for this scene.

Verbatim VTT roleplay quotes are also collected separately (via `vtt_summary.py`) and stored in the Quote Ledger. Auto-assign maps each quote to a scene by matching the quote's source chunk number to the scene's chunk range — deterministic, no guessing.

### Pass 5 — Narration
The narration LLM receives a structured prompt in this order:

1. **Narrator and focus** — who is narrating, what they're focused on
2. **Character roster** — all party members and their classes/roles
3. **Party document** — shared campaign context, relationships, current situation
4. **Scene: What Happened** ← *the gmassistant scene text, injected here*
5. **Voice notes** — the narrator's voice profile (speech patterns, thought sources, internal voice)
6. **Roleplay summary** — the player's own recap of their character's arc
7. **Handoff** — where the previous scene left the narrator emotionally
8. **Narrator's extracted moments** — verbatim quotes and character beats from Pass 4

The system prompt tells the LLM:

> *This is the GM's authoritative account of what occurred in this scene. Use it as the structural skeleton — the events, decisions, and NPC reactions that the narration must cover. The character's Roleplay Moments (below) provide verbatim quotes and character-specific beats to weave in.*

**gmassistant role:** structural skeleton. The LLM knows what happened before it reads how the character experienced it.

---

## Why the Order Matters

The prompt is deliberately ordered from general to specific:

- **Party document** establishes the world and relationships
- **Scene: What Happened** establishes what actually occurred in this scene — the authoritative sequence
- **Voice notes** establish how this character thinks and speaks
- **Extracted moments** provide the character's specific dialogue and beats to work into the skeleton

If extracted moments arrived before the scene skeleton, the LLM would be pattern-matching on fragments. With the skeleton first, the LLM has the complete event sequence and can correctly place each extracted moment within it — even moments that don't appear in the extraction at all are covered because the skeleton told the LLM they happened.

---

## The Three Sources and What Each Provides

| Source | What it provides |
|--------|-----------------|
| **gmassistant** | What happened — events, decisions, NPC reactions, outcomes, sequence |
| **Voice file** | How the narrator thinks, speaks, and filters experience |
| **VTT quotes / extracted moments** | What was actually said, verbatim, and how the character experienced specific beats |

The narration is the intersection of all three: the right events (gmassistant), in the right voice (voice file), with the right words (quotes).

---

## Prose Mode

When `--prose-mode` is active, an additional instruction block is appended to the system prompt. It translates all mechanical language — HP numbers, dice rolls, saving throw DCs, game mechanic instructions, GM framing — into narrative experience. The character doesn't "fail a DC-14 Wisdom saving throw." Something presses against their mind, cold and insistent, trying to get in.

Prose mode does not change what the narration covers (that's determined by the skeleton). It changes how the narration renders everything it covers.
