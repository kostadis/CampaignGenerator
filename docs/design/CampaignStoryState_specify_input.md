# Spec Kit input: campaign story-state foundation

**Date:** 2026-11-13

**Companion design:** [CampaignStoryState_design.md](CampaignStoryState_design.md)

**Status:** feature description for a future Spec Kit run; not a generated `specs/<feature>/spec.md`.

Paste the following instruction into a Spec Kit conversation:

```text
$speckit-specify Use docs/design/CampaignStoryState_specify_input.md as the
complete feature description. Read CampaignStoryState_design.md for evidence,
architecture constraints, and follow-up boundaries. Specify the foundation
feature only. Preserve all human checkpoints and the disk-as-truth contract.
Do not include reviewed source mutations or thread-registry retirement.
```

## Feature and problem

Provide CampaignGenerator's first-class read model for campaign story arcs, sandboxes, clocks, and in-fiction calendars. The GM should be able to ask what is running in a place, which arcs share a junction, which clocks need attention, and what date it is, without an agent rediscovering and reconciling the same Markdown tables at every prep.

The existing GM-assistant lives in the separate campaigns repository. Its `gm-arc` skill owns the new/record/mine workflow; `gm-session-prep` reads those files and asks whether offscreen clocks moved; `gm-player-calendar` renders a reviewed player timeline. Their reusable bookkeeping should be supplied by the installed CampaignGenerator package.

The evidence-backed failure is Phandalin's Leilon timing: `calendar.md` retains the older 17 Kythorn condition, while the arc clock includes a later arrival-by-21-Kythorn ruling and still retains the older date. The first feature must expose the competing assertions with their sources. It must leave the ruling to the GM.

This feature is the **read-only foundation** of the companion design. It establishes imports, relationships, diagnostics, setting-calendar calculations, and supported views. Reviewed source editing is a separate feature. A successful foundation does not claim to have implemented `gm-arc record` or automatic clock advancement.

## Users and authority

- The GM uses the CLI, web face, or an assistant's read-only tools to inspect campaign state and prepare questions.
- A prep skill consumes the same dated, cited snapshot and discusses unresolved matters with the GM.
- Players receive only the existing explicitly reviewed player-calendar content; the service does not derive disclosures from GM notes.
- Campaign files are the authority. Every database and generated view can be deleted and rebuilt from the declared files.

## Scope

Include:

- One-campaign configuration, source inventory, deterministic import, and derived-index status.
- Arcs, sandboxes, beats, affordances, clocks, rulings, junctions, calendar spans and expectations, and linked evidence/strategy references.
- Existing identity resolution and played-session mapping; traceable unresolved references.
- Harptos, the campaign's confirmed Greyhawk Common Year definition, and numbered-day calendars.
- Arc/clock/junction/calendar queries, exact-source thread suggestions, consistency diagnostics, and a GM prep snapshot.
- Package-owned calendar validation and local rendering from already reviewed player-calendar JSON.
- A CLI engine, a thin web invocation face for every delivered CLI capability, and read-only assistant tools sharing the query contract.

Exclude:

- Writing or regenerating GM-owned origins, summaries, registries, strategy documents, approved dates, scores, or review verdicts.
- Implementing new/record/advance mutations, granting approvals, proposing story content with a model, or automatically promoting threads.
- Retiring the current thread registry or changing grounding synthesis to consume arc prose.
- A quest graph editor, retrospective pinned character milestones, or a whole-campaign graph visualization.
- External hosting, calendar sharing, and automatic publication to an existing public/player URL.
- A database daemon, embedding search, fuzzy identity resolution, or a general Cypher write surface.

## User scenarios and acceptance

### US1 — Inspect a campaign without changing it (P1)

The GM explicitly builds a derived state view from declared campaign sources, sees its coverage, and follows every displayed record to its origin.

1. Given the sanitized Phandalin-shaped fixture, rebuilding imports three arcs, two sandboxes, thirteen global and six arc-local clocks, and ten junctions, with exact source locators.
2. Given the same source bytes and configuration, repeated rebuilds yield equivalent normalized records and relationships, with no duplicates. Runtime timestamps and engine-internal IDs are not part of equivalence.
3. Given an unknown arc reference, ambiguous entity, duplicate authored slug, or unsupported row, the report names the source and the problem; nothing is silently merged or omitted from coverage.
4. Given changed source bytes during import or an interrupted build, no partial generation is published. Existing origins and the previous usable generation remain intact.

### US2 — Get one reliable prep snapshot (P1)

The GM selects a sandbox and/or explicit arcs and receives their pending beats, clocks, shared junctions, deferred decisions, and source links.

1. The snapshot lists only selected scope and explicitly linked relevant records. An empty action selection refuses rather than exporting everything.
2. Dead beats remain in history and do not appear as pending offers. A possible beat stays unplayed regardless of its planned date.
3. An unknown numeric score with a recorded increment remains unknown; a pending increment changes no value.
4. A stale clock or arc is flagged using its own last-touched/reconciled fields. Neither status nor state advances.
5. A GM-only ruling remains confined to GM output. A mention of an NPC does not establish presence or knowledge.

### US3 — Calculate time and expose uncertainty (P1)

The GM inspects ruled dates, elapsed days, and due expectations in the campaign's own calendar.

1. Calendar comparisons cross supported month, festival, leap, and year boundaries correctly, including Harptos Shieldmeet and the confirmed Greyhawk festival-week ordering.
2. Unknown dates/years/anchors and grouped chapter spans remain unresolved at the precision the sources support. The service does not allocate days to individual chapters inside an unsplit group.
3. An uncertain today range produces a bounded due/overdue result, never a fabricated exact date or an automatic clock event.
4. Leilon-style conflicting timing text is displayed together with source dates and locators. Departure, arrival, and failure conditions are not collapsed into one selected deadline.
5. A difference between declared elapsed days and explicit start/end dates is reported without rewriting the calendar.

### US4 — Reuse the same operations across interfaces (P1)

The GM can invoke the delivered capabilities from the CLI and web face, and an assistant can read the same query results.

1. Every CLI capability and meaningful option has a reachable web control in this feature. Routes delegate to the CLI rather than reimplementing behavior.
2. CLI, web, and assistant queries return equivalent domain values, coverage, freshness, and source references for identical scope.
3. A missing/stale/corrupt derived index produces an actionable status. A normal query does not silently rebuild it; an explicitly requested stale diagnostic is visibly marked.
4. Every interface remains bound to one campaign; invalid paths or links cannot read another campaign's sources.

### US5 — Build a player calendar from reviewed content (P2)

The GM renders an existing reviewed player-calendar JSON file using the installed package.

1. Supported dates, ordering, groups, and the displayed today are validated using the shared calendar rules. Invalid input fails before replacing output.
2. The local result preserves reviewed wording and contains no GM source content, private review notes, or publication metadata injected from the GM snapshot.
3. Rendering works from an installed distribution without locating the campaigns repository's scripts/templates. No external publishing or sharing occurs.

### US6 — Find existing thread suggestions (P2)

The GM or prep skill searches explicitly selected checked thread-note sources by approved entity aliases or literal terms.

1. Results preserve their citations, latest supported status, and suggestion label. Repeated titles may be grouped exactly; similar titles are not merged by inference.
2. Old/resolved observations are down-ranked using documented rules, retained, and never automatically attached to an arc.
3. The source mode is declared. Missing checked sources do not silently switch to ensemble history; the operator can explicitly configure the alternate source adapter.

## Functional requirements

- **FR-001:** Bind each operation to one campaign using the existing config-root contract. Reject source/output path escapes, including symlinks.
- **FR-002:** Declare source paths, calendar definition, derived-output paths, and thresholds once in strict campaign-owned configuration. Runtime readers never silently migrate a layout.
- **FR-003:** Preserve origin files byte-for-byte. Only explicitly requested derived builds/renders may write their declared output locations.
- **FR-004:** Import the supported source structures without model calls, including frontmatter, relevant sections/tables, provenance, and explicit references. Preserve and report unsupported content.
- **FR-005:** Include origin path, locator, original text, source fingerprint, and parsed authority/review/disclosure/precision attributes on each observation where available; absence is visible.
- **FR-006:** Reuse existing entity and session identity authorities. Do not equate mention with presence, chapter label with session identity, or similar names with identity.
- **FR-007:** Use authored IDs where present and documented deterministic observation keys otherwise. Treat edited legacy rows as changed observations, not as proven enduring identities.
- **FR-008:** Retain unresolved/ambiguous references and duplicate declarations as source-linked findings. Invalid required structure prevents publication of a usable generation.
- **FR-009:** Build and publish complete, fingerprinted generations. Interrupted or concurrently invalidated builds must not replace a usable generation with partial results.
- **FR-010:** Allow all derived database/snapshot/view data to be deleted and reconstructed from source files. No origin or human decision may exist only in the index.
- **FR-011:** Detect freshness against configuration, source, identity, calendar-definition, and importer versions. Queries do not conceal stale or incomplete coverage.
- **FR-012:** Provide selected-scope queries for arcs, sandboxes, beats, clocks, junctions, calendar spans/expectations, and prep state, with source references.
- **FR-013:** Keep planned, played, ruled, and proposed information distinct. Foundation never confirms an outcome, advances a clock, changes a score, or promotes a thread.
- **FR-014:** Represent exact, uncertain, relative, conditional, and unknown fictional time without Gregorian coercion or precision invented from prose.
- **FR-015:** Calculate supported calendar arithmetic and elapsed/due intervals across festival/leap/year boundaries. Unknown anchors remain unresolved; date comparisons never authorize events.
- **FR-016:** Preserve recorded dating methods and uncertainty. Report source day-count inconsistencies and multiple timing assertions without automatically choosing a ruling.
- **FR-017:** Distinguish fixed due dates, arrival/departure conditions, progress tracks, numeric increments, and unresolved natural-language states. Unknown totals remain unknown.
- **FR-018:** Flag stale clocks/arcs and down-rank thread observations using declared 2/4/6 played-chapter defaults, without deleting or changing the records.
- **FR-019:** Keep GM-facing output separate from player rendering. The player renderer reads explicitly reviewed player JSON only and preserves its wording.
- **FR-020:** Support deterministic local calendar rendering, validating dates/order/groups before replacing output, with required assets packaged in the distribution.
- **FR-021:** Provide the delivered capabilities through one CLI engine and a thin web face with full option reachability. Read-only assistant tools share the query contract.
- **FR-022:** Require explicit scope for batch prep/export actions. An empty selection performs no batch action; read-only discovery can list available choices.
- **FR-023:** Emit structured status/results/diagnostics suitable for assistants, alongside readable output. Results state source coverage and freshness.
- **FR-024:** Prevent active-reader/build races and unsafe database connection sharing. Concurrent rebuild/query behavior must be deterministic, refused clearly, or served from a complete retained generation.
- **FR-025:** Preserve current grounding, thread-registry, villain-ledger, and dossier ownership contracts. No foundation output becomes new grounding authority.
- **FR-026:** Provide exact-source thread discovery with explicit source-mode selection. Report missing inputs rather than silently changing provenance mode.
- **FR-027:** Keep all import/check/query/calendar logic free of model calls. The feature must spend no model tokens.
- **FR-028:** Ship operator documentation for initialization, explicit rebuild, status/refusals, supported source coverage, local rendering, and recovery by rebuilding derived state.

## Key entities

- **Story arc:** prospective story question, possible beats, rulings, and witnessed evidence; distinct from the retrospective character milestones in issue #537.
- **Sandbox:** a location's factions, party goals, affordances, and explicitly associated arcs.
- **Clock/expectation:** sourced state and optional time/trigger condition, with ownership and last touch.
- **Observation/reference:** an exact source-backed record or unresolved relationship, carrying identity and provenance.
- **Calendar span/date expression:** an approved or unresolved date/range, its dating method, uncertainty, and basis.
- **Index generation/prep snapshot:** a complete derived view with configuration/source fingerprints, selection, diagnostics, and freshness.
- **Player calendar:** explicitly reviewed event wording and dates supplied independently of GM-only state.

## Success criteria

- **SC-001:** Every imported fixture record is either queryable with a source locator or explicitly accounted for in the coverage report; no silent record loss.
- **SC-002:** Repeated builds over identical inputs produce equivalent normalized records and relationships with no duplicate accumulation.
- **SC-003:** Origin-byte comparisons before/after all foundation operations show zero changes, including failure and interrupted-build cases.
- **SC-004:** All specified calendar boundary/uncertainty fixtures produce the expected comparison, interval, or unresolved result; the Leilon fixture leaves both origin assertions intact and visible.
- **SC-005:** Every delivered operation is reachable through the web face; equivalent interface queries return the same domain values and freshness state.
- **SC-006:** Deleting every derived artifact and rebuilding restores equivalent query results without a human re-entering any campaign decision.
- **SC-007:** All selected-scope and secrecy fixtures prevent unselected batch output, automatic state changes, and GM-only content in player output.
- **SC-008:** The installed package can perform an import/query and render the reviewed calendar using packaged assets; no campaigns checkout or model service is required.

## Assumptions and planning constraints

- Use the companion design's Relate evaluation as evidence for a rebuildable graph adapter. Pin and validate a supported release in planning; the scratch v1.0.1 checks establish functional feasibility only.
- Foundation must meet constitution I–XIII, including disk truth, human checkpoints, CLI/web parity, explicit selection, shared option definitions, and explicit one-shot migrations for any breaking state change.
- Source ambiguities remain findings for a later GM ruling. A citation resolving is not proof that it supports a claim.
- The current thread registry remains in service. Its retirement requires a separate consumer/migration specification, coordinated with issues #534/#535 and the GM-assistant's later arc design.
- A later reviewed-write feature owns enduring row IDs, proposal/review adapters, stale-approval refusal, atomic source-file application, and skill shims. None may enter this foundation through an implementation shortcut.
- Campaign-specific facts are fixtures and operator inputs, never hardcoded defaults. Verify Greyhawk against a declared campaign-approved definition and use sanitized fixtures for committed tests.
- Planning must settle exact module/command/config names, supported legacy grammar, backend packaging, generation locking/retention, diagnostics taxonomy, and the minimal web face. These are engineering decisions within the stated scope, not permission to change source authority.
