# CLI tools reference

Per-script invocations and flags. All scripts auto-detect `config.yaml` from CWD, falling back to `<script-dir>/config/config.yaml`.

## Shared flag: `--batch` (Message Batches, 50% cost)

Every LLM-bearing CLI accepts `--batch` (registered by
`campaignlib.api.client.add_backend_args`): Claude API calls go through the
Anthropic Message Batches API at 50% token cost. The command **blocks and
polls** until the batch completes (progress on stderr; the batch id is
printed at submission so an orphaned batch can be cancelled by hand).
Anthropic backend only — combining `--batch` with `--backend dgx/openrouter/
claude-code/codex-cli` (or `CG_BACKEND`) fails fast before any work. Ctrl-C/SIGTERM
during the wait cancels the remote batch. Any failed item exits non-zero;
succeeded items' files stay on disk, so a re-run submits only what's missing.

Shape per CLI: multi-unit pipelines (`distill`, `planning`, `party`,
`campaign_state` extract fan-outs; `scene_extract`;
`query`'s map phase; `extract_facts`) group their independent calls into one
submission. Order-dependent chains (`prep`'s 5 stages, `sd_narrate`'s
handoff-threaded scenes) run as sequential one-item batches — slower, same
discount, identical outputs. Single-call CLIs submit a one-item batch.
`polish` accepts the flag but its agentic tool-use loop has no batch shape —
it prints a notice and runs live. Not related to `ensemble_batch` (local
multi-chapter dispatch). `scene_extract`/`enhance_summary` additionally keep
their detached `--batch --submit-only` / `--batch --collect` mode.

## Shared backend: `codex-cli` consistency audits

`session_doc/check_consistency.py --backend codex-cli` runs the canonical audit
through one isolated `codex exec` process using the operator's saved ChatGPT
subscription login. Install Codex and run `codex login` first. The child does
not receive `OPENAI_API_KEY` or `CODEX_API_KEY`; it runs ephemerally from a
private temporary directory with repository instructions, user configuration,
plugins/MCP, web search, subagents, executable tools, and writes disabled.

Model precedence is explicit `--model`, then `CG_CODEX_MODEL`, then the Codex
subscription default. `CG_CODEX_TIMEOUT` is a positive finite number of seconds
and defaults to `600`. A missing CLI/login, incompatible `claude-*` model,
timeout, failed process, or empty result exits nonzero without retrying another
provider or saving a successful report. `max_tokens` remains accepted by the
shared facade but Codex exposes no matching CLI output-limit flag.

This feature certifies the single-document consistency auditor and the
`consistency-check`/`staged-consistency` Codex skills. The shared backend name is
visible to other CLIs for vocabulary consistency, but other request shapes and
the web backend selector are outside this feature. `--batch` is the Anthropic
Message Batches API and is always refused with `codex-cli`.

## prep

Single-beat or session-arc encounter generation.

### Common invocations

```bash
# Single beat, interactive input
prep

# Single beat, inline
prep --beat "The party enters Icespire Hold"

# Pipeline mode (Lore Oracle → Encounter Architect → Voice Keeper)
prep --mode pipeline --beat "The party enters Icespire Hold"

# Session arc: full numbered outline, interactive entry
prep --session

# Session arc: inline outline
prep --session "1. Travel to Hold 2. Confront Carver 3. Cryovain reveal"

# Copy assembled prompt to clipboard instead of calling API
prep --clipboard --beat "..."

# Skip saving a log file
prep --no-log --beat "..."
```

### All flags

| Flag | Default | Description |
|---|---|---|
| `--beat` / `-b` | interactive | Single session beat |
| `--session` / `-s` | interactive | Numbered session outline |
| `--mode` / `-m` | `single` | `single` or `pipeline` |
| `--clipboard` / `-c` | off | Copy output instead of (or after) API call |
| `--config` | CWD `config.yaml` or `config/config.yaml` | Path to config YAML |
| `--model` | `claude-sonnet-4-20250514` | Claude model to use |
| `--no-log` | off | Skip saving log file |

### Pipeline mode

Three sequential API calls per beat:

1. **Lore Oracle** — verifies the beat against canon; returns CLEAR / FLAGS / GAPS
2. **Encounter Architect** — receives the beat + Oracle report; produces the full structured encounter document
3. **Voice Keeper** — receives the encounter document; tunes NPC dialogue and PC behavioral notes to match established voice

If the Lore Oracle response contains the word `FLAGS`, the user is prompted before continuing to Stage 2.

## campaign_state

Generates `campaign_state.md` — a grounding document that tells all planning scripts what has been completed and what is currently true. Prevents hallucination of completed content as still active.

```bash
campaign_state summaries.md --output docs/campaign_state.md

# With a tracking list to ensure specific events are never missed
campaign_state summaries.md \
    --track-file docs/tracking.txt \
    --output docs/campaign_state.md

# Re-synthesize without re-extracting (delete state_extractions/ to re-extract)
campaign_state --synthesize-only \
    --extract-dir docs/state_extractions \
    --output docs/campaign_state.md
```

The output contains: Completed Encounters & Quests, Resolved Plot Threads, NPC Current States table, Active Quests & Open Threads, Party Current Situation, and (if a tracking list was provided) a Tracked Items Status section where missing items are flagged as `NOT FOUND IN SUMMARIES`.

`campaign_state.md` is loaded first in `config.yaml` so it is the first context `prep` sees.

## make_tracking

Extracts a tracking list from an adventure module markdown. Items are phrased neutrally (subject + event type, no outcome) so `campaign_state` can determine whether each one has happened yet.

```bash
make_tracking "Dragon of Icespire Peak.md" --output docs/tracking.txt
```

Then pass the result to `campaign_state --track-file`. Review and edit the list before use — the model may include events that have not yet occurred in your campaign.

## query

Ad-hoc search tool. Scans session summaries for a specific event, NPC, or topic and synthesizes a direct answer. Useful when `campaign_state.md` is missing something and you want to verify whether it happened.

```bash
query summaries.md "Did the party clear Gnomengarde?"
query summaries.md "What happened with Grundar at Icespire Hold?"
query summaries.md "Xalvosh" --hits-only   # raw matching extracts only
query summaries.md "Kraken Society arc score" -o notes/kraken.md
```

Uses a smaller default chunk size (40k) for more precise hits. The filter pass runs silently; only the synthesis streams to the terminal.

## planning

Generates `planning.md` from NPC dossiers, threat arc score documents, and session summaries. Two modes:

```bash
# Standard: dossiers + arc scores + summaries → planning.md
planning \
    --npc grundar.md xalvosh.md \
    --arc-scores brundar_echo.md kraken_echoes.md \
    --summaries summaries.md \
    --output docs/planning.md

# Build individual per-NPC dossier files from summaries (run once, then edit)
planning \
    --summaries summaries.md \
    --build-dossiers \
    --dossier-dir docs/npcs/

# Re-synthesize without re-extracting
planning \
    --npc grundar.md xalvosh.md \
    --synthesize-only \
    --extract-dir docs/planning_extractions \
    --output docs/planning.md
```

`--build-dossiers` extracts per-NPC information from summaries into individual files (`docs/npcs/grundar_quartzvein.md`, etc.) for review and editing before the synthesize pass.

For dossier merge rules and cross-pipeline alias propagation, see `docs/dossier_aliases.md`.

## party

Generates `party.md` from character sheets, session summaries, backstories, and arc score mechanics.

**Preferred: `--party-config` YAML.** Maps each PC explicitly to their sheet, backstory, and arc score mechanic so the synthesizer can't misattribute which file belongs to which character. `arc_score: null` is a first-class "intentionally trackless" signal — the synthesizer will not invent a track for that PC or suggest creating one.

```bash
party \
    --party-config config/party.yaml \
    --summaries summaries.md \
    --context docs/campaign_state.md \
    --output docs/party.md
```

See `config/party.example.yaml` for the full schema. Every referenced file is validated at load time; missing paths fail loud.

**Legacy flat flags** still work unchanged (mutex with `--party-config`):

```bash
party \
    --character soma.md vukradin.md valphine.md \
    --summaries summaries.md \
    --arc-scores soma_arc.md vukradin_arc.md \
    --backstory soma_backstory.md valphine_backstory.md \
    --context docs/campaign_state.md \
    --output docs/party.md

# Re-synthesize without re-extracting
party \
    --character soma.md \
    --synthesize-only \
    --extract-dir docs/party_extractions \
    --output docs/party.md
```

**Output shape — candidates, not decisions.** Each non-trackless PC gets a "Candidate Arc Score Events" bullet list: session events with the verbatim trigger text quoted from the mechanic file and a proposed direction (+/-). The GM decides which candidates actually fire. The synthesizer never commits to a current value, running total, or threshold claim — adjudicating score changes is a precision decision, not a rendering one. Trackless PCs have no candidate section at all.

**Output file — draft, not in-place rewrite.** `party.md` is hand-edited downstream (session summaries and the GM add content the LLM never sees), so if `--output` already exists `party` writes a sibling `<stem>.candidate<ext>` (e.g. `docs/party.candidate.md`) and prints a `diff -u` command for manual merge. The live `party.md` is never clobbered. Pass `--overwrite` only when bootstrapping a fresh party.md.

## dnd_sheet

Converts a D&D Beyond character sheet PDF to structured markdown using Claude's vision API.

```bash
dnd_sheet Soma.pdf --party-config config/party.yaml    # roster mode (recommended)
dnd_sheet Soma.pdf --output soma.md                    # legacy: explicit path
dnd_sheet *.pdf --output-dir ~/campaigns/characters/   # legacy: one .md per PDF
```

**Roster mode** (`--party-config`, feature 008). The campaign's `party.yaml`
becomes the authority for where the sheet goes and who plays the character:

| Step | What happens |
|---|---|
| Attribute | The `# ` title of the converted sheet is matched to a roster `name`. **Exact match, case-insensitive, whitespace-trimmed — no fuzzy fallback.** |
| Name | The sheet is written to `<the roster's sheet directory>/<char-name>.md`, never to the PDF's own name. |
| Archive | Any sheet already there is moved to `old/level/<N>/<char-name>.md` first, keyed by the level *that* sheet records — so the archive reads as "the sheet as it was at level N". |
| Player | The roster's `player:` is written over the exported one, in **both** the YAML frontmatter and the `## Identity` block. A D&D Beyond download stamps the *downloader's* name into every sheet, so the export is wrong about this for every character. |
| Report | Per PDF: `Matched roster entry`, `Archived … (level N)`, `Player: … (from party.yaml)`, `Saved to`. |

`player:` must be the player's **Zoom display name**, not their legal name —
`normalize_vtt_speakers` matches transcript prefixes exactly, and a near-miss
silently drops that character's lines from every downstream extraction.

Relative paths in the roster resolve against the **current directory**, and
every campaign's roster is written campaign-root-relative (`docs/party/…`), so
run this from the campaign root — the same invariant every other CLI here has.
If you run it from somewhere else it refuses rather than writing a stray tree.

**Refusals.** Each names the file, shows the values that disagree, says which
file to fix, and ends `Nothing was written or moved.` — literally nothing: the
API call completes before the first filesystem mutation, so a refusal costs
tokens and changes no bytes. The run exits `1`; other PDFs in the same
invocation still convert.

| Refusal | Fix |
|---|---|
| The sheet's name is not in the roster | Edit `party.yaml` or the sheet's `# ` title so one matches exactly. Prefer the sheet: `characters[].name` is also the canonical PC name consumed by `load_pc_names` and `roster_from_config`. |
| The name matches two roster entries | Roster names must be unique. |
| The roster's `sheet:` basename isn't what would be written | The message prints the exact replacement line. This tool never edits `party.yaml`. |
| The displaced sheet records no level, or more than one (`Fighter 9 / Bard 2`) | Archive it by hand, or record a single class & level. Picking one of two invents precision the source lacks. |
| `old/level/<N>/<char-name>.md` already exists | Never overwritten and never suffixed — losing an archived sheet is the one thing this exists to prevent. |
| The roster's sheet directory doesn't exist | You are probably running from the wrong directory. It will not create the tree. |

**Legacy modes are unchanged.** With no `--party-config`, or with an explicit
`--output`/`--output-dir`, sheets are named after their source PDF exactly as
before — and the run says which mode it is in, so a suppressed roster is never
silent.

## npc_table

Generates a markdown NPC reference table (Name / Faction / Current State / Motivations) from one or more campaign documents.

```bash
npc_table                              # uses world_state
npc_table --docs world_state planning  # combine multiple docs
npc_table --output npc_state.md
```

## distill

Converts a large session-summary file into a structured `world_state.md` via a two-pass extract → synthesize pipeline. Intermediate extractions are saved so the synthesis can be re-run without re-extracting.

```bash
distill summaries.md --output docs/world_state.md
distill --synthesize-only --extract-dir docs/distill_extractions --output docs/world_state.md
```

## transform

Converts a NotebookLLM planning document into `prep` input format.

```bash
transform dossier.txt
transform dossier.txt --single          # extract as a single beat
transform dossier.txt -o beats/out.txt  # save for later
```

## Post-session pipeline (Stage 1 → 4)

The recommended way to turn a finished session into a narrative document
runs four scripts back-to-back with a human-review checkpoint after each.
For the full reference (flags, batch mode, voice files, examples,
dialogue handling), see [`docs/session_doc_pipeline.md`](session_doc_pipeline.md).

```
gm-assist.md                                       (human-authored recap)
    │
    ▼  Stage 1 — enhance_summary               (single cached call · --batch ✓)
session-summary.md                                 ◄── HUMAN REVIEW
    │
    ▼  Stage 2 — scene_extract                  (per-scene · cached VTT · --batch ✓)
scene_extractions/NN_<slug>.md                     ◄── HUMAN REVIEW
    │
    ▼  Stage 3a — sd_consistency                (Pass 1: continuity check, optional)
    ▼  Stage 3b — sd_plan                       (Pass 3: one narrator per scene)
    ▼  Stage 3c — sd_narrate --per-scene-output (Pass 5: per-scene narration)
narration/session_doc_scene_NN_<slug>.md           ◄── HUMAN REVIEW
    │
    ▼  Stage 4 — assemble
session_doc.md
```

### enhance_summary

Stage 1: enrich a `gm-assist.md` recap with VTT detail. Single cached
call. Output preserves the recap's section structure (Summary, Memorable
Moments, Scenes, NPCs, Locations, Items, Spells) and fills in details +
verbatim moments the recap missed.

```bash
enhance_summary session.vtt \
    --gmassist  gm-assist.md \
    --output    session-summary.md

# Batch mode (Anthropic Message Batches API; 50% off list price)
enhance_summary ... --batch                # block + poll
enhance_summary ... --batch --submit-only  # detach; sidecar in <output>.batch.json
enhance_summary ... --batch --collect      # retrieve from sidecar
```

Default model: `claude-sonnet-4-6`. `--fast` switches to Haiku.

### scene_extract

Stage 2: per-scene verbatim quote extraction. The full VTT is cached as a
system prefix; the script issues one call per scene named in the
session-summary's `## Scenes` section. Output is one
`scene_extractions/NN_<slug>.md` per scene. Resume semantics: existing
files are skipped.

```bash
scene_extract session.vtt \
    --summary    session-summary.md \
    --output-dir scene_extractions/ \
    [--dossier-dir docs/npcs/]      # rewrites NPC aliases to canonical names

# Batch mode — N scenes submitted as one Message Batches job; cache hits compound
scene_extract ... --batch                # block + poll
scene_extract ... --batch --submit-only  # detach; sidecar in <output-dir>/.batch.json
scene_extract ... --batch --collect      # retrieve from sidecar

# Batched scene extraction — one exchange for all pending scenes, instead
# of one call per scene (013). For the subscription backend, not the
# metered one — see docs/cli/session_doc_pipeline.md § Batched scene
# extraction for why, and the measured 87.5% reduction in transmitted
# tokens.
scene_extract ... --batch-scenes                          # default ceiling: 32,000 tok/group
scene_extract ... --batch-scenes --batch-max-tokens 48000  # raise the per-group ceiling
scene_extract ... --no-batch-scenes                        # explicitly force the per-scene loop
```

Default model: `claude-sonnet-4-6`.

| Flag | Default | Description |
|---|---|---|
| `--batch-scenes` | off | Send every pending scene in one exchange, grouped against `--batch-max-tokens` if the projected output would exceed it, instead of one call per scene. Shares its `dest` with `--no-batch-scenes` so a caller can always render an explicit flag either way. |
| `--no-batch-scenes` | — | Explicitly force the per-scene loop, overriding a caller-supplied default. |
| `--batch-max-tokens` | `32000` | Output ceiling a `--batch-scenes` run packs scene groups against. A **per-group** ceiling, not a per-scene one — it does not touch `--max-tokens` (`8192`), which keeps governing the per-scene loop only, with or without `--batch-scenes`. Accepted but inert without `--batch-scenes`. |

**`--batch` and `--batch-scenes` are different features and are refused
together** (`scene_extract` exits 1 before reading any input if both are
set):

| | `--batch` | `--batch-scenes` |
|---|---|---|
| What | Submits N per-scene requests as one Message Batches job | Collapses N scenes into one exchange |
| Calls | N requests, one job | 1 (or a few) |
| Backend | `anthropic` only | Any; the point is the subscription |
| Buys | 50% list discount | Removes transcript repetition |

`--batch` only works on the metered backend, where the repeated transcript
is already cached — the saving `--batch-scenes` exists for does not exist
on that path, so the two aren't alternatives worth composing. Full detail:
[`docs/cli/session_doc_pipeline.md`](session_doc_pipeline.md) § Batched
scene extraction and
`specs/013-batched-scene-extraction/contracts/cli-surface.md`.

### sd_consistency / sd_plan / sd_narrate

Stage 3: post-Phase-5 split of the old `session_doc.py` monolith into
three single-LLM-call tools. Each reads its inputs from disk and writes
its output, then exits. For full pass details, all flags, and voice
files, see [`docs/session_doc_pipeline.md`](session_doc_pipeline.md).

```bash
# Pass 1 — continuity check (optional; runs only if --context is supplied)
sd_consistency session-summary.md \
    --context docs/campaign_state.md docs/world_state.md docs/party.md \
    --out     narration/consistency_report.md

# Pass 3 — narrative plan (assigns one narrator per scene)
sd_plan \
    --scene-extractions scene_extractions/ \
    --characters        "Vukradin, Valphine, Soma, Brewbarry" \
    --party             docs/party.md \
    --session-summary   session-summary.md \
    --out               narration/plan.md
# REVIEW narration/plan.md before running narrate

# Pass 5 — per-scene narration (one file per scene)
sd_narrate session-summary.md \
    --plan              narration/plan.md \
    --scene-extractions scene_extractions/ \
    --voice-dir         voice/ \
    --examples          examples/ \
    --characters        "Vukradin, Valphine, Soma, Brewbarry" \
    --per-scene-output  narration/

# Re-narrate a single scene after editing its quote file
sd_narrate ... --scene 3
```

Default model: `claude-sonnet-4-6`. `--fast` switches to Haiku.

### assemble

Stage 4: concatenate the per-scene narration files into a single session
document.

```bash
assemble narration/ \
    --output session_doc.md \
    --title  "Chapter 37 — A Gem of a Problem"
```


## migrate_session_doc

One-shot migration: moves a pre-isolation campaign's `ui.session_doc` / `ui.profiles` fragment out
of `<config>/ui_state.yaml` into its own `<config>/session_doc.yaml`, now owned exclusively by
`SessionEditorConfigService`. Only needed for a campaign whose config predates the Session Doc
Editor config isolation — see
[`docs/config/session-editor-isolation.md`](../config/session-editor-isolation.md#migrating-an-existing-campaign).
Run once per campaign, then launch the server normally.

```bash
python -m server.migrate_session_doc --campaign-dir /path/to/campaign
```

| Flag | Default | Description |
|---|---|---|
| `--campaign-dir` | required | Campaign root directory (contains `<config-dir>/ui_state.yaml`) |
| `--config-dir` | `config` | Configuration subdirectory within the campaign |
| `--force` | off | Overwrite an existing `session_doc.yaml` at the destination |

Prints `nothing to migrate` and exits `0` if the source has no non-empty `ui.session_doc` /
`ui.profiles` data — safe to run against a campaign that never had session-editor state, or one
that's already been migrated. Reads `ui_state.yaml` raw (not through the typed `UIState` model,
which no longer declares these fields) so it can rescue data the current schema would otherwise
silently drop.

## new_workspace

Creates a new campaign workspace.

```bash
new_workspace ~/campaigns/icespire --name "Icespire Peak"
```

Generates a `config.yaml` with absolute paths so it works from any directory. Pass `--world-state`, `--mechanics`, `--planning`, `--party`, or `--campaign-state` to point at existing files instead of creating placeholders.

## Logs

Logs are saved to `log_dir` (from config) as timestamped markdown files. Single-beat logs include the system prompt, user prompt, and response. Session logs include all beats and all pipeline stages in one combined file (stem: `session_arc`).

## Typical workflow for a new campaign

```bash
# 1. Create workspace
new_workspace ~/campaigns/icespire --name "Icespire Peak"
cd ~/campaigns/icespire

# 2. Convert character sheets
dnd_sheet *.pdf --output-dir docs/characters/

# 3. Extract tracking list from adventure module
make_tracking "adventure.md" --output docs/tracking.txt
# (review and edit tracking.txt)

# 4. Generate grounding documents from session summaries
campaign_state summaries.md \
    --track-file docs/tracking.txt --output docs/campaign_state.md
distill summaries.md --output docs/world_state.md
party \
    --character docs/characters/soma.md \
    --summaries summaries.md --output docs/party.md

# 5. Build NPC dossiers, then synthesize planning doc
planning \
    --summaries summaries.md --build-dossiers --dossier-dir docs/npcs/
# (review docs/npcs/*.md)
planning \
    --npc docs/npcs/*.md --arc-scores arc_scores/*.md \
    --output docs/planning.md

# 6. Run session prep
prep --beat "The party arrives at Icespire Hold"
```
