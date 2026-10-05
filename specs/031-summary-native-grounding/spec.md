# Feature Specification: Summary-Native Grounding Docs

**Feature Branch**: `031-summary-native-grounding`

**Created**: 2026-10-05

**Status**: Draft

**Input**: User description: "https://github.com/kostadis/CampaignGenerator/issues/499 describes another approach to create grounding docs from session summaries. I want you to implement that as another distinct approach. The system should assume the existence of a set of files that are in the right format in a directory that is specified. In other words, how the summaries get created is not part of this feature, this feature should assume the summaries exist."

## Context

The campaign's grounding documents (world state, campaign state, party, planning) are currently produced by the ensemble path: a model re-reads chapter/session prose, extracts atomic facts, and synthesis builds the documents from those facts. Issue #499 records a prototype against Out of the Abyss that skipped re-extraction entirely. It read the campaign's already-reviewed structured session summaries, parsed their declared structure (a scene spine, entity sections, memorable moments) without a model, and only then called a model to write each document. The GM judged the results "fantastic — much better than the other ones we have built" and promoted all four drafts to live use.

This feature makes that approach a **distinct, supported pipeline** that sits beside the existing ensemble path. It does not replace or change the existing path.

**Out of scope by explicit instruction:** how the structured summaries are produced. The pipeline starts from a directory of summaries that already exist and are already in the expected format. It validates that format and reports problems. It never writes, repairs or regenerates a summary.

**Precision-decision accounting (Constitution II):** the deterministic stages (validation, parsing, chronology, dossiers, selection) remove no decisions from the human because they only restate declared structure. Which headings name the same entity is an identity decision. The pipeline only lists likely duplicates, and the GM resolves them by correcting the summary files (or by ruling a pair distinct). Nothing is merged by a model or a similarity score, and no misspelling is ever mapped as an alias. Each synthesis call makes a rendering decision only. Its output is a draft, and a human must review it before it is promoted or fed into a later document's synthesis.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Validate and parse a summary corpus into a lossless evidence corpus (Priority: P1)

The GM points the pipeline at a directory (or file pattern) of structured session summaries. The pipeline checks every file's identity and structure and writes a report. It then produces, with no model call, a chronological scene spine, a memorable-moments collection, and one dossier per entity. Every dossier holds every observation of that entity, each tagged with where it came from.

**Why this priority**: Every later document depends on this corpus. On its own it is already useful: the GM gets a complete, ordered, searchable record of the whole campaign in seconds rather than the 7–10 hours the extraction route projected. It costs no tokens and decides nothing on the GM's behalf.

**Independent Test**: Run against the Out of the Abyss summaries directory (67 files). Confirm the validation report, chronology, memorable moments and dossiers are produced. Confirm that re-running gives byte-identical output. Separately, confirm that the unfixed chapter-070 file (title says "Chapter 66") makes the run refuse, naming the file.

**Acceptance Scenarios**:

1. **Given** a directory of 67 well-formed summaries, **When** the GM runs the parse stage, **Then** all 67 are parsed and every `### <scene>` heading appears in the chronology in chapter-then-scene order.
2. **Given** a summary whose filename says chapter 70 but whose title line says "Chapter 66", **When** that chapter is inside the selected range, **Then** the run fails loudly before writing any corpus or draft artifact (only the validation report is written). The report names the file, both chapter numbers, and what to fix. Nothing guesses which number is right; the GM corrects the summary and re-runs.
3. **Given** a summary with no `## Scenes` section, or a filename with no numeric chapter prefix, **When** the corpus is validated, **Then** the report names the file and the specific problem, and the file is not silently processed as one undifferentiated block.
4. **Given** a corpus where five files have problems of different kinds (a title/filename conflict, a missing `## Scenes`, a duplicate scene id, a scene id from another chapter, two files sharing a chapter number), **When** the GM runs validation, **Then** one run reports every problem in every file in a single report, grouped by file. It does not stop at the first error, and fixing them takes one pass rather than five re-runs.
5. **Given** any corpus, **When** the GM runs validation alone, **Then** the full report is produced without writing any corpus artifact or calling any model, so the GM can check the summaries before committing to a run.
6. **Given** the same input directory, **When** the parse stage is run twice, **Then** every artifact it writes is byte-identical across runs.
7. **Given** an entity that appears under `## NPCs` in 12 chapters, **When** its dossier is produced, **Then** it contains all 12 observations. Each one records the source file, the chapter, the heading as written, the category, and the scene it falls under where the summary places it in one.
8. **Given** a directory of chapters 2–70, **When** the GM selects chapters 2–40, **Then** only those summaries are parsed and synthesised (files outside the range are still scanned, and their problems are reported as non-blocking). The drafts describe the campaign as of chapter 40, with no content from chapters 41–70 in the corpus, any prompt or any draft. The validation report may name out-of-range files and their problems. The chosen range is recorded in the manifest and in every draft's provenance.
9. **Given** a run for chapters 2–40 already exists, **When** the GM runs chapters 2–70, **Then** neither run's corpus or drafts overwrite the other's.

---

### User Story 2 - Draft world state and campaign state from the corpus (Priority: P1)

From the evidence corpus, the GM generates a world-state draft and then a campaign-state draft. The campaign-state draft can also take the campaign's tracking or planning files. It treats them as *questions to check*, not as evidence. Each tracked claim is either supported by the summaries or labeled as not found in them.

**Why this priority**: These two documents are the core of the issue and the ones where the prototype's improvement was largest (coverage through the latest chapter, correct key-item state, no module defaults imported as history).

**Independent Test**: Run on the Out of the Abyss corpus. Confirm a world-state draft and a campaign-state draft are written as drafts beside, not over, the live documents. Confirm the exact prompts and selection manifest are retained. Confirm that a tracking claim with no support in the summaries is labeled unsupported rather than stated as fact.

**Acceptance Scenarios**:

1. **Given** a parsed corpus, **When** the GM runs world-state synthesis, **Then** the prompt includes every entity observed in the most recent chapters plus recurring background entities, the complete chronology, and the memorable moments, and the selection that was made is recorded in a manifest.
2. **Given** a tracking file asserting an event that no summary records, **When** campaign-state synthesis runs, **Then** the draft labels that claim as not found in the summaries and does not present it as campaign history.
3. **Given** a reviewed world-state draft, **When** campaign-state synthesis runs, **Then** it uses that draft as context only once the GM has explicitly designated it as reviewed. It never consumes an unreviewed draft automatically.
4. **Given** any synthesis run, **When** it completes, **Then** a draft file is written and the live grounding document is not modified.

---

### User Story 3 - Find duplicate entity headings so the GM can fix the summaries (Priority: P2)

Different summaries sometimes name the same entity differently: a typo ("Manshon"), or an inconsistent qualifier ("Manshoon (Simulacrum)"). These are errors in the summaries. **The fix is to correct the summary files, not to map one name onto another.** The pipeline finds likely duplicates within each category (NPC, location, item, spell, …) using deterministic similarity, and lists them, with every file and line where each spelling occurs, in the same validation report the GM already works through (US1). The GM either corrects the summaries or records that the pair is genuinely two different things, in a small hand-authored rulings file (`canon.yaml`), so the pair is not flagged again. Neither a model nor a similarity score ever merges two headings.

Legitimate alternate names (an approved alias such as a title or full name) are the entity registry's job, not this file's. Exact registry aliases group headings within matching categories. The registry does not carry spells, so spells are only ever grouped by identical heading.

**Why this priority**: The prototype left near-duplicate dossiers among 868. Surfacing them as a fix list cleans the source for every later run. It is not a blocker for drafting.

**Independent Test**: Run on a corpus seeded with a typo duplicate and a genuinely distinct look-alike. Confirm both are listed with file and line, and that nothing merges. Fix the typo in the summary, record the look-alike as not-a-duplicate in `canon.yaml`, re-run, and confirm the list is empty and the dossiers are correct.

**Acceptance Scenarios**:

1. **Given** two headings in the same category that the registry lists as exact aliases (a non-spell category), **When** dossiers are built, **Then** their observations land in one dossier under the registry's canonical name and each observation keeps its original heading.
2. **Given** two similar headings with no registry relationship, **When** the corpus is validated, **Then** they are listed as a possible duplicate with every file and line where each spelling occurs, and they stay as separate dossiers.
3. **Given** the GM corrects the misspelling in the summary file, **When** the pipeline runs again, **Then** the pair is no longer listed and the dossiers combine because the headings now match.
4. **Given** a pair the GM recorded as not-a-duplicate in `canon.yaml`, **When** the pipeline runs again, **Then** that pair is not listed again.
5. **Given** two headings with the same name in different categories (a spell and an item), **When** the corpus is built, **Then** they are never combined and never listed as duplicates of each other.

---

### User Story 4 - Draft party and planning documents (Priority: P3)

The GM generates party and planning drafts from the corpus, the party configuration, the character sheets and backstories, the planning configuration, and the reviewed world and campaign drafts. If no planning arc scores are configured, the Threat Tracker stays empty rather than being invented.

**Why this priority**: The prototype produced and the GM promoted both documents, but they depend on Stories 1–2 and on campaign files outside the summaries.

**Independent Test**: Run on Out of the Abyss. Confirm the party draft's level matches the last recorded level-up in the summaries. Confirm the planning draft's Threat Tracker is empty when the planning configuration declares no arc scores. Confirm the list of NPC dossiers chosen for planning is recorded.

**Acceptance Scenarios**:

1. **Given** the corpus and party configuration, **When** party synthesis runs, **Then** any character-state claim the summaries do not support (e.g. a level not recorded as reached) is corrected or flagged rather than carried forward.
2. **Given** a planning configuration with no arc scores, **When** planning synthesis runs, **Then** no scores are invented and the Threat Tracker is empty.

---

### User Story 5 - Run the pipeline from the web UI (Priority: P3)

Every stage reachable from the command line is also reachable from the web UI. The GM chooses the summaries location, runs each stage, sees the validation report (including possible duplicates), and sees which drafts were written. The judgment between stages (reviewing drafts, ruling on merges, promoting) stays in files, the CLI, or chat.

**Why this priority**: Required for CLI/UI parity (Constitution XI), but the pipeline delivers value from the CLI first.

**Independent Test**: From the UI, choose the Out of the Abyss summaries directory, run parse and world-state synthesis, and confirm the same files appear as a CLI run produces.

**Acceptance Scenarios**:

1. **Given** the summary-native pipeline page, **When** the GM runs a stage, **Then** the UI calls the same command-line tool with explicit arguments and shows the files that tool wrote.
2. **Given** no summaries location configured, **When** the GM tries to run, **Then** the run is refused with a message saying a location must be chosen. Nothing defaults to an implicit "all".
3. **Given** the summaries location, **When** the GM opens the pipeline page, **Then** the GM can choose a start and end chapter from the chapters actually present. "All chapters" is a deliberate choice that fills in the full range, never the state an untouched picker falls into.

---

### Edge Cases

- **Filename vs. title chapter conflict**: hard failure for in-range files. The run refuses before writing any corpus or draft artifact (only the validation report is written) and names every conflicting file. There is no override: the GM fixes the summary.
- **Two files claiming the same chapter number**: refuse, naming both files. Ordering would be ambiguous.
- **A file missing `## Scenes`, or with no scene headings under it**: reported as a structural error. The file is never chunked as a whole document. The run refuses.
- **Scene heading whose id does not match its file's chapter** (e.g. `### 066.02` inside `070-…md`): hard failure, the same as a title conflict.
- **Duplicate scene ids within one file**: reported as an error.
- **Very long scenes**: any subdivision made only to fit a model call never replaces or renumbers the original scene id. Every derived piece keeps the scene id it came from.
- **Optional sections absent** (`## Memorable Moments`, `## Spells`, `## Abilities`, `## Session-End State`): accepted. The absence is recorded in the manifest and is not an error.
- **Unrecognised H2 sections**: preserved in the corpus and listed in the report rather than dropped silently.
- **Entity observation outside any scene** (entity appendices sit after `## Scenes`): recorded with its chapter and category and an explicit "no scene" marker. No scene is ever guessed.
- **Mixing corpora**: if the output location already holds chapter/ensemble-derived artifacts, or the input set includes them, the run refuses. Summary-derived and chapter-derived facts must never be double-counted.
- **Synthesis output longer than one model response**: detected by the outline check and never saved as a draft. The GM re-runs it in explicit, declared parts that are assembled, rather than relying on an implicit continuation.
- **Re-running over existing drafts**: an existing draft is not overwritten unless the GM passes the standard overwrite flag.
- **Empty or missing input directory**: refused with a clear message. No output is written.
- **Range bound that matches no file** (e.g. a start of chapter 1 when the first file is 002): refused, naming the chapters actually present. A bound is never silently snapped to the nearest file.
- **Start after end, or a range containing no files**: refused.
- **Gaps inside a range** (a chapter number with no file): allowed. The missing numbers are listed in the validation report and the manifest so the GM can see them, and they are not an error.
- **Errors in files outside the selected range**: still scanned and listed, in a separate "outside range — not blocking" section, so the whole directory can be fixed in one pass. They do not stop the run. The exception is duplicate chapter numbers anywhere in the directory, which do block, because they make the range itself ambiguous.

## Requirements *(mandatory)*

### Functional Requirements

**Input & validation**

- **FR-001**: The pipeline MUST take its input as an explicitly specified directory or file pattern of structured session summaries. It MUST NOT create, edit, repair or regenerate any summary file.
- **FR-002**: The pipeline MUST require each file's numeric filename prefix, its title-line chapter number, and the chapter part of every scene id to agree. Any disagreement in a file inside the selected range MUST fail the run loudly before any corpus or draft artifact is written (out-of-range files are reported non-blocking per FR-005c; duplicate chapter numbers block wherever they occur), naming the file and the conflicting values. The pipeline MUST NOT pick a winner, and there is no override. The fix is to correct the summary.
- **FR-003**: The pipeline MUST validate the expected summary structure (a title line and a `## Scenes` section with `### <scene>` headings, both required; entity sections such as `## NPCs` are optional and recognised when present). It MUST produce an actionable validation report naming each file and each problem.
- **FR-004**: The pipeline MUST NOT fall back to treating a file as one undifferentiated block when scene identity would be lost. Any in-range file that fails validation MUST stop the run before any corpus or draft artifact is written. There is no per-file exclusion or override.
- **FR-005**: The pipeline MUST refuse a run in which two files claim the same chapter, an input directory is empty, or no input location is given.
- **FR-005a**: Validation MUST scan every input file and collect every problem across the whole corpus before reporting. It MUST NOT stop at the first failing file or the first error within a file. The report MUST list each non-conforming file with all of its problems (file, location in the file, problem, expected vs. found), end with a summary count of failing files and errors, and also be written to a file the GM can work through.
- **FR-005b**: Validation MUST be runnable on its own, writing nothing except the report and calling no model. Every later stage MUST run the same full validation first and refuse on any error. Synthesis MUST also refuse when any summary in the range has changed since the corpus was built (its content digest differs from the corpus manifest), directing the GM to rebuild.
- **FR-005c**: The GM MUST be able to restrict a run to an inclusive range of chapters (start and end chapter, taken from filename prefixes). Parsing, selection and synthesis MUST then consider only summaries inside that range. Only errors in files inside the range MAY block the run, but validation still scans and reports the rest of the directory as non-blocking (FR-005a). No content from a chapter outside the range MAY appear in any artifact or prompt.
- **FR-005d**: A range bound that matches no file, a start after the end, or a range with no files MUST be refused, listing the chapters present. Chapter gaps inside a range MUST be reported but MUST NOT be errors.
- **FR-005e**: The chosen range MUST be recorded in the corpus manifest, every selection manifest and every draft's provenance. Outputs for different ranges MUST be kept apart so that no run overwrites another range's corpus or drafts.
- **FR-005f**: At the command line, giving no range means every summary in the explicitly named location. In the UI, the range MUST be chosen explicitly, and "all chapters" MUST be a deliberate selection (Constitution X).

**Deterministic corpus (no model)**

- **FR-006**: The pipeline MUST produce, without any model call, a chronological scene spine covering every scene of every included summary in chapter-then-scene order.
- **FR-007**: The pipeline MUST preserve every memorable-moments section verbatim (character-for-character), attributed to its chapter.
- **FR-008**: The pipeline MUST produce one dossier per entity (headings grouped only by identical text or exact same-category registry alias) containing every observation of it, losslessly. Each observation MUST record the source file, the authoritative chapter, the heading as written, the category, and the source scene id where the summary places it inside a scene.
- **FR-009**: The source scene id MUST be the id declared in the summary. It MUST stay independent of any later subdivision or model-call chunk position.
- **FR-010**: Given identical input files, registry and `canon.yaml`, every deterministic artifact MUST be byte-identical across runs.
- **FR-011**: Summary-derived artifacts MUST be written to their own corpus location. The pipeline MUST refuse to read or write a location holding chapter/ensemble-derived artifacts, so the two corpora cannot be mixed.
- **FR-012**: Each dossier MUST be readable by the existing dossier consumers that read ensemble state dossiers, so downstream tools can use either corpus without change.

**Canonicalization (human-ruled)**

- **FR-013**: The pipeline MUST group headings only when they are identical within a category, or when the entity registry lists them as exact aliases of an entity whose type matches the category. The registry's inferred aliases MUST NOT be used. Spells and abilities have no registry type and are grouped by identical heading only.
- **FR-014**: The pipeline MUST detect likely duplicate headings within a category (near-identical spelling at or above a configurable similarity threshold, default 0.88, or the same name with and without a parenthetical qualifier). It MUST list each pair in the validation report, with every file and line where each spelling occurs, as a non-blocking fix-at-source item. It MUST NOT merge, rename or alias them.
- **FR-015**: The GM MUST be able to record a pair as not-a-duplicate in a hand-authored rulings file (`canon.yaml`), which the pipeline only reads. Recorded pairs MUST NOT be listed again. A ruling whose headings no longer occur in the selected range MUST be reported as stale. The file MUST NOT be able to express a merge or alias.
- **FR-016**: No merge decision MAY be made by a model or a similarity score. Duplicates are resolved by the GM editing the summary files.

**Selection & synthesis**

- **FR-017**: For each document, the pipeline MUST select which dossiers enter the synthesis context. It MUST support (a) every entity observed in a configurable number of most-recent chapters (counted back from the end of the selected range) and (b) recurring entities above a configurable observation count. The selection MUST never delete or alter the lossless corpus.
- **FR-018**: The pipeline MUST synthesise, as separately invokable steps, drafts of world state, campaign state, party, and planning.
- **FR-019**: Campaign-state synthesis MUST accept tracking, planning or module files as audit questions. It MUST label every claim from them that the summaries do not support (e.g. "NOT FOUND IN SUMMARIES") rather than presenting it as history.
- **FR-020**: A synthesis step that uses another document's draft as context MUST take it only from a file the GM explicitly names. It MUST NOT automatically consume the previous step's unreviewed output.
- **FR-021**: Planning synthesis MUST NOT invent arc scores. When none are configured, the Threat Tracker MUST be empty.
- **FR-022**: Each synthesis step MUST budget its output explicitly. Every output MUST be checked against the document's declared outline. An incomplete output MUST NOT be written as a draft; it MUST be kept separately and reported, naming the missing sections. The GM MUST be able to stage generation in declared parts that are assembled into one draft.
- **FR-023**: Synthesis MUST go through the project's standard model-access layer and accept the standard backend and model options used by the other grounding-doc tools.

**Reproducibility, drafts & promotion**

- **FR-024**: For every run, the pipeline MUST retain the exact prompts (system and user), the input file list with content digests, the chapter range, the selection decisions, and the digests of the registry and `canon.yaml` that were read.
- **FR-025**: Synthesis MUST write only draft files. It MUST NEVER modify the live grounding documents. Promotion stays a separate human act.
- **FR-026**: The pipeline MUST be able to report a comparison between each draft and the current live document (size, chapter coverage, and a textual diff) to support the promotion decision.
- **FR-027**: Existing corpus and draft outputs MUST NOT be overwritten unless the GM passes the standard overwrite flag. The validation report is exempt: it is regenerated on every run, because it describes the summaries as they are now.

**Coexistence & surfaces**

- **FR-028**: The pipeline MUST be a distinct approach. The existing chapter/ensemble grounding path and its outputs MUST keep working unchanged.
- **FR-029**: Every stage MUST be runnable from the command line, and every command-line capability MUST be reachable from the web UI. The UI MUST invoke the command-line tool and MUST NOT reimplement its logic.
- **FR-030**: Option names and defaults MUST follow the existing project vocabulary (config auto-detection, backend/model, overwrite, registry) rather than introducing new spellings.

### Key Entities

- **Summary file**: one structured session summary on disk. Its identity is its numeric filename prefix (the chapter). It contains a title line, a scene section, entity sections, and optionally memorable moments. Input only, never modified.
- **Validation report**: per-file results of identity and structure checks. Includes conflicts (filename vs. title chapter, scene id vs. chapter), missing sections, duplicates, and unrecognised sections.
- **Scene**: a `### <id> <title>` block within a summary. Carries its declared source scene id, title, chapter, and body.
- **Chronology**: the ordered spine of all scenes across the corpus.
- **Memorable moments**: verbatim preserved dialogue and table texture, per chapter.
- **Observation**: one entity entry from one summary. Records source file, chapter, heading as written, category, source scene id (or an explicit "no scene" marker), and its text.
- **Dossier**: all observations of one canonical entity within one category, with its chapter range.
- **Possible duplicate**: a pair of same-category headings that look like one entity spelled two ways, with every file and line where each occurs. A fix-at-source item in the validation report.
- **Duplicate rulings (`canon.yaml`)**: the GM's hand-authored record of pairs that are genuinely distinct, so they stop being flagged. Read-only to the pipeline; it cannot merge or alias anything.
- **Chapter range**: the inclusive start and end chapter selected for a run, with any gaps inside it. It determines which summaries enter the corpus and labels every output of the run.
- **Selection manifest**: per synthesis run, which dossiers and context were included and why (recent / recurring / explicitly named).
- **Synthesis record**: the exact prompts, input digests, backend and model, and output path for one draft.
- **Draft grounding document**: a world-state, campaign-state, party or planning draft awaiting GM review and promotion.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the 67-file Out of the Abyss corpus (with `070-session-untitled.md`'s title corrected to Chapter 70), the deterministic stages finish in under 2 minutes, parse 67/67 files, and keep all 409 scene headings in order. The extraction route projected 7–10 hours for the same corpus.
- **SC-002**: Two consecutive runs on unchanged input produce byte-identical deterministic artifacts (100% of files).
- **SC-003**: 100% of dossier observations carry source file, chapter, heading and category, and every in-scene observation carries its source scene id. Zero dossiers lack a chapter range.
- **SC-004**: A run whose selected range contains any chapter-identity disagreement (e.g. the unfixed chapter-070 file) produces no corpus or draft artifacts, and a validation report naming 100% of the disagreeing files.
- **SC-004a**: On a corpus seeded with N independent problems across several files, one validation run reports all N. The GM never has to re-run validation to discover an error that was present in the earlier run.
- **SC-005**: Zero headings are combined except by identical text or an exact same-category registry alias. Every seeded duplicate in the test corpus is listed with its file and line locations.
- **SC-006**: Every claim from an audited tracking file that the summaries do not support is labeled unsupported in the campaign-state draft. None is stated as played history.
- **SC-007**: Zero live grounding documents are modified by any pipeline run.
- **SC-008**: On the Out of the Abyss corpus, the GM judges the generated world-state and campaign-state drafts at least as good as the promoted prototype drafts retained from issue #499. Those drafts are the regression reference.
- **SC-009**: Every synthesis run can be reproduced from its retained record: the same prompts can be re-issued from the retained files without consulting anything else.

## Assumptions

- The summaries already exist in a directory the GM names, in the structured format shown by Out of the Abyss `docs/summaries/` (numeric-prefixed filenames, `# Chapter N` title, `## Scenes` with `### NNN.SS Title` headings, entity sections such as `## NPCs`, `## Locations`, `## Items`, `## Spells`, optional `## Memorable Moments`). How they were produced is out of scope.
- The recognised entity categories are those seen in the reference corpus (NPCs, Locations, Items, Spells, Abilities). Other sections are preserved and reported rather than rejected.
- The campaign's entity registry, where present, is the authority for exact aliases. Without one, grouping is by exact heading within a category until the GM accepts proposals.
- Default selection windows (number of recent chapters, recurring-observation threshold) follow the prototype (recent chapters ≈ the last 4; recurring ≥ 10 observations) and are configurable.
- Synthesis defaults to the same backends and models the other grounding-doc tools use. The prototype used `claude-opus-5-5` at medium effort.
- The prototype outputs from issue #499 (retained under `experiments/20261004-oota-ensemble-summary-prototype/` and in the Out of the Abyss workspace) serve as reference material and regression goldens. The prototype code itself is not assumed to be reusable as-is.
- The Out of the Abyss corpus currently fails validation on `070-session-untitled.md` (title says Chapter 66). The GM fixes that file. The pipeline never works around it.
- Promotion of drafts to live documents remains a manual GM action. This feature supports it with a comparison report but does not automate it.
- Single-user system: no concurrent runs against the same output location are expected.
