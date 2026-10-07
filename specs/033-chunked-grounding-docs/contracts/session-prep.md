# Contract: session prep reads the state documents as an index

**Consumer**: the gm-assistant `gm-session-prep` skill (separate repository). This contract is what it adopts. The documents this feature builds are designed to satisfy it. The draft skill text is `experiments/20261007-chunked-state-docs/skills_variant/gm-session-prep-pointer/SKILL.md`.

## The two tiers

| Tier | Files | Role |
|---|---|---|
| **Authority** | `docs/summaries/NNN-*.md` (session summaries) | what happened |
| **Index** (generated) | `docs/campaign_state.md`, `docs/world_state.md`, `docs/party.md`, `docs/npcs/<slug>.md`, `docs/reference/*.md`, `docs/canon_events_timeline.md` | who/what exists, roughly where it stands, and **where to look** |

This is the repo's provenance rule (authoritative outranks `generated_by`) applied to session prep.

## What the documents guarantee (this feature's side)

1. **Every line carries at least one citation** `[ch NNN / target]` that resolves to a scene id or a named section of `docs/summaries/NNN-*.md`.
2. **world_state opens with a reading contract** that states:
   - the markers: `⚠ later:` (newer information about the same subject; where the two conflict, the later wins), `ℹ since:` (the later status of someone the line mentions; context, not a correction) and `⚠ unverified:` (not confirmed; treat as a paraphrase);
   - the citation grammar;
   - where the timeline and reference files are;
   - that anything unsettled is a GM decision.
3. **Key NPCs lines end in `→ docs/npcs/<slug>.md`.** A line marked `(no published dossier — from checked notes)` has no dossier.
4. **Nothing in the documents was rewritten by a model after the code check.** A change after drafting is an annotation or the removal of a player-character line.

## What session prep does (the skill's side)

1. **Index pass.** Read the state documents, following world_state's reading contract, to decide what the session puts on stage.
2. **Read the last two summaries in full.**
3. **Verify pass.** For every NPC, item, faction or thread the prep will *use* (on stage, carried, acting, or the subject of a branch):
   - find the latest mention in a summary, by following the citation or the dossier pointer, or by searching the summaries;
   - confirm its current state there.

   Background mentions are not verified.
4. **The summary wins.** On disagreement, use the summary's version.
5. **Tag the provenance.** A verified state claim is tagged `[TABLE chNN NNN.SS]`. An unverified one taken from a generated doc is tagged `[DOC unverified: <doc>]`.
6. **End the prep with "Doc errors found".** One entry per disagreement, giving:
   - the doc and line, and what it says;
   - what the summary says, with its citation;
   - which version the prep used.

   Write "none" if every verified claim agreed. This list is the GM's fix-at-source queue: the summary, the registry, a dossier's authored file, or a rebuild.

## Measured basis

Experiment round 5: four runs on the same beat.
- **Pointer contract with the new documents:** caught every known trap, found 8 document errors (including the registry's missing `Edvaldo` alias and a dossier's invented "third simulacrum"), and took 5.7 min against 6.0 min for the non-pointer run.
- **Pointer contract with the old documents:** marked a stale fact "verified". Verification is only as good as the citation it follows, which is why guarantees 1–3 above matter.
