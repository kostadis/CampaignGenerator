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
    │                │  chronological slice (chunk mode) or a scene (scene mode)
    └───────┬────────┘
            │ plan.md
    ┌───────▼────────┐
    │  Pass 4 × N    │  Per-character/scene extraction (silent)
    │                │  Each character's moments pulled from their assigned chunk/scene:
    │                │  dialogue exchanges (both sides), action beats, environment
    └───────┬────────┘
            │ scene_extractions/NN_narrator_scene.md
    ┌───────▼────────┐
    │  Pass 5 × N    │  Per-character/scene narration
    │                │  First-person prose from each character's moments,
    │                │  with style examples and handoff from previous narrator
    └───────┬────────┘
            │ narrative sections (top half of final doc)
            ▼
    narrative sections + structured sections → final document
```

---

## Two Narration Modes

### Chunk mode (default)

Each character covers a chronological slice of the session. Together all characters
cover the whole session without redundancy. Good for long sessions where no single
character is present everywhere.

Plan format:
```
## Section 1
narrator: Vukradin
chunks: 1
focus: Vukradin's stoic wonder at the stone giants

## Section 2
narrator: Soma
chunks: 1-2
focus: Soma's unease crossing the glacier
```

Dialogue mandate: **"THE DIALOGUE IS THE STORY"** — the narration pass is instructed
that dialogue exchanges are not decoration, they are the structure. Every verbatim
exchange must appear.

### Scene mode (`--by-scene`)

Each scene from the recap is narrated by one rotating character. Better for sessions
with well-defined scenes and a mix of combat, roleplay, and travel — matches the
handcrafted campaign summary style.

Plan format:
```
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

Dialogue mandate: **"USE DIALOGUE IF PRESENT"** — if a scene had no spoken dialogue
(wordless combat, environmental crossing), the model narrates from action beats and
environment only. It does not invent dialogue.

---

## Key Engineering Problems

### 1. Narrative bleed

Early versions passed all session extractions to every narrator. The result: the
barbarian's section described things only the cleric witnessed; the druid's section
referenced the bard's internal monologue. Characters "knew" things they weren't
present for.

**Solution**: Two-stage isolation.

- Pass 3 (plan) assigns each character a *chunk range* or *scene* — a chronological
  slice of the session. Characters with important moments throughout get a wider range;
  characters central to a specific scene get a narrower one.
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
  and together they cover the whole thing.

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
| 3 | `PLAN_SYSTEM` | Assign narrators to chunk/scene ranges; cover all; no redundancy |
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

## Iterative Workflow

The pipeline supports breaking the run into two phases so you can review and edit
extractions before committing to narration. This is the recommended workflow.

### Phase 1 — Extract only (passes 1–4)

```bash
python session_doc.py session-recap \
    --roleplay-extract-dir vtt_roleplay_extractions/ \
    --summary-extract-dir  vtt_extractions/ \
    --context docs/campaign_state.md docs/world_state.md \
    --party   docs/party.md \
    --characters "Vukradin, Soma, Valphine, Brewbarry" \
    --voice-dir voice/ \
    --by-scene \
    --extract-dir scene_extractions/ \
    --extract-only \
    --output /dev/null
```

This stops before narration and writes:
- `scene_extractions/plan.md` — the narrator assignments
- `scene_extractions/01_vukradin_the_stone_giants.md`, etc. — one extraction file per scene

### Phase 2 — Review, edit, narrate

Open each extraction file and:
- Add missing dialogue (the model sometimes misses quiet exchanges)
- Remove hallucinated lines
- Adjust emphasis — move key moments to the top of a block

Then narrate from the edited extractions:

```bash
python session_doc.py session-recap ... \
    --by-scene \
    --from-extractions scene_extractions/ \
    --output session-doc.md
```

`plan.md` is auto-loaded from `scene_extractions/` — no `--plan-file` needed.

### Re-running a single scene

After editing one extraction file, re-narrate just that scene:

```bash
python session_doc.py session-recap ... \
    --by-scene \
    --from-extractions scene_extractions/ \
    --scene 3 \
    --output scene3.md
```

Pass multiple scene numbers to re-run several at once: `--scene 3 7`.

---

## Session Doc UI

`session_doc_ui.py` is a Flask-based browser editor for the extract → edit → narrate
workflow. It wraps the iterative workflow above in a three-panel UI so you don't have
to edit raw markdown files and re-run the CLI manually.

### Layout

```
┌──────────────┬────────────────────────────────┬─────────────────────┐
│ Scene list   │ Extraction editor              │ VTT roleplay source │
│              │                                │                     │
│ 01 Vukradin  │ [editable textarea]            │ extract_001.md      │
│ 02 Soma      │                                │ extract_002.md      │
│ 03 Valphine  │ [Save] [Edit in Typora]        │                     │
│ ...          │ [Reload]                       │                     │
│              │                                │                     │
│ token counts │ [Narrate]                      │                     │
│ ⚠ if over    │ [streaming narration output]   │                     │
│              │                                │                     │
│              │ [Open narration in Typora]     │                     │
└──────────────┴────────────────────────────────┴─────────────────────┘
```

### Starting the UI

From the campaign workspace directory:

```bash
# Via wrapper script (recommended — reads ui_config.yaml automatically)
./ui.sh

# Or directly
python ~/CampaignGenerator/session_doc_ui.py session-recap \
    --extract-dir scene_extractions/ \
    --roleplay-extract-dir vtt_roleplay_extractions/ \
    --output-dir . \
    --party partyfile.md \
    --voice-dir voice/ \
    --narrate-tokens 4000

# Then open http://localhost:5000
```

Can also be launched from the Streamlit app (`app.py`) → Session Doc Editor → Launch Server.

### Workflow in the UI

1. Run phase 1 (extract-only) from the CLI first to populate `scene_extractions/`
2. Open `http://localhost:5000`
3. Click a scene in the left panel — extraction loads in the editor
4. Edit directly in the browser, or click **Edit in Typora** to open in Typora on Windows
5. After editing in Typora, click **Reload** to pull changes back into the browser
6. Click **Save** to write changes to disk
7. Click **Narrate** — streams the narration output live in the centre panel
   (calls `session_doc.py --from-extractions --scene N` under the hood)
8. Click **Open narration in Typora** to review the saved output file

### Token estimates

The scene list shows a token estimate for each extraction file. If the estimate
exceeds `--narrate-tokens`, a warning is shown next to the scene name.

To override the estimate for a specific scene, add a `tokens:` line at the top of
the extraction file:

```
tokens: 6000
```

### `ui_config.yaml` keys

```yaml
session_doc_session:              /path/to/session-recap
session_doc_extract_dir:          /path/to/scene_extractions
session_doc_roleplay_extract_dir: /path/to/vtt_roleplay_extractions
session_doc_summary_extract_dir:  /path/to/vtt_extractions
session_doc_output_dir:           /path/to/output
session_doc_voice_dir:            /path/to/voice
session_doc_narrate_tokens:       4000
session_doc_port:                 5000
```

### WSL / Typora

The UI runs in WSL but opens files in Typora on Windows. It uses `wslpath -w` to
convert paths and `powershell.exe -c Start-Process "path"` to launch Typora, which
handles UNC paths correctly (explorer.exe and cmd.exe do not).

---

## Running It (CLI reference)

### Full run, scene mode

```bash
python session_doc.py session-recap \
    --roleplay-extract-dir vtt_roleplay_extractions/ \
    --summary-extract-dir  vtt_extractions/ \
    --context docs/campaign_state.md docs/world_state.md \
    --party   docs/party.md \
    --characters "Vukradin, Soma, Valphine, Brewbarry" \
    --voice-dir voice/ \
    --examples examples/vukradin_arrival.md \
    --by-scene \
    --output session-doc.md
```

### Useful flags

| Flag | Effect |
|---|---|
| `--by-scene` | Scene-by-scene narration mode (recommended) |
| `--plan-only` | Print the narrator assignments and exit — verify coverage before committing |
| `--extract-dir DIR` | Save pass-4 extractions to this directory |
| `--extract-only` | Stop after pass 4; skip narration |
| `--from-extractions DIR` | Skip passes 1–4; narrate from saved (possibly edited) extractions |
| `--scene N [M …]` | Re-run only the specified scene number(s) |
| `--plan-file FILE` | Supply a hand-written plan; skip pass 3 |
| `--narrator NAME` | Single character only; skips passes 1–2 |
| `--dry-run` | Print pass-4 prompts without calling the API |
| `--verbose` | Print all prompts before each API call |
| `--fast` | Use Haiku instead of Sonnet (~4× cheaper) |
| `--no-log` | Skip saving the full log |

---

## Source

All pipeline logic lives in `session_doc.py`. Shared utilities (API calls, logging,
config loading, file I/O) are in `campaignlib.py`. The Flask UI is `session_doc_ui.py`.
All scripts live in `~/CampaignGenerator/`.
