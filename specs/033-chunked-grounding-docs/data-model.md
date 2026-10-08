# Data Model: Chunked, Code-Checked Grounding Documents

Everything is files. Inputs are read-only: the summaries, the spec 031 corpus, the entity registry, `players.yaml`, the published dossiers in `docs/npcs/` and the tracking files. Outputs live under the range's corpus directory. Nothing in the live `docs/` is written by a tool.

## On-disk layout

```text
<out_root>/ch{since:03d}-{until:03d}/        # spec 031 corpus dir (manifest.json, chronology.md, dossiers/ …: read-only here)
└── state/                                    # NEW, everything this feature writes
    ├── notes/
    │   ├── manifest.json                     # extraction manifest: range, chunks, cache keys, corpus sha, model, backend
    │   ├── chunk{NN}.{aaa-bbb}.user.md        # the exact prompt sent (Principle VIII)
    │   ├── chunk{NN}.{aaa-bbb}.out.md         # raw model output
    │   ├── chunk{NN}.{aaa-bbb}.checked.json   # kept notes by kind + drops, after the code check
    │   └── drops.md                          # every dropped note: chunk, kind, reason, text; outlier chunks flagged
    ├── runs/{stamp}/                         # one per extract | synth | audit run
    │   ├── record.json                       # inputs (paths + sha256), backend, model, endpoints, timings, per-chunk/per-call results
    │   └── <step>.{system,user,out}.md        # prose and audit prompts and outputs
    ├── audit/
    │   ├── items.json                        # numbered tracking items, candidate chapters per item, cache keys
    │   ├── audit.json                        # verdict per item (see Audit verdict)
    │   └── audit.md                          # human-readable verdicts
    ├── drafts/
    │   ├── world_state.draft.md              # reading contract + sections (+ annotations)
    │   ├── campaign_state.draft.md
    │   ├── canon_events_timeline.md          # code-built, every event in chapter order
    │   ├── reference/{factions,npcs,locations,items,threads,threats}.md
    │   ├── annotations.md                    # every annotation and removal
    │   └── npc_status_report.md              # merged forms, unresolved names, dropped PC rows
    └── (drafts/*.incomplete.md when a section is missing — never promoted)
```

Promotion (manual, as in spec 031) copies these into the live `docs/`:
- `world_state.draft.md` becomes `docs/world_state.md`, and `campaign_state.draft.md` becomes `docs/campaign_state.md`.
- `canon_events_timeline.md` goes to `docs/canon_events_timeline.md`.
- `reference/` goes to `docs/reference/`.

The reading contract's paths assume that layout.

## Entities

### Chapter group (chunk)
| Field | Rule |
|---|---|
| `index` | 1-based, in chapter order |
| `chapters` | consecutive whole chapters; never split |
| `chars` | total characters; ≤ `chunk_chars` unless a single chapter exceeds it |
| `cache_key` | sha256 of the chapter texts, the extraction prompt and outline, backend, model, `max_tokens` and `chunk_chars` |
| `status` | `pending` → `extracted` → `checked`, or `failed` (error recorded, retried on the next run) |
| `endpoint` | which endpoint served it (dgx) |

### Note
| Field | Rule |
|---|---|
| `kind` | `event`, `concluded`, `thread`, `status_row`, `world`, `party` |
| `tag` | thread: `OPENED|ADVANCED|RESOLVED|ABANDONED`; world: `FACTION|NPC|LOCATION|ITEM|THREAT` |
| `subject` | bold `**Name**` for threads/world, first column for status rows; resolved to a registry canonical where an exact name or alias matches |
| `text` | the bullet, verbatim as the model wrote it |
| `citations` | ≥ 1 `[ch NNN / target]` part; each resolves within the chunk's chapters |
| `first_chapter` | the chapter of the first citation; sorts notes |
| `chunk` | owning chapter group |

A **status row** additionally carries `status` (Alive, Dead, Missing, Imprisoned, Departed or Unknown), `location` and `disposition`.

### Drop record
`{chunk, kind, reason, text}`. Reason is one of:
- `uncited`
- `invalid-citation <bracket>`
- `outside-chunk <bracket>`
- `quoted-span-not-found <span>`
- `missing-thread-tag`, `missing-world-tag`
- `malformed-row`
- `nested-bullet`

The `drops.md` totals are per chunk and per reason. A chunk is an **outlier** if its drops are more than 3× the run's median per chunk and at least 20.

### Code-owned section
Built only by `state_sections.py`. Byte-identical for identical kept notes, registry and roster (FR-010).
- **Timeline**: every kept `event`, sorted by `first_chapter` (stable within a chunk), duplicates removed.
- **Completed**: every kept `concluded`, same ordering.
- **NPC status table**: one row per resolved entity (or per unresolved literal name, marked ⚠).
  - **Kept row:** the latest row with a known status.
  - **Later report:** a later `Unknown` row is appended as "later, status not stated: … [cite]".
  - **Player characters:** rows for `players.yaml` characters are dropped.
  - **Column:** "Established" holds the row's citation.
- **Audit**: rendered from `audit.json`, or the single line "Audit not run for this range." when it is absent.

### Prose section
| Field | Rule |
|---|---|
| `doc` / `heading` | fixed outline per document |
| `routed_notes` | chosen by code (research R8) |
| `budget_words` | world_state only; defaults in `schema.py`; an overrun is reported, never truncated |
| `backend` / `model` / `effort` | prose step settings |
| `output` | must contain exactly its own heading; missing → `*.incomplete.md` |

### Reference file
One per World tag plus threads. Each holds every kept note of that kind, verbatim, under one `## Subject` per subject, sorted case-insensitively, and in chapter order within a subject.

### Key NPC line
- **Source:** a published dossier `docs/npcs/<slug>.md` whose provenance header says `source: summary_native`, the build's range, and `verify: pass`. Only `## Identity` and `## Last Observed State` are read (`published_view()`).
- **Line:** `- **<Name>** — … [citations] → docs/npcs/<slug>.md`.
- **Checks:** one line per selected NPC; citations only from that dossier (`entry` ≡ `npcs`); quotes verbatim. A failing line falls back to the dossier's first cited Last-Observed-State sentence.
- **Without a publishable dossier:** the build refuses by default. With `--fallback-npc-lines`, the line is built by code from the status row and the checked notes and ends `(no published dossier — from checked notes)`.

### Annotation
`{doc, line_no, kind, marker, evidence_text, evidence_citation}`.

| Kind | Marker |
|---|---|
| stale | `⚠ later:` |
| cross-section | `⚠ later: see <Section>:` |
| mentioned-status-change | `ℹ since:` |
| non-verbatim quote / invalid citation | `⚠ unverified:` |
| pc-in-npc-section | (line removed) |

Annotations are written as sub-bullets directly under their line. The original line's text is never changed.

### Audit item and verdict
- **Item:** `{id: A<n>, file, text, candidate_chapters: [..≤3], cache_key}`.
- **Verdict:** one of
  - `SUPPORTED` + `{citation, span}`. The span is verbatim in the cited candidate chapter.
  - `NOT FOUND` + `{reason: no-candidates | not-shown | unverified, partial?: [cited notes]}`.

### Run record
- **Inputs:** range, the summaries' sha256, the corpus manifest sha256, registry sha256, players sha256, dossiers used (path + sha256), and the track files' sha256.
- **Settings:** backend, model, effort, endpoints and parallel (requests per endpoint).
- **Results:** per chunk or per call: seconds, characters, kept and dropped counts, the endpoint; budget overruns; outputs.
- **Times:** started and finished.

## State transitions

```text
corpus built (031) ──extract──▶ notes checked ──synth world_state|campaign_state──▶ drafts (+annotations) ──GM review──▶ promoted (manual)
                         │                                   ▲
                         └──audit──▶ audit verdicts ─────────┘ (campaign_state Audit section)
published dossiers (032) ───────────────────────────────────┘ (world_state Key NPCs; missing → refuse unless --fallback-npc-lines)
```

**Staleness.** When the summaries, registry or `players.yaml` change after `extract`, or the track files change after `audit`, the next dependent step refuses with the command to re-run. The check uses the sha256 values in `notes/manifest.json` and `audit/items.json`, following spec 031's freshness rule. Only chunks whose chapters changed are re-extracted. **Published dossiers are not a staleness input:** `synth world_state` reads them live at build time, so a newly published dossier is picked up by the next build; the run record keeps their sha256 so two builds can be compared.
