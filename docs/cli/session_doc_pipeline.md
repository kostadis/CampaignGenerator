# Post-session narration pipeline

(`sd_consistency` + `sd_plan` + `sd_narrate` — the Phase-5 split of the old `session_doc.py` monolith, now living in `session_doc/`.)

Generates per-scene first-person narration from a session recap, the human-verified `scene_extractions/` directory (Stage 2 output), per-character voice files, and optional style examples. Writes one file per scene; `assemble` (Stage 4) combines them.

## Where it sits in the post-session flow

```
gm-assist.md (structure, human-authored)
    │
    ▼  Stage 1 — enhance_summary
session-summary.md  ◄── sd_verify_quotes ──► quote_report.md
    │                   HUMAN REVIEW (edit freely)
    ▼  Stage 2 — scene_extract --summary
scene_extractions/NN_<slug>.md  ◄── sd_verify_quotes ──► quote_report.md
    │                               HUMAN REVIEW
    ▼  Stage 3 — sd_consistency + sd_plan + sd_narrate  ← these scripts
narration/session_doc_scene_NN_<slug>.md  ◄── HUMAN REVIEW
    │
    ▼  Stage 4 — assemble
session_doc.md
```

The "LLM extracts → human reviews and imposes structure → LLM renders inside that structure" rule (`~/.claude/CLAUDE.md`) drives the boundaries: each stage is the LLM doing one thing the human can verify before the next call inherits its output. Per-scene narration files mean a single bad voice take only requires re-running that scene.

## Batched scene extraction — `scene_extract --batch-scenes`

### What it is

Stage 2 (`scene_extract`) normally runs a loop: the full VTT is cached once as
a system-prompt prefix, then the script issues **one call per scene**, each
carrying that scene's name and gm-assist bullets. `--batch-scenes` replaces
the loop with one exchange — the transcript is assembled once and every
pending scene is requested together — or, when one exchange would not fit
the output ceiling, the fewest exchanges that will (see "The grouping rule"
below). Either way the on-disk result is unchanged: one
`scene_extractions/NN_<slug>.md` per scene, same front-matter, same `##
Scene summary` / `## Verbatim moments` structure as the per-scene loop
produces today.

### Why the subscription backend needs it and the metered one does not

On the `anthropic` backend, the repeated transcript is already close to
free after the first scene — it is marked as a cached prefix, so scenes
2..N read it at cache-hit rates, and `--batch` (Message Batches) compounds
that with a further 50% discount. None of that applies on `claude-code`
(the subscription path): each scene is a separate `claude -p` subprocess
with a fresh session, the cache markers are flattened to plain text on the
way in, and Message Batches submission isn't available there at all. So on
the subscription, the per-scene loop pays for the full transcript, from
scratch, once per scene.

Measured on the calibration session (`~/Phandalin/Phandalin/summaries/20260811`,
8 scenes; research D14): the per-scene loop transmitted **~158,700** input
tokens across 8 calls; `--batch-scenes` transmitted **~19,800** across 1 —
an **87.5%** reduction in tokens sent over the wire for the same extraction.
That percentage is the measured part — the run report counts transmissions, and
the payload is identical across them. The absolute token figures are estimates:
the subscription backend reports no usage, so they are character counts over the
transcript's ~7.4 chars/token.

### `--batch` and `--batch-scenes` are different features, and are refused together

| | `--batch` | `--batch-scenes` |
|---|---|---|
| What | Submits N per-scene requests as one Message Batches job | Collapses N scenes into one exchange (or a few) |
| Calls | N requests, one job | 1, or the fewest groups that fit |
| Backend | `anthropic` only | Any — the point is the subscription |
| Buys | 50% list-price discount | Removes transcript repetition |

Passing both is **refused, not silently composed** — `scene_extract` exits 1
before any input is even read. The combination looks appealing (why not
both discounts?) but buys nothing: `--batch` only runs on the metered
backend, and on that backend prompt caching already makes the repeated
transcript cheap. The saving `--batch-scenes` exists for doesn't exist on
the path `--batch` runs on, so implementing the composition would spend
engineering effort making a no-op flag combination "work" instead of just
saying so. See `specs/013-batched-scene-extraction/contracts/cli-surface.md`
§1 for the full flag reference.

### Two ceilings, not one

`--max-tokens` (default `8192`) is the **per-scene** output budget for the
per-scene loop — unchanged, and it keeps governing that loop whether or not
`--batch-scenes` is set. `--batch-max-tokens` (default `32000`) is a
different knob: the **per-group** ceiling a batched run packs scenes
against. Raising `--max-tokens` does nothing for a batched run, and raising
`--batch-max-tokens` does nothing for the per-scene loop — they are not
interchangeable, and the CLI accepts `--batch-max-tokens` even without
`--batch-scenes` (it's simply inert there, with a note).

### The grouping rule

A batched run projects each pending scene's output size from its
gm-assist summary-bullet size, then packs scenes into the fewest
contiguous groups whose projected total fits under `--batch-max-tokens`.
One call when the whole request fits; the fewest calls that fit otherwise.

Already-extracted scenes are filtered out **before** projection and
grouping — not sent and discarded afterward — so a partial session
projects and requests only what's actually missing. A session with 5 of 8
scenes already on disk projects and groups over the remaining 3, not the
full 8; with every scene already extracted and `--force` not set, the run
makes no call at all.

The projection is an estimate made before any response exists, and it only
has to decide *how many groups to try* — it doesn't have to be exact.
Measured against the calibration session: projected **23,336** output
tokens against **23,684** actually produced — **−1.5%** (research D14).

### Exit code 3 — the partial state

If a response ends before covering every requested scene — the model runs
out of room, the process dies, a group's response is truncated mid-scene —
the scenes that arrived complete are written, and the run exits **3**,
naming every scene that didn't come back. This is a **resumable state, not
a failure**: the files that were written are valid, and re-running without
`--force` requests only the still-missing scenes.

Exit **4** is a different failure: a group's response could not be
reconciled against the scenes that were requested of it (a mismatched
scene, an unparseable split). **Nothing from that group** is written — but
other groups in the same run are unaffected, and any scenes they wrote
stay on disk. See `contracts/cli-surface.md` §4 for the full exit-code
table.

### Fidelity — measured, not assumed

Batching changes what the model sees when it writes a quote: instead of
one scene's bullets with a full output budget to itself, it sees every
scene boundary in the group at once and rations one budget across all of
them. That's exactly the condition under which a quote could get
paraphrased or dropped, so fidelity was measured rather than assumed to
hold — the same session, extracted both ways, checked with the existing
deterministic quote verifier (`sd_verify_quotes`).

Final measurement (research D14, after two prompt fixes — see that section
for what regressed and was corrected along the way): quotes verified exact
went **937 → 948**, **100% exact-verbatim in both runs** — batching did not
trade quote accuracy for fewer transmissions. Extracted moments went
**654 → 835**. The worst single scene's moment count changed by **−17%**,
inside the −20% bound the gate was measured against. Read
`specs/013-batched-scene-extraction/research.md` D14 for the method, the
two intermediate failures the gate caught and how they were fixed, and the
one pre-existing (non-batching) defect it surfaced in the per-scene path.

### `sd_agent --stage scenes`

The orchestrator forwards the mode too, and picks it from the backend when you
do not say:

```bash
sd_agent --stage scenes --session-dir DIR --backend claude-code    # batched
sd_agent --stage scenes --session-dir DIR --backend anthropic      # per-scene
sd_agent --stage scenes --session-dir DIR --backend claude-code --no-batch-scenes
```

`sd_agent` normally forwards an enumerated flag list rather than inferring
anything — implicit forwarding once dropped `--similarity` silently for a month
(#197). This flag is the one exception, and it is safe only because `sd_agent`
prints every resolved command before running it, so the mode it chose is
visible in the output rather than hidden in a subprocess. The flag is always
rendered explicitly, never omitted.

It reaches the `scene_extract` step only. `enhance_summary` has no such flag,
so `--stage summary` never sees it.

### Turning it on

The CLI default is off — an unadorned `scene_extract` invocation behaves
exactly as it does today. The Session Doc Editor's Re-Extract Quotes
control exposes batched mode as its own toggle, pre-selected when the
resolved backend is the subscription and left off on the metered API,
always overridable by the GM before the run.

## Quote verification — `sd_verify_quotes`

Stages 1 and 2 both instruct the model to quote dialogue verbatim. `sd_verify_quotes` is what checks that it did. It is **deterministic and free** — a quote is a span of the VTT or it is not, so no model is called and no token is spent.

```bash
SESS=summaries/20260623

sd_verify_quotes --vtt "$SESS"/*.transcript.vtt \
    --summary            "$SESS/session-summary.md" \
    --scene-extractions  "$SESS/scene_extractions_new" \
    --out                "$SESS/narration/quote_report.md"
```

Exit code `0` = no unverified quotes, `1` = findings, `2` = could not run (missing transcript or artifact). A finding is not an error.

### Three verdicts, not two

Measured over 522 real quotes, **only 65% are exact verbatim** — and that was a Claude-generated session. Most of the rest are *disfluency edits*: the extraction says `"I do cross promotions."` where the tape says `"I do, like, cross promotions."` A binary verbatim check would report ~180 findings per session with the overwhelming majority benign, which teaches you to ignore the report.

| verdict | meaning | a problem? |
|---|---|---|
| `verified` | exact, or differing only by whitespace/reflow | no |
| `near` | not verbatim, but traceable to a transcript line — usually a filler word removed | no, informational |
| `unverified` | no plausible source line | **yes — review these** |
| `unscored` | under 4 tokens; matches anything, so neither a high nor low score means anything | no |
| `exempt` | `(paraphrase)`, `(truncated)`, `[inaudible]` — the sanctioned markers | no |

Every finding carries the **nearest transcript line**, so a reflow is distinguishable from a fabrication at a glance. Quotes containing `...` are additionally flagged **Likely stitched** — two separate utterances joined into one, which is fixed by splitting rather than rewording.

### What it does not check

Stated in every report, because silent non-coverage reads exactly like a pass:

- **Inline `"…"` in prose** — not reliably dialogue (`the "liberators of the Ordning"` is a label). Only `> "…"` blockquotes are verified.
- **Speaker attribution** — it answers *were these words said*, not *did this person say them*.
- **`## Scene summary` sections** — human-authored gm-assist content, not model output.
- Multi-line blockquote quotes, if any appear (none exist in the measured corpus); the count is reported.

### Nothing is auto-corrected

The only write to a checked file is an additive `<!-- cg:unverified -->` marker on an unverified quote's line, applied idempotently — re-running leaves the file byte-identical. Quote text is never altered. `--report-only` suppresses even that. Repair is a human decision made in Claude; the autonomous-repair alternative is what removed spells from narration in issue #151.

### `near` means *an edit*, not *a safe edit*

Similarity cannot tell a harmless edit from a damaging one, because both are edits of the same size. Measured on a real DeepSeek run:

| score | quote | transcript | verdict |
|---|---|---|---|
| 0.92 | "**My kind** has been spreading violence…" | "**Mankind** has been spreading violence…" | `near` — but the meaning changed |
| 0.94 | "No, I have my soul is for rent." | "No, I, I have, my soul is for rent." | `near` — harmless |

The corrupting edit scored *lower* than the harmless one, and no threshold separates them. **Skim the `near` list for changed words, not for low scores.**

### Which `.vtt` — it is not a tie-break

**Use the same `.vtt` the artifact was generated from.** A session may carry both `*.transcript.vtt` and `*.transcript.cleaned.vtt`; where they differ it is on proper nouns — exactly where false findings cluster. On session 20260623 the two differ on **72 cue lines** (`Blueberry`→`Brewbarry`, `Cryovane`→`Cryovain`, …), and the same 522 quotes score:

| VTT | verified | near | unverified |
|---|---|---|---|
| `*.transcript.vtt` (raw ASR) | 339 (65%) | 139 (27%) | **39** |
| `*.transcript.cleaned.vtt` | 374 (72%) | 113 (22%) | **31** |

A 26% swing in the finding count from the transcript choice alone. Any `unverified` number is meaningless without naming the VTT behind it. When more than one is present `sd_agent` takes the first alphabetically (`…cleaned.vtt`) and prints which one it used — pass `--vtt` to choose deliberately.

## One stage at a time — `sd_agent`

`sd_agent` runs a stage's generation **and** that stage's checks as one action, then stops:

```
sd_agent --stage summary  →  enhance_summary  →  sd_verify_quotes  →  sd_consistency  →  STOP
sd_agent --stage scenes   →  scene_extract    →  sd_verify_quotes                     →  STOP
```

**It stops at the stage boundary on purpose.** The Stage 1 → Stage 2 human review is a checkpoint; an orchestrator that ran straight through would delete it. There is no `--stage all`.

```bash
SESS=summaries/20260623

sd_agent --stage summary --session-dir "$SESS" \
    --context "$SESS/../../docs/campaign_state.md" \
    --backend dgx --model deepseek-ai/DeepSeek-V4-Flash-0731

# after you have reviewed session-summary.md:
sd_agent --stage scenes --session-dir "$SESS" \
    --dossier-dir docs/npcs --gm-player Kostadis \
    --backend dgx --model deepseek-ai/DeepSeek-V4-Flash-0731
```

Every resolved command is printed before it runs, so the hop is visible rather than implicit. Backend flags reach **generation only** — verification calls no model. Exit `0` clean, `1` findings, `2` a step could not run.

Two things it will tell you rather than do silently:

- **`--context` omitted** ⇒ the consistency check is skipped and the run says so. There is nothing to compare a recap against without grounding docs.
- **`--dossier-dir` omitted on `--stage scenes`** ⇒ it checks whether `scene_extract` can auto-discover `docs/entity_registry.yaml` from the CWD. **If it can, you need no flag** — a registry *replaces* the dossier scan outright, so the roster already reaches the model (run from the campaign root and this is the normal case). **If it can't**, the run says so loudly: since `6e00f54` the roster is the *only* channel for canonical spellings (the VTT is deliberately never rewritten — see `docs/rlm/dossier_aliases.md`), so a run without it produces name-shaped quote findings that look like fabrication but are really missing grounding.

Use `--skip-generate` to re-check an artifact without re-spending tokens, and `--dry-run` to print the commands and exit.

## Passes

Inside the three `session_doc/sd_*.py` tools:

| Pass | Status | System prompt | Purpose |
|---|---|---|---|
| 1 | optional (runs iff `--context`) | `CONSISTENCY_SYSTEM` | Compare recap against campaign context; surface factual errors |
| 2 | skipped (`--enhanced-sections` supplies it) | — | Memorable Moments / NPCs / Scenes block (built upstream, e.g. by the Editor) |
| 3 | always runs (unless `--plan-file`) | `PLAN_SYSTEM` | Assign one narrator per scene from the `scene_extractions/` checklist |
| 4 | skipped (scene-extraction file supplies it) | — | Character moments — `## Scene summary` + `## Verbatim moments` already in each `NN_*.md` |
| 5 | runs per scene | `NARRATE_SYSTEM_BASE` | First-person memoir rendered against the scene's summary + moments |

Pass 5 user-prompt assembly order (in `build_narrate_prompt()`): narrator + focus → character roster → party document → scene scope ("what happened") → voice notes → handoff sentence → narrator's extracted moments.

## Typical invocations

All three CLIs accept the shared `--batch` flag (Message Batches, 50% cost —
see `docs/cli/cli_tools.md` § Shared flag). `sd_consistency`/`sd_plan` submit
their single call as a one-item batch; `sd_narrate` degrades to sequential
one-item batches because each scene's narration hands off into the next
scene's prompt — grouping would break the chain.


```bash
SESS=summaries/20260414

# Full Stage 3 run
# Pass 1 — consistency check (writes consistency_report.md)
sd_consistency "$SESS/session-summary.md" \
    --context docs/campaign_state.md docs/world_state.md docs/party.md \
    --out     "$SESS/narration/consistency_report.md"

# Pass 3 — narrative plan (writes plan.md)
sd_plan \
    --scene-extractions "$SESS/scene_extractions/" \
    --characters        "Vukradin, Valphine, Soma, Brewbarry" \
    --party             docs/party.md \
    --session-summary   "$SESS/session-summary.md" \
    --out               "$SESS/narration/plan.md"

# Pass 5 — per-scene narration (one file per scene)
sd_narrate "$SESS/session-summary.md" \
    --plan              "$SESS/narration/plan.md" \
    --scene-extractions "$SESS/scene_extractions/" \
    --party             docs/party.md \
    --party-config      config/party.yaml \
    --characters        "Vukradin, Valphine, Soma, Brewbarry" \
    --voice-dir         voice/ \
    --examples          examples/ \
    --per-scene-output  "$SESS/narration/"
# REVIEW & EDIT narration/session_doc_scene_NN_*.md (one narrator per file).

# Re-narrate a single scene after editing its quote file
sd_narrate "$SESS/session-summary.md" \
    --plan              "$SESS/narration/plan.md" \
    --scene-extractions "$SESS/scene_extractions/" \
    --per-scene-output  "$SESS/narration/" \
    --scene 3

# Inspect the plan only (no narration)
sd_plan \
    --scene-extractions "$SESS/scene_extractions/" \
    --characters        "Vukradin, Valphine, Soma, Brewbarry" \
    --party             docs/party.md \
    --out               "$SESS/narration/plan.md"

# Single character (filters the plan to one narrator; still per-scene output)
sd_narrate "$SESS/session-summary.md" \
    --plan              "$SESS/narration/plan.md" \
    --scene-extractions "$SESS/scene_extractions/" \
    --per-scene-output  "$SESS/narration/" \
    --narrator Brewbarry
```

Stage 4 — combine per-scene narration into one document:

```bash
assemble "$SESS/narration/" \
    --output "$SESS/session_doc.md" \
    --title  "Chapter 37 — A Gem of a Problem"
```

## What "review" means at the Stage 2 / scene-extraction checkpoint

Each `scene_extractions/NN_<slug>.md` has two sections, parsed by
`_split_scene_body` in `session_doc/io.py`:

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
| `--party FILE` | — | `party.md` — backstory, personality, relationships. NOT the roster: since #265 the character classes come from `--party-config`, and `--party` without it is an error |
| `--party-config FILE` | — | `config/party.yaml` — the roster, read from each character's sheet frontmatter. Required whenever `--party` is given |
| `--characters NAMES` | — | Comma-separated narrator roster (`"Vukradin, Valphine, Soma, Brewbarry"`) |
| `--voice-dir DIR` | — | Directory of per-character voice specs written by players. Filenames need not be `{name}_voice.md` — `{name}.md` and `{name}_<anything>.md` resolve too, and an ambiguous prefix is refused rather than guessed (#247). `_`-prefixed files (`_genre.md`) are shared campaign material, not specs. **A declared directory must deliver (#300):** a path that is not a directory is fatal, and once the directory holds *any* spec, every narrator in the render must resolve to one — checked before the first API call, so a miss stops the run instead of surfacing as one narrator who quietly lost their voice. A directory that exists but holds no specs yet is not an error; it renders without them, as does omitting the flag. |
| `--examples DIR` | — | Directory of style-reference `.md` files. Files whose stem matches a character's first name route to that character only; others are global. |
| `--enhanced-sections FILE` | — | Pre-built Memorable Moments / NPCs / Scenes block to inject as scene context |
| `--narrator NAME` | — | Filter the plan to one character's scenes only |
| `--plan-file FILE` | — | Supply a pre-written plan; skip Pass 3 |
| `--plan-only` | off | Run Pass 1 + Pass 3, write `plan.md`, exit |
| `--no-plan-review` | off | Skip the Pass-3 review checkpoint when `--extract-dir` is set |
| `--extract-dir DIR` | — | Save `plan.md` + `consistency_report.md` here for human review before narration |
| `--extract-only` | off | Run Pass 1 + Pass 3, save artefacts to `--extract-dir`, exit before Pass 5 |
| `--scene N [M …]` | — | Run only the listed scene number(s) from the plan (1-based) |
| `--narrate-tokens N` | 16000 | Override the Pass-5 narration token limit. Per-scene override: add `tokens: N` as the first line of the scene-extraction file. |
| `--prose-mode` | off | Strip mechanical / GM framing from narration (no rolls, HP, "the GM says…") |
| `--narration-genre-file PATH` | — | File holding the genre/register rulebook injected into Pass 5, conventionally `<campaign>/voice/_genre.md`. A one-line directive or a full document both work; anything longer than a short label gets its own delimited block. **The file is the single source of truth** — a missing path means Pass 5 runs with no register rules at all, and warns. Replaces `--narration-genre TEXT` (#276). |
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

**Solution**: scene-anchored extraction happens at Stage 2 (`scene_extract`), not inside the `sd_narrate` loop. Each `NN_*.md` already pairs `## Scene summary` with `## Verbatim moments`.

### 7. Speaker labels in extractions

VTT speaker labels often include player names in parentheses: `Thorin (Joe)`, `GM (Kostadis)`. These need normalising before they bleed into narration prose.

Normalisation is now Stage 2's responsibility (in `scene_extract`). `sd_narrate` treats `## Verbatim moments` as authoritative — it does not re-normalise.
