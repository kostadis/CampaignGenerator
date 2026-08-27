# Feature Specification: Thread Registry Surface

**Feature Branch**: `feat/337-thread-registry-ui`

**Created**: 2026-08-25

**Status**: Draft

**Input**: User description: "CG #337"

GitHub issue: [kostadis/CampaignGenerator#337](https://github.com/kostadis/CampaignGenerator/issues/337) — "Planning projection UI has no surface for thread_registry — threads section (and everything depending on it) dead-ends in a CLI-only error"

**Scope ruling (GM, 2026-08-25)**: of the three fixes the issue offers, this
feature builds **option 1 — the thread registry surface**. Options 2 (a
generic "here's what to run" hint for every required section in `no-input`)
and 3 (an auto-created empty registry stub) are **not** adopted; see
Assumptions.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See what threads the corpus is offering (Priority: P1)

A GM has run extraction over their campaign's chapters and wants to work on
threads. Today the thread material exists — the extraction lenses already
emit thread-typed facts with quotes — but nothing in the interface shows it.
The GM opens the Threads surface, explicitly chooses which chapters to
harvest from, runs the harvest, and gets a queue of candidate threads: each
one's title, the chapters it appears in, whether it already matches a
ratified thread, and the underlying evidence (the fact, its chapter, and its
verified quote where one exists).

**Why this priority**: This is the first half of the dead-end. A GM cannot
decide anything about threads they cannot see, and seeing them today means
running a command, then opening a YAML file in an editor. Nothing enters
canon in this story — it is pure discovery — which is exactly why it can
ship alone and be safe.

**Independent Test**: On a campaign with extraction output and no thread
registry, open the Threads surface, choose a corpus, run the harvest, and
confirm a queue of candidates appears with per-candidate evidence, that the
registry is still empty, and that the planning document's `threads` section
is unchanged.

**Acceptance Scenarios**:

1. **Given** a campaign whose thread registry does not exist, **When** the GM
   opens the Threads surface, **Then** it loads and reports an empty registry
   as a normal state — not an error, and not a blank screen.
2. **Given** the GM has explicitly chosen one or more chapter sources,
   **When** they run the harvest, **Then** the queue lists every candidate
   thread with its title, its chapters, its evidence, and whether it matches
   an already-ratified thread — and the registry is not modified.
3. **Given** the GM has chosen nothing, **When** they try to run the harvest,
   **Then** the surface refuses and says so, rather than silently harvesting
   every chapter in the campaign.
4. **Given** the chosen sources match no files, **When** the harvest runs,
   **Then** the GM is told no files matched and which patterns were tried, in
   readable form.

---

### User Story 2 - Rule on a candidate: accept, reject, or discuss (Priority: P1)

For each candidate in the queue the GM makes exactly one of three decisions,
one thread at a time:

- **Accept** — this is a real thread. The GM is shown a form pre-filled from
  the candidate (an id, a title, the chapter it opened in, and one log row
  per chapter with a summary and optional quote drawn from the evidence),
  edits anything they disagree with, and commits. The thread enters the
  registry. A candidate that already matches a ratified thread adds its
  fresh chapters as log rows to that thread rather than creating a second one.
- **Reject** — this is not a thread. The decision is recorded and the
  candidate does not come back as pending on the next harvest.
- **Discuss** — the GM isn't ready to rule. The decision is recorded like a
  reject (nothing enters the registry), *and* the candidate with its evidence
  is written to a file the GM can hand to a Claude conversation to adjudicate,
  then come back and accept or reject.

**Why this priority**: This is the other half of the dead-end and the reason
the issue was filed — it is what turns a missing `threads` input into a real
one. It is P1 alongside US1 because a queue you cannot rule on leaves the
planning document exactly as broken as it is today.

**Independent Test**: From a queue produced by US1, accept one candidate,
reject another, and mark a third for discussion. Confirm the registry gains
exactly one thread with the fields the GM confirmed, the rejected and
discussed candidates do not reappear as pending after a re-harvest, and the
discussed candidate's evidence is available in a file outside the interface.

**Acceptance Scenarios**:

1. **Given** a pending candidate, **When** the GM accepts it, **Then** they
   are first shown every field that will be written, pre-filled and editable,
   and the thread is created only after they confirm — there is no path from
   pending to canon that does not pass through that form.
2. **Given** a candidate that matches an already-ratified thread, **When** the
   GM accepts it, **Then** its unlogged chapters are added to the existing
   thread and no duplicate thread is created.
3. **Given** a candidate whose evidence carries no recognisable chapter
   number, **When** the GM accepts it, **Then** the surface requires a real
   chapter before committing rather than writing a placeholder.
4. **Given** the GM rejects a candidate, **When** the harvest is re-run later,
   **Then** that candidate is still recorded as rejected and is not presented
   as pending again.
5. **Given** the GM marks a candidate for discussion, **When** the ruling is
   saved, **Then** the candidate and its evidence appear in an adjudication
   file suitable for handing to a Claude conversation, and the candidate stays
   visible on the surface so it can be ruled on again later.
6. **Given** a ruling would produce an invalid registry (a duplicate id, a
   title or alias that collides with another thread, a status that requires a
   chapter without one), **When** the GM confirms it, **Then** the write is
   refused, nothing is saved, and the reason is shown in the interface.
7. **Given** any of the three rulings, **When** it is recorded, **Then** it is
   recorded for exactly one candidate — there is no control that rules on
   several candidates at once.

---

### User Story 3 - Maintain the ratified registry (Priority: P2)

Threads have a life after ratification. The GM opens the Threads surface and
sees every ratified thread grouped by status (open, dormant, resolved,
abandoned) with its log. From there they can add a per-chapter log row to a
thread, move a thread to a different status (supplying the closing chapter
when resolving or abandoning it), record an alternative title as an alias for
an existing thread, and run the registry's own consistency check to see any
invariant problems.

**Why this priority**: Without it the surface is write-once — the GM can get
a first registry but must return to a terminal the moment a thread advances
or closes, which is the same dead-end one chapter later. It is P2 because a
campaign is unblocked by US1+US2 alone.

**Independent Test**: On a registry with at least one thread, add a log row,
change the thread's status to resolved with a closing chapter, add an alias,
and run the check — then confirm each change is visible on reload and in the
rendered planning section.

**Acceptance Scenarios**:

1. **Given** a ratified thread, **When** the GM adds a log row naming a
   chapter, a change type, and a summary, **Then** the row is stored against
   that thread in chapter order.
2. **Given** a ratified thread, **When** the GM sets its status to resolved or
   abandoned without naming a closing chapter, **Then** the change is refused
   with that reason.
3. **Given** two threads, **When** the GM records an alias on one that already
   names the other, **Then** the alias is refused and the colliding thread is
   named.
4. **Given** any registry, **When** the GM runs the consistency check, **Then**
   every problem it reports is shown in the interface with the thread it
   belongs to, and a clean registry is reported as clean.

---

### User Story 4 - Get from the failed planning build to the fix (Priority: P3)

A GM on the Planning document's State Projection page sees `threads` sitting
in a "no input" state. Instead of learning only after a failed build that a
YAML file they have never heard of is missing, the row itself names the
missing store and offers the way to the Threads surface.

**Why this priority**: It closes the loop the issue actually describes — the
GM's entry point is the Planning page, not the Threads page, and a surface
they cannot find is only half a fix. It is P3 because it is navigation: once
US1–US3 exist, a GM who knows about the Threads surface is already unblocked.

**Independent Test**: On a campaign with no thread registry, open the Planning
document's projection table and confirm the `threads` row names its missing
input and leads to the Threads surface without a build having to fail first.

**Acceptance Scenarios**:

1. **Given** the `threads` section is in a "no input" state, **When** the GM
   views the Planning projection table, **Then** the row names the store that
   is missing and offers a way to reach the Threads surface.
2. **Given** a build of any planning section fails because a required section
   has no file yet, **When** the failure is reported, **Then** the GM is told
   which section is missing and how to get to the surface that creates it —
   not only the raw error text.
3. **Given** the environment holds no Anthropic credential, and the GM has
   followed the signpost, ratified a thread and returned, **When** they build
   the `threads` section from the projection table, **Then** the build starts
   and runs — because nothing asks about credentials before a run any more.
   *(Added 2026-08-26. Before #342/PR #343 it was refused before it started,
   under a warning naming a key the build never reads; see FR-032–FR-034.)*

---

### Edge Cases

- **No registry file at all.** The surface treats an absent registry as an
  empty one, the same way the engine already does; it never presents "file not
  found" as the GM's problem to solve.
- **Empty corpus selection.** Refused, explicitly. There is no implicit "all
  chapters" — which chapters a harvest reads is the GM's choice every time.
- **Corpus matches no files.** Reported as "no files matched", naming the
  patterns tried.
- **Candidate with no chapter.** Harvested evidence can carry no recognisable
  chapter number. Such a candidate is shown, but cannot be accepted until the
  GM supplies a real chapter — a log row without one is invalid by the
  registry's own rules.
- **Candidate matching a ratified thread with nothing new.** Not presented as
  pending; already-logged chapters are not re-proposed.
- **A ruling already made.** Accepted, rejected and discussed candidates keep
  their ruling across re-harvests; a re-harvest never resets a decision to
  pending.
- **A write that fails the consistency check.** Nothing is saved and the
  invariant errors are shown; the registry is never left in a state its own
  check rejects.
- **Two names for one thread.** Matching is by exact normalised title or a
  recorded alias, never by similarity — a near-miss title produces a second
  candidate for the GM to rule on, not an automatic merge.
- **A discussed candidate with no adjudication yet.** Stays visible and
  re-rulable; the adjudication file accumulates rather than being overwritten
  out from under a conversation in progress.
- **The registry exists but has no threads.** The planning document's threads
  section renders as an empty-but-valid section rather than blocking assembly.
- **A thousand-candidate harvest.** Real corpora produce ~1000 candidates,
  almost all of them single-chapter observations rather than threads. The
  surface must stay usable at that size without hiding anything silently and
  without ruling on anything automatically — and the way to the hidden tail is
  a query, not a "show everything" button.
- **Two candidates that are obviously the same thread.** "Ajar door on third
  floor" and "ajar third-floor door" arrive as two candidates. They stay two
  candidates until the GM ratifies one and records the other as an alias —
  software never merges them.

---

## Requirements *(mandatory)*

### Functional Requirements

**Discovery and harvest**

- **FR-001**: The system MUST provide a Threads surface in the interface that
  shows the campaign's ratified threads and its pending thread candidates.
- **FR-002**: The system MUST let the GM run the thread harvest from that
  surface over a corpus the GM explicitly chooses.
- **FR-003**: The system MUST refuse to run a harvest with no corpus chosen,
  and MUST NOT substitute a default or an implicit "every chapter".
- **FR-004**: The harvest MUST remain deterministic and spend no model tokens.
- **FR-005**: The system MUST show, per candidate, its title, the chapters it
  was found in, whether it matches an already-ratified thread, and its
  supporting evidence including verified quotes where the extraction recorded
  them.
- **FR-006**: The system MUST NOT modify the registry as part of a harvest.

**Ruling**

- **FR-007**: The system MUST offer exactly three rulings per candidate —
  accept, reject, and discuss — and MUST apply a ruling to exactly one
  candidate at a time. No control may rule on multiple candidates in one act.
- **FR-008**: Accepting MUST present every field that will be written (id,
  title, opening chapter, and one log row per chapter with change type,
  summary and optional quote), pre-filled from the candidate's evidence and
  editable by the GM, and MUST write only after the GM confirms.
- **FR-009**: Accepting a candidate that matches an already-ratified thread
  MUST add its unlogged chapters to that thread rather than creating a second
  thread.
- **FR-009a**: A thread that has been accepted MUST keep surfacing as later
  chapters mention it, carrying only its unlogged chapters. Accepting a
  candidate ratifies *what has happened so far*, never the thread's whole
  future (GM ruling, 2026-08-25; research D17).
- **FR-010**: Rejecting MUST record the decision durably such that the
  candidate is not presented as pending by a later harvest.
- **FR-011**: Discussing MUST record the decision the same way a rejection is
  recorded — nothing enters the registry — and MUST additionally write the
  candidate and its evidence to an adjudication file that a Claude
  conversation can consume without re-running the harvest.
- **FR-012**: A discussed candidate MUST remain visible on the surface and
  MUST be re-rulable as accept or reject later.
- **FR-013**: A reject or a discuss ruling MUST survive a re-harvest
  unchanged — those are the one-way doors. An accept records that the
  candidate became a thread and MUST NOT suppress later chapters of it
  (FR-009a).

**Maintenance**

- **FR-014**: The system MUST let the GM add a per-chapter log row to a
  ratified thread, naming the chapter, the change type, a summary, and an
  optional quote.
- **FR-015**: The system MUST let the GM change a thread's lifecycle status
  among the statuses the registry defines, and MUST require a closing chapter
  when the new status is one that closes the thread.
- **FR-016**: The system MUST let the GM record an alias on a ratified thread,
  and MUST refuse an alias that already names a different thread.
- **FR-017**: The system MUST let the GM run the registry's consistency check
  and MUST display every problem it reports.

**Integrity and boundaries**

- **FR-018**: Every registry write the interface performs MUST go through the
  same engine the command line uses, so that a thread ratified in the
  interface and one ratified at the command line are indistinguishable on
  disk.
- **FR-019**: Every ruling and every adjudication export MUST likewise be
  performed by that engine — the interface MUST NOT be the only place a ruling
  can be recorded, and MUST NOT write these files itself.
- **FR-020**: The system MUST refuse any write that would leave the registry
  failing its own consistency check, save nothing, and show the reason.
- **FR-021**: Every refusal the engine can produce MUST reach the GM as a
  readable message naming the cause — never as a raw stack trace and never as
  silence.
- **FR-022**: The system MUST NOT auto-ratify, auto-merge, or infer thread
  identity from similarity. Identity is matched by exact normalised title or a
  recorded alias only.
- **FR-023**: The interface MUST hold no thread state of its own. Everything it
  shows MUST be re-derivable from the files on disk, so the same work can be
  done at the command line or in a Claude conversation with nothing lost.

**Signposting**

- **FR-024**: When a required section of a grounding document has no input
  yet, the projection table MUST name the missing store on the row itself,
  before any build is attempted.
- **FR-025**: For the `threads` section specifically, that row MUST offer a way
  to reach the Threads surface.
- **FR-026**: When a build fails because a required section has no file, the
  reported failure MUST name the section and point at the surface that creates
  it, in addition to the underlying error text.

**Queue tractability** *(added 2026-08-25 from a Phase 0 measurement — a real
62-chapter corpus harvests to 986 candidates, of which 16 span more than one
chapter — and revised on a GM ruling the same day; see research D15 and D16)*

- **FR-027**: The queue's default view MUST separate candidates into two named
  bands, each with its own count, most-likely first (GM ruling, 2026-08-25):
  **recurring** — appears in two or more chapters — and **single chapter,
  repeated** — one chapter, but mentioned more than once. Within each band,
  order by chapters spanned, then evidence count, then title.
- **FR-028**: Everything below both bands — a candidate mentioned exactly once
  — MUST be excluded from the default view, and the count excluded MUST be
  stated on screen. The excluded remainder MUST NOT be offered as an
  undifferentiated list: at ~900 entries that is not reachability, it is a
  wall (GM ruling, 2026-08-25).
- **FR-028a**: Every band count and the excluded count MUST be computed from
  the loaded candidate set, never stated as a fixed number. Measured spreads:
  16 / 54 / 916 on a 62-chapter corpus, 2 / 19 / 394 on a 31-chapter one, and
  3 / 12 / 104 on a 15-chapter one.
- **FR-029**: Every candidate MUST instead be reachable by query: free-text
  search over candidate titles, every title variant, and evidence text; and a
  filter by chapter. A candidate the GM can name, or can place in a chapter,
  MUST be findable without paging.
- **FR-030**: Search MUST cover the full candidate set regardless of ruling —
  a rejected or deferred candidate stays findable, because "what did I already
  decide about this" is the question the GM will ask.
- **FR-031**: Filtering, ordering and search MUST be presentation only. Nothing
  may rule on, merge, group or discard a candidate on the GM's behalf —
  including by similarity between candidate titles.

**Run gating** *(added 2026-08-26 on a GM ruling. The surface this feature
builds ends at a planning build, and the interface refuses to start that build
whenever one particular provider's key is absent from the environment — even
when the build calls no model, and even when the run targets a backend that
never reads it. Filed as #341, then pulled in scope because it gates SC-001:
without it, US4 signposts a button the GM cannot press. See research D21.)*

*(Revised 2026-08-26 after the GM ruled on #342: the predicate is **deleted**,
not corrected. An earlier draft of FR-032–FR-034 required the gate to ask about
the resolved backend and to declare each backend's credential once. No gate now
asks anything, so there is nothing to declare. Delivered by PR #343.)*

- **FR-032**: No control in the interface may gate a run on whether a
  credential is present. Every run starts; a run that needs a credential it
  does not have refuses **at the call**, from the backend that needs it.
- **FR-033**: That refusal MUST name the credential and at least one way to
  proceed without it. Naming the problem alone reproduces the failure this
  replaces — the deleted warning named a credential three of the four supported
  backends never read.
- **FR-034**: A credential check MUST live with the backend that needs one, and
  nowhere else. No global "is a key set" probe may exist, in the server or the
  interface — including one derived under a different name.

### Key Entities

- **Thread**: a ratified narrative thread. Has a stable id, a title, a
  lifecycle status, the chapter it opened in, an optional closing chapter, an
  optional link to a GM arc tracker, a list of alternative titles, free notes,
  and an ordered log. Arc scores are not threads.
- **Log row**: one ratified per-chapter transition on a thread — a real
  chapter number, a change type, a summary, and an optional quote.
- **Candidate (proposal)**: a harvested, un-ratified thread suggestion — a
  normalised key, the titles it was seen under, the chapters it appeared in,
  the ratified thread it matches if any, its supporting evidence, and its
  current ruling.
- **Ruling**: the GM's decision on a candidate — pending, accepted, rejected,
  or under discussion. Durable, and preserved across re-harvests.
- **Adjudication bundle**: the file of under-discussion candidates and their
  evidence, produced for a Claude conversation to reason over and handed back
  to the GM as an accept/reject decision.
- **Section state**: how a grounding document's section stands — fresh, stale,
  unbuilt, optional, or without input — as already reported per section by the
  projection surface.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A campaign that has never had a thread registry can go from zero
  threads to a planning document that assembles, without the GM opening a
  terminal or a text editor at any point.
- **SC-002**: Zero paths through the interface end in an error naming a file
  the interface offers no way to create — the specific dead-end #337 reports
  is gone for `threads`.
- **SC-003**: A GM can rule on a candidate — read its evidence and record
  accept, reject or discuss — in under 60 seconds, and can clear the
  **recurring** band (measured at 16 candidates on a 62-chapter corpus, 2 on a
  31-chapter one) in a single sitting without leaving the surface. Clearing all
  ~1000 raw candidates is explicitly **not** a goal; see SC-010/SC-011 and
  FR-027–FR-031.
- **SC-004**: 100% of threads that enter the registry through the interface
  passed through a form the GM saw and confirmed. Zero threads can be created
  by a single click from the queue.
- **SC-005**: A thread ratified through the interface and the same thread
  ratified through the command line produce identical registry content.
- **SC-006**: After ruling on N candidates and re-running the harvest, 100% of
  those N rulings are still recorded and none of them reappear as pending.
- **SC-007**: Every candidate marked for discussion is present in the
  adjudication file with enough evidence to be adjudicated without re-running
  the harvest — measured by handing the file alone to a conversation and
  getting a decision back.
- **SC-008**: 100% of engine refusals (empty corpus, no files matched,
  duplicate id, colliding alias, missing closing chapter, failed consistency
  check) are shown in the interface with their cause; zero raw tracebacks
  reach the GM.
- **SC-009**: Nothing on the surface is lost by doing the same work at the
  command line — after a command-line ratification, a reload of the surface
  shows the identical state.
- **SC-010**: On a corpus that harvests to ~1000 candidates, the GM reaches the
  handful that span multiple chapters without paging through the rest, both
  band counts and the excluded count are visible without any action, and every
  one of those numbers matches the loaded set rather than a figure written into
  the interface.
- **SC-011**: Any candidate the GM can name — including one already rejected or
  deferred — is on screen within a few seconds of typing part of its title, and
  every candidate from a given chapter can be listed in one step. No candidate
  requires scrolling an unfiltered list to reach.
- **SC-012**: With no Anthropic credential in the environment, every
  deterministic build and every run targeting a local or subscription backend
  can be started from the interface. The only runs refused are the ones that
  genuinely need a credential that is missing, and each names which one and how
  to proceed without it. This is what makes SC-001's "without opening a
  terminal" true on the GM's own machine rather than only on one that happens to
  hold a metered API key.

---

## Assumptions

- **Single GM, one campaign at a time.** The surface is used by one person
  working one campaign; simultaneous editing from two places is not a case
  this feature designs for.
- **Issue option 1 only.** The GM ruled on 2026-08-25 that this feature builds
  the thread registry surface. Option 2 — a generic "here's the command to
  run" hint for *every* required section in a no-input state — is not adopted;
  US4/FR-024–FR-026 deliberately cover only naming the missing store and
  routing the `threads` case, not composing commands for arbitrary sections.
  Option 3 — auto-creating an empty registry stub for new campaigns — is not
  adopted either: the engine already treats an absent registry as empty, so a
  stub would buy an assembling-but-contentless planning document while leaving
  the real gap (no way to get thread content) untouched.
- **The harvest source already exists.** Thread candidates come from
  extraction output that a campaign must already have produced; this feature
  does not run extraction, and a campaign with no extraction output has
  nothing to harvest.
- **No ruling verb exists yet.** The engine can harvest candidates and
  preserve rulings it finds, but nothing today *records* a ruling or exports an
  adjudication bundle — both are new engine capabilities this feature must add
  at the command line first, because the interface is forbidden from being the
  only place they exist.
- **The speculation surface stays out of scope.** The registry's separate
  model-driven brainstorm — explicitly non-canon idea material — is not part of
  this feature; nothing here spends model tokens.
- **Prior scope call is being revisited deliberately.** The State Projection
  service shipped with thread triage excluded from the interface on the
  grounds that a proposal write route would move a judgment checkpoint into
  the interface. This feature reverses that call on the GM's ruling, and
  preserves the underlying principle instead of the exclusion: one candidate
  at a time, every field shown before it is written, and no control that rules
  in bulk. The checkpoint stays a human decision — it changes keyboard, not
  owner.
- **Adjudication happens in conversation, not in the interface.** "Discuss"
  hands work to a Claude conversation through a file, and the answer comes
  back through the GM. The interface never asks a model to rule on a thread.
- **The harvest's signal-to-noise is upstream and unchanged.** Candidates are
  keyed on the free-text subject the extraction lens wrote, which is why most
  of them are not threads. Improving that lens is out of scope here; this
  feature makes the resulting queue navigable, not smaller.
- **Existing controls are reused.** The surface follows the conventions the
  interface already has for choosing a corpus, running a step and streaming
  its output, so nothing here needs a new interaction model.
