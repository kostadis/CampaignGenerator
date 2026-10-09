Quests from summaries: a quests-only extraction pass that feeds the quest registry, a hooks list kept as brainstorming material, and the GM's tracking files as the quest vocabulary. This extends the chunked summary-native build (`summary_native extract` → `synth`, specs 033 and 034). Sources: issues #538 (decision comment, 2026-10-09), #534, #535 (reframe comment) and #539; the experiments are recorded on #534 and #538.

**Problem.** The extraction's `## Threads` section asks for "a goal, mystery, promise, debt, threat or obligation", and those notes feed the thread registry, `thread-propose` and planning's Active Plots. So mysteries, debts, reputations and character beats are treated as plot progress.
- **Most notes have no group.** On Out of the Abyss (ch 002–070, 318 thread notes), `thread-propose` produced 258 proposals, 233 of them single notes.
- **Many model "threads" are not quests.** *Ember Vanguard Reputation*, *Glabbagool's Integration* and *Jimjar's Bets* are themes or character beats.
- **The GM's own quest names never reach the model.** The GM already authored the campaign's quests in the tracking files named in `grounding.yaml` `campaign_state.track_files` (OOTA: `docs/tracking/tracking.txt`, `tracking_candlekeep_murders.txt`, `tracking_blingdenstone_travelogue.txt`). Today only the campaign_state audit reads them, so `thread-propose` groups blind and invents titles.

**The reframe (GM, 2026-10-09).** "Threads" are **quests and their progress**. Themes ("demon chaos", "madness") and character arcs (Glabbagool) are separate features. The broad thread list is still valuable, but **only for brainstorming more adventures**: a seeding tool for ideas, never a statement about the plot.

**What the GM wants.**
1. **The current extraction stays as it is.** No campaign re-extracts for this feature, and its broad `## Threads` notes stay checked exactly as today. They become **the hooks list**: rendered verbatim, cited, grouped, in a reference file headed "Ideas for adventures, not statements about the plot". They may feed planning's DM Notes, which are already labelled as suggestions. They stop feeding the quest registry, `thread-propose` and Active Plots.
2. **A quests-only pass per chunk.** It is its own narrow model call over the same chunk evidence, with a prompt whose only section is quests and their progress steps (OPENED / ADVANCED / RESOLVED / ABANDONED), named as goals. Mysteries, rumours, promises, debts, threats, bets, feelings, reputations and relationships are excluded unless the party actively pursues them as a goal.
   - It has the same code checks as every note: citations resolve in the chunk, quotes are verbatim, tags are present, and the leading-bold-citation form is accepted (#533).
   - It has its own cache key and cache, so a re-run of either pass does not invalidate the other.
   - It runs on the same backends and endpoints as extraction, with several endpoints sharing one queue.
3. **Tracking files seed the quest registry.** A deterministic import, no model, writes one quest per tracking-file item line in the GM's chosen sections:
   - **Sections:** the default is the quest sections (Main Quests, Side Quests, Scholar Tracks, Arc Milestones). The experiment showed that seeding locations, loot, completable events and NPC events makes exact-name traps.
   - **Each quest records:** the title as authored, the description, the section and the source file and line.
   - **Behaviour:** idempotent, with a dry run. A title collision is reported, never merged.
4. **Quest notes feed the registry and proposals.**
   - **Exact names attach by code:** a quest note whose name equals a quest's title or alias attaches.
   - **The rest go to `thread-propose`**, which proposes "these notes continue <your quest>" against the seeds, or a new quest. A note-less seed shows the model its section and description.
   - **The GM rules on every proposal.** The ratification UX is replaced by a separate feature (the quest graph editor); this feature keeps the existing Threads page working on quest notes.
5. **planning's Active Plots means active quests:** open quests with their latest progress step, plus quests the GM set dormant.
   - A seeded quest with no notes in the range never appears (a plan is not evidence).
   - The threads report lists seeds as "planned, no notes in this range".

**Measured (OOTA, qwen3.8 on two Sparks, Sonnet 5.5 for proposals).**
- **Quests-only notes:** 159 instead of 318. `thread-propose` with the 89 quest seeds gave 88 proposals instead of 218, and single-note proposals fell from 58% to 42%. Exact-name attachments rose from 2 to 9. All 22 groups checked by hand are real quests: Blingdenstone's Ooze Problem (9 notes), the red dragon egg (7), the Candlekeep murder investigation (7, continuing the GM's quest), Escape the Underdark, and others.
- **Other sections hold:** after excluding noisy chunks, Events +5%, Status 0%, Party 0%, World −8%, Concluded −15%.
- **Seeding:** seeding only quest sections gave 12 of 12 correct continues-groups. Seeding every tracking line added noise.
- **Why two passes:** a single prompt with a 7th `## Hooks` section lost that section in 12 of 60 chunks. Hence two passes rather than one combined prompt.

**Who decides what.**
- **Quest identity** comes from the GM's registry and tracking files, by exact title or alias. A model only proposes; the GM ratifies.
- **Open or closed** is decided by code from the registry status, else the latest progress tag. **Order** is decided by code, by latest activity.
- **Hooks are never statements about the plot**, and no document says a hook happened.

**Constraints.**
- No model output feeds another model call unchecked.
- A seed import writes the registry only as an explicit GM command.
- Drafts only; promotion stays manual.
- No API-key gate.
- Every capability is reachable from the web UI and the CLI (constitution XI).
- Single user: no back-compat shims.

**Decide in planning.**
- Whether `extract` runs both passes by default, or the quests pass is its own subcommand.
- Whether to rename "thread" to "quest" across code, the registry file, routes and pages now.
- What a chunk whose quests pass comes back empty means: retry under #532 and #515, or a genuinely quest-free chapter.
- Whether the extract default `--parallel` should come from dgxlib's per-model concurrency (#539: qwen3.8 serves 8, the default is 6). This could be folded in or kept separate.

**Out of scope.**
- The graph editor (next feature).
- Themes (#536).
- Character arcs (#537).
- Re-extracting campaigns.
- Changing the main extraction prompt.
