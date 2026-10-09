# Data Model: Chunked, Code-Checked Party and Planning Documents

Everything is files.

- **Read-only inputs:**
  - spec 033's checked notes;
  - the entity registry and `players.yaml`;
  - `party.yaml` and `planning.yaml`, with their sheets, backstories and arc-score mechanic files;
  - the published dossiers in `docs/npcs/`.
- **The thread registry** (`docs/thread_registry.yaml`) is read by the build and written **only** by GM ratification (`thread_registry ratify|rule|log|set-status|alias`).
- **The proposals file** is written by `thread-propose` and `thread_registry propose`, preserving rulings.

Spec 033's layout and entities (chunk, note, drop record, run record, reference file, reading contract, annotation) are unchanged except where noted below.

## On-disk layout (additions to spec 033's `state/`)

```text
<out_root>/ch{since:03d}-{until:03d}/state/
├── notes/…                                  # 033; party notes now carry a subject, plus [LEVEL] rows (R1)
├── runs/{stamp}/
│   ├── record.json                          # + doc party|planning, config files and sha256, threads registry sha256
│   └── {doc}.{section}.{user,out}.md         # one per prose / NPC / faction / arc call
├── threads/
│   ├── attach.json                          # code: note id -> thread id | "ambiguous" | null, per run (R4)
│   ├── propose.{user,out}.md                # thread-propose prompt(s) and raw output(s), one pair per batch
│   └── propose_report.md                    # members dropped and why, groups dropped, single-note fallbacks
└── drafts/
    ├── party.draft.md                       # reading contract + sections (+ annotations)
    ├── planning.draft.md
    ├── reference/threads_unratified.md      # NEW (planning): every unattached thread note, verbatim, chapter order; a counts line; says none when empty
    ├── reference/party.md                   # NEW: party notes by attributed character, plus Companions and Unattributed
    ├── party_report.md                      # NEW: attribution (unattributed subjects, companions), level source per character
    ├── planning_npcs_report.md              # NEW: like key_npcs_report.md (model / substituted / fallback per NPC)
    ├── arc_report.md                        # NEW: candidates kept and dropped, with reasons
    └── threads_report.md                    # NEW: ratified threads in range (open/closed, why), ambiguous names, unattached count
docs/thread_registry.yaml                    # existing; GM-ratified, the thread identity authority
docs/ensemble/thread_proposals.yaml          # existing path (projections.yaml thread_proposals); gains group proposals
```

**Superseded:** the one-shot drafts under `<range>/drafts/{party,planning}.draft.md` are no longer written. `schema.draft_dir` now returns `state/drafts` for every document.

**Promotion** stays manual:
- `party.draft.md` becomes `docs/party.md`, and `planning.draft.md` becomes `docs/planning.md`.
- `reference/party.md` joins `docs/reference/`.
- planning's reading contract lists four reference files (`factions`, `npcs`, `threads`, `threads_unratified`); promote all four beside `planning.md`.

## Entities

### Party note (changed: spec 033's `Note`, kind `party`)
| Field | Rule |
|---|---|
| `subject` | bold `**Name**` at the start of the bullet: one character's name, several joined by `,` / ` and ` / `&`, or exactly `Party` (R1). Missing → dropped `missing-party-subject`. Resolved whole first; split only when the whole resolves to nothing (R2) |
| `tag` | `LEVEL` for a level row, else none |
| `level` | for `LEVEL` rows: integer N, confirmed in a level phrase of a cited section (R1). Unconfirmed → dropped `level-not-in-cited-text` |

### Party attribution (code, R2)
| Field | Rule |
|---|---|
| `note_id` | R6 id |
| `scope` | `character` \| `party` \| `companion` \| `unattributed` |
| `characters` | canonical player-character names, when `scope = character`; several when the subject names several and all resolve |
| `reason` | for `unattributed`: the piece that resolved to nothing, or "claimed by more than one entity" |

### Character section (party)
| Part | Built by |
|---|---|
| `### {name}` heading, in `party.yaml` order, named exactly as configured | code |
| level line `Level: N [cite]` or `Level: not recorded in the summaries (sheet says N)` | code (R3) |
| body (current situation, recent decisions, injuries, acquisitions, relationships) | model, from this character's notes + sheet + backstory only |
| `Unsupported by the summaries: …` | model, checked by the annotators like any prose line |
| `#### Candidate Arc Score Events` | model, checked by `arc_check` (R10); absent for trackless characters |
| `_Full notes: reference/party.md_` | code |

### Thread registry entry (existing schema; read here)
| Field | Rule |
|---|---|
| `id`, `title`, `aliases[]` | identity; a note attaches when `norm_title(note.name)` equals `norm_title` of the title or an alias (R4) |
| `status` | `open | dormant | resolved | abandoned`. Set by the GM: when not `open`, it wins over note tags |
| `log[]` | `{chapter, change, summary, quote?, cite?}`. `cite` is new and optional, written by group ratification (R7) |

### Thread attachment (code, per run)
| Field | Rule |
|---|---|
| `note_id` → `thread_id` | exact match only. A name matching two threads → `ambiguous` (reported). No match → unattached |
| `open` | registry status `dormant` / `resolved` / `abandoned` wins (dormant → the dormant block); a status of `open` (the default) defers to the latest attached note's tag ∈ {OPENED, ADVANCED} |
| `latest` | the latest attached note (max `first_chapter`, then extraction order); sets Active Plots order (newest first) |

### Thread proposal (group; new shape in the existing proposals file, R5)
| Field | Rule |
|---|---|
| `key` | `g-` + sha1 of sorted member ids (12 hex). Stable for an identical grouping, so a ruling on it persists |
| `kind` | `new` (suggested `title`) \| `continues` (`thread` = an existing registry id) \| `single` (one member, from code fallback) |
| `members[]` | `{id, chapter, tag, name, text, cite}`. Every id is a real, unattached checked note of the run; a note is in at most one pending proposal |
| `status` | `pending` → `ratified` \| `rejected` \| `deferred` (existing statuses). `rejected` members are kept out of future model input and re-offered as `single` |
| `source` | `summary_native ch{aaa}-{bbb} run {run_id}` |

**State transitions:**
- `pending` → (GM `ratify --key K --plan P`) → `ratified`. The registry gains the thread or log rows plus aliases. `ratify` refuses (nothing written) an `aliases_add` name carried only by members the plan leaves out. When P covers a subset of the members, the remainder becomes a new `pending` group (split), and the ratified thread records the remainder's ids as `excluded_notes` (below, #529).
- `pending` → (GM `rule --key K --status rejected|deferred`) → `rejected`/`deferred`. These are one-way doors, as today.
- **Registry thread field `excluded_notes: [note id]` (optional, #529).** The ids of the notes a split left out of this thread. `thread_attach` skips a thread for an excluded note before comparing names, so a split-off note that shares a ratified name is neither attached nor lost: it is unattached and stays in its pending remainder. Additive and optional (an older registry has none; `check_registry` requires a list of non-empty strings when present), so no migration. Removed in the same write that ratifies the note into the same thread; kept when it is ratified into another. Ids belong to one extraction, so `thread-propose` reports an id that is in no range's notes on disk ("excluded note n-… is in no range's notes on disk (re-extracted?)") and never removes it.
- A ratified group whose member ids no longer exist after re-extraction is listed as **stale** in `propose_report.md`. Its aliases keep attaching any note that repeats a name. A ratified member whose note exists but attaches to no thread (an alias was removed) is listed under "Ratified but no longer attached (alias removed?)" in `propose_report.md` and `threads_report.md` and offered again as a pending `single` carrying an optional `reoffer: {from_group, thread}` hint (additive; older readers ignore it).

### Planning NPC entry
| Part | Built by |
|---|---|
| selection (tracked in `planning.yaml` ∪ recent/recurring ∪ `--name`), order (as `select_key_npcs`) | code |
| `### {name}` + `Status and location:` / `Goals:` / `Relationships:` lines, cited | model, from the dossier's Identity, Personality and Motivations, Last Observed State and Relationships only (R8) |
| check: citations ⊆ that dossier's, quotes verbatim, heading set/order exact; fail → the dossier's first Last Observed State sentence, reported | code |
| `→ docs/npcs/{slug}.md` | code |
| no published dossier: refuse (default), or `{KEY_NPC_FALLBACK_MARK}` line from status row + notes (`--fallback-npc-lines`) | code |

### Faction entry
| Part | Built by |
|---|---|
| selection: `planning.yaml` factions ∪ `[FACTION]` subjects (canonical by registry `forms`), newest first, at most `DEFAULT_MAX_FACTIONS` written, the rest named with a pointer | code |
| `### {name}` + body from that faction's notes only | model; heading set/order checked; fail → latest note verbatim |

### Arc-score candidate (R10)
| Field | Rule |
|---|---|
| `subject` | a `party.yaml` character or a `planning.yaml` NPC/faction with a non-trackless `arc_score` file |
| `event` | text, with ≥ 1 citation drawn from the subject's checked notes' citations |
| `trigger` | quoted span, verbatim in the mechanic file |
| dropped when | `cite-not-in-notes`, `trigger not verbatim`, `states a value` (listed in `arc_report.md`) |

### Active Plots section (planning)
```text
## Active Plots
<one entry per open ratified thread, newest activity first: "### {title}" + model body from its attached notes; failed checks → latest attached note verbatim>
### Dormant threads
<code-built, only when a ratified thread with notes in the range has registry status `dormant`: "- **{title}** — {latest attached note text, verbatim, with its citation}", newest first; no model call>
### Unratified thread notes (not yet ruled on)
_{N} checked thread notes are not in the thread registry. Verbatim, in chapter order, in reference/threads_unratified.md. They are evidence, not plots: rule on them at /grounding/threads (or `summary_native thread-propose`, then `thread_registry ratify`)._
(no notes are listed here: FR-009b, GM ruling 2026-10-09; they are in reference/threads_unratified.md)
```
When the registry has no thread with notes in the range, the ratified part is the single line `_No ratified thread has notes in this range._`; when ratified threads have notes but none is open, it is the `NO_OPEN_THREADS` line instead

## Defaults (declared once in `schema.py`)
| Name | Value |
|---|---|
| `DEFAULT_PARTY_BUDGETS` | `{"Party Overview": 300, "Characters": 500, "Party Dynamics": 300}`. Characters is per character |
| `DEFAULT_PLANNING_BUDGETS` | `{"NPC Dossiers": 1500, "Faction States": 600, "Active Plots": 1200, "DM Notes": 400}` |
| `DEFAULT_MAX_FACTIONS` | 20 |
| `DEFAULT_THREAD_PROPOSE_MAX_INPUT_CHARS` | 150000 |
| `PARTY_SUBJECT` | `"Party"` |
