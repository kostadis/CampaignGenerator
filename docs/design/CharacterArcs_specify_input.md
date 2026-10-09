Character arcs: the big events the party remembers, per character, for example the companion Glabbagool. Evidence is gathered by code, candidate beats are surfaced by code, and the milestones are pinned by the GM. **This feature starts with a design decision: is it its own feature, or part of the NPC dossiers (spec 032)?** The specification should settle that before anything is built. Source: issue #537.

**Problem.** A companion's story is told across dozens of sessions, but what the table remembers is a handful of beats. Nothing records those beats today:
- thread notes catch almost none of them;
- the NPC dossier's "History with the Party" re-derives a chronicle from evidence, and it can fail verification (Glabbagool's dossier is one of six that currently block `synth planning`).

**Measured (OOTA checked notes, ch 002–070).** 133 notes name Glabbagool, across 32 chapters (ch 034–069):

| Kind of note | Count |
|---|---|
| Events | 56 |
| Party | 30 |
| Status rows | 26 |
| Thread notes | 10 |
| `[NPC]` facts | 7 |
| Concluded | 4 |
| Citing a Memorable Moment | 4 |

The beats the party remembers are about 11:

```
ch 034  joins the party, a sentient gelatinous cube
ch 038  officially counted as an adventurer
ch 040  drunk on spilled alcohol, singing sea shanties
ch 047  swaps bodies with the Pudding King, stays a grey ooze
ch 048  pacifies the ooze horde with the Bone Die
ch 050  passed off as Daz's ooze "familiar"
ch 055  first cheese; pesters Zalthir about monk training
ch 056  becomes jailer of the shrunken T'sarran spy
ch 059  completes the Whispering Dome trial, becoming an eighth-level sidekick bonded to Zalthir
ch 064  stands over the unconscious Zalthir
ch 065  carries the real High Tower key inside himself
```

The rest is routine: status rows reading "Alive | With Party | Friendly", and incidental mentions.

**Common to either placement.**
1. **Evidence by entity**, deterministic, no model: every checked note of any kind naming the character by exact registry name or alias, in chapter order.
2. **Candidate beats surfaced by code, never chosen by it.** The signals:
   - a status or disposition change between consecutive status rows;
   - a concluded note naming the character;
   - a change in the character's `[NPC]` facts;
   - a citation of a summary's Memorable Moments, which the GM authored;
   - first and last appearance.
3. **The GM pins the milestones.** The arc is the ordered list of pinned beats, each with its cited note, and a rebuild never removes a pinned beat.

**The design decision.**
- **Option A — its own feature.**
  - **Store:** an arc file per character, or one campaign file.
  - **Readers:** party.md (an "Arcs" view for companions, perhaps player characters), the NPC dossier (citing it) and session prep ("the party remembers…").
  - **For:** one concept for companions, NPCs and player characters (which have no dossier); it sits alongside themes and the quest graph; it is independent of dossier verification.
  - **Against:** a second place describing an NPC, beside the published dossier, which runs against "an NPC is fixed in one place".
- **Option B — part of the NPC dossiers.**
  - **Store:** the GM pins beats in the character's dossier authored file (`docs/npcs/authored/<slug>.authored.yaml`). "History with the Party" becomes the arc; `npc-compose` renders it and `npc-publish` ships it.
  - **For:** one place per character; existing readers (world_state Key NPCs, planning NPC Dossiers) get it for free; it reuses the authored-file guarantees (never tool-written, Secrets never in a prompt); a history built from pinned, cited beats may also fix verification.
  - **Against:** player characters have no dossier; it ties arcs to the draft/verify/publish cycle and to per-range builds; beats are harder to link to quests and themes.
- **A hybrid is possible:** beats pinned in dossiers, and player characters' arcs in party.md.

**The spec should also settle:**
- Who has arcs: companions only, any NPC, player characters.
- How a beat links to quests and themes, since a beat can belong to both. This is the full-graph model of the quest graph editor.
- How pinned beats survive rebuilds across ranges (#512).
- Whether a model may also suggest beats, as candidates only.

**Measurement to inform the decision:** run the candidate-beat signals on Glabbagool and two other companions (for example Jimjar and Eldeth). Compare the candidates with the GM's own list of remembered beats, as precision and recall of the signals.

**Out of scope.** Themes (#536); quests and the quest graph editor.
