Summary-native NPC dossiers: per-NPC dossiers built from the GM's reviewed structured session summaries, as an extension of the summary-native grounding pipeline (`summary_native`, spec 031). Background and measurements: `docs/design/NpcDossiersFromSummaries_proposal.md`.

**Problem.** A GM preparing a session needs one dossier per recurring NPC: who they are, how they behave, what they did with the party and in what order, and where they were last seen. Today's options either re-extract from narrated chapter prose with a model, which lets the model decide which NPC a mention belongs to (`planning --build-dossiers`), or build dossiers from atomic facts, which has inverted who-did-what and reported a dead antagonist as alive (the ensemble). `summary_native build` already writes a deterministic evidence dossier per entity, but each one holds only the NPC's `## NPCs` entry from each summary, and every observation says `Scene: none`. The scenes and memorable moments where the NPC acts and speaks are not attached. On the Out of the Abyss corpus, scenes name an NPC 2–4× as often as the NPC sections do (Jimjar: 33 entries, 71 scenes, 17 moments). Some sessions mention an NPC with no entry at all (Ilvara: 6 sessions with an entry, 10 with any mention).

**What the GM wants.**
1. Each NPC's evidence dossier also carries every scene and memorable moment in the summaries that names that NPC, in authored order (chapter, then scene id), with file and line for every item. This step makes no model call and gives byte-identical output across runs.
2. A readable dossier draft per selected NPC, written by a model only from that evidence, in a fixed structure: identity, demonstrated personality and motivations, chronological history with the party, last observed state, relationships, and notable quotes. Every claim cites the chapter and scene it came from.
3. Drafts the GM reviews and promotes by hand. Nothing is written over live documents.

**Who decides what (hard requirements).**
- **Identity.** It comes only from summary headings and exact same-type aliases in the entity registry. No fuzzy matching, no similarity-score merges, and no aliases a model proposes. A name form that could refer to more than one entity, or is too generic to link safely, is listed for the GM to rule on and is not linked. The GM rules in the existing summary-native rulings file, which the pipeline only reads.
- **Ordering.** It comes from the authored structure: summary filename number, then scene id, then line.
- **Attribution.** Observations are whole summary paragraphs or scenes, never split into atomic facts.
- **Mentioned vs present.** A scene that names an NPC is evidence that the NPC was *mentioned*, not that they were *present*. Dossiers must keep that distinction.
- **Header facts are computed, not generated.** Canonical name, aliases, first seen, last seen, the list of chapters, and counts of entries, scenes and moments.
- **Current status.** It is the latest observation, labelled with its chapter. The model must not infer a status such as alive or dead from the absence of later mentions.
- **Unsupported claims are labelled, not narrated.**
- **Arc-score material is listed only as candidate events with quoted triggers,** never as values or totals.
- **No GM secrets are invented.** Summaries record play and do not hold hidden information, so a "what the party doesn't know" field cannot come from them.
- **Rendered dossiers are a leaf output.** They do not feed planning or any other synthesis unless the GM explicitly names a draft as reviewed. Planning keeps reading the deterministic evidence dossiers.

**Scope and selection.** Which NPCs get a rendered dossier uses the existing summary-native selection rules: named NPCs, recent ones, and recurring ones above a minimum observation count. That selection is recorded with each run. Re-runs re-render only NPCs whose evidence has changed.

**Provenance and reproducibility.** Each render run keeps the exact prompt, a digest of the input evidence, the selection decisions, and the backend and model used. Every chapter and scene citation in a draft must exist in the corpus, and every quote must appear verbatim in the summaries. Both checks are deterministic and their results are reported to the GM. Rendering works with any configured backend, including a local DGX endpoint, so Spark and Claude drafts of the same evidence can be compared.

**Out of scope.** Creating or editing summaries. Changing how `summary_native build` groups entities or lists possible duplicates. Replacing the world_state, campaign_state, party or planning drafts. Merging or deleting existing `docs/npcs/` files. Building a graph store.

**Open questions (leave for clarification; the GM has not decided these):**
1. Do promoted dossiers replace `docs/npcs/`, or live beside it until compared?
2. What does a link attach: the whole scene, or only the paragraphs and bullets that name the NPC?
3. Do creatures filed under `## NPCs` in the summaries (for example an aquatic troll or animated statues) get rendered dossiers, or are they excluded by selection?
4. If a dossier should show GM-only secrets, where do they live? A separate hand-authored file, shown under an explicit "GM secret" label, is the candidate shape.
5. Is this a new `summary_native` subcommand (or subcommands), and does it need a web UI surface in this feature or a later one?
