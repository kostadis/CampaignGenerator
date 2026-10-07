---
name: gm-session-prep
description: Generate a co-GM session prep document for the active campaign in the style of toee/notes/phase3_endgame.md — win condition, default trajectory, branches, scene staging, anticipated player questions. Invoke when the user says "prep the next session", "co-gm me", "help me run the next session", "/gm-session-prep", or asks for help thinking through what happens at the next table. The output is a working doc for the GM to read at the table, not a player-facing handout. This is the foundational co-GM prep skill; other skills (gm-faction-network, gm-strategy-doc, gm-handout, gm-npc-build) are narrower specializations.
---

# gm-session-prep

The co-GM prep workflow that produced `toee/notes/phase3_endgame.md`. The output is a **working doc the GM reads before and during the session** — not narrative prose, not a player handout.

## When to invoke

Trigger phrases:
- "prep the next session"
- "co-gm me"
- "help me prep/run the next session"
- "/gm-session-prep"
- Any "help me think through what happens when [event]"

Refuse politely if the working directory is not inside one of the campaign subdirs (`Phandalin/`, `out-of-the-abyss/`, `Hillsfar/`, `toee/`, or a future sibling). The skill is campaign-scoped — see `campaigns/CLAUDE.md` for the isolation rule.

## Inputs to confirm (one at a time, via AskUserQuestion)

Only ask for things you can't infer. If the user already supplied an answer in the invocation, skip that question.

1. **The beat.** What does the user want this session to *do*? One sentence. ("The party arrives in Kelno's quarters", "the cult attacks the wedding", "the merchant prince tests the party's loyalty.")
2. **Genre/tone.** Political thriller? Dungeon crawl? Heist? Comedy of errors? Horror? This is the single most useful framing the user can give — it determines pacing, NPC density, and which moves to pull from the style sheet. Default if pressed: "whatever fits the current campaign state."
3. **Player level.** Numeric. Affects which threats are existential vs trivial. The user's own recipe was "the players were 15."
4. **Anything else load-bearing the docs won't tell you.** E.g., "one player is missing this week", "we're running short — needs to wrap in 90 minutes", "I want to introduce X NPC."

## Required context: the state docs are an INDEX, the summaries are the AUTHORITY

Read from the current campaign's `docs/` and `summaries/`. If a path doesn't exist in this campaign, skip it and note the gap rather than failing.

**Two tiers of source.** The session summaries are the authoritative record of play. Everything else in
`docs/` that describes campaign state — `campaign_state.md`, `world_state.md`, `party.md`, the NPC dossiers in
`docs/npcs/`, `docs/reference/`, the timeline — is **generated** from the summaries and can be stale or wrong.
Treat those as an **index**: they tell you who and what exists, roughly where things stand, and *where to
look*. They are not proof.

1. **Index pass (fast).** Read `docs/campaign_state.md`, `docs/world_state.md` (follow its reading header), and
   `docs/party.md` (or `docs/party_state.md`). Skim `docs/background/` selectively for the beat. Use these to
   decide **what this session will put on stage**: the NPCs who can speak, the items in play, the factions and
   threats that act.
2. **The last two session summaries**, most recent first, read in full. They are authoritative for what just
   happened.
3. **Verify pass (the important one).** For every NPC, item, faction or open thread the prep will actually
   *use* — on stage, carried, acting, or the subject of a branch — find its most recent status in a **summary**
   and confirm it there:
   - Follow the citation the doc gives (`[ch NNN / NNN.SS]` → that scene in `docs/summaries/NNN-*.md`), or the
     dossier's latest citation (`docs/npcs/<slug>.md`), or search the summaries for the name.
   - Check the **latest** mention, not the first: a status can change after the chapter a doc cites.
   - Do not verify background mentions you won't use; verification scales with the beat, not the campaign.
4. **When a doc and a summary disagree, the summary wins.** Use the summary's version, and record the
   disagreement under **Doc errors found** (see Output shape) so it can be fixed at its source.
5. If a `mempalace` is configured (`.mcp.json` lists it), assume the user can also retrieve scene-level detail
   via search — but don't depend on it.

Do **not** read other campaigns' directories. Do **not** invent canon — if a fact isn't in a summary, the module,
or a doc you could not verify against a summary, mark it as a decision the user needs to make.

**Tag verification.** A `[TABLE]` claim you confirmed in a summary carries its location: `[TABLE ch67 067.03]`.
A state claim you took from a generated doc without confirming it is tagged `[DOC unverified: <doc>]` — the GM
should treat it as likely but unchecked.

## Style notes for this output

Co-GM prep docs in this workspace follow a recognizable shape. The user has corrected explicitly: **this is fanfic-narrative GMing, not lit-RPG.** That means:

- **Strategic clarity over mechanical exhaustion.** State the win condition plainly. State the default trajectory if the party does nothing. State the optimal play. Don't drown the GM in stat blocks — they have those elsewhere.
- **Branches, not rails.** For every choice point, sketch ≥2 paths. The party *will* go off-script; pre-stage the off-script.
- **Antagonists get interiority.** Even one-scene NPCs need a stake, a worry, a small goal. The party may never learn it; the GM needs to know it to play the NPC right.
- **Failure is comedic and material.** If a roll fails, what does the party *lose*? (A bow. A reputation. An ally's trust. Not "you take damage.")
- **In-fiction vs GM-only is explicit.** Mark which information the players can pick up and which is GM-only. Use quoted-block (`>`) for GM-only.
- **Theatrical timing matters.** When to be silent. When to escalate. When to let an NPC interrupt. Call these out as stage directions.
- **Modern register is fine.** Contemporary jokes, management-speak, references — all in bounds. Don't force "thou."
- **The Tenday calendar is real.** Use FR date stamps when relevant.
- **Mark provenance on every claim.** The GM must be able to tell, at a glance, what is adventure canon, what is already-played table history, and what you invented. See *The three mandatory blocks*, below.
- **No NPC arrives unannounced.** If someone can speak this session, they are in the cast sheet with a reason for being there.
- **Offstage clocks are visible to the GM.** Anything running on its own schedule is listed up front, not buried in a branch.

## The three mandatory blocks (before Scene 1)

**These go at the top of every prep doc, after the rulings and before the first scene.** They exist because of three failures at the table, and each block fixes one.

### 1. Provenance legend — and tag accordingly

The GM cannot tell where the module ends, the intended plan begins, and your invention starts. **Fix it with visible tags:**

| Tag | Means | Trust |
|---|---|---|
| `[MODULE §x]` | Adventure text, with a section reference | Canon |
| `[TABLE]` | Already played, or a locked ruling | Canon |
| `[OVERLAY]` | **Yours.** Invention, staging, connective tissue, recommendations | **Cuttable — nothing downstream breaks** |

State the tiebreak explicitly: **if an overlay item and a module item disagree, the module wins and the overlay is what you got wrong.**

*Failure this fixes: prep docs blended module canon, campaign state, and invention indistinguishably, so the GM could not tell what was safe to cut or what the adventure actually required.*

### 2. THE CAST — everyone who can walk on this session

A table: **who they are, what they are, why they are here, and the source tag.**

**Include module-supplied support NPCs first** — the allied detachment attached to an objective, the faction contact, the escort. **These are the ones that ambush the GM**, because they arrive automatically without being anybody's plot.

*Failure this fixes: an allied priestess the module attaches to an objective walked into a scene and the GM said "what's she doing there?" — she had been mentioned only in a setup line and an NPC-notes footer.*

### 3. ALREADY IN MOTION — clocks running whether or not the party touches them

A table of everything happening offstage this session on its own schedule, with where each one stands tonight.

**The rule this enforces:** *if something is going to land on the party later, it should already be visible this session as noise, weather, or a messenger — never introduced at the moment it matters.*

*Failure this fixes: a major NPC was leaving a trail of bodies across the region during a session and the GM did not realise it was happening.*

---

## Output shape

Use `toee/notes/phase3_endgame.md` for register and `toee/notes/sessions/nulb-knows-now.md` for **structure** — the latter states the intended session order up front in a blockquote, gives "keep this beside you" reference tables before Scene 1, and labels its invented layer explicitly as an overlay. The headings vary by session shape, but the canonical structure is:

```
# {Session title — evocative, not functional}

Co-GM working doc. Not canon yet — staging for {what session}.
Party: {level, names, who is player-run vs GM-run}
Register: {one line — the genre this session is in}

> **Scope:** where the session opens and where it stops. State the intended order and say what NOT to pull forward.

## How to read this doc — provenance legend
{[MODULE §x] / [TABLE] / [OVERLAY], and the tiebreak}

## THE CAST — everyone who can walk on tonight
{Table: who / what they are / why they are here / tag. Module-supplied support NPCs FIRST.}

## ALREADY IN MOTION — running whether or not the party touches it
{Table: what / where it stands tonight / tag}

Co-GM working doc. Not canon yet — staging for {what session}.

## The Win Condition (state plainly to yourself)
{One paragraph. What state must obtain for this session to count as "landed"?}

## The Default Trajectory (what happens if the party does nothing)
{Bulleted. The fates of each major NPC/faction if the party is passive.}

## The Clever Play (what the optimal party would do — the GM should know this)
{Numbered. Not because the party must do this, but so the GM knows when to nudge.}

---

## {Scene 1 — name}

### Setup
- Time and place in-fiction.
- Who's present, who's offstage.
- Map/area references if applicable.

### Approach — {sub-area or first beat}
{Prose + dialogue snippets the GM can lift verbatim if the moment lands.}

### Branch — if the party {does X}
{Consequence + how the next scene shifts.}

### Branch — if the party {does Y}
{Consequence + how the next scene shifts.}

### NPC notes
- **{NPC}** — one-line current motivation, one-line voice tic, what they want from this scene.

---

## {Scene 2 — name}
...

---

## Anticipated player questions
- **"What about {X}?"** → answer the GM should give, plus what's *not* answered.
- **"Can we just {bypass plan}?"** → the path-of-least-resistance the GM should leave open or close.

## Stage directions (timing/silence cues)
- When the party reads {handout}, leave a beat before reacting.
- If {NPC} is killed, don't fill the silence.
- {Other moments where pacing carries the weight.}

## Open decisions (for the user — don't decide for them)
- {Things the canon-and-state docs don't answer that the GM needs to pick before play.}

## Doc errors found (for the user — fix at the source)
- {Each place a generated doc disagreed with a summary: the doc and line, what it says, what the summary says (with its citation), and which you used. Write "none" if every verified claim agreed.}
```

## Steps

1. Read the docs in the order above: index pass, the last two summaries, then the verify pass for everything the beat puts on stage. Don't try to absorb everything — the index tells you what matters for this beat, the summaries confirm it.
2. Ask the 1-4 inputs the user hasn't supplied, one at a time.
3. **Draft the doc to `notes/session_prep/{YYYYMMDD}_{last_chapter_title}.md`.** Create `notes/session_prep/` if it does not exist — do not fall back to a flat `notes/{slug}.md` just because the directory is missing, and do not name the file after the location or the beat.

   - **`{YYYYMMDD}` is the date the prep is written**, not the date of the session being prepped and not the date of the chapter it follows.
   - **`{last_chapter_title}` is the title of the most recent *played* chapter**, snake-cased, chapter number included — the session this prep picks up from. Take it verbatim from that session's summary heading. A prep written on 2026-09-04 to follow `# Chapter 10 The Wizard of the Old Owl Well` is:

     ```
     notes/session_prep/20260904_chapter_10_the_wizard_of_the_old_owl_well.md
     ```

   **Why the last chapter and not the next one:** the chapter being prepped has no title yet, and it will not have one until it is played and summarised — sessions routinely stop somewhere other than where the prep expected, so a forward-looking name goes stale the moment the dice hit the table. Naming from the played chapter makes the filename a stable, sortable pointer to a document that already exists, and it means the prep and the summary it descends from can be lined up by eye.

   The `# H1` inside the doc is still the evocative session title — the filename is an index, not a headline. If prep gets rewritten before the session runs, overwrite the same file rather than minting a second date.
4. Open with a 2-3 sentence summary of what you understood from the docs so the user can catch you if you misread.
5. Produce the working doc. **Write the three mandatory blocks before writing any scene** — building the cast sheet first is also how you catch NPCs you were about to leave unintroduced.
6. **Re-read your own scenes and check every named NPC appears in the cast sheet.** If one doesn't, add it — that is exactly the NPC that will surprise the GM.
7. End with **Open decisions** explicitly. Don't decide things the user should decide.
8. Then **Doc errors found**: every disagreement the verify pass caught between a generated doc and a summary.

## What this skill is NOT for

- Writing player handouts (use `gm-handout`)
- Building a faction operational map (use `gm-faction-network`)
- Per-NPC strategic dossier (use `gm-strategy-doc`)
- Designing a single NPC (use `gm-npc-build`)
- Mid-session improv (use `gm-improv`)
- Writing up what happened *after* the session (that's CampaignGenerator's job, not this skill)
