# session_doc.py — How It Works

A five-pass LLM pipeline that takes a raw D&D session recap and produces a
narrative document combining rotating first-person character voices with
fact-checked structured sections.

---

## The Problem

After each session we have:

- A structured recap from gmassisstant.app (Scenes, NPCs, Memorable Moments, etc.)
  — accurate but dry, and occasionally wrong about who did what
- A Zoom `.vtt` transcript — hours of raw dialogue, mostly noise
- Handcrafted session summaries from earlier in the campaign — the gold standard
  for voice and style, but too slow to write every week

The goal: produce something that reads like the handcrafted summaries (each character's
distinct voice) while also being factually verified against the campaign documents.

---

## Pipeline Overview

```
recap + VTT extractions + context docs
            │
    ┌───────▼────────┐
    │  Pass 1        │  Consistency check
    │  (silent)      │  recap vs. campaign_state / world_state / party
    └───────┬────────┘
            │ consistency report
    ┌───────▼────────┐
    │  Pass 2        │  Enhance structured sections
    │                │  Memorable Moments expanded, Scenes/NPCs preserved,
    │                │  Consistency Notes appended. Summary intentionally omitted.
    └───────┬────────┘
            │ structured sections (bottom half of final doc)
    ┌───────▼────────┐
    │  Pass 3        │  Narrative plan
    │                │  Reads all extractions, assigns each character a
    │                │  chronological slice of the session (chunk range + focus)
    └───────┬────────┘
            │ plan: [{narrator, chunk_start, chunk_end, focus}, …]
    ┌───────▼────────┐
    │  Pass 4 × N    │  Per-character extraction (silent)
    │                │  Each character's moments pulled from their assigned chunks:
    │                │  dialogue exchanges (both sides), action beats, environment
    └───────┬────────┘
            │ per-character moment lists
    ┌───────▼────────┐
    │  Pass 5 × N    │  Per-character narration
    │                │  First-person prose from each character's moments,
    │                │  with style examples and handoff from previous narrator
    └───────┬────────┘
            │ narrative sections (top half of final doc)
            ▼
    narrative sections + structured sections → final document
```

---

## Key Engineering Problems

### 1. Narrative bleed

Early versions passed all session extractions to every narrator. The result: the
barbarian's section described things only the cleric witnessed; the druid's section
referenced the bard's internal monologue. Characters "knew" things they weren't
present for.

**Solution**: Two-stage isolation.

- Pass 3 (plan) assigns each character a *chunk range* — a chronological slice of the
  session. Characters with important moments throughout get a wider range; characters
  central to a specific scene get a narrower one.
- Pass 4 (extract) runs silently once per character, pulling *only that character's
  moments* from their assigned chunks. The narration pass (pass 5) then receives only
  this character-specific list — no cross-contamination possible.

### 2. Coverage vs. redundancy

Getting the chunk assignment right took several iterations:

- **Too narrow**: Plan assigned 3 of 4 characters to chunk 1 only. The entire second
  half of the session fell to one character who couldn't cover it alone. Story cut short.
- **Too broad**: We overcorrected by giving every character all chunks. Each character
  then narrated the entire session, producing four redundant full-length accounts.
- **Correct**: The plan prompt now explicitly models the intended distribution — novel
  chapter style, where each character covers a chronological *portion* of the session,
  and together they cover the whole thing. The example output in the prompt shows this:
  two characters on chunk 1, two on chunk 2.

The plan is parsed with regex into structured dicts; chunk ranges are integers, not
filenames, to avoid string-matching failures.

### 3. Wrong character classes

The model kept misidentifying character classes — calling the bard a paladin, for
example — by inferring class from action descriptions in the VTT rather than reading
`party.md`.

**Solution**: `extract_character_roster()` parses the bold class lines from `party.md`
at startup (e.g. `**Human Bard 5, Player: Alice**`) and injects a compact
`## Character Classes (definitive — never contradict these)` block at the top of both
the extraction and narration prompts, before any session content.

### 4. Style transfer

The handcrafted summaries have a distinctive voice: non-linear structure, narrator
intrusion, verbatim dialogue exchanges (both sides), humour, short punchy paragraphs.
Getting the model to match this from a system prompt description alone wasn't reliable.

**Solution**: Few-shot examples via `--examples`. Excerpts extracted from earlier
chapters of the campaign document, one per character, each covering a different scene
type:

| File | Character | Scene type |
|---|---|---|
| `bard_arrival.md` | Bard | Travel + flashback structure |
| `cleric_debate.md` | Cleric | Political comedy, sardonic observer |
| `druid_combat.md` | Druid | Combat + Wild Shape transformation |
| `barbarian_moment.md` | Barbarian | Emotional beat, simple inner voice |

These are injected into the narration system prompt under a `STYLE REFERENCE` block
with instructions to study voice, structure, and tone.

### 5. Handoff continuity

Between narrators, the last sentence of the previous section is passed as a "handoff"
to the next narrator's prompt, so each voice picks up naturally from where the previous
one left off — without knowing the full text of the previous section.

---

## Prompt Architecture

Each of the five passes uses a dedicated system prompt:

| Pass | System prompt | Key instruction |
|---|---|---|
| 1 | `CONSISTENCY_SYSTEM` | Find factual errors vs. context docs |
| 2 | `ENHANCE_SYSTEM` | Expand Memorable Moments; preserve Scenes/NPCs; omit Summary |
| 3 | `PLAN_SYSTEM` | Assign narrators to chunk ranges; cover all chunks; no redundancy |
| 4 | `CHAR_EXTRACT_SYSTEM` | Extract this character's moments only: dialogue (both sides), action, environment |
| 5 | `NARRATE_SYSTEM_BASE` | First-person prose; dialogue is the story; match style examples |

All API calls use `stream_api()` from `campaignlib.py`, which streams output to the
terminal. Pass 1 and all Pass 4 calls run silently (`silent=True`).

---

## Token Budget

| Pass | max_tokens | Why |
|---|---|---|
| 1 (consistency) | default | Short report |
| 2 (enhance) | default | Structured sections only |
| 3 (plan) | default (8096) | Plan can be long with many characters |
| 4 (extract) | 4096 | One character's moments from a chunk range |
| 5 (narrate) | 12000 | Cover all extracted moments; don't stop early |

`max_tokens` is a ceiling, not a cost driver — you pay for what's generated. Model
choice is the main cost lever: `--fast` selects Haiku (~4× cheaper, good for iteration);
default is Sonnet. A full Sonnet run costs roughly $0.25–0.40 depending on session length.

---

## Running It

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

Useful flags:

| Flag | Effect |
|---|---|
| `--plan-only` | Stop after pass 3 and print the section assignments — verify coverage before committing |
| `--fast` | Use Haiku instead of Sonnet |
| `--no-log` | Skip saving the full log |

---

## Source

`session_doc.py`, `narrative.py`, `enhance_recap.py`, `vtt_summary.py` and supporting
tools live in `~/CampaignGenerator/`. Shared utilities (API calls, logging, config
loading) are in `campaignlib.py`.
