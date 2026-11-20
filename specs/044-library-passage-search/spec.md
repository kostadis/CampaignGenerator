# Feature Specification: Library Passage Search

**Feature Branch**: `044-library-passage-search`

**Created**: 2026-11-20

**Status**: Draft

**Input**: User description: "(https://github.com/kostadis/CampaignGenerator/issues/664) describes a feature I want which is a natural extension of the RLM feature"

## Context

The RLM feature already answers "which books" (rpg-lib) and "what is in the books I ingested by hand" (MemPalace drawers, statblocks, conversion candidates). Two gaps remain:

- **Coverage.** Nothing searches *inside* the hundreds of DMsGuild books that were already converted to 5etools JSON but never ingested.
- **Granularity.** rpg-lib's search only sees titles, descriptions and tags. In the pilot, a search for "druid" found 8 of 8,671 books.

The pilot (#664, `experiments/20261120-rpglib-palace-pilot/FINDINGS.md`) proved the idea on 50 books. An agent asked for "a statblock for a tavern keeper" ran several searches, read the hits, and recommended a specific innkeeper with stats from a book whose blurb never mentions one. The GM judged the result "useful enough".

This feature makes that capability a first-class part of RLM retrieval:
- a **library** of converted books with its own search index;
- a way for the GM to declare which books are in it;
- a search that returns whole passages, each linked back to its book;
- a surface where an AI agent can run the search and come back with an opinion.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ask the agent to find something in the library (Priority: P1)

During prep, the GM asks an AI agent in plain words for an example of a thing: "find me a statblock for a tavern keeper", "druid NPCs I could borrow from", "a haunted lighthouse". The agent searches the library, possibly several times with different wordings. It reads the passages it gets back and answers with a recommendation and the reasoning behind it, naming:
- the book (title and rpg-lib id);
- the section the passage comes from;
- what is usable and why;
- the fallbacks;
- which hits were noise.

**Why this priority**: This is the use case that proved its value in the pilot. Raw lists of hits were much less useful than an agent that reads them and gives an opinion.

**Independent Test**: With a library of at least 50 books built, ask the agent for "a statblock for a tavern keeper". The answer names at least one specific passage. The book, section and quoted details in the answer can all be checked against the source passage.

**Acceptance Scenarios**:

1. **Given** a built library, **When** the GM asks the agent for an example of a thing, **Then** the agent's answer cites each recommended passage by book title, rpg-lib id and section path, and every detail it attributes to a passage appears in that passage.
2. **Given** a built library that contains no matching passage, **When** the GM asks, **Then** the agent says plainly that nothing in the library matches and does not invent a source.
3. **Given** results dominated by one book, **When** results are returned, **Then** no single book contributes more than a configurable number of passages (default 2).

---

### User Story 2 - Search the library directly from the command line (Priority: P2)

The GM, or a script, runs a search with a query and gets back a ranked list of whole passages. Each passage carries its book title, rpg-lib id, publisher and section path. A summary reports how many distinct books appeared and whether the per-book limit removed any results.

**Why this priority**: This is the engine under Story 1 (Principle VI: the CLI is the engine). It is also the surface for checking and debugging results without an agent.

**Independent Test**: Run a search for "tavern keeper statblock" against a built library. Every result is a whole passage, never a fragment cut mid-section, and maps to a known book.

**Acceptance Scenarios**:

1. **Given** a built library, **When** a search is run, **Then** each result is a complete section of a book, labelled with its book and section path, and the run reports distinct books, cap activity and any unmapped hits.
2. **Given** a hit the system cannot trace to a book, **When** results are shown, **Then** it is reported as unmapped and is not silently dropped.

---

### User Story 3 - Library hits appear in normal RLM retrieval (Priority: P2)

When the GM uses the existing RLM retrieval, library passages appear as their own kind of hit alongside the existing ones:
- **drawer**
- **statblock**
- **cheap candidate:** a 5etools entity not yet in the palace, with the command to ingest it
- **expensive candidate:** a PDF with no converted JSON, with the commands to convert and ingest it

Library passages follow the same tier rules and carry the same book identifiers, so a passage can be promoted into a campaign through the existing proposal flow.

**Why this priority**: The GM asked for this as an extension of RLM, not a parallel tool. Without it there would be two retrieval front doors.

**Independent Test**: Run the existing RLM retrieval on a query known to hit the library. Library passages appear with their own kind label and book identifiers, and existing hit kinds are unchanged.

**Acceptance Scenarios**:

1. **Given** a built library, **When** RLM retrieval runs, **Then** library passages appear as a distinct kind, ranked by the documented tier rule, and existing results are unchanged.
2. **Given** no library has been built, **When** RLM retrieval runs, **Then** it behaves exactly as before and says that the library is absent.
3. **Given** a book that the converter has no 5etools JSON for but that is in the library, **When** RLM retrieval runs, **Then** it does not offer that book as an expensive conversion candidate.

---

### User Story 4 - Declare the library and keep it current (Priority: P3)

The GM declares which converted books belong in the library: by product type, by an explicit list, or by an explicit "all converted". Later, after fixing one book's JSON by hand, the GM refreshes the library, and only the changed books are re-processed. This feature provides the declaration and the build/refresh **commands**. Running them as part of machine bring-up belongs to hypostasis (see Out of Scope).

**Why this priority**: The other stories need a built library, but the pilot already shows a build works. The new value here is an explicit selection and a cheap refresh after a book is fixed. That matches the GM's approach to messy books: "if I really care about a book, I fix the JSON".

**Independent Test**: Declare 50 books and run the build command. Change one book's JSON and run the refresh. Only that book is re-processed, and a search reflects the change.

**Acceptance Scenarios**:

1. **Given** no selection has been declared, **When** a build is requested, **Then** the build refuses and explains how to declare one. It never defaults silently to "all" (Principle X).
2. **Given** a built library and one changed book JSON, **When** the GM refreshes, **Then** only that book's passages are replaced and the run reports what changed.
3. **Given** a selected book whose JSON is missing or unreadable, **When** building, **Then** the build continues with the other books and reports that book by id and reason.
4. **Given** the library has not been brought up on this machine, **When** a search or RLM retrieval runs, **Then** it reports that the library is unavailable and names the hypostasis step that provides it. It does not try to build the library itself.

### Edge Cases

- **Dirty structure.** A converted book has junk sections, for example table cells promoted to headings. It is indexed as-is. No repair is attempted, by GM ruling, and results from it are still labelled with whatever section names it has.
- **No page numbers.** A converted book has no page data. Results show the page as unknown and do not invent one.
- **Duplicates.** Several versions of one book exist ("Print Friendly", old versions, duplicates). Only one version is included unless the GM explicitly selects more.
- **Oversize sections.** One section is larger than the search index can hold as a single unit. It is split at sub-headings without losing text, and each part stays traceable to its book and section.
- **Unreachable source.** The source folder is unreachable, for example a cloud-synced drive in streaming mode. The build fails with a clear message naming the path. It does not produce an empty library that reports success.
- **Embedder mismatch.** The library was built with one embedding setup and searched with another. The search refuses or warns and names both setups.
- **Isolation.** A build or search pointed at a palace that is in use for a campaign, or at the default palace, is refused.

## Requirements *(mandatory)*

### Functional Requirements

**Library contents**

- **FR-001**: The system MUST maintain a book library index separate from every campaign palace and from the default palace. It MUST refuse to build or search against any location used by a live palace.
- **FR-002**: The GM MUST declare the library's book selection explicitly: by product type, by an explicit list of books, or by an explicit "all converted" choice. A build without a declared selection MUST be refused.
- **FR-003**: The system MUST include only books that have a finished converted JSON. Intermediate conversion files MUST be ignored, and by default only one version of a book is included (old versions, duplicates and "Print Friendly" variants are excluded).
- **FR-004**: The system MUST index each book's text with lists, tables and boxed text preserved. It MUST NOT silently drop content.
- **FR-005**: The system MUST keep, for every indexed passage, its book's rpg-lib id, title, publisher and section path. It MUST also keep the page when the source has one.
- **FR-006**: The system MUST support refreshing the library so that only books whose source JSON changed, or that were added to or removed from the selection, are re-processed.
- **FR-007**: The system MUST record which embedding setup built the library. It MUST refuse or warn when a search uses a different one.

**Search**

- **FR-008**: A search MUST return whole sections, not sub-section fragments. Several hits in the same section MUST collapse into one result.
- **FR-009**: A search MUST cap results per book, with a default of 2 that can be changed per search. It MUST report how many distinct books appeared and how many results the cap removed.
- **FR-010**: A search MUST report hits that cannot be traced to a book, rather than dropping them.

**Surfaces**

- **FR-011**: The search MUST be available from the command line, for humans and scripts, with a machine-readable output option.
- **FR-012**: The search MUST be available to an AI agent through the same tool surface the RLM feature already exposes, so that an agent can run several searches, read the full passages and form a recommendation.
- **FR-013**: RLM retrieval MUST include library passages as their own kind of hit. That kind MUST have a documented position in the existing tier order, and the existing hit kinds MUST behave unchanged.
- **FR-014**: When an agent recommends from library results, every passage it cites MUST be identified by book and section, so the GM can check it. The surface MUST return enough text for the agent to quote the passage verbatim.

**Operations**

- **FR-015**: The build MUST report books selected, books indexed, books skipped (with id and reason), the number of passages, elapsed time and the size of the index.
- **FR-017**: The library's location, its selection declaration and the embedding setup MUST be read from hypostasis's central configuration (the authority file), not from per-campaign config or hard-coded defaults. Searches and builds MUST use exactly what that configuration says.
- **FR-018**: The build/refresh and health-check commands MUST be callable non-interactively and MUST return distinct exit statuses for "ok", "failed", "not configured" and "library not built", so that hypostasis setup, start and status can drive and report them.
- **FR-016**: The library MUST NOT feed any render pipeline directly. As with all RLM retrieval, a passage reaches campaign documents only through the human-approved proposal flow (Principle III).

### Key Entities

- **Library Selection**: The GM's declaration of which converted books belong in the library. It is a rule (product types), a list, or an explicit "all", and it is stored where the GM can see and edit it.
- **Library Book**: A selected book. It has its rpg-lib id, title, publisher, product type, the location of its source JSON, and the size and time of its last processing.
- **Passage**: One whole section of a Library Book. It has its book, section path, page (optional) and text. A passage is the unit of every search result.
- **Library Index**: The searchable store of passages. It records the embedding setup that built it, and it is isolated from campaign palaces.
- **Search Result Set**: An ordered list of passages, plus distinct-book count, cap activity and unmapped hits.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a prep request like "a statblock for a tavern keeper", the agent returns a recommendation, built from the library's actual passages, within 2 minutes of the request.
- **SC-002**: 100% of passages cited in agent recommendations can be traced to a book and section in the library, and every quoted detail appears verbatim in the cited passage.
- **SC-003**: A single direct search returns results in under 3 seconds on a library of all currently converted DMsGuild books (667 at the time of writing).
- **SC-004**: In a top-10 result list, at least 5 distinct books appear whenever the library holds at least 5 books with relevant passages.
- **SC-005**: Refreshing after one book's JSON changed takes under 5% of the time of a full build.
- **SC-006**: No build or search ever modifies a campaign palace or the default palace. This is verifiable by comparing them before and after.
- **SC-007**: Across 10 real prep requests, the GM judges at least 7 answers useful.

## Out of Scope

- **Bringing up the library and making it available on a machine.** This is an extension of hypostasis setup and start in `github.com/kostadis/local_machine` (`local-machine hypostasis setup|start|status`). That covers when the library is built or restored from backup, where it lives, whether it counts as up, and how status reports it. It is tracked separately and is not part of this feature. This feature supplies the commands and the health check that hypostasis calls (FR-017, FR-018).
- Other publishers and game systems.
- Re-converting PDFs and adding page data to the conversion.
- Structural repair of dirty converted JSON.

## Assumptions

- The corpus is the DMsGuild books already converted to 5etools JSON, read from the GM's Drive folder (`/mnt/g/My Drive/DriveThru/Dungeon Masters Guild`). Other publishers and game systems are out of scope for this feature.
- Converted JSON is often structurally dirty. That is expected. The GM fixes a book's JSON when it matters, and this feature does not attempt structural repair.
- The search engine and embedding setup are the existing local ones, configured centrally (`hypostasis.yaml`), as in the pilot. The search engine itself is not modified.
- The agent's recommendation is a draft for the GM's eyes only, which is consistent with Principles II and III. It removes no decision from the GM.
- The pilot code on `feat/rpglib-palace-pilot` (`pipelines/rpglib_palace/`) is the starting point for this feature.
- Page numbers are shown only when the source JSON carries them. Adding them to the conversion is out of scope.
- Re-converting PDFs is out of scope.
