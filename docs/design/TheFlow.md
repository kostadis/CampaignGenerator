# The Flow

## Why this doc exists

[CampaignGenerator](https://github.com/kostadis/CampaignGenerator) was originally pitched as a complete system. In practice it is one actor in a larger workflow that also includes Zoom, [gmassist.app](https://gmassist.app), the Anthropic API, a growing set of Claude skills that live **outside this repo**, MemPalace, and a fair amount of manual stitching at the seams.

The flow has never been written down end-to-end. This doc fixes that, so we can use it to:

1. Identify where the architecture **helps or hinders** the flow.
2. Identify and fix **UX problems** in the web UI.
3. Propose **new UI features** that close the gaps the flow currently routes around.

## The design principle

> Never feed an LLM's output to another LLM without human review if you want precision.

I want precision. I run a complex campaign with hundreds of NPCs and factions, and I cannot afford a moment where my own lack of precision breaks the fourth wall — a player questioning why an NPC behaves out of character, or an action that should ripple through the world quietly disappearing. So I need:

- A precise accounting of **what happened** at the table each session.
- Augmentation with **what was said** at the table — verbatim dialogue and chatter.
- A "memoir" pass that attempts to describe **what was going on in the players' minds**, grounded in the first two.

The rest of this doc is the workflow that produces those three things and feeds them back into the next session's prep.

## Actors in the flow

The flow is run by these distinct actors. Each step below names which actor is doing the work.

| Actor | What it is | Where it lives |
|---|---|---|
| **CG-CLI** | CampaignGenerator's python scripts | `~/src/CampaignGenerator/*.py` |
| **CG-UI** | CampaignGenerator's Vue/FastAPI web UI | `frontend/` + `server/` |
| **Skill** | A Claude Code skill — slash-command-invoked, runs in a normal Claude Code session | `~/src/mytools/dotfiles/claude/skills/<name>/SKILL.md`, linked into `~/.claude/skills/` |
| **Anthropic API** | Direct Claude API call (via `campaignlib.stream_api` / `call_api`) | Embedded in CG-CLI and CG-UI |
| **gm-assist** | External service that ingests Zoom recordings and produces a structured session summary | [gmassist.app](https://gmassist.app) |
| **MemPalace** | Local-first verbatim retrieval over the curated campaign | `~/src/mempalace/`; per-campaign palace |
| **Manual** | Human-in-the-loop editing, reviewing, decisions | Editor / browser / brain |

**Important:** the skills are not in this repo. They live in `~/src/mytools/dotfiles/claude/skills/` and are loaded into Claude Code via `~/.claude/`. They are first-class steps in the flow but invisible from inside CampaignGenerator's codebase. Any conversation about "what the flow looks like" that doesn't name them is incomplete.

### The skill inventory

| Skill | Slash command | What it does | Where it fits |
|---|---|---|---|
| `campaign-prep` | `/campaign-prep` | Loads the 4 grounding docs (campaign_state, world_state, planning, party) so Claude has authoritative context before any prep | Pre-session prep |
| `vtt-spell-pass` | `/vtt-spell-pass [vtt]` | Glossary replacements on the Zoom/Otter transcript + interactive prompts for unrecognised proper nouns | Transcript cleanup |
| `gmassist-precheck` | `/gmassist-precheck [session-dir]` | Runs `session_doc/enhance_summary.py` then `session_doc/check_consistency.py` on the gm-assist + VTT *before* per-scene extraction, to catch canon problems while the artifact is still cheap | Right after gm-assist |
| `consistency-check` | `/consistency-check [doc]` | One-shot `session_doc/check_consistency.py` on any document vs the grounding docs | After any LLM extraction or narration pass |
| `staged-consistency` | `/staged-consistency [session-dir]` | The multi-stage version: a `consistency-check` gated by a human-review/fix cycle at *every* LLM boundary (gm-assist → summary → scenes → narration). Prevents per-scene quotes silently re-injecting errors into the narrator | Across the whole session_doc pipeline |
| `voice-file` | `/voice-file <char>` | Builds `{character}_voice.md` for `session_doc.py` Pass 5 by deeply reading source material | One-time per character |
| `voice-examples` | `/voice-examples <names>` | Per-character `examples/<firstname>.md` files (Phase 1 routing). Makes narrators sound distinct instead of regressing to an average voice | One-time per character; refreshed when prose accumulates |
| `style-examples` | `/style-examples` | Global verbatim-excerpt style pool for narration | One-time per campaign |
| `voice-critic` | `/voice-critic <narration>` | Post-hoc critique of generated narration — flags generic prose / voice drift / wrong narrator. Never auto-rewrites | After Pass 5 |
| `dossier-merge` | `/dossier-merge [dir]` | Deduplicates `docs/npcs/*.md` from `pipelines/grounding/planning.py --build-dossiers` (typos, alias-as-filename, garbage filenames) into one canonical file per NPC. Also folds `.new_notes.NNN.md` sidecars back in via batch | Whenever `--build-dossiers` runs |
| `mempalace-campaign` | (setup) | Stand up a per-campaign MemPalace palace over the curated content | One-time per campaign |

## Ordering: see also

The post-recording segment (VTT → assembled document) has since moved to the
split-CLI pipeline (`sd_plan` / `sd_narrate`) and gained six skills not in the
inventory above — `speaker-attribution`, `scene-extract`, `voice-smooth`,
`scrub`, `no-mech`, `remove-recap`. **[SkillPipelineOrder.md](SkillPipelineOrder.md)**
records that ordering and the reasoning for each position; where the two docs
disagree on ordering, it is newer than this one.

## The flow, end to end

The flow is a loop: prep → session → memoir → updated grounding → next session's prep. I'll describe one full revolution.

### Phase A — Session prep

The goal here is to walk into the session knowing what NPCs are around, what they want, and what's likely to come up. Input is the four grounding docs; output is whatever I print/keep open at the table.

| # | Step | Actor | Notes |
|---|---|---|---|
| A1 | Load the 4 grounding docs into a Claude Code session | Skill: `/campaign-prep` | Pulls `campaign_state.md`, `world_state.md`, `planning.md`, `party.md` from CWD's `docs/` |
| A2 | Optional: ask MemPalace for verbatim recall of past behavior ("is X behaving consistently with how Y was described in session 12?") | MemPalace MCP | Prose-retrieval question, not graph |
| A3 | Optional: visualise NPC/faction connections | CG-UI → `ConnectionGraph` | Graph question — who is connected to whom |
| A4 | Optional: brainstorm beats / encounters / NPC drafts | CG-UI → `SessionPrep` or CG-CLI `pipelines/session_prep/prep.py` | Single-mode or pipeline-mode with `lore_oracle`/`encounter_architect`/`voice_keeper` |
| A5 | Optional: regenerate the NPC reference table | CG-UI → `NpcTable` or CG-CLI `pipelines/grounding/npc_table.py` | Print-friendly index |

**Human checkpoint:** I read whatever was generated, edit/discard, and decide what to bring to the table.

### Phase B — At the table

| # | Step | Actor | Notes |
|---|---|---|---|
| B1 | Record the session | Zoom | Audio + speaker-labeled VTT transcript |
| B2 | Track events live | CG-UI → `MakeTracking` outputs feed this; tracking files | Trackable events get logged against the planning doc structure |

### Phase C — Raw artifact ingest

The boundary between session and post-session work. Two artifacts come out of Zoom: the recording and the transcript. They take two different paths.

| # | Step | Actor | Input | Output |
|---|---|---|---|---|
| C1 | Submit Zoom recording to gm-assist | External: gm-assist | Zoom audio | `gm-assist.md` — structured scene-by-scene summary |
| C2 | Manually verify the gm-assist summary | Manual | gm-assist output | Cleaned `gm-assist.md` |
| C3 | Clean up the Zoom VTT transcript | Skill: `/vtt-spell-pass` | Raw VTT | Spell-corrected VTT with unknown proper nouns resolved by interactive prompt |
| C4 | (Optional) Pre-extraction consistency check on the human-authored structure | Skill: `/gmassist-precheck` | gm-assist + cleaned VTT | An enhanced session summary + a consistency report — catches canon contradictions before per-scene extraction spends tokens |

**Why two paths:** gm-assist is good at "what happened in what order"; the VTT is the only verbatim record of "what was said." We need both, and we need to clean both before they meet.

### Phase D — Build the enhanced summary

| # | Step | Actor | Notes |
|---|---|---|---|
| D1 | Generate enhanced summary from cleaned gm-assist + cleaned VTT | CG-CLI: `session_doc/enhance_summary.py` (or via the precheck skill in C4) | `session-summary.md` |
| D2 | Consistency check the enhanced summary | Skill: `/consistency-check session-summary.md` or `/staged-consistency` | Catches contradictions with grounding docs |
| D3 | Review & edit | Manual | Hard checkpoint — this artifact is the spine of everything downstream |

### Phase E — Per-scene quotes

The first place CG-UI is the centre of gravity.

| # | Step | Actor | Notes |
|---|---|---|---|
| E1 | Scene-by-scene quote extraction from the VTT | CG-UI → `SessionDocEditor` (Scene Editor / `QuotePicker`) backed by `session_doc/quote_ledger.py` | The UI surfaces candidate quotes per scene; I assign / reject |
| E2 | Review every scene's quote list | Manual | Quotes are the layer that silently re-injects errors into the narrator — this is the highest-leverage review in the flow |
| E3 | Consistency check at the scene-extraction boundary | Skill: `/consistency-check` or `/staged-consistency` | Specifically catches verbatim transcription errors before they reach narration |

### Phase F — Build the per-scene composite

| # | Step | Actor | Notes |
|---|---|---|---|
| F1 | Assemble a per-scene document containing the events (from the enhanced summary) + the quotes (from E1) | CG-CLI: `session_doc.py` / `session_doc/narrative.py` (Pass 1–4) | This is the input the narrator sees |
| F2 | Review the assembled per-scene doc | Manual | Last chance to fix scope/attribution before generation |

### Phase G — Narrate

| # | Step | Actor | Notes |
|---|---|---|---|
| G1 | Prerequisite: per-character voice files | Skill: `/voice-file <char>` | One-time per character |
| G2 | Prerequisite: per-character example files (Phase 1 routing) | Skill: `/voice-examples <names>` | One-time per character; refreshed as prose accumulates |
| G3 | Prerequisite: global style examples | Skill: `/style-examples` | One-time per campaign |
| G4 | Generate first-person narration per scene | CG-CLI: `session_doc.py` Pass 5 (Anthropic API) | First-person, grounded in events + verbatim dialogue + player backstory |
| G5 | Strip mechanical language | CG-CLI: voice pass / `session_doc.py` later pass | "rolls a 17", "AC 14" etc. removed |
| G6 | Voice pass | CG-CLI: `session_doc.py` voice pass (Anthropic API) | Aligns sentences to the character's voice |
| G7 | Critique generated narration | Skill: `/voice-critic <narration>` | Flags generic prose / voice drift / wrong narrator — review artifact, never auto-rewrites |
| G8 | Fix voice issues | Manual + targeted re-runs | |
| G9 | Final consistency check | Skill: `/consistency-check` (or final gate of `/staged-consistency`) | |

### Phase H — Update the grounding docs

This is the loop that makes the next session's prep precise.

| # | Step | Actor | Notes |
|---|---|---|---|
| H1 | Distill the new memoir into world-state deltas | CG-CLI: `pipelines/grounding/distill.py` → `world_state.md` | |
| H2 | Update `campaign_state.md` (completed content) | CG-CLI: `pipelines/grounding/campaign_state.py` | |
| H3 | Update `party.md` (arc score candidate events, not values) | CG-CLI: `pipelines/grounding/party.py` | LLM surfaces candidates; the GM accepts/rejects |
| H4 | Build/refresh NPC dossiers from the new memoir | CG-CLI: `pipelines/grounding/planning.py --build-dossiers` → `docs/npcs/*.md` | |
| H5 | Deduplicate the dossier directory | Skill: `/dossier-merge` | Collapses typos / aliases / sidecars into one canonical file per NPC |
| H6 | Synthesize the planning doc from the deduped dossiers | CG-CLI: `pipelines/grounding/planning.py --synthesize` → `planning.md` | |
| H7 | (Optional) refresh the MemPalace palace over the curated content | Skill: `mempalace-campaign` or its update path | Keeps verbatim-retrieval fresh |

After H, we're back at A for the next session.

## The seams

The places the flow currently leaves the UI and falls back to a skill, CLI, or manual step. These are the spots where the architecture is being asked questions it doesn't answer.

- **C1 (gm-assist submit)** — fully external, no UI integration; I jump out to a browser.
- **C2 (verify gm-assist)** — pure manual editing in a markdown editor; no in-UI editor for this artifact.
- **C3 (VTT spell pass)** — only available as a skill. The UI has no glossary editor and no interactive unknown-proper-noun prompt. This is one of the most-touched per-session steps and it's invisible to the UI.
- **C4 / D2 / E3 / G9 (consistency checks at boundaries)** — the *script* (`session_doc/check_consistency.py`) is in the repo, but the **staged pattern** that prevents drift between stages lives only in the `/staged-consistency` skill. The UI runs the script; it doesn't orchestrate the staged human-review gates.
- **G1–G3 (voice / examples / style files)** — only available as skills. There is no UI for inspecting or refreshing the voice/example library a campaign depends on.
- **G7 (voice-critic)** — only available as a skill. Post-narration critique is a flagged-sentences report, not a structured artifact the UI knows about.
- **H5 (dossier-merge)** — only available as a skill. The UI runs `pipelines/grounding/planning.py --build-dossiers`; the deduplication step that makes the output *usable* is outside the UI.
- **A1 (campaign-prep load)** — a skill exclusively. The UI doesn't have a "drop me into a Claude Code session with these four docs preloaded" affordance.
- **A2 (MemPalace prose query)** — runs in a Claude Code session via MCP, not in the UI.

The pattern is clear: **anything that is "agent flags, human decides"** (the precision steps) currently lives outside the UI, in skills. **Anything that is "render this structured input into a longer artifact"** lives inside CG (CLI or UI). That split actually matches the design principle — but it means the UI is missing the workflow scaffolding around the skills.

## What this doc is for

Three follow-on lists, to be filled in against this flow:

### 1. Architecture helps / hinders

- *Helps:* `campaignlib` as the API surface, `assemble_docs` for grounding-doc composition, the retrieval/render separation (CI-enforced), the 4-stage `session_doc` pipeline with human gates baked in.
- *Hinders:* (to enumerate) — anywhere a skill exists because the architecture didn't offer a place to put the equivalent step inside CG.

### 2. UX problems in the UI

(To enumerate against the seams above. Initial hypotheses: no glossary editor; no per-stage review queue across the session_doc pipeline; voice/example library is invisible; staged-consistency state isn't represented; dossier deduplication is hidden; gm-assist round-trip is a manual context-switch.)

### 3. Candidate new UI features

(Driven by 1 + 2. Initial hypotheses: an in-UI VTT spell-pass page with the glossary as a first-class object; a "session board" that represents the C→G pipeline as gated stages with consistency-check results attached to each gate; a voice/examples library page; a dossier dedup review queue; an embedded "campaign-prep Claude Code session" affordance.)
