# Feature Specification: Grounding Navigation Hierarchy

**Feature Branch**: `022-grounding-nav-hierarchy`

**Created**: 2026-09-23

**Status**: Draft

## Clarifications

### Session 2026-09-23

- Q: Does the hierarchy group only the three ways of producing world-state content, or all three rendering paths for every grounding document? → A: All three paths for every grounding document (option B). Campaign State, Party and Planning move into the per-tool branch alongside World State.

**Input**: User description: "there are three features in campaing genreator that are overlapping for distill content and appear at the top level of the UI, I would like to re-organize the UI so that it is obvious they are overlapping with a hierarchy"

## Background

CampaignGenerator has three independent ways of turning a campaign's session record into grounding documents. Feature 006 named them the three **rendering paths** and deliberately kept them side by side, each writing its own output, so they can run in any order without overwriting each other (`docs/design/StateProjectionService_seed.md`):

| Path | What the GM sees today | Where it sits in the sidebar |
|---|---|---|
| **Per-tool** | World State ("Distill World State"), plus Campaign State, Party Document, Planning Document | GROUNDING DOCS group |
| **Dossier synthesis** | Ensemble Grounding Docs (Setup → Extract → Bundle → Synthesize) | its own top-level ENSEMBLE WORKFLOW group |
| **State projection** | State Projection, Threads | GROUNDING DOCS group, mixed in with the per-tool pages |

The navigation flattens this structure. Two of the three paths share one group with nothing separating them, the third sits in a separate top-level group, and no label says these are alternative routes to the same kind of document. A GM looking at the sidebar cannot tell that "World State", "Ensemble Grounding Docs" and "State Projection" all produce world-state content, or which one produced the file currently on disk.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See that the paths are alternatives (Priority: P1)

A GM opens the app wanting to refresh the world-state document. The navigation shows one parent area for grounding documents, and inside it the three rendering paths as sibling branches, each named for what it is and carrying a one-line description of how it differs from the others. Without reading any documentation, the GM can tell that these are three ways to produce the same kind of document, not three unrelated tools.

**Why this priority**: This is the whole request. Until the overlap is visible in the navigation, every other improvement is decoration.

**Independent Test**: Show the reorganized sidebar to someone who knows the app and ask them to point to every place that produces world-state content. All three paths are found without opening any page.

**Acceptance Scenarios**:

1. **Given** the app is open on any page, **When** the GM looks at the sidebar, **Then** the three rendering paths appear as named children of a single grounding-documents parent, not as peers of unrelated sections such as Session Workflow or Prep.
2. **Given** the sidebar shows the three paths, **When** the GM reads a path's label, **Then** a short description states what makes it different from its siblings (for example: per-document and direct; fact extraction then dossier synthesis; section-level rebuild of what changed).
3. **Given** the GM is on a page belonging to one path, **When** they look at the sidebar, **Then** the active page and its parent path are both visibly marked.

---

### User Story 2 - Nothing becomes unreachable (Priority: P1)

A GM who uses a particular page every session opens the app after the reorganization. Every page that existed before is still reachable, and a bookmarked or previously shared link still lands on the right page.

**Why this priority**: A navigation reorganization that loses a page, or silently breaks a link, fails the constitution's parity principle (XI) and costs more than it gains. It is equal in priority to Story 1 because Story 1 cannot ship without it.

**Independent Test**: List every page reachable from the current sidebar, and every existing link path, before the change. After the change, every page is reachable from the sidebar and every old link resolves to the same page.

**Acceptance Scenarios**:

1. **Given** the list of sidebar entries before the change, **When** the reorganization ships, **Then** each entry is reachable from the new sidebar in at most one more click than before.
2. **Given** a link saved before the change (for example the Ensemble Setup page or the World State page), **When** the GM opens it, **Then** it shows the same page, either at the same address or through an automatic redirect.

---

### User Story 3 - See the shared stages between paths (Priority: P2)

A GM planning which path to run wants to know what the paths share. The hierarchy makes visible that dossier synthesis and state projection both consume the same extracted fact corpus, while the per-tool path does its own extraction, so the GM understands that running one ensemble extraction feeds two paths.

**Why this priority**: This turns "these overlap" into "this is how they overlap", which is what prevents redundant, token-spending runs. It builds on Story 1 but is not required for it.

**Independent Test**: Ask a GM, using only the navigation and each path's page header, which paths reuse the ensemble extraction. They answer correctly.

**Acceptance Scenarios**:

1. **Given** the GM is viewing the dossier-synthesis or state-projection branch, **When** they read the branch or page header, **Then** it names the shared extraction stage it depends on.
2. **Given** the GM is viewing the per-tool branch, **When** they read its header, **Then** it states that it performs its own extraction and does not use the shared fact corpus.

### Edge Cases

- **Threads**: today a separate sidebar entry, but part of the state-projection path. It must sit inside that branch. The State Projection page's existing signpost to Threads must keep working.
- **World State's legacy address**: an older `world-state` address already opens World State. That must keep working.
- **A path with nothing built yet**: a branch whose documents don't exist on disk must still appear, and must not look broken or disabled. Showing what is unbuilt is part of the point (constitution Principle VIII).
- **Sidebar height**: the sidebar is a fixed 210px wide, so width never squeezes it. The real cost of the extra level is height: three header rows plus their descriptions. At the smallest supported window height (1280×720, the test viewport) every entry must stay reachable by scrolling the sidebar.
- **Two paths producing the same document**: when both the per-tool and dossier-synthesis paths have produced a world-state document, nothing in the reorganization may imply that one supersedes the other. Choosing between them stays the GM's decision (Principle II).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The navigation MUST present one parent area for grounding documents, containing the three rendering paths as distinct, named children.
- **FR-002**: Each rendering path MUST carry a label and a short description that says how it differs from its sibling paths.
- **FR-003**: The dossier-synthesis path (currently the top-level ENSEMBLE WORKFLOW group) MUST move inside the grounding-documents parent and MUST no longer appear as a separate top-level section.
- **FR-004**: The per-tool pages and the state-projection pages MUST no longer sit in one undifferentiated group. Each page MUST appear under its own path.
- **FR-005**: Threads MUST appear under the state-projection path.
- **FR-006**: Every page reachable from the sidebar before this feature MUST remain reachable from it afterwards, within at most one additional click.
- **FR-007**: Every page address that worked before this feature MUST still open the same page, directly or by redirect, including the existing `world-state` → World State mapping.
- **FR-008**: The sidebar MUST mark both the active page and the rendering path it belongs to.
- **FR-009**: The dossier-synthesis and state-projection paths MUST state, in their branch description or page header, that they depend on the shared ensemble extraction. The per-tool path MUST state that it extracts independently.
- **FR-010**: The reorganization MUST NOT change what any page does, what it runs, or what it writes to disk. This feature changes where pages sit and what they say about each other, nothing else.
- **FR-011**: The reorganization MUST NOT rank, recommend, or hide any path. All three remain equally available, and choosing between them stays with the GM.
- **FR-012**: The hierarchy MUST cover all three rendering paths for every grounding document, not only world-state content. The per-tool branch MUST contain World State, Campaign State, Party Document and Planning Document; the dossier-synthesis branch MUST contain the single Ensemble entry, whose own wizard holds the Setup → Extract → Bundle → Synthesize stages; the state-projection branch MUST contain State Projection and Threads.

### Key Entities

- **Rendering path**: one of the three independent routes from session record to grounding documents: per-tool, dossier synthesis, state projection. Has a name, a short differentiating description, the pages that belong to it, and whether it depends on the shared extraction.
- **Shared extraction stage**: the ensemble fact extraction whose output both dossier synthesis and state projection consume. Not a new page. It is named so that the dependency is visible.
- **Navigation entry**: a page's place in the sidebar: its label, its parent path, and every address that reaches it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A GM shown the new sidebar, and asked "where can I produce world-state content?", names all three paths within 30 seconds without opening a page.
- **SC-002**: 100% of pages reachable before the change are reachable after it, each within one additional click at most.
- **SC-003**: 100% of page addresses that worked before the change still open the same page.
- **SC-004**: The number of top-level sidebar sections that contain a grounding-document rendering path goes from two to one.
- **SC-005**: Asked "which paths reuse the ensemble extraction?", a GM answers correctly using only the navigation and page headers.

## Assumptions

- The three features the description refers to are feature 006's three rendering paths, identified from `docs/design/StateProjectionService_seed.md` and the current sidebar. The page most associated with "distill" is World State, whose page title is "Distill World State".
- This is a navigation and labelling change only. No pipeline, script, output directory or configuration changes (FR-010). The paths remain independent and side by side, as feature 006 designed them.
- Session Workflow, Prep, Setup, Integrations and Settings are out of scope and keep their current place.
- Descriptions are short (one line per path). Longer explanation belongs in the existing design documents, not in the sidebar.
- Merging, retiring or recommending between paths is out of scope. Whether the paths should eventually converge is a separate decision.
- Constitution Principles VIII (state is discoverable) and XI (every capability keeps a face) are the governing constraints: the hierarchy must make relationships visible without removing any page's reach.
