# Contract: Threads page + projection row (014)

## Route and entry points

- `/grounding/threads` → `frontend/src/views/grounding/Threads.vue`, registered
  as a child of `/grounding` in `frontend/src/router.ts`.
- `AppSidebar.vue` gains a **Threads** entry beside **State Projection**.
- `ProjectionSections.vue`'s `threads` row links here when its state is
  `no-input` (FR-025).

## Page regions

**1. Registry** — every ratified thread grouped by status (`open`, `dormant`,
`resolved`, `abandoned`), each showing title, id, opened/closed chapters,
tracker, aliases and its log rows in chapter order. Empty registry renders as
"no threads yet" — a normal state, never an error (spec edge case 1).

**2. Health** — the result of `check`, always visible: `N thread(s), M
problem(s)`, with each problem listed. A clean registry says so.

**3. Harvest** — a corpus field (multiple whitespace-separated patterns), a
**Resolve** action listing the matched files by name, and a **Run harvest**
action that streams. Run is disabled while nothing is resolved; attempting it
with an empty corpus surfaces the route's 400 text.

The file list shows **names only, no chapter numbers** (GM ruling, research
D20) — the server would have had to import the engine's `chapter_of()` or grow
a verb to feed one column. The warning it would have carried appears on the
candidate card instead, at the point of decision.

**4. Queue** — one card per proposal, filterable by ruling.

> **Sizing (research D15/D17, measured on three corpora):**
>
> | Band | Rule | OOTA (62 ch) | toee (31 ch) | Hillsfar (15 ch) |
> |---|---|---|---|---|
> | **Recurring** | appears in ≥2 chapters | 16 | 2 | 3 |
> | **Single chapter, repeated** | `<2` chapters, ≥2 mentions | 54 | 19 | 12 |
> | *(excluded)* | mentioned exactly once | 916 | 394 | 104 |
>
> The default view renders **both bands**, each under its own heading with its
> own count, recurring first; within a band, sort by chapters spanned, then
> evidence count, then title (FR-027). The band names carry the reasoning a
> bare count cannot — *recurring* is what a thread structurally is, *single
> chapter, repeated* is where a thread that opened last session lives before it
> has had the chance to recur.
>
> Below both bands, in words, not a badge:
> *"916 candidates mentioned exactly once are not shown — search or filter by
> chapter to reach them."*
>
> **Every one of these numbers is computed from the loaded set** (FR-028a).
> They differ by an order of magnitude across corpora, and a literal string is
> precisely the defect this replaced.
>
> **There is no "Show all" button** (GM ruling, 2026-08-25, research D16). At
> ~900 entries an undifferentiated list is not reachability, it is a wall of
> *"ajar third-floor door"*. The way in is a query instead:
>
> - **Search box** — free text over candidate title, every variant in
>   `all_titles`, and evidence `fact` + `quote` text. Matches are drawn from
>   the **full** set including already-ruled candidates (FR-030), each card
>   badged with its ruling, so *"what did I already decide about this"* is
>   answerable.
> - **Chapter filter** — list every candidate whose `chapters` includes N.
>   This is the realistic post-session move: "what did chapter 41 throw up."
> - **Ruling filter** — pending / ratified / rejected / deferred.
>
> Search and filters compose, and every heading restates its count under the
> current query. **Bands, ordering and search are presentation only** — nothing
> rules on, merges, groups or discards a candidate on the GM's behalf
> (FR-031). Near-duplicate titles ("Ajar door on third floor" / "ajar
> third-floor door") stay separate cards in whichever band each lands in;
> clustering them would be a similarity-based identity assertion (FR-022).
>
> Search runs in the browser over the payload `GET /threads/proposals` already
> returns whole; no server-side paging or query route exists, so "which
> candidates matter" never becomes a server decision.

Each card shows the title, every spelling seen, the chapters, whether it
matches a ratified thread, and its evidence rows (chapter · fact · quote where
verified · source — a row whose `source` is absent renders without one, never
as "None"). Quotes render verbatim and are visually distinguished from the
paraphrased fact.

Three actions per card, and only per card:

| Action | Opens | Writes |
|---|---|---|
| **Accept** | the ratification form (below) | `POST /threads/ratify` — one atomic call; success or a 400 whose `detail` is the engine's own refusal (research D18) |
| **Reject** | an optional note | `POST /threads/rule` status `rejected` |
| **Discuss** | an optional note | `POST /threads/rule` status `deferred`, and tells the GM where the adjudication file is |

There is **no** select-all, no multi-select, no "ratify remaining". A control
that rules on more than one candidate is a spec violation (FR-007, SC-004), not
a missing feature.

## The ratification form (FR-008)

Pre-filled from the proposal, every field editable, nothing written until the
GM confirms. The form **is** the engine's `--plan` object rendered as fields —
`thread_registry ratify --emit-plan` prints the same starting point for a GM
working at the terminal, so the two surfaces edit one shape:

| Field | Pre-fill | Notes |
|---|---|---|
| `id` | `norm` | Editable; collision is refused by the CLI and shown. |
| `title` | `title` | |
| `status` | `open` | |
| `opened` | `min(chapters)` | **Empty and required** when `chapters` is `[]`. |
| `tracker`, `notes` | empty | |
| log rows | one per chapter, `change` = `opened` for the first and `advanced` after, `summary` from that chapter's evidence fact, `quote` from its verified quote | Rows are addable, editable and removable. A row with no chapter blocks submit. |

When the proposal has `matches`, the thread fields are shown **read-only** with
the matched thread named, and only the log rows are editable — accept means
"add these chapters to that thread" (research D3).

## Maintenance (US3)

On a ratified thread: **Add log row**, **Change status** (closing chapter
required for `resolved`/`abandoned`, enforced in the form *and* by the CLI),
**Add alias**. Each is a single POST whose refusal text is rendered inline.

## Refusals and errors

Every 400 renders the `detail` string as-is, in an error box on the control
that caused it. No error is swallowed, and no stack trace is shown. The
existing `.error-box` style in `ProjectionSections.vue` is the pattern.

## State

None held across a reload. The page fetches registry, proposals and check on
mount, on doc/filter change, and after any successful write (FR-023, matching
`ProjectionSections.vue`'s "re-derived on load" comment).

## The harvest's run control (research D19)

The Threads page has **its own** run control. `RunPanel` is not modified and is
not used here (GM ruling, 2026-08-25).

`RunPanel` exists to make token spend visible and overridable before a run — it
carries `SelectionPanel`, previews the resolved model and backend, and disables
its button with an `ANTHROPIC_API_KEY not set` warning when that variable is
absent (`RunPanel.vue:70,133,137`). None of that applies to a pass that cannot
reach a model. Two behaviours, two controls; if
real duplication appears later, refactor then.

The harvest control: streams through the shared `connectSSE` client, shows the
output, reports the exit code, and checks nothing about API keys. It shows no
model, no backend and no selection, because the harvest has none.

## `RunPanel`'s gate — deleted (#342, PR #343)

There is no gate. The check that blocked the State Projection page's
deterministic builds, and every run on `dgx`/`openrouter`/`claude-code`, was
deleted outright rather than corrected — GM ruling, 2026-08-26. `apiKeyPresent`
is gone from the store and from all ten consumers; a backend that needs a
credential refuses at the call, naming it and the keyless alternatives.

Consequences for this feature: **none to build.** US4's signpost leads to a
button that starts. `RunPanel` still mounts `SelectionPanel` and still blocks on
an incompatible selection — that is a different check, about a model/backend
pair, and it stays.

D19 is unaffected, and in fact strengthened: "the harvest control checks nothing
about API keys" is now true of every control in the app, so the dedicated
control differs from `RunPanel` only in the ways D19 named — no `SelectionPanel`,
no model/backend preview, because a zero-token pass has neither.

## `ProjectionSections.vue` changes (US4)

- The **Inputs** cell renders the input paths rather than a count, with any
  path in `missing` marked.
- A `threads` row in `no-input` state shows a link: *"no thread registry yet →
  Threads"*.
- A failed build whose stderr names a missing section file is accompanied by a
  line naming the section and, for `threads`, the same link (FR-026).
