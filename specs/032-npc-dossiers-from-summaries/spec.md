# Feature Specification: Summary-Native NPC Dossiers

**Feature Branch**: `research/npc-dossiers-from-summaries`

**Created**: 2026-10-06

**Status**: Draft

**Input**: User description: `docs/design/NpcDossiersFromSummaries_specify_input.md`. This feature extends summary-native grounding (spec 031). Background and measurements are in `docs/design/NpcDossiersFromSummaries_proposal.md`.

## Context

A GM preparing a session needs one dossier per recurring NPC. It should say who the NPC is, how they behave, what they did with the party and in what order, and where they were last seen. The current options all hand a precision decision to a model or to an atomised fact store:

- `planning --build-dossiers` re-extracts from narrated chapter prose, so the model decides which NPC each mention belongs to.
- Ensemble atomic-fact dossiers inverted who-did-what and reported a slain antagonist as alive.

`summary_native build` (spec 031) already writes a deterministic evidence dossier per entity, with no model call. Each one holds only the NPC's `## NPCs` entry from each summary, and every observation says "no scene". The scenes and memorable moments where the NPC acts and speaks are not attached. On the Out of the Abyss corpus, scenes name an NPC 2–4× as often as NPC entries do (Jimjar: 33 entries, 71 scenes, 43 moments). Some sessions mention an NPC that has no entry at all (Ilvara: 6 sessions with an entry, 10 with any mention).

**What decision is removed from the human:** only prose, meaning compressing one NPC's verified evidence into a readable dossier. Identity, ordering, attribution, scope and status stay with the authored summaries, the entity registry, deterministic rules or the GM. A draft dossier is a leaf output: if one is 10% wrong, nothing downstream inherits the error, and only a copy the GM has reviewed and published reaches the gm-assistant skills.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See every scene and moment an NPC appears in (Priority: P1)

The GM opens an NPC's evidence dossier and finds, in chapter order, that NPC's entry from each summary plus every scene and memorable moment in the summaries that names the NPC. Each item gives its file and line. Linked items are labelled as *mentions*. The dossier header gives computed facts: canonical name, aliases, first seen, last seen, chapters, and counts of entries, scenes and moments. Name forms that are too ambiguous to link safely are not linked. They are listed in a report for the GM to rule on. No model is involved, and two runs on unchanged input produce identical files.

**Why this priority**: This is where the missing evidence is, and every later story depends on it. It is valuable without any drafting, because the GM can read the linked evidence directly and planning can use it.

**Independent Test**: Run the linker on the Out of the Abyss corpus. For Jimjar, confirm the evidence dossier carries 33 entries, 71 linked scenes and 43 linked moments, in chapter-then-scene order, each with file and line. For Ilvara, confirm it covers 10 chapters, not 6. Run again and confirm the output is byte-identical. Seed an ambiguous name form and confirm it appears in the link report and links nothing.

**Acceptance Scenarios**:

1. **Given** an NPC whose name appears in a scene of a chapter where it has no `## NPCs` entry, **When** the linker runs, **Then** that chapter appears in the NPC's dossier with the scene labelled as a mention, and the header's chapter list and last-seen value include it.
2. **Given** a name form that the entity registry assigns to two different entities, **When** the linker runs, **Then** the form links to neither, the run ends with a warning giving the count of ambiguous forms, and the link report lists each one with every file and line where it occurs. **Given** the GM edits those summaries to use each NPC's full name, **When** the linker runs again, **Then** the full names link, and the form drops out of the report once no summary uses it.
3. **Given** a name form flagged as too generic to link safely, **When** the linker runs, **Then** it links nothing and appears in the link report. **Given** the GM records it in the rulings file as "safe to link", **When** the linker runs again, **Then** it links and is no longer reported. **Given** the GM records it as "never link", **Then** it links nothing and is no longer reported as unruled.
4. **Given** a name that occurs inside a longer word or in a different letter case, **When** the linker runs, **Then** it is not linked.
5. **Given** a registry alias whose entity type is not NPC, **When** the linker runs, **Then** the alias does not link to the NPC.
6. **Given** unchanged summaries, registry and rulings, **When** the linker runs twice, **Then** every output file is byte-identical.

---

### User Story 2 - Draft a readable dossier per selected NPC (Priority: P1)

The NPCs eligible for drafting are the **global NPCs**: entities the entity registry lists with type NPC. By default a run drafts every eligible NPC that has evidence in the chosen range. The GM can narrow that set by name, or with the existing summary-native recent and recurring rules. NPCs that are not in the registry are one-offs. Drafting them is deferred to the follow-up local-NPC feature. **Drafting is the only model step** *(GM ruling, 2026-10-06)*. For each selected NPC, a model writes the draft dossier from that NPC's linked evidence plus the GM's Manual edits (never the Secrets), in a fixed structure: identity; demonstrated personality and motivations; chronological history with the party; last observed state; relationships; and notable quotes. Every claim cites the chapter and scene it came from, or the manual edit it came from. Where a manual edit conflicts with the evidence, the manual edit wins. A deterministic check then confirms that every manual edit was used. The computed header is inserted as computed, not generated. The draft dossier stays a draft until the GM reviews it and publishes it (User Story 6). The GM dossier is the draft dossier with the Secrets section appended, composed without a model. No live document is touched.

**Why this priority**: This is the product the GM reads at the table. It is P1 alongside Story 1 because the feature's purpose is a readable dossier. It cannot ship without Story 1.

**Independent Test**: Draft Jimjar, Ilvara and one low-observation NPC from the Out of the Abyss corpus. Confirm each draft has every section in order, every history bullet carries a chapter/scene citation, the header matches the evidence dossier exactly, and nothing under `docs/npcs/distilled/` or any other live document changed.

**Acceptance Scenarios**:

1. **Given** an NPC whose evidence says they were last mentioned in chapter N, **When** the draft is written, **Then** the "last observed state" section quotes or paraphrases the latest observation, labelled with chapter N, and asserts no status (such as alive or dead) that the evidence does not state.
2. **Given** evidence where the NPC is only mentioned in a scene, **When** the draft is written, **Then** the draft describes the NPC as discussed or mentioned there, not as present.
3. **Given** evidence that contains a possible arc-score trigger, **When** the draft is written, **Then** it is listed as a candidate event with its quoted trigger, and no score value or total appears.
4. **Given** a claim the model cannot support from the evidence, **When** the draft is written, **Then** the claim is labelled unsupported rather than narrated as fact.
5. **Given** an NPC whose authored file has secrets, **When** the dossier is drafted, **Then** the secrets are not in the model's input, the draft dossier contains no secret or "what the party doesn't know" content, and the GM dossier carries the Secrets section exactly as the GM wrote it.
6. **Given** a selection by recurring threshold, **When** a draft run completes, **Then** the run's record lists each selected NPC and the rule that selected it, and each NPC that was not selected.
7. **Given** a manual edit that contradicts the evidence (for example "Jimjar is a deep gnome, not a drow"), **When** the dossier is drafted, **Then** the drafted text follows the manual edit, cites it as `[manual N]`, and does not repeat the contradicted claim as fact.

---

### User Story 3 - Trust a draft: citations and quotes checked mechanically (Priority: P2)

After a draft run, the GM gets a deterministic report for each draft. It lists every chapter/scene citation that does not exist in the corpus and every quoted passage that does not appear verbatim in the summaries. The report is the same whichever backend wrote the draft. This lets the GM compare a local DGX (Spark) draft with a Claude draft of the same evidence on an objective measure.

**Why this priority**: The GM can review a draft by eye without it, but this is what makes review fast and makes the Spark-versus-Claude comparison meaningful.

**Independent Test**: Hand-edit a draft to add a citation to a scene that does not exist and a quote with one changed word. Run the check and confirm both are reported, with no model call. Draft the same NPC on two backends and confirm both drafts get the same kind of report.

**Acceptance Scenarios**:

1. **Given** a draft citing a chapter/scene pair that the corpus does not contain, **When** the check runs, **Then** the citation is reported with its location in the draft.
2. **Given** a draft quote that differs from the summaries by any character other than quote marks and apostrophes, **When** the check runs, **Then** it is reported as not verbatim. A quote that differs only in curly versus straight quote marks or apostrophes passes and is listed as `typography-normalised`.
3. **Given** a draft whose citations and quotes are all valid, **When** the check runs, **Then** the report says so explicitly and gives the totals checked.
4. **Given** an authored file with three manual edits and a draft dossier that cites only two of them, **When** the check runs, **Then** the third is reported as dropped, with its text, and the verdict is fail.
5. **Given** a draft dossier citing `[manual 4]` when only three manual edits exist, **When** the check runs, **Then** the citation is reported as invalid.

---

### User Story 4 - Re-draft only what changed (Priority: P3)

When the GM adds new summaries or corrects old ones and runs again, only NPCs whose linked evidence changed are re-drafted. The run reports which NPCs were re-drafted, which were skipped as unchanged, and why.

**Why this priority**: It saves time and tokens on a corpus with dozens of selected NPCs. It is not needed for correctness.

**Independent Test**: Draft a selection, edit one summary that mentions exactly one selected NPC, re-run, and confirm only that NPC is re-drafted and the rest are reported as unchanged.

**Acceptance Scenarios**:

1. **Given** a previous draft whose evidence is unchanged, **When** the GM re-runs, **Then** that NPC is not re-drafted and is reported as skipped (unchanged).
2. **Given** the GM passes the standard overwrite option, **When** the GM re-runs, **Then** every selected NPC is re-drafted whether or not it changed.
3. **Given** the prompt, template, backend or model changed since the previous draft, **When** the GM re-runs, **Then** the affected NPCs are treated as changed.
4. **Given** the GM edits an NPC's Manual edits, **When** the GM re-runs, **Then** that NPC is re-drafted. **Given** the GM edits only its Secrets, **Then** it is not re-drafted; only its GM dossier is re-composed.

---

### User Story 5 - Run the stages from a dedicated NPC dossiers page (Priority: P3)

The GM opens an **NPC dossiers page in the web UI. It is separate from the summary-native grounding-documents page**, because NPCs and grounding documents are different things *(GM ruling, 2026-10-06)*. From it the GM runs linking, drafting, verification, compose and publishing. Publishing has a button on the page as well as the CLI command *(GM ruling, 2026-10-06)*. The GM chooses the summaries location and chapter range, narrows the set of global NPCs (by name, recent or recurring), and picks the backend and model. The page shows which drafts were written, which NPCs were re-drafted or skipped and why, the link report and the verification reports. Reviewing drafts, ruling on name forms and editing authored files stay in files, the CLI or chat. The page only invokes `npc-publish` for the NPCs the GM selects, with the same refusals as the CLI.

**Why this priority**: Required for CLI/UI parity (Constitution XI), and the GM ruled it ships in this feature. The stages deliver value from the CLI first.

**Independent Test**: From the NPC dossiers page, choose the Out of the Abyss summaries and a chapter range, run linking, then draft one named global NPC. Confirm the same files appear as a CLI run with the same arguments produces, and that the page shows the link and verification reports.

**Acceptance Scenarios**:

1. **Given** the NPC dossiers page, **When** the GM runs a stage, **Then** the UI calls the same command-line tool with explicit arguments and shows the files and reports that run wrote.
2. **Given** the GM has not chosen a chapter range or an NPC selection, **When** the GM tries to draft, **Then** the page requires an explicit choice, and "every global NPC" or "all chapters" is a deliberate selection (Constitution X).
3. **Given** the summary-native grounding-documents page, **When** the GM uses it, **Then** it does not include the NPC dossier stages. They live only on their own page.
4. **Given** a draft run that skipped unchanged NPCs, **When** it finishes, **Then** the page lists each NPC as re-drafted or skipped, with the reason.
5. **Given** the GM selects NPCs and presses Publish, **When** the run finishes, **Then** the page shows the same per-NPC results and refusals as `npc-publish` at the CLI, and publishing without an explicit selection (named, all, or all hand-built) is impossible.

### User Story 6 - Publish reviewed dossiers where the GM's skills read them (Priority: P2)

After reviewing an NPC's GM dossier, the GM publishes it. The dossier is copied to `docs/npcs/<slug>.md`, the flat location the gm-assistant skills (`gm-npc-voice`, `gm-social-encounter`, `gm-session-prep`, `gm-faction-network`, `gm-npc-build`) already read. Nothing reaches that directory until the GM publishes it.

**Why this priority**: This is how the dossiers get used at the table, and publishing is the human checkpoint before another model reads them. It depends on Stories 1 and 2.

**Independent Test**: Draft, verify and compose Jimjar, then publish him. Confirm `docs/npcs/jimjar.md` holds the GM dossier with Secrets and a provenance header, and that `gm-npc-voice` finds it. Place a file in `docs/npcs/` that this feature did not publish, try to publish over it, and confirm the refusal.

**Acceptance Scenarios**:

1. **Given** a GM dossier whose verification passed, **When** the GM publishes it, **Then** `docs/npcs/<slug>.md` holds it byte-for-byte below a provenance header, and nothing else in `docs/npcs/` changes.
2. **Given** a GM dossier whose verification failed, **When** the GM publishes it without the overwrite option, **Then** publishing refuses and names the failures.
3. **Given** `docs/npcs/<slug>.md` exists and was not published by this feature, **When** the GM publishes that NPC, **Then** publishing refuses unless the overwrite option is given.
4. **Given** a published file the GM edited by hand afterwards, **When** the GM re-publishes, **Then** publishing refuses and reports the hand-edit, so the correction can be moved into the authored file first.
5. **Given** no NPC names and no explicit "all", **When** publish runs, **Then** it refuses.

---

### Edge Cases

- An NPC has entries but no scene or moment names it. The dossier still lists the entries, and the scene and moment counts are zero.
- An NPC is named in scenes but has no `## NPCs` entry anywhere in the range. It has no evidence dossier from `summary_native build`. The linker must not invent an NPC from a scene mention, so the name is reported, not given a dossier. Identity comes only from headings and registry aliases.
- Two different NPCs share a form, for example a first name. The form is ambiguous: it is linked to neither, the run warns, and it stays in the link report until the GM edits the summaries. No ruling can resolve it (FR-003a).
- A scene names the NPC several times. It is linked once, with the line of each mention.
- A memorable moment sits outside any scene. It is linked with its chapter and line and an explicit "no scene" marker.
- A summary changes after linking but before drafting. Drafting refuses and directs the GM to re-link, the same rule as 031 synthesis.
- The campaign has no entity registry. Drafting is refused and names the registry-building commands. Linking and verification still run (FR-012b).
- The selected NPC set is empty. The run is refused, with the selection rules and counts that produced the empty set.
- A model output is missing a template section or is truncated. It is not written as a draft. It is kept separately and reported, naming the missing sections (031's incomplete-output rule).
- A creature or group is filed under `## NPCs`, for example an aquatic troll or animated statues. If the registry does not list it as an NPC, it is a one-off. It still gets a linked evidence dossier, but no draft. If the registry lists it as an NPC, it is drafted like any other global NPC. Registry membership is the GM's existing identity decision, and the pipeline never guesses what counts as a creature. *(GM ruling, 2026-10-06.)*
- A registry NPC has no evidence in the chosen range. It is not drafted, and it is recorded in the selection as excluded ("no evidence in range").
- A chapter range is given. Only summaries inside it contribute evidence, and the range labels every output (031's range rules).

## Requirements *(mandatory)*

### Functional Requirements

**Linking (deterministic, no model)**

- **FR-001**: The pipeline MUST attach to each NPC evidence dossier every `## Scenes` subsection and every `## Memorable Moments` item in the selected range that names the NPC. It MUST do this without calling a model.
- **FR-002**: The forms that name an NPC MUST be only the NPC's own summary headings and the entity registry's exact aliases for an entity of the matching type. Matching MUST be case-sensitive and on word boundaries. Fuzzy matching, similarity-score matching, the registry's inferred aliases and model-proposed aliases MUST NOT be used.
- **FR-003**: A form that could name more than one entity (*ambiguous*), or that is flagged as too generic to link safely (*generic*), MUST NOT be linked unless a ruling below allows it. Every withheld form MUST produce a warning at the end of the run giving counts by kind. It MUST also be listed in the link report, a file kept on disk as the GM's fix list, with every file and line where it occurs. The report is regenerated on every run, so it always reflects the current summaries.
- **FR-003a**: The rulings file (`canon.yaml`, read-only to the pipeline) MAY record, for a *generic* form only, one of two rulings: "safe to link" or "never link". Neither ruling can point a form at an entity it does not already name. *Ambiguous* forms MUST NOT be rulable. They stay withheld until the GM edits the summaries to disambiguate them (fix at source). The pipeline MUST refuse a ruling on an ambiguous form, naming the form and the entities it collides on. A ruling whose form no longer occurs in the range MUST be reported as stale. The pipeline MUST NOT write to the rulings file or to the registry. *(GM ruling, 2026-10-06.)*
- **FR-003b**: A form MUST be flagged *generic* when it is a single word that appears, case-insensitively, in a fixed standard English word list that ships with the tool. The GM's "safe to link" or "never link" ruling for that form (FR-003a) MUST override the flag. The word list's digest MUST be recorded with each linker run, so that a change to the list explains a change in links. *(GM ruling, 2026-10-06.)*
- **FR-004**: A linked scene MUST be attached whole: the scene's full authored text, verbatim, so "who else was there" is preserved. The lines that name the NPC MUST be identifiable within it, so the mention can be told apart from the scene's other participants. Every linked item MUST carry its source file, chapter, scene id (or an explicit "no scene" marker) and line. *(GM ruling, 2026-10-06.)*
- **FR-005**: Linked material MUST be labelled as a *mention*. It MUST never be labelled or counted as the NPC's presence.
- **FR-006**: Evidence MUST be ordered by summary filename chapter number, then scene id, then line. Within a chapter, the NPC's entry comes first, then linked scenes, then linked moments.
- **FR-007**: Observations MUST be whole summary paragraphs, scenes or moment items, as authored. They MUST NOT be split into atomic facts or rewritten.
- **FR-008**: Each evidence dossier header MUST be computed from the evidence: canonical name, aliases used, entity type, first-seen chapter, last-seen chapter, the list of chapters, and counts of entries, linked scenes and linked moments. First seen, last seen and the chapter list MUST include chapters where the NPC is only mentioned.
- **FR-009**: Given identical summaries, registry and rulings file, every linker output MUST be byte-identical across runs.
- **FR-010**: Linking MUST NOT change how `summary_native build` groups entities or lists possible duplicates, and MUST NOT create a dossier for a name that has no heading.
- **FR-011**: Linking MUST run the same full validation as the other summary-native stages first, and refuse on any validation error.

**Drafting (model, draft only)**

- **FR-012**: Only global NPCs, meaning entities the entity registry lists with type NPC, MAY be drafted in this feature. A heading that matches no registry NPC MUST NOT be drafted, even if it is recurring or named explicitly. An explicit name that matches no registry NPC MUST be refused with that reason. By default, a run drafts every global NPC with evidence in the chosen range. The GM MUST be able to narrow the set by explicit name, or with the existing summary-native recent and recurring rules. The selection decisions, both included and excluded with the reason (not in registry, no evidence in range, narrowed out), MUST be recorded with each run. An empty selection MUST be refused. A registry NPC whose `scope` is not `persistent` (`chapter-N`, `scene`) is local, not global, and MUST be excluded with that reason. *(GM ruling, 2026-10-06.)* A player character, meaning a character named in the campaign's `players.yaml` `plays` and resolved to a registry entity by exact name or alias, is not an NPC and MUST be excluded with the reason `player character (players.yaml)`. *(GM ruling, 2026-10-06.)*
- **FR-012a**: Linking (FR-001–FR-011) is not restricted to global NPCs. Every NPC evidence dossier is linked, so the follow-up local-NPC feature starts from complete evidence.
- **FR-012b**: In a campaign with no entity registry, drafting MUST be refused. The refusal MUST say that no global NPCs are declared and name the commands that build a registry (`registry init`, `registry import-inventory`). There is no fallback selection. Linking and verification MUST still run without a registry. *(GM ruling, 2026-10-06.)*
- **FR-013**: Drafting MUST be the only model step. It MUST support two modes: **chunked** (the default) and **one-shot** (one model call per selected NPC). In chunked mode the NPC's evidence is split by code into consecutive whole chapters up to a configured size; one *map* call per chunk returns only History, Notable Quotes and Arc-Score candidates for that chunk; code checks each map output against that chunk's evidence (citations exist in the chunk, quotes verbatim in the chunk) and drops what fails, logging every drop with its reason; code joins the survivors in chapter order; then one *reduce* call writes Identity, Personality and Motivations, Last Observed State and Relationships from the verified notes plus the last chunk's evidence. No model output reaches another model call unchecked. The default backend MUST be the local Spark model (`dgx`, `qwen3.8-flash-next`, endpoint from the existing DGX wiring), read from configuration, never a literal in code. *(GM rulings, 2026-10-06: Spark is the default because it is the cheapest; chunked is the default because it gave 2–5× the citations of one-shot Spark with none invalid.)* The input MUST be only that NPC's linked evidence, the Manual edits from its authored file (if any), and the fixed template and instructions. *(GM ruling, 2026-10-06.)*
- **FR-014**: Each draft dossier MUST follow a fixed structure in this order: computed header; identity; personality and motivations as demonstrated, with cited examples; chronological history with the party; last observed state; relationships; notable quotes. Every history item MUST end with a citation: a chapter/scene citation, or `[manual N]` for a claim taken from manual edit N.
- **FR-015**: The draft's header MUST be inserted from the computed evidence header (FR-008), not written by the model.
- **FR-016**: The "last observed state" MUST be the latest observation, labelled with its chapter. The model MUST NOT be instructed or permitted to infer a status, such as alive, dead or departed, from the absence of later mentions.
- **FR-017**: The model MUST be instructed to label unsupported claims as unsupported rather than narrate them, to keep the mentioned-versus-present distinction, to quote only verbatim text from the evidence in notable quotes (from any evidence item: entry, scene or moment; quotes **about** the NPC, spoken by anyone, each naming its speaker as the evidence gives it and citing the item it comes from, *GM rulings 2026-10-06*), and to list arc-score material only as candidate events with quoted triggers, never as values or totals.
- **FR-018**: The GM's input for each NPC MUST be a per-NPC **authored file**, `docs/npcs/authored/<slug>.authored.yaml` (FR-022a), that the GM writes and no pipeline stage ever writes. It holds **Manual edits**, a numbered list of corrections and additions, and **Secrets**, GM-only notes. The **draft dossier** is the model's synthesis of the linked evidence and the Manual edits (FR-013). The model MUST be instructed that a manual edit takes precedence over conflicting evidence, and that every claim taken from manual edit N cites `[manual N]`. The **GM dossier** is the draft dossier with the Secrets section appended (FR-018b). *(GM ruling, 2026-10-06.)*
- **FR-018a**: Secrets MUST NOT be part of any model prompt, so that secret content cannot leak into the draft dossier.
- **FR-018b**: A deterministic compose step that calls no model MUST produce the **GM dossier** from the draft dossier and the authored file's Secrets, with the Secrets reproduced byte-for-byte under an explicit Secrets heading. Compose MUST NOT modify either source. It MUST be runnable for one NPC, a named set, or every NPC with a draft dossier. Drafting MUST compose the GM dossier for each NPC it drafts or skips as unchanged, so publishing always reads a current GM dossier. A change to Secrets alone MUST be applied by re-composing, without a model call. Composed documents are regenerated on every compose. A hand-edit to one MUST be reported as unrecorded, because the next compose discards it.
- **FR-018c**: A deterministic check MUST confirm that every manual edit was used. Each manual edit N MUST be cited as `[manual N]` at least once in the draft dossier. An uncited manual edit MUST be reported as *dropped*, with its text, and a citation to a manual edit that does not exist MUST be reported as invalid. Both make the verification verdict fail. The check confirms that each edit was used, not that its meaning survived the rewrite; the report MUST say so, so the GM knows to read the cited passages. *(GM ruling, 2026-10-06.)*
- **FR-019**: A draft missing any template section, or truncated, MUST NOT be written as a draft. It MUST be kept separately and reported, naming the missing sections.
- **FR-020**: Drafting MUST go through the project's standard model-access layer and accept the standard backend and model options, including a local DGX endpoint. It MUST NOT require any particular credential unless the chosen backend needs one.
- **FR-021**: Drafting MUST refuse when any summary in the range has changed since the evidence was linked, and direct the GM to re-link.

**Leaf output and promotion**

- **FR-022**: Drafting MUST write draft dossiers only under `docs/npcs/summary_native/`, and compose MUST write GM dossiers only there. Neither MAY modify `docs/npcs/distilled/`, any file directly in `docs/npcs/`, any evidence dossier, any authored file, or any other live grounding document. Only publishing (FR-031) writes to `docs/npcs/`.
- **FR-022a**: `docs/npcs/` MUST hold only the **published NPC dossiers** directly, one file per NPC (`docs/npcs/<slug>.md`). That is where the gm-assistant skills read them. Its generated subdirectories MUST hold only generated and tool data, one per approach: `docs/npcs/distilled/` for the distilled dossiers (the approach being retired) and `docs/npcs/summary_native/` for this feature's evidence, drafts, GM dossiers, run records and reports. Everything a person creates MUST live in a separate `docs/npcs/authored/`: this feature's per-NPC `<slug>.authored.yaml` (Manual edits and Secrets) and hand-built NPC dossiers such as `gm-npc-build` output (`<slug>.md`). Clearing a generated subdirectory can then never delete human-created material. *(GM rulings, 2026-10-06.)*
- **FR-022b**: Moving distilled dossiers out of `docs/npcs/` into `docs/npcs/distilled/` is a change of shape on disk. It MUST be done by a separate one-shot migration command the GM runs deliberately (Constitution XIII), in two steps. It leaves `docs/npcs/authored/` alone, as it does `distilled/` and `summary_native/` *(GM ruling, 2026-10-06)*:
  1. **Propose (dry run).** Writes a classification file listing every entry directly in `docs/npcs/` (except `distilled/`, `summary_native/` and `authored/`), each with a proposed disposition and its evidence. Dispositions are `distilled` (move to `distilled/`), `authored` (a hand-built dossier; move to `authored/`) and `unknown`. The evidence is: the presence of the distilled pipeline's `source_extracts:` frontmatter marker; from git, the commit that added the file (sha, date, subject); every later commit that changed it; and whether the file has changed since it was added. A file carrying the marker is proposed `distilled`; sidecars and merge-state files follow their dossier or are proposed `distilled`; everything else is proposed `unknown` unless its evidence is unambiguous. The proposal MUST NOT infer from commit-message wording alone, so it is evidence for the GM, not a decision. A distilled file changed since it was added is flagged `hand-edited`, so the correction is not lost. Outside a git repository, the git evidence is reported as unavailable and the marker alone drives the proposal.
  2. **Apply.** Reads the GM-reviewed classification file and moves every `distilled` entry to `distilled/` and every `authored` entry to `authored/`, unchanged. It MUST refuse while any entry is `unknown`, or when the file no longer matches what is on disk. It MUST refuse to clobber without the standard overwrite option, and report anything it does not recognise rather than drop it.
  The feature MUST ship a migration document (`specs/032-npc-dossiers-from-summaries/migration.md`, plus operator instructions in `docs/`).
- **FR-022c**: Every existing tool that reads or writes distilled dossiers (the alias scan used by the render CLIs, `planning --build-dossiers`, and any other consumer found in planning) MUST be pointed at `docs/npcs/distilled/`. Such a tool MUST refuse, with the migration command in its message, when `docs/npcs/` directly holds any `.md` file **without** the publishing provenance header (FR-031), because that is unmigrated (or not yet classified) material. Published dossiers never count as unmigrated, so a campaign that never had distilled dossiers keeps working after its first publish. A tool MUST also refuse when it is configured to read `docs/npcs/` itself, because that directory holds published dossiers, not distilled ones. A missing `docs/npcs/distilled/` with nothing unmigrated means no distilled dossiers, not an error. There is no dual-location fallback.
- **FR-022d**: No existing tool's alias scan or dossier read MAY pick up anything under `docs/npcs/summary_native/`, or treat a published dossier in `docs/npcs/` as an identity source. Drafts and GM dossiers are output; identity comes from the registry and the summaries.
- **FR-023**: No pipeline stage, including planning synthesis, MAY read a draft dossier or a GM dossier. Planning MUST keep reading the deterministic evidence dossiers. A dossier reaches any model-driven consumer (the gm-assistant skills) only through publishing, which is the GM's review checkpoint.
- **FR-031**: Publishing MUST be an explicit, deterministic GM act that calls no model. It copies the GM dossier (draft dossier plus Secrets) of each named NPC to `docs/npcs/<slug>.md`, where `<slug>` is the lowercase, hyphenated canonical name (the gm-assistant convention). It MUST require explicit names or an explicit "all" (Constitution X). Each published file MUST carry a provenance header naming the chapter range, the draft run, the digests of the draft and authored file, and the verification verdict. *(GM ruling, 2026-10-06.)*
- **FR-031a**: Publishing MUST refuse, unless the standard overwrite option is given: an NPC whose verification failed; a target file that this feature did not publish; and a previously published file that was edited by hand since it was published. Each refusal MUST name the file and the reason.
- **FR-031b**: Publishing MUST rewrite every `[manual N]` citation to a self-contained `[GM]` tag and keep every chapter/scene citation unchanged, so a published file never refers to a list it does not contain, and readers can still tell a GM ruling from table history. The rewrite is deterministic. The draft and GM dossiers keep the numbered form, so verification (FR-018c) is unaffected. *(GM ruling, 2026-10-06.)*
- **FR-031c**: Publishing MUST also publish hand-built NPC dossiers. For a named NPC with a hand-built `docs/npcs/authored/<slug>.md` and no GM dossier in the chosen range, publishing copies the file verbatim to `docs/npcs/<slug>.md` below a provenance header marking it hand-built. It MUST support an explicit "every hand-built dossier" selection, so the skills can see hand-built NPCs again after the migration. An NPC with both a hand-built dossier and a GM dossier MUST be refused, with both paths named, until the GM picks one with an explicit option. Verification does not apply to hand-built dossiers, and the header says so. *(GM ruling, 2026-10-06.)*

**Verification (deterministic, no model)**

- **FR-024**: For every draft, the pipeline MUST check that each chapter/scene citation exists in the corpus (*invalid* otherwise) and in that NPC's own evidence dossier (*outside-evidence* otherwise), that each quoted passage appears verbatim in the summaries (curly and straight quote marks and apostrophes compared as equal, each such case listed as *typography-normalised*) and that every history item carries a citation (*uncited* otherwise). A history bullet with nested bullets under it is a label: it needs no citation of its own when every bullet nested under it is cited. All of these fail the verdict. It MUST report every failure with its location in the draft, and totals. It MUST NOT call a model or modify the draft. Wording that asserts a status (for example alive, dead or killed) that appears nowhere in the NPC's evidence MAY be reported as an advisory warning that does not change the verdict.
- **FR-025**: The verification report MUST be produced for every draft run, regardless of backend, so drafts of the same evidence from different backends can be compared.

**Provenance, incrementality and overwrite**

- **FR-026**: Each draft run MUST retain the exact prompts (system and user) for each NPC, a digest of each NPC's input evidence and Manual edits, the chapter range, the selection decisions, the backend and model used, and the digests of the registry and rulings file that linking read.
- **FR-027**: A re-run MUST re-draft only NPCs whose evidence, Manual edits, prompt, template, backend or model differs from their last successful draft. A change to Secrets alone MUST NOT trigger a re-draft. The run MUST report each NPC as re-drafted or skipped, with the reason. The standard overwrite option MUST force every selected NPC to re-draft.
- **FR-028**: Existing draft dossiers MUST NOT be overwritten except as FR-027 allows. The link report, the verification reports and the GM dossiers are regenerated on every run. Authored files are never written.

**Interfaces**

- **FR-029**: Every new stage MUST be runnable from the command line as part of the summary-native tool, with option names and defaults that follow the existing summary-native and project vocabulary (range, registry, rulings file, backend/model, overwrite).
- **FR-030**: Every command-line capability of these stages MUST be reachable from a dedicated NPC dossiers page in the web UI, separate from the summary-native grounding-documents page. The page MUST invoke the command-line tool with explicit arguments, MUST NOT reimplement its logic, and MUST NOT hardcode a flag the CLI leaves to the GM. Publishing MUST be reachable from the page as well as the CLI. Judgment between stages (reviewing drafts, ruling on name forms, editing authored files) MUST stay outside the UI. *(GM ruling, 2026-10-06.)*

### Key Entities

- **Name form**: a string that names an NPC. It is a summary heading or an exact, same-type registry alias. It is linkable, or held as ambiguous or too generic pending a GM ruling.
- **Linked item**: a scene or memorable moment that names an NPC, with file, chapter, scene id (or "no scene"), line, and the "mention" label.
- **Linked evidence dossier**: an NPC's `## NPCs` entries plus linked items in authored order, under a computed header. Deterministic. It is the only evidence input to drafting.
- **Link report**: forms withheld from linking (ambiguous or generic, plus each generic form's ruling status), stale rulings, and names mentioned without any heading, each with file and line. A persisted GM fix list, regenerated each run.
- **Rulings file**: the existing summary-native, hand-authored rulings file (`canon.yaml`). Read-only to the pipeline.
- **Global NPC**: an entity the entity registry lists with type NPC and `scope: persistent`, that is not a player character declared in `players.yaml`. It is eligible for drafting in this feature.
- **One-off NPC**: an NPC heading in the summaries with no registry NPC entry. It is linked but not drafted here. Deferred to the local-NPC feature.
- **Draft selection**: which global NPCs a run drafts and why, recorded per run.
- **Draft record**: per run, the prompts, evidence digests, selection, range, backend, model and input-file digests.
- **Authored file**: per NPC, GM-written Manual edits (a numbered list) and Secrets. Read-only to every pipeline stage. Manual edits feed drafting; Secrets feed only the GM dossier.
- **Draft dossier**: per NPC, the model's synthesis of evidence and Manual edits, in the fixed structure (FR-014). Contains no Secrets. Stays a draft until published.
- **GM dossier**: the draft dossier with the authored Secrets appended, composed deterministically under `docs/npcs/summary_native/`.
- **Published NPC dossier**: a GM dossier the GM has published to `docs/npcs/<slug>.md`, with a provenance header. The only form model-driven consumers (the gm-assistant skills) read.
- **Manual-edit check**: the deterministic report of which manual edits the draft dossier cites, which it dropped, and any invalid `[manual N]` citations.
- **Verification report**: per draft, invalid citations and non-verbatim quotes with locations and totals.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the Out of the Abyss corpus (chapters 2–70), linked evidence dossiers for the eight measured NPCs carry these entries / scenes / moments: Jimjar 33/71/43, Glabbagool 30/94/48, Eldeth Feldrun 24/36/8, Stool 16/0/0 (withheld as generic until ruled safe), Sarith Kzekarit 13/33/15, Buppido 12/32/28, Ilvara Mizzrym 6/26/14, Jorlan Duskryn 4/10/4. Each withheld form is listed in the link report. *(Re-derived with this feature's linker on 2026-10-06, with moment boundaries per research R3; GM ruling replaced the proposal's scratch counts, whose moment figures (Jimjar 17) used an unrecorded rule. Taken before the Dawnbringer refiling, which changes only Dawnbringer's own counts; re-take if the corpus changes.)*
- **SC-002**: Ilvara's evidence dossier covers 10 chapters, compared with 6 before linking.
- **SC-003**: Two linker runs on unchanged input produce byte-identical output (100% of files). The linker makes zero model calls.
- **SC-004**: Zero links are made through a form that is not a heading or an exact same-type registry alias. Every seeded ambiguous form in the test corpus appears in the link report and links nothing.
- **SC-005**: Zero files under `docs/npcs/distilled/`, zero evidence dossiers, zero authored files and zero other live documents are modified by any draft or compose run.
- **SC-005a**: After the migration on toee and stormgiants (the campaigns that have a `docs/npcs/`), zero unpublished dossier files remain loose in `docs/npcs/`, and every moved file is byte-identical under the folder its disposition names (`distilled/` or `authored/`). Deterministic reads of those dossiers give the same results before and after the migration: `registry check`, the alias map loaded from the distilled dossiers, and the planning synthesis prompt written by `planning --dump-input FILE --dump-only` (no model call).
- **SC-006**: 100% of history items in every written draft carry a chapter/scene citation, and 100% of drafts pass the section-completeness check before being written.
- **SC-007**: The verification check reports 100% of seeded invalid citations, non-verbatim quotes, dropped manual edits and invalid `[manual N]` citations, with zero false reports on a dossier where all of them are valid.
- **SC-008**: Zero drafts assert a status (alive, dead, departed) that no observation in the evidence states.
- **SC-009**: A re-run after editing one summary that mentions one selected NPC re-drafts exactly that NPC and reports the rest as unchanged.
- **SC-010**: Every draft can be reproduced from its retained record alone: the same prompts can be re-issued without consulting anything else.
- **SC-011**: On the Out of the Abyss corpus, the GM judges draft dossiers for at least three recurring NPCs more useful for session prep than the current evidence-only dossiers.
- **SC-012**: Zero files directly in `docs/npcs/` are written by any stage except publishing, and zero files under `docs/npcs/authored/` are written by any stage. A published NPC is found by the gm-assistant skills at `docs/npcs/<slug>.md` with no change to those skills, and contains zero `[manual N]` references.
- **SC-013**: On toee and stormgiants, the migration proposal lists 100% of `docs/npcs/` entries with evidence, and `--apply` refuses while any entry is `unknown`. Every moved file is byte-identical at its new path.

## Clarifications

### Session 2026-10-06

- Q: What does a link attach? → A: The whole scene, verbatim, with the lines that name the NPC identifiable inside it (FR-004).
- Q: Do creatures filed under `## NPCs` get rendered dossiers? → A: Only if the registry lists them as NPCs. Registry NPCs are global and rendered here. Everything else is a one-off, linked but not rendered (FR-012, FR-012a).
- Q: Does this feature ship a web UI surface? → A: Yes, on a dedicated NPC dossiers page, separate from the grounding-documents page, because NPCs and grounding documents are different things (User Story 5, FR-030).
- Q: What does rendering do with no entity registry? → A: It refuses and names the registry-building commands. Linking and verification still run (FR-012b).
- Q: When the linker withholds a name form, what can a GM ruling say? → A: A generic form can be ruled "safe to link" or "never link". An ambiguous form can't be ruled: it's fixed by editing the summaries. Every withheld form raises a run-end warning and is logged in the persisted link report as a fix list (FR-003, FR-003a).
- Q: How does the linker decide a form is too generic to link safely? → A: An automatic rule (a single word found in a fixed standard English word list) flags candidates, and the GM's per-form rulings override it (FR-003b).
- Q: Should a dossier show GM-only secrets, and where are they written? → A: In one document per NPC with three parts: Manual edits (read first), Secrets, and the auto-generated part. A publish step produces a copy without the Secrets section (FR-018, FR-018a, FR-018b).
- Q: Are manual edits and secrets typed into the dossier itself, or kept in a separate file it is built from? → A: In a separate per-NPC authored file that no pipeline writes. A compose tool combines the authored file and the Generated part into the GM dossier, and into a published copy without secrets (FR-018, FR-018b).
- Q: Where do composed NPC dossiers live relative to `docs/npcs/`? → A: `docs/npcs/` gets two subdirectories: `distilled/` for the existing distilled dossiers (being retired) and `summary_native/` for this feature's files. Moving the existing files is a Constitution XIII migration (FR-022a–FR-022d).
- Q: Which step synthesises the dossier? → A: Publishing (this step was later renamed **draft**; see below). It is the only model step: one call per NPC over the evidence plus Manual edits (never Secrets), with manual edits taking precedence and cited as `[manual N]`. A deterministic check reports any manual edit the output dropped. The GM dossier is the published dossier with Secrets appended, composed without a model. This supersedes the earlier "three parts, Manual edits read first" composition (FR-013, FR-018–FR-018c, FR-027).
- Q: Are registry NPCs with a local scope (`chapter-N`, `scene`) global? → A: No. They are kept out of publishing until this feature is finished; local NPCs belong to the follow-up feature (FR-012).
- Q: Does the NPC output root get a per-run control? → A: No. `npc_root` lives only in `npc_dossiers.yaml`. A configuration-management page is filed as #502 for later.
- Q: Which version do the gm-assistant skills read? → A: The GM dossier, Secrets included. They are GM tools, and some need GM-only facts.
- Q: How does a dossier reach the skills? → A: By explicit publishing (`npc-publish`, deterministic, no model). The reviewed GM dossier goes to `docs/npcs/<slug>.md`, where the skills already read. `docs/npcs/distilled/` and `docs/npcs/summary_native/` hold only generated and tool data. The model step is renamed **draft**. *(FR-022a, FR-023, FR-031.)*
- Q: How does the migration tell distilled files from hand-built ones? → A: A dry run proposes a disposition for each file from git evidence (the adding commit, later edits, whether it changed) and the `source_extracts:` marker. The GM reviews and edits the classification file, and the apply step follows it, refusing while any entry is `unknown` (FR-022b). This supersedes an interim "move everything" answer.
- Q: Do citations survive into the published `docs/npcs/<slug>.md`? → A: Chapter/scene citations stay. `[manual N]` becomes `[GM]` at publish time, because the published file does not contain the numbered list (FR-031b).
- Q: Where do authored files live? → A: `docs/npcs/authored/<slug>.authored.yaml`: GM-owned and separate from the generated subdirectories (FR-022a).
- Q: What goes in `docs/npcs/authored/`? → A: Everything a person creates: the `.authored.yaml` files and hand-built NPC dossiers such as `gm-npc-build` output. The migration's hand-built disposition moves files there (FR-022a, FR-022b).
- Q: How does a hand-built NPC in `authored/` reach the skills? → A: `npc-publish` copies it verbatim to `docs/npcs/<slug>.md` with a hand-built provenance header, deterministically, with an explicit "all hand-built" selection for after the migration (FR-031c).
- Q: Does publishing have a UI button? → A: Yes. Publish exists both at the CLI (`npc-publish`) and as a button on the NPC dossiers page, with identical selection rules and refusals (FR-030, User Story 5).
- Q: How are local and temporal NPCs handled? → A: In a separate, follow-up feature with a registry scoped by time and place. See Out of Scope.
- Q: How are player characters kept out of NPC drafting, given the registry has no PC type and OOTA files Daz, Gyrgum, Zalthir and Thorin as `npc`? → A: Exclude any character named in `players.yaml` `plays` (exact name or alias); reason `player character (players.yaml)`.
- Q: Dawnbringer is a thinking sword filed as both item (25) and NPC (5), so it is withheld as ambiguous. → A: It is an NPC. Fix at source in the campaign: registry `type: npc`, its `## Items` entries refiled under `## NPCs`. No pipeline change.
- Q: OOTA has a real NPC named `Y`, a one-letter form that is not in the word list. → A: Not handled in this feature; Y has not appeared yet. Tracked in CampaignGenerator#503 (likely an explicit tag in the summary).
- Q: The linker's OOTA moment counts exceed the proposal's scratch counts (Jimjar 43 vs 17; every one names him). Which are SC-001? → A: The linker's counts replace the scratch counts.
- Q: Should Notable Quotes be only the NPC's own words? (Ilvara's moments are almost all other characters speaking about her.) → A: No. Quotes about the NPC, by anyone, verbatim from moments, each attributed to its speaker as the moment gives it.
- Q: Which model drafts by default? → A: The local Spark model (`dgx`, `qwen3.8-flash-next`): it is the cheapest. Sonnet 5.5 read better; it stays available by flag.
- Q: Chunked or one-shot drafting by default? → A: Chunked by default, one-shot kept as an option (FR-013).
- Q: Sonnet and Opus group History under label bullets (`- Ch 5:`) with cited points nested beneath. Does a label need its own citation? → A: No, when every bullet nested under it is cited.
- Q: Should the verbatim check treat curly and straight quote marks and apostrophes as equal? → A: Yes, and report each such quote as `typography-normalised`. The summaries mix both styles; the transcripts have none. Fixing the summaries at source is kostadis/campaigns#371.
- Q: Must Notable Quotes come from memorable moments? → A: No. Any quote verbatim in the NPC's evidence is fine (entry, scene or moment), cited to the item it comes from.
- Q: Quoted spans inside History bullets and Arc candidates were not checked per chunk, so paraphrases in quote marks reached the draft and failed verification. → A: The chunk check verifies them and drops a bullet whose span is not verbatim. Nested single/double quotes and a comma or period just inside the closing mark count as typography-normalised.

## Assumptions

- The summaries, the summary-native corpus, its validation, its chapter-range rules and its selection rules from spec 031 exist and are reused unchanged. Linking runs after `summary_native build`.
- The entity registry is the authority for exact aliases and for which NPCs are global. Without a registry, linking matches only the NPC's own headings, and drafting is refused (FR-012b).
- The standard English word list used by FR-003b is pinned and ships with the tool rather than coming from the operating system, so linking stays byte-identical across machines. Which list is a planning decision.
- Default selection thresholds follow 031 (recent ≈ last 4 chapters; recurring ≥ 10 observations) and are configurable.
- The largest global NPC evidence pack in Out of the Abyss (Glabbagool, about 431K characters, about 105K tokens) fits the Spark's 262K context in one-shot mode. Chunked mode is the default anyway, for coverage, not for fit.
- Drafting defaults to the same backends and models as the other grounding-doc tools.
- Single-user system: no concurrent runs against the same output location.

## Out of Scope

- Creating or editing summaries.
- Changing how `summary_native build` groups entities or lists possible duplicates.
- Replacing the world_state, campaign_state, party or planning drafts.
- Merging, deleting or rewriting the content of existing distilled dossiers. FR-022b moves them unchanged; it does not edit them.
- Retiring the distilled approach itself. Its dossiers move to `docs/npcs/distilled/` and keep working.
- Building a graph store.
- Automating publishing: it is always an explicit GM act per NPC or an explicit "all".
- Changing the gm-assistant skills. They already read `docs/npcs/<slug>.md`.
- **Local and temporal NPCs (the next feature).** The registry is global today. It has no notion of an NPC that matters only in one region or one stretch of chapters, such as a dungeon's cast once the party has left. A registry that is scoped by time and place, and drafting of the one-off and local NPCs that such a registry would cover, are a separate feature. This feature's computed footprint per NPC (first seen, last seen, chapter list) is evidence that feature can start from.
