Themes: campaign-wide "things happening", such as "demon chaos" and "madness", defined by the GM by what they are about, with evidence gathered by code from every kind of checked note, and shown in planning separately from quests. Source: issue #536 (GM decision 2026-10-09: themes are their own feature). This feature is independent of the quest features, but shares their registry and identity rules.

**Problem.** Threads come in different kinds:
- **A quest** has a goal and an end. *Cleanse the Steadfast Stone* opens at ch 039 and resolves at ch 043.
- **A theme** is what is happening across the campaign. It surfaces and recedes; it does not resolve. GM examples: **"demon chaos"** (OOTA's premise, the demon lords loose in the Underdark) and **"madness is a theme"**.

Demon chaos appears nowhere as a thread today. The tracking files hold quests that respond to it, but no entry for the chaos itself, and the model never proposed one. The tracking file's own "Surface-Madness Thread" section is a theme, not a list of quests.

**Measured (OOTA checked notes, ch 002–070).** 195 notes mention demons or a demon lord, across 41 chapters (ch 004–070):

| Kind of note | Count |
|---|---|
| Events | 57 |
| Thread notes | 40 |
| `[THREAT]` | 16 |
| Party | 16 |
| `[FACTION]` | 14 |
| `[ITEM]` | 12 |
| Status rows | 11 |
| `[LOCATION]` | 11 |
| `[NPC]` | 10 |
| Concluded | 8 |

A theme built only from thread notes sees about 20% of its evidence, and hand-attaching 195 notes is not a workflow.

**What the GM wants.**
1. **A theme is defined, not curated.** The GM authors each theme in a file:
   - a name and description;
   - the **registry entities** it is about (demon chaos: Demogorgon, Juiblex, Zuggtmoy, Orcus, Yeenoghu, Baphomet, Graz'zt, Fraz-Urb'luu, …);
   - optional **words of the GM's own** ("demonic", "the Abyss");
   - **pins** (defining moments) and **exclusions** (false hits).
2. **Code gathers the evidence** deterministically, with no model: every checked note of any kind that names one of the entities by exact registry name or alias, or contains one of the GM's words. No similarity matching. The GM's prunes and pins persist across rebuilds.
3. **Presence over time:** evidence per chapter, so the GM sees when a theme surges (Zuggtmoy's wedding, the Pudding King, Candlekeep). The theme's state is the GM's ruling, never inferred by a model. A first-guess vocabulary is *active / fading / dormant*.
4. **Themes link to quests.** A quest *touches* a theme, so a theme shows the quests that express it.
5. **A "Running themes" section** in planning, and perhaps world_state: each theme with its state, recent cited evidence and the quests touching it, separate from Active Plots.

**Who decides what.**
- The registry says who the entities are.
- The GM says what a theme is about, what counts and what state it is in.
- Code gathers and counts.
- A model at most renders the section's prose from the gathered, cited evidence, within a budget, like other prose sections. Whether a model may *propose* new themes as candidates is open.

**Open questions for the spec.**
- Where theme definitions live: a campaign `docs/themes.yaml`, or inside the quest registry.
- Whether the GM's words match in every note kind, or only alongside an entity. This is a precision question; measure it on demon chaos and madness.
- The state vocabulary.
- How a tracking section such as "Surface-Madness Thread" seeds a theme.
- Whether themes appear in world_state as well as planning.

**Out of scope.**
- Quests and the quest graph editor (separate features).
- Character arcs (#537).
