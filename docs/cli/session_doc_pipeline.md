# session_doc.py — narration pipeline

Generates a post-session narrative document from a session recap, VTT roleplay extractions, and per-character voice files.

## Five-pass pipeline

1. **Consistency check** — compares the recap against campaign context documents
2. **Enhance structured sections** — rewrites Memorable Moments, appends Consistency Notes, preserves Scenes/NPCs/Locations/Items/Spells
3. **Narrative plan** — assigns each character a portion of the session to narrate
4. **Character extraction** (silent, per character/scene) — pulls that character's moments from their assigned chunk
5. **Narration** (per character/scene) — writes first-person prose from the extracted moments

Two narration modes:
- **Chunk mode** (default): each character covers a chronological slice of the session
- **Scene mode** (`--by-scene`): each scene is narrated by one rotating character — matches the handcrafted campaign summary style

```bash
# Full run, chunk mode
python session_doc.py session-mar \
    --roleplay-extract-dir vtt_roleplay_extractions/ \
    --summary-extract-dir  vtt_extractions/ \
    --context docs/campaign_state.md docs/world_state.md \
    --party partyfile.md \
    --characters "Vukradin, Valphine, Soma, Brewbarry" \
    --voice-dir voice/ \
    --examples examples/ \
    --output session-doc.md

# Scene-by-scene mode
python session_doc.py session-mar ... --by-scene --output session-doc.md

# Inspect plan only (no narration)
python session_doc.py session-mar ... --plan-only

# Dry run: print pass 4 prompts without calling API
python session_doc.py session-mar ... --by-scene --dry-run --output /dev/null

# Use a hand-edited plan (skip pass 3)
python session_doc.py session-mar ... --plan-file my_plan.md --output session-doc.md

# Single character only (skips passes 1–2, useful for voice tweaking)
python session_doc.py session-mar ... --narrator Brewbarry --output brewbarry.md
```

## Iterative workflow (review extractions before narrating)

```bash
# Step 1: run passes 1–4, save per-scene extractions, stop before narration
python session_doc.py session-mar ... --by-scene \
    --extract-dir scene_extractions/ --extract-only --output /dev/null

# Step 2: review and edit files in scene_extractions/
#   Files are named: 01_vukradin_the_stone_giants.md, 02_soma_the_glacier.md, etc.
#   Add missing dialogue, remove hallucinated lines, adjust emphasis.

# Step 3: narrate from the edited extractions (skips passes 1–4)
python session_doc.py session-mar ... --by-scene \
    --from-extractions scene_extractions/ --output session-doc.md
#   plan.md is auto-loaded from scene_extractions/ — no --plan-file needed.

# Re-run a single scene after editing its extraction file
python session_doc.py session-mar ... --by-scene \
    --from-extractions scene_extractions/ --scene 7 --output scene7.md

# Re-run multiple scenes
    --scene 3 7
```

## Four-stage recap → narration pipeline (recommended)

Replaces the older single-shot `session_doc.py` flow when you want a human checkpoint after each LLM pass. The structural spec is the human-authored `gm-assist.md`; every stage that follows enriches or renders inside that spec.

```
gm-assist.md (structure, human-authored)
    │
    ▼  Stage 1 — enhance_summary.py
session-summary.md  ◄── HUMAN REVIEW (edit freely)
    │
    ▼  Stage 2 — scene_extract.py --summary
scene_extractions/NN_<slug>.md  ◄── HUMAN REVIEW
    │
    ▼  Stage 3 — session_doc.py --per-scene-output
narration/session_doc_scene_NN_<slug>.md  ◄── HUMAN REVIEW
    │
    ▼  Stage 4 — assemble.py
session_doc.md
```

```bash
SESS=summaries/20260414

# Stage 1 — enrich gm-assist with VTT detail (single cached call)
python enhance_summary.py "$SESS"/*.vtt \
    --gmassist  "$SESS/gm-assist.md" \
    --output    "$SESS/session-summary.md"
# REVIEW & EDIT $SESS/session-summary.md before continuing.

# Stage 2 — per-scene verbatim quote extraction
python scene_extract.py "$SESS"/*.vtt \
    --summary    "$SESS/session-summary.md" \
    --output-dir "$SESS/scene_extractions/"
# REVIEW & EDIT scene_extractions/NN_*.md (drop bad quotes, add missing).

# Stage 3 — per-scene narration to disk (no final assembly)
python session_doc.py "$SESS/session-summary.md" \
    --scene-extractions "$SESS/scene_extractions/" \
    --voice-dir voice/ \
    --characters "Vukradin, Valphine, Soma, Brewbarry" \
    --per-scene-output "$SESS/narration/"
# REVIEW & EDIT narration/session_doc_scene_NN_*.md (one narrator per file).

# Re-narrate a single scene after editing its quotes
python session_doc.py "$SESS/session-summary.md" \
    --scene-extractions "$SESS/scene_extractions/" \
    --voice-dir voice/ \
    --characters "Vukradin, Valphine, Soma, Brewbarry" \
    --per-scene-output "$SESS/narration/" \
    --scene 3

# Stage 4 — combine per-scene narration into one document
python assemble.py "$SESS/narration/" \
    --output "$SESS/session_doc.md" \
    --title "Chapter 37 — A Gem of a Problem"
```

Why four stages: the global rule is "LLM extracts → human reviews and imposes structure → LLM renders inside that structure." Each stage is the LLM doing one thing the human can verify before the next call inherits its output. Per-scene narration files mean a single bad voice take only requires re-running that scene, not the whole session.

### What "review" means at the Stage 2 / scene-extraction checkpoint

Each `scene_extractions/NN_<slug>.md` has two sections, parsed by
`_split_scene_body` (`session_doc.py:430`):

1. `## Scene summary (from gm-assist, verbatim)` — the structural skeleton
   for Pass 5.
2. `## Verbatim moments` — the VTT-derived quotes / action beats that Pass
   5 narrates over.

Pass 5's prompt explicitly tells the model not to reorder events: *"The
scene scope defines the authoritative event order — do not reorder, skip,
or reorganise events"* (`session_doc.py:275-276`). So Pass 5 is a
**renderer over two pre-anchored inputs**, not a rearranger.

Practical implication for the human review step:

- **Reading through and confirming the moments are in a sane order is the
  checkpoint.** If the order already reads right, you do not need to edit
  anything. The VTT is timestamped, so the extracted moments are already
  roughly chronological; the LLM follows the order it is given.
- **Edits are only required when something is actually wrong.** Examples:
  an interleaved exchange that should be tightened, a moment that is out
  of order relative to the scene's arc, a stray line that belongs in a
  different scene, a hallucinated quote, a missing beat the GM remembers
  but the VTT garbled.
- A "no edits needed" review pass is a valid outcome. It is not a sign
  you skipped the checkpoint — it is the checkpoint succeeding.

### Batch mode (`--batch`) — 50% off list price

Stages 1 and 2 both accept `--batch`, which routes the call(s) through Anthropic's Message Batches API. Pricing is half list, prompt caching still applies (so Stage 2's per-scene cache hits compound on top of the discount), and results typically return in minutes — 24 h SLA worst case. The tradeoff is no live token streaming.

```bash
# Stage 1 — single batched call (50% off; blocks, polls, writes output)
python enhance_summary.py "$SESS"/*.vtt \
    --gmassist "$SESS/gm-assist.md" --output "$SESS/session-summary.md" \
    --batch

# Stage 2 — N scenes submitted as one batch (50% off + cache hits across scenes)
python scene_extract.py "$SESS"/*.vtt \
    --summary "$SESS/session-summary.md" \
    --output-dir "$SESS/scene_extractions/" \
    --batch
```

Detach mode (fire-and-forget, e.g. overnight):

```bash
# Submit, write a sidecar, exit.
python enhance_summary.py ... --batch --submit-only
#   → writes <output>.batch.json next to the output path
python scene_extract.py  ... --batch --submit-only
#   → writes <output-dir>/.batch.json

# Later — retrieve from the sidecar.
python enhance_summary.py --output "$SESS/session-summary.md" --batch --collect
python scene_extract.py  --output-dir "$SESS/scene_extractions/" --batch --collect
```

Resume semantics carry over: if some scene files already exist on disk when `scene_extract.py --batch` runs, only the missing ones are submitted. Failed scenes leave the sidecar in place so a re-run can resubmit just the failures.

The Web UI Scene Editor exposes the same toggle as a `Batch` checkbox in the Stage 1 / Stage 2 toolbar (persisted as `sd_batch` in `ui_config.yaml`). The poll-progress lines stream over the existing SSE endpoint, so the UI needs no other changes.

## All flags

| Flag | Default | Description |
|---|---|---|
| `--roleplay-extract-dir` | required | VTT roleplay extractions (quoted dialogue and character moments) |
| `--summary-extract-dir` | — | VTT session extractions (action detail, events, environment) |
| `--context` | — | Campaign context files for pass 1 consistency check |
| `--party` | — | `party.md` — backstory, personality, relationships |
| `--characters` | — | Comma-separated narrator roster |
| `--voice-dir` | — | Directory of `{name}_voice.md` files written by players |
| `--examples` | — | Directory of handcrafted `.md` files as style references (all `*.md` in dir are loaded) |
| `--session-name` | recap filename | Document title |
| `--by-scene` | off | Scene-by-scene narration mode |
| `--plan-file` | — | Supply a hand-written plan; skip pass 3 |
| `--narrator NAME` | — | Single character only; skips passes 1–2 |
| `--scene N [M …]` | — | Run only the specified scene number(s) from the plan |
| `--extract-dir DIR` | — | Save pass-4 extractions to this directory (one file per scene, plus `plan.md`) |
| `--extract-only` | off | Stop after pass 4; don't narrate |
| `--from-extractions DIR` | — | Skip passes 1–4; load saved extractions and narrate only |
| `--plan-only` | off | Print the plan and exit |
| `--dry-run` | off | Print pass 4 prompts without calling the API |
| `--verbose` | off | Print all prompts before each API call |
| `--model` | `claude-sonnet-4-6` | Claude model (64K output cap required for long narrations) |
| `--fast` | off | Use Haiku (~4× cheaper, faster, slightly lower quality) |
| `--no-log` | off | Skip saving the log file |

## Voice files

Per-character voice files live in `--voice-dir` (e.g. `voice/vukradin_voice.md`). Each file is injected only into that character's narration pass. Players write their own; see `PLAYER_VOICE_GUIDE.md` for the format.

## Dialogue handling

- **Chunk mode**: strong mandate — "THE DIALOGUE IS THE STORY". Full sessions reliably have dialogue.
- **Scene mode**: conditional — "USE DIALOGUE IF PRESENT". If a scene had no dialogue (wordless combat, environmental crossing), the model narrates from action beats and environment only. It does not invent dialogue.

## Recap context (Pass 4)

Pass 4 (per-scene character extraction) includes the GMassistant recap's `## Summary` and `## Memorable Moments` sections alongside the scene scope and roleplay extractions. This ensures narrative detail and character backstory beats (e.g. reflections, backstory triggers) that only appear in the recap — not in VTT dialogue — are available to the extraction model.

## Player name mapping

VTT roleplay extractions reference players by real name (e.g. "David (Vukradin)"), but scene scopes reference characters by name only. `session_doc.py` bridges this by parsing player names from `party.md`. The expected format in party.md is:

```
## Soma
**Tortle Druid 5, Player: Wade**
```

`extract_character_roster()` parses this into roster lines like `- Soma (Wade): Tortle Druid 5`, which are injected into Pass 4 extraction prompts so the model can match VTT player names to characters.

If a player is absent and someone else plays their character, update `party.md` temporarily (e.g. `Player: Wade/Kostadis`).

## Token scaling

Pass 4 extraction output tokens scale dynamically with input size: `min(8192, max(1500, len(prompt) // 4))`. This prevents truncation on dense scenes while keeping short scenes efficient.

The default `narrate_tokens` is 12000 for all modes (scene and chunk). Scene-mode narrations routinely need 3000–6000 tokens for dialogue-heavy scenes. The `--narrate-tokens` flag and `tokens:` extraction file header still override this.

## VTT transcript → session summary (`vtt_summary.py`)

Converts a Zoom `.vtt` transcript into a structured session summary using the same two-pass extract → synthesize pipeline as `distill.py`.

```bash
python vtt_summary.py session.vtt --output docs/summaries/session_12.md
python vtt_summary.py session.vtt -o session_12.md --date "2026-03-15" --session-name "Session 12 — Icespire Hold"
python vtt_summary.py --synthesize-only --extract-dir vtt_extractions/ -o out.md
```

Output is a `# Session Name` markdown document suitable for appending to your summaries file and feeding into `campaign_state.py` or `distill.py`.

### Reference summaries (GMassistant anchor)

The `--reference-summaries` flag passes a pre-existing session summary (e.g. a GMassistant recap) to the extraction and synthesis passes. This is the recommended workflow when a GMassistant recap is available.

```bash
python vtt_summary.py session.vtt \
    --output summaries/20260318/session-summary.md \
    --reference-summaries summaries/20260318/gm-assist.md \
    --context docs/campaign_state.md docs/world_state.md docs/party.md
```

**Architecture**: the GMassistant recap is treated as the authoritative account of what happened — it is generated from the same VTT transcript, so every scene it describes has corresponding dialogue in the transcript. The extraction passes are anchored on it:

1. **Primary**: find verbatim dialogue for every scene and character moment the reference describes
2. **Bonus**: catch any significant exchanges the reference missed (side conversations, throwaway jokes that turned into moments)

Without `--reference-summaries`, the extraction falls back to an unguided scan — less precise because each chunk is processed independently with no knowledge of what matters in the full session.

The reference summary also feeds into the synthesis pass for cross-referencing, ensuring the final summary doesn't miss events that appear in the GMassistant recap.
