# session_doc.py — narration pipeline

Generates per-scene first-person narration from a session recap, the human-verified `scene_extractions/` directory (Stage 2 output), per-character voice files, and optional style examples. Writes one file per scene; `assemble.py` (Stage 4) combines them.

## Where it sits in the post-session flow

```
gm-assist.md (structure, human-authored)
    │
    ▼  Stage 1 — enhance_summary.py
session-summary.md  ◄── HUMAN REVIEW (edit freely)
    │
    ▼  Stage 2 — scene_extract.py --summary
scene_extractions/NN_<slug>.md  ◄── HUMAN REVIEW
    │
    ▼  Stage 3 — session_doc.py --per-scene-output     ← this script
narration/session_doc_scene_NN_<slug>.md  ◄── HUMAN REVIEW
    │
    ▼  Stage 4 — assemble.py
session_doc.md
```

The "LLM extracts → human reviews and imposes structure → LLM renders inside that structure" rule (`~/.claude/CLAUDE.md`) drives the boundaries: each stage is the LLM doing one thing the human can verify before the next call inherits its output. Per-scene narration files mean a single bad voice take only requires re-running that scene.

## Passes

Inside session_doc.py:

| Pass | Status | System prompt | Purpose |
|---|---|---|---|
| 1 | optional (runs iff `--context`) | `CONSISTENCY_SYSTEM` | Compare recap against campaign context; surface factual errors |
| 3 | always runs (unless `--plan-file`) | `PLAN_SYSTEM` | Assign one narrator per scene from the `scene_extractions/` checklist |
| 5 | runs per scene | `NARRATE_SYSTEM_BASE` | First-person memoir rendered against the scene's summary + moments |

(Pass 2 enhancement and Pass 4 character extraction are no longer run — the scene-extraction file produced by `scene_extract.py` already supplies both inputs.)

Pass 5 user-prompt assembly order (in `build_narrate_prompt()`): narrator + focus → character roster → party document → scene scope ("what happened") → voice notes → handoff sentence → narrator's extracted moments.

## Typical invocations

```bash
SESS=summaries/20260414

# Full Stage 3 run
python session_doc.py "$SESS/session-summary.md" \
    --scene-extractions "$SESS/scene_extractions/" \
    --context           docs/campaign_state.md docs/world_state.md docs/party.md \
    --party             docs/party.md \
    --characters        "Vukradin, Valphine, Soma, Brewbarry" \
    --voice-dir         voice/ \
    --examples          examples/ \
    --per-scene-output  "$SESS/narration/"
# REVIEW & EDIT narration/session_doc_scene_NN_*.md (one narrator per file).

# Re-narrate a single scene after editing its quote file
python session_doc.py "$SESS/session-summary.md" \
    --scene-extractions "$SESS/scene_extractions/" \
    --per-scene-output  "$SESS/narration/" \
    --plan-file         "$SESS/narration/plan.md" \
    --scene 3

# Inspect the plan only (no narration)
python session_doc.py "$SESS/session-summary.md" \
    --scene-extractions "$SESS/scene_extractions/" \
    --extract-dir       "$SESS/narration/" \
    --plan-only

# Single character (filters the plan to one narrator; still per-scene output)
python session_doc.py "$SESS/session-summary.md" \
    --scene-extractions "$SESS/scene_extractions/" \
    --per-scene-output  "$SESS/narration/" \
    --narrator Brewbarry
```

Stage 4 — combine per-scene narration into one document:

```bash
python assemble.py "$SESS/narration/" \
    --output "$SESS/session_doc.md" \
    --title  "Chapter 37 — A Gem of a Problem"
```

## What "review" means at the Stage 2 / scene-extraction checkpoint

Each `scene_extractions/NN_<slug>.md` has two sections, parsed by
`_split_scene_body` in `session_doc.py`:

1. `## Scene summary (from gm-assist, verbatim)` — the structural skeleton
   for Pass 5.
2. `## Verbatim moments` — the VTT-derived quotes / action beats that Pass
   5 narrates over.

Pass 5's prompt explicitly tells the model not to reorder events: *"The
scene scope defines the authoritative event order — do not reorder, skip,
or reorganise events."* So Pass 5 is a **renderer over two pre-anchored
inputs**, not a rearranger.

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

## All flags

| Flag | Default | Description |
|---|---|---|
| `recap` (positional) | required | Session recap markdown (typically `session-summary.md`) |
| `--scene-extractions DIR` | required | Stage 2 output — `NN_*.md` scene files |
| `--per-scene-output DIR` | required* | Where to write per-scene narration files. *Unless `--plan-only` or `--extract-only`. |
| `--summary-extract-dir DIR` | — | VTT session extractions (action detail, events, environmental context) — passed to Pass 3 plan prompt |
| `--session-summary FILE` | — | Synthesised VTT session summary — passed to Pass 1 and Pass 3 |
| `--context FILE [FILE …]` | — | Campaign context files for Pass 1 consistency check (typically `campaign_state.md world_state.md party.md`) |
| `--party FILE` | — | `party.md` — backstory, personality, relationships, character classes |
| `--characters NAMES` | — | Comma-separated narrator roster (`"Vukradin, Valphine, Soma, Brewbarry"`) |
| `--voice-dir DIR` | — | Directory of `{name}_voice.md` files written by players (one per character) |
| `--examples DIR` | — | Directory of style-reference `.md` files. Files whose stem matches a character's first name route to that character only; others are global. |
| `--narrator NAME` | — | Filter the plan to one character's scenes only |
| `--plan-file FILE` | — | Supply a pre-written plan; skip Pass 3 |
| `--plan-only` | off | Run Pass 1 + Pass 3, write `plan.md`, exit |
| `--no-plan-review` | off | Skip the Pass-3 review checkpoint when `--extract-dir` is set |
| `--extract-dir DIR` | — | Save `plan.md` + `consistency_report.md` here for human review before narration |
| `--extract-only` | off | Run Pass 1 + Pass 3, save artefacts to `--extract-dir`, exit before Pass 5 |
| `--scene N [M …]` | — | Run only the listed scene number(s) from the plan (1-based) |
| `--narrate-tokens N` | 16000 | Override the Pass-5 narration token limit. Per-scene override: add `tokens: N` as the first line of the scene-extraction file. |
| `--prose-mode` | off | Strip mechanical / GM framing from narration (no rolls, HP, "the GM says…") |
| `--narration-genre TEXT` | — | One-line genre/register directive injected into Pass 5 (e.g. `"First-person comic-noir fantasy memoir"`) |
| `--reflections` | off | Inject `campaign_state` and `world_state` context into Pass 5 so the narrator can draw on past events as memories. Requires `--context`. |
| `--dossier-dir DIR` | — | Per-NPC dossier files. Aliases in frontmatter are rewritten to canonical names before Pass 5; a "Known NPCs" roster seeds the prompt. |
| `--campaign-dir DIR` | `$CAMPAIGN_DIR` or recap parent | Campaign workspace root. Used to locate `docs/dossier_proposal.md`. |
| `--require-proposal` | off | Refuse to run unless the proposal has been approved (see `docs/rlm/rlm_pipeline.md`) |
| `--session-name NAME` | — | Title injected at the top of the Pass-3 plan prompt |
| `--model` | `claude-sonnet-4-6` | Claude model (64K output cap required for long narrations) |
| `--fast` | off | Use Haiku 4.5 (~4× cheaper, faster, slightly lower quality) |
| `--dgx-endpoint URL` | — | Route LLM calls to an OpenAI-compatible server (e.g. vLLM on a DGX Spark). Falls back to `DGX_ENDPOINT` env var. |
| `--dgx-model NAME` | — | Model name for the DGX endpoint (falls back to `DGX_MODEL` env var) |
| `--verbose` | off | Print full system and user prompts before each API call |

## Voice files

Per-character voice files live in `--voice-dir` (e.g. `voice/vukradin_voice.md`). Each file is injected only into that character's narration pass. Players write their own; see [`docs/player/voice_guide.md`](../player/voice_guide.md) for the format.

The `voice-critic` skill (`/voice-critic`) checks generated narration against a character's voice spec; the `voice-file` skill (`/voice-file`) scaffolds new voice files from existing narration.

## Player name mapping

VTT roleplay extractions reference players by real name (e.g. "David (Vukradin)"), but scene scopes reference characters by name only. `extract_character_roster()` parses player names from `party.md` — expected format:

```
## Soma
**Tortle Druid 5, Player: Wade**
```

The roster lines (`- Soma (Wade): Tortle Druid 5`) get injected into Pass 5 prompts so the narration prose uses character names, not player names.

If a player is absent and someone else plays their character, update `party.md` temporarily (e.g. `Player: Wade/Kostadis`).

## Design rationale

Why the pipeline looks the way it does. These are the engineering problems that drove the current shape — read this when you're tempted to "simplify" something.

### 1. Narrative bleed

Early versions passed all session extractions to every narrator. The result: the barbarian's section described things only the cleric witnessed; the druid's section referenced the bard's internal monologue. Characters "knew" things they weren't present for.

**Solution**: scene-anchored isolation.

- Pass 3 (plan) assigns one narrator per scene from the human-verified `scene_extractions/` checklist. The scene defines what that narrator covers — nothing else.
- Pass 5 receives only that scene's `## Verbatim moments` (the VTT-derived quotes) and `## Scene summary` (the gm-assist skeleton). No cross-scene contamination possible because each scene file is read in isolation.

The earlier `--by-scene` vs chunk-mode dichotomy is gone — every run is scene-anchored.

### 2. Coverage vs. redundancy

Pass 3 used to assign chunk ranges (multi-chunk overlap was possible and frequently produced redundant accounts). The current shape — one scene per narrator — sidesteps that: every scene in `scene_extractions/` becomes exactly one section in the final doc.

`--plan-only` writes `plan.md` for review before narration burns tokens. Re-running with `--plan-file plan.md` skips Pass 3 entirely.

### 3. Wrong character classes

The model kept misidentifying classes — calling the bard a paladin, for example — by inferring class from action descriptions in the VTT rather than reading `party.md`.

**Solution**: `extract_character_roster()` parses the bold class lines from `party.md` at startup (e.g. `**Human Bard 5, Player: Alice**`) and injects a compact `## Character Classes (definitive — never contradict these)` block at the top of the narration prompt, before any session content.

### 4. Style transfer

The handcrafted summaries have a distinctive voice: non-linear structure, narrator intrusion, verbatim dialogue exchanges (both sides), humour, short punchy paragraphs. Getting the model to match this from a system-prompt description alone wasn't reliable.

**Solution**: few-shot examples via `--examples`. The directory can hold both:

- Global examples (any `.md` whose stem does not match a character's first name) — shown to every narrator under a `STYLE REFERENCE` block.
- Per-character examples (e.g. `vukradin_examples.md` or `vukradin.md` when "Vukradin" is in `--characters`) — shown only to that character's narration, under a stronger `STYLE REFERENCE — {narrator}'s VOICE SPECIFICALLY` block that overrides the global examples.

The `voice-examples` and `style-examples` skills can generate these from existing campaign narration.

### 5. Handoff continuity

Between scenes, the last sentence of the previous narration is passed as a "handoff" to the next narrator's prompt, so each voice picks up naturally from where the previous one left off — without knowing the full text of the previous section.

For single-scene re-runs (`--scene N`), the handoff is empty; the contrast signal instead comes from sampling the previous narrator's per-character examples (see `extract_contrast_sample` and `PREV_VOICE_CONTRAST_BLOCK`).

### 6. VTT roleplay quote tracking

The VTT contains verbatim roleplay quotes that are higher fidelity than what the LLM summary alone produces. These need to be matched to scenes so the narration can use the actual words, not a paraphrase.

**Solution**: scene-anchored extraction happens at Stage 2 (`scene_extract.py`), not inside session_doc.py. Each `NN_*.md` already pairs `## Scene summary` with `## Verbatim moments`. The Quote Ledger ([`quote_ledger.py`](../../quote_ledger.py)) is the inspection / re-matching tool the Web UI uses to drag quotes between scenes.

### 7. Speaker labels in extractions

VTT speaker labels often include player names in parentheses: `Thorin (Joe)`, `GM (Kostadis)`. These need normalising before they bleed into narration prose.

Normalisation is now Stage 2's responsibility (in `scene_extract.py`). session_doc.py treats `## Verbatim moments` as authoritative — it does not re-normalise.
