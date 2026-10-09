Quest graph editor: the GM rules on quests by editing a graph (tracking file › section › quest › evidence, with typed links), replacing the one-proposal-at-a-time ratify cards on the Threads page (spec 034 US3). It depends on "Quests from summaries" (`docs/design/QuestsFromSummaries_specify_input.md`). Source: issue #535 and its comments. A throwaway prototype was used by the GM on real OOTA data: https://claude.ai/artifact/JiYBvgTtD2z83KQwBU4tGc.

**Problem.** Spec 034's Threads page presents group proposals as cards, one at a time, to ratify, split, reject or defer. But the GM's decisions are relational:
- which quest a note belongs to;
- whether two proposed quests are one;
- whether a quest sits under another quest or a tracking section;
- whether a model-invented quest should become a tracked quest.

None of these can be judged card by card; the GM has to see the structure and edit it. When the GM used the prototype, the first request was to **select many at once**: the decisions come in clusters.

**What the GM wants.**
1. **The hierarchy as the spine:** tracking file › section › quest, then the model-proposed quests, the GM's own new quests, and a pool of unplaced quest notes. Each row shows its accepted evidence count and its pending suggestions. A filter narrows it.
2. **A quest workbench.** The selected quest shows:
   - its title (editable), status, chapter span and origin (tracking file, model or GM);
   - its parents and its typed links;
   - its evidence: each note with chapter, tag and verbatim text, model suggestions shown dashed with accept or reject, and an "also in" list when a note supports several quests.
3. **A neighbourhood graph:** the quest with its parents above, linked quests at the sides, and evidence by chapter, coloured by progress tag. Suggested edges are dashed, and clicking a node moves to it. The neighbourhood is shown, not the whole graph: OOTA alone has about 90 quests and 320 quest notes.
4. **Edit operations, each recorded:**
   - attach or detach a note to a quest;
   - merge quests (one title survives; the rest become aliases);
   - split a quest by selecting notes;
   - create a quest;
   - promote a model quest into a tracking section;
   - set status;
   - add, retype or remove a link;
   - accept or reject a model suggestion in place (no cards).
5. **Multi-select everywhere.**
   - **Notes:** checkboxes, shift-click ranges, Select all, Select suggested. Bulk accept, reject, attach to, detach, and split into a new quest.
   - **Quests in the spine:** Ctrl/Cmd and Shift selection. Bulk merge into, put under, set status, and link to.
   - Every bulk action is one undoable step.
6. **The graph is full, not a tree (GM decision).**
   - A note may support several quests: it is evidence, not property.
   - A quest may have several parents (sections or quests).
   - Quests link to each other with typed relations. The prototype offered *part of*, *continues*, *causes* and *related*.
7. **The registry is the saved state of the graph:** nodes plus typed edges in a GM-owned file on disk, diffable and written only by GM action. A CLI applies and checks edits so the UI is not the only way in (constitution VI, IX, XI). The saved graph drives quest attachment on the next build: the GM's accepted evidence edges and aliases.

**Who decides what.**
- Every edge, merge, split and status is the GM's.
- The model's groupings arrive only as suggested edges.
- Code renders and checks: a note must be a real checked note, a target must exist, and there are no cycles in *part of*.

**Downstream to define.**
- How planning's Active Plots renders multi-parent quests and nesting.
- How exact-name attachment interacts with GM detachments. Spec 034's split could not separate a note sharing a ratified name (#529), and a removed alias left notes unflagged (#525). The graph model should resolve both.
- How a pending proposal spanning a range edge is handled (#524).

**Open questions for the spec.**
- The final link-type set, and whether links carry chapter ranges.
- How unplaced notes are shown: a pool, or dangling under their suggested parent.
- Whether notes from other kinds (events, world facts) can be evidence for a quest.
- Performance at about 500 nodes.

**Out of scope.**
- Themes (#536) and character arcs (#537), including the prototype's quest/theme kind marker: in this feature everything is a quest.
- The quests extraction pass (previous feature).
