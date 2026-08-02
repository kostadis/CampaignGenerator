# Feature Specification: State-Projection Rendering as its own service

**Feature Branch**: `feat/213-phase1-source-lineage` *(existing; no new branch created — no `before_specify` hook is registered)*

**Created**: 2026-08-01

**Status**: Draft

**Input**: User description: "Split the campaign's document-generation into four explicit services and give the newest one its own configuration and UI. `ensemble_batch` + `facts_to_state` become a shared Extraction & State service producing the fact corpus and the per-entity dossiers. Two rendering services consume that state and are siblings, neither depending on the other: dossier synthesis and state projection. A third rendering path — the per-tool API path — keeps its own extraction and its own config. Each rendering path must write its documents into its own directory so the three can run in any order, side by side, without overwriting each other or feeding each other by accident. The state-projection service gets a strict config document of its own and a UI layer surfacing its GM checkpoints: summary-map row approval, the lineage report, section staleness with per-section rebuild, thread triage, and draft promotion."

> **Pre-seeded research**: `docs/design/StateProjectionService_research.md` records the codebase
> survey behind this spec (service map, execution order, declaration inventory, output-collision
> evidence, corpus record contract, per-section dependencies, governing config doctrine). Planning
> should extend it rather than re-derive it.

## Clarifications

### Session 2026-08-01

- Q: Per-service output layout, and the fate of the one existing cross-service input → A: Each rendering service writes to its own subdirectory; the cross-service input follows Dossier Synthesis to its new location (Option A)
- Q: Scope of the first interface release → A: Section staleness view + per-section rebuild only; the service's other review checkpoints (summary-map row approval, lineage report, thread triage, draft promotion) stay command-line/skill-driven (Option A)
- Q: Does the shared service's curation (entity importance, alias review, duplicate merging) surface in the State Projection interface? → A: Read-only — the page names which curation inputs fed each section; the decisions themselves stay in the shared service's own workflows (Option B)
- Q: What happens to drafts already on disk at the old shared locations when outputs move? → A: Leave them in place; a rendering service refuses to produce a document while that document's legacy draft still exists, until the GM clears it (Option D)
- Q: Canonical terminology for the four units of work → A: "Service" is canonical — Extraction & State, Per-Tool Rendering, Dossier Synthesis, State Projection. "Path" is reserved for describing a route through the pipeline in prose (Option A)

**Glossary (canonical terms, per the answer above):**

| Term | Means |
|---|---|
| **Extraction & State service** | Produces the fact corpus and the per-entity dossiers; consumed by both rendering services |
| **Per-Tool Rendering service** | Produces the four documents by extracting the chapter text itself; needs no local hardware |
| **Dossier Synthesis service** | Renders the four documents from the per-entity dossiers |
| **State Projection service** | Renders the four documents as independently-stamped sections over the event spine, thread registry and dossiers; the subject of this feature |
| **path** | A route *through* the pipeline in prose ("the post-session path"). Not a unit of ownership — use "service" for that |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run every rendering service without losing work (Priority: P1)

The GM has three ways to produce the campaign's four grounding documents and wants to compare them.
Today, running the newest one overwrites the drafts the previous one produced, and a third reads
whichever happened to run last — so a comparison silently destroys one of the things being compared.
The GM wants to run all three in any order and still have three separate sets of documents to diff.

**Why this priority**: This is a live data-loss defect, not a convenience. It also blocks the GM from
ever evaluating the new renderer against the old, which is the reason the new one exists. Every other
story is easier to accept once outputs are separated.

**Independent Test**: Produce documents with each rendering service in turn, in any order, and
confirm every document produced by the other two is byte-identical afterwards. Delivers a trustworthy
side-by-side comparison with no other part of this feature built.

**Acceptance Scenarios**:

1. **Given** all three rendering services have run at least once, **When** the GM runs any one of
   them again, **Then** only that service's own documents change and the other two services'
   documents are byte-identical to before.
2. **Given** a document that one rendering service consumes as input is produced by another, **When**
   the producing service has not run, **Then** the consuming service reports the missing input rather
   than silently reading a document produced by a third.
3. **Given** the GM is looking at a generated document, **When** they check where it lives, **Then**
   its location alone identifies which service produced it.

---

### User Story 2 - Extract once, render twice (Priority: P2)

Fact extraction and per-entity bundling are expensive and shared. The GM wants to run them once and
then render with either renderer — or both — without either renderer re-extracting, and without
having to run one renderer as a prerequisite of the other.

**Why this priority**: Establishes the service boundary the rest of the feature rests on. It is P2
rather than P1 because the pipeline already behaves this way in practice; what is missing is that the
boundary is nowhere declared, so nothing prevents the next change from re-entangling the two.

**Independent Test**: Run the shared extraction and bundling once; then run each renderer separately
from a clean state and confirm both succeed, produce their documents, and neither triggers extraction
or requires the other renderer to have run.

**Acceptance Scenarios**:

1. **Given** the shared extraction and bundling have completed, **When** the GM runs the
   state-projection renderer without ever running the dossier-synthesis renderer, **Then** it produces
   its documents successfully.
2. **Given** the shared extraction has completed but bundling has not, **When** the GM runs the
   state-projection renderer, **Then** the sections that need per-entity dossiers are skipped with a
   stated reason and the sections that do not need them are produced normally.
3. **Given** a chapter's facts change, **When** the GM re-runs the shared extraction for that chapter
   only, **Then** both renderers see the change without either re-extracting anything else.

---

### User Story 3 - Change where things live without editing code (Priority: P2)

Every location the State Projection service reads or writes is currently fixed in code, in several
places at once. The GM wants each location declared once, so a campaign with a different layout is a
configuration change rather than a code fork.

**Why this priority**: Prerequisite for the UI story — a UI cannot offer a setting the system has no
place to store. It also removes a correctness hazard: one location is currently written in three
places, and the freshness check and the actual read are among them.

**Independent Test**: Redirect one store to a different location in configuration, run the service,
and confirm both the freshness check and the render follow the new location together.

**Acceptance Scenarios**:

1. **Given** no configuration file exists for the State Projection service, **When** the GM runs it,
   **Then** it behaves exactly as it does today, using the shipped defaults.
2. **Given** the GM redirects a store's location in configuration, **When** the service runs,
   **Then** every consumer of that store — including the freshness check — uses the new location, and
   the affected section re-renders rather than reporting itself unchanged.
3. **Given** the GM writes an unrecognised setting into the configuration, **When** the service runs,
   **Then** it reports the unrecognised setting rather than ignoring it.
4. **Given** the GM changes the State Projection service's configuration, **When** the other two
   rendering services run, **Then** their behaviour and their configuration are unaffected.

---

### User Story 4 - See what is stale and rebuild just that, from the UI (Priority: P3)

The State Projection service has no interface. The GM wants to see which parts of a document are out
of date and rebuild only those, without remembering a sequence of commands.

**Why this priority**: The highest-value story for daily use, but it depends on Stories 1–3 being
settled: a UI over colliding outputs and undeclared configuration would harden both problems.

**Scope of this release**: staleness and per-section rebuild only. The service's other review
checkpoints — summary-map row approval, the lineage report, thread triage, and draft promotion —
remain command-line and skill-driven; they are workflows over files that lose little outside a
browser, and each already works today.

**Independent Test**: From the UI alone, identify an out-of-date section and rebuild only that
section — confirming it produced the same file the equivalent command would have, and that no other
section changed.

**Acceptance Scenarios**:

1. **Given** an input store changed, **When** the GM opens the service's page, **Then** the affected
   sections are shown as out of date and the unaffected ones as current.
2. **Given** an out-of-date section, **When** the GM rebuilds only that section, **Then** only that
   section is regenerated and the rest are untouched.
3. **Given** a rebuild that would spend money, **When** the GM starts it, **Then** the cost-bearing
   choice is explicit and a run that has not made it stays free.
4. **Given** a section whose inputs are missing, **When** the GM views the page, **Then** it is
   distinguished from a merely out-of-date section and names what is missing.
5. **Given** the GM has rebuilt from the UI, **When** they switch to the command line, **Then** the
   same files are there and nothing is held only in the browser.

---

### Edge Cases

- **A renderer runs before the shared service has ever run.** Expected: a stated missing-input
  result, not an empty document and not a crash.
- **Bundling has run but produced nothing for a category** (a campaign with no faction dossiers).
  Expected: those sections skip cleanly with a reason; unrelated sections still render.
- **A campaign has only the older, un-curated dossier set** — one live campaign is in exactly this
  state. Expected: the fallback is used *and named in the output*, so the GM knows which set fed the
  document.
- **The GM redirects a location to somewhere that does not exist.** Expected: a loud failure naming
  the missing path, never a silently empty section.
- **A draft from before the output move is still sitting at the old shared location.** Expected: the
  rendering service refuses to produce that document and names the file. Both live campaigns are in
  this state today, so it is the first thing every campaign hits.
- **Two documents are requested and one has no inputs.** Expected: partial success with a per-section
  report, not an all-or-nothing failure.
- **A rebuild is requested with no selection made.** Expected: refusal. An empty selection means
  nothing was chosen; it must never expand to "everything".
- **The upstream fact record changes shape.** Expected: a failure that names the mismatch, rather
  than silently thinner documents (today a renamed field yields fewer entries with no error).
- **The same document is requested from two rendering services concurrently.** Expected: separated
  outputs make this harmless; neither run can observe the other's partial writes.

## Requirements *(mandatory)*

### Functional Requirements

**Service boundaries**

- **FR-001**: The system MUST treat fact extraction and per-entity bundling as one shared service
  whose outputs are consumed by both rendering services.
- **FR-002**: A rendering service MUST NOT require another rendering service to have run in order to
  produce its own documents. This binds all three; in practice it is Dossier Synthesis and State
  Projection that could have coupled, since Per-Tool Rendering extracts for itself.
- **FR-003**: A rendering service MUST NOT read another service's configuration; where it depends on
  another service's output, it MUST declare its own pointer to that output.
- **FR-004**: The shared service's fact record MUST have a declared set of fields its consumers rely
  on, and a change that breaks it MUST fail visibly rather than reduce output silently.

**Separated outputs**

- **FR-005**: The State Projection and Dossier Synthesis services MUST each write their generated
  documents into their own subdirectory, distinct from each other and from the shared `docs/` root.
  *(Merged with the former FR-007, which said the same thing more strongly.)*
- **FR-005a**: **Per-Tool Rendering is exempt**, and deliberately so: its draft path is whatever the
  operator passes as `--output`, so there is no default to relocate. The residual risk is accepted —
  an operator who types a path another service owns can still collide, and nothing in this feature
  prevents it.
- **FR-006**: A rendering service MUST NOT overwrite, or read as its own input, a document produced
  by another service unless that dependency is explicitly declared.
- **FR-007a**: Where a rendering service consumes another's output, that dependency MUST be declared
  and MUST resolve to the producing service's own location — never to whichever service wrote a
  shared filename last. The existing cross-service input (Per-Tool Rendering staging Dossier
  Synthesis's world-state draft) MUST follow Dossier Synthesis to its new location, preserving
  today's behaviour.
- **FR-007b**: Drafts already on disk at the pre-move shared locations MUST NOT be moved or deleted
  by the system. While such a draft exists for a document, the **State Projection** service asked to
  produce that document MUST refuse, naming the file and what clearing it means. Once cleared by the
  GM the gate never fires again for that document. Rationale: the old files cannot be attributed to
  a service, and they are the left-hand side of the GM's diffs — neither guessing nor deleting is
  acceptable.
- **FR-007c**: The gate is **not** required of the other two services. It is a one-time migration
  aid, not a permanent guard, and the other two never wrote into the State Projection namespace. The
  accepted consequence: a legacy draft is protected from being clobbered by State Projection, not
  from being clobbered by Dossier Synthesis.

**Configuration**

- **FR-008**: Every location the State Projection service reads or writes MUST be declared exactly
  once.
- **FR-009**: All consumers of a declared location — including freshness checks — MUST resolve it
  from that single declaration.
- **FR-010**: The State Projection service's configuration MUST live in its own document, separate
  from every other service's, so a change to one cannot invalidate or corrupt another.
- **FR-011**: The configuration MUST reject unrecognised settings rather than ignore them.
- **FR-012**: Absent configuration MUST behave identically to today's shipped defaults.
- **FR-013**: The set of inputs a run acts on MUST remain an explicit choice at every layer; the
  system MUST NOT supply a default that means "everything".
- **FR-014**: Which sections exist and which document they belong to MUST remain a fixed editorial
  decision, not a configurable value.
- **FR-015**: Durable campaign content MUST stay where campaign content lives; only *pointers* to it
  become configuration.

**Operation and review**

- **FR-016**: The GM MUST be able to see, per section, whether it is current, out of date, unbuilt,
  or missing its inputs.
- **FR-017**: The GM MUST be able to rebuild an individual section without rebuilding the rest.
- **FR-018**: A section MUST be considered out of date only when the content of its inputs changed,
  not when a file was merely touched.
- **FR-019**: A run MUST NOT incur cost unless the GM has explicitly chosen a cost-bearing option.
- **FR-020**: Every decision the service surfaces for review MUST remain a decision — the system
  MUST NOT act on a proposal that has not been ruled on.
- **FR-021**: A GM ruling MUST survive regeneration of the queue that surfaced it.
- **FR-022**: The interface MUST cover section staleness and per-section rebuild. The service's
  other review checkpoints — summary-map row approval, the lineage report, thread triage, and draft
  promotion — remain command-line and skill-driven in this release and MUST continue to work
  unchanged.
- **FR-022a**: Anything achievable in the interface MUST be equally achievable from the command
  line, and every step MUST hand off through a file rather than state held only in the interface.
- **FR-023**: The interface MUST NOT reimplement any generation logic; it drives the same engine the
  command line does.
- **FR-024**: Generated documents MUST continue to land in a draft state that the GM compares and
  promotes by hand.
- **FR-024a**: The interface MUST show, read-only, which shared-service curation inputs fed each
  section — which dossier set was used (curated or fallback) and which importance list was applied —
  so a thin or surprising section can be traced to its inputs without leaving the page.
- **FR-024b**: The interface MUST NOT offer editing of another service's state. Alias review,
  duplicate merging and importance editing remain the shared service's own workflows.

### Key Entities

- **Fact corpus** — the per-chapter set of atomic facts produced by the shared service; the common
  input to both renderers. Each fact carries its kind, its subject, its verbatim quote and provenance,
  and which source artifact it was extracted from.
- **Entity dossier** — a per-entity current-state summary aggregated from the corpus by the shared
  service, in an initial and a curated form.
- **Event spine** — a durable, chapter-ordered record of what happened, derived from the corpus and
  owned by the State Projection service. Never hand-edited; any chapter can be rebuilt from the
  corpus.
- **Thread registry** — the GM-ratified set of ongoing plot threads, with a separate holding area of
  proposals awaiting a ruling, and a clearly non-canonical idea surface.
- **Section** — one independently rendered part of a document, carrying a stamp of the exact input
  content it was rendered from, which is what makes selective rebuild possible.
- **Draft** — an assembled document awaiting the GM's comparison and promotion; the last checkpoint
  before anything becomes canon.
- **Rendering service** — one of the three ways to produce the four documents (Per-Tool Rendering,
  Dossier Synthesis, State Projection), each owning its own configuration and its own output
  location.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Running any one rendering service leaves 100% of the documents produced by the other
  two unchanged, verified by content comparison before and after.
- **SC-002**: The GM can produce documents from all three rendering services and compare them side
  by side in a single sitting, with zero manual file copying to protect earlier output.
- **SC-003**: Either renderer can run to completion from a state where only the shared service has
  run — neither requires the other renderer as a prerequisite.
- **SC-004**: Re-running a rendering service when no input content has changed regenerates nothing
  and costs nothing.
- **SC-005**: Changing where any store or input lives requires editing exactly one place, and takes
  effect for every consumer of that location including freshness checks.
- **SC-006**: A campaign with no configuration file produces **identical content** to today, at the
  new declared location. FR-005 (the output namespace) and FR-007b (the legacy gate) are the two
  intended deviations — the bytes match, the path does not.
- **SC-007**: An unrecognised or unresolvable configuration value produces a message naming it; in no
  case does it produce a silently empty or partial document.
- **SC-008**: The GM can go from "something changed" to "only the affected section rebuilt" from the
  interface, without consulting documentation for a command sequence.
- **SC-009**: Every review decision the State Projection service surfaces is still made by the GM,
  and no proposal advances without a ruling — measurable as zero automated promotions in a full run.
- **SC-010**: A change to the shared service's fact record that breaks a consumer is caught by an
  automated check rather than appearing as a thinner document.
- **SC-011**: No draft that predates the output move is moved or deleted by the system; each is
  either still in place or cleared by a deliberate GM action.

## Assumptions

- **Single operator, no installed base.** One user, three campaigns, local machine. Migrations are
  migrate-and-delete; no compatibility shims or dual-location fallbacks are carried. The one
  exception is deliberate: pre-existing drafts are neither migrated nor deleted (FR-007b).
- **All three rendering services remain supported.** None is deprecated by this feature. Per-Tool
  Rendering is the fallback when no local hardware is available; the other two depend on it
  existing.
- **Files on disk remain the source of truth**, and every generated document remains a draft until
  the GM promotes it. This feature does not change what "promote" means.
- **The interface is a face over the same engine**, not a second implementation; anything it can do
  is doable from the command line.
- **Where the shared service's configuration ultimately lives** — whether it separates from the
  document it currently shares with a renderer — is a planning decision, not a scope question. Both
  answers satisfy this spec.
- **Which service owns the synthesis engine** that both renderers currently invoke is likewise a
  planning decision.
- **The State Projection service's incremental behaviour is content-derived** and stays that way;
  timestamps are not a substitute.
- **Existing enforcement checks are constraints, not obstacles** — single config location, no
  cross-layer imports, one strict document per service, explicit selection. The design conforms to
  them rather than exempting itself.

## Dependencies

- The shared extraction and bundling service must have run for a campaign before either renderer can
  produce documents that depend on facts or dossiers.
- One live campaign has only the un-curated dossier set, so the fallback behaviour in FR/edge cases
  is exercised in practice, not hypothetically.
- The chapter-to-session join underpinning source selection is GM-approved per row; nothing in this
  feature bypasses that gate.
