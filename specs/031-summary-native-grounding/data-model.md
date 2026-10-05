# Data Model: Summary-Native Grounding Docs

All entities are in-memory dataclasses in `pipelines/summary_native/`, plus the
files they serialise to. Paths stored in any artifact are **relative to the
campaign root** (research R5).

## Input (read-only)

### SummaryFile
| Field | Type | Source |
|---|---|---|
| `path` | Path (campaign-relative) | glob/dir listing |
| `chapter` | int | filename prefix `^(\d+)[-_.]` |
| `title_chapter` | int \| None | `# Chapter N` |
| `date` | str \| None | `Date:` line (informational only) |
| `sections` | ordered map H2 → `Section` | parse |
| `in_range` | bool | the run's `ChapterRange` |

Invariant (blocking if violated, FR-002): `title_chapter == chapter`, and every
scene id's chapter part `== chapter`.

### Section
`name` (the H2 text, verbatim), `body` (exact text between this H2 and the next),
`entries: list[Entry]` (its `###` children in order).

### Entry
`heading` (the H3 text, verbatim), `body` (exact), `line` (1-based, for findings).

### Scene (Entry under `## Scenes`)
| Field | Rule |
|---|---|
| `source_scene_id` | the leading `NNN.SS` of the heading, verbatim; required (`bad-scene-id`) |
| `title` | the heading after the id |
| `synopsis` | the `####` lines joined with " / ". If there are none, the first narrative paragraph. Chosen verbatim from the scene, never generated |
| `body` | exact |

## Validation

### ChapterRange
`since: int | None`, `until: int | None`, `present: list[int]`, `gaps: list[int]`. The names match the `--since`/`--until` flags and `range_since`/`range_until` config.
- Both bounds unset means every file in the directory (CLI only; the UI always sets both).
- Refused if a bound matches no file, `since > until`, or the range holds no file (FR-005d).

### Finding
`file`, `line | None`, `code` (see research R2 table), `message`, `expected | None`,
`found | None`, `blocking: bool`, `in_range: bool`.

### ValidationReport
`range: ChapterRange`, `files_scanned: int`, `findings: list[Finding]`, with derived
values `blocking_count` and `files_failing`. Serialised as:
- `validation_report.json`: machine-readable, read by the UI.
- `validation_report.md`: grouped by file, in-range first, then an
  "Outside range — not blocking" section, then the summary counts.

## Corpus (deterministic, byte-stable)

### Observation
| Field | Notes |
|---|---|
| `category` | `npc` \| `location` \| `item` \| `spell` \| `ability` |
| `heading` | the H3 as written (kept even when grouped under a registry canonical) |
| `canonical` | the heading, or the registry canonical for an exact same-type alias |
| `chapter` | from the filename |
| `source_file` | campaign-relative |
| `source_scene_id` | `NNN.SS`, or `null` = explicitly no scene |
| `line` | 1-based |
| `body` | exact |

### Dossier — `dossiers/<category>_<slug>.md`
Frontmatter must satisfy `synthesise_world_state.read_dossiers` (FR-012):

```yaml
---
subject: Manshoon
type: npc
n_facts: 7            # = number of observations (name kept for read_dossiers)
chapters: 41-70       # lo-hi over observations
source_kind: summary_native
headings: [Manshoon, Manshoon (Simulacrum)]   # every distinct heading merged in
grouped_by: [registry]                        # present only if a registry alias contributed
---
```
The body holds one block per observation in `(chapter, line)` order, each with
`source_file`, `chapter`, `scene` (`070.02` or `none`), `heading`, and the exact
body text.

A slug collision appends the first 8 hex characters of
`sha256(category\0subject)`, as the prototype did.

### Chronology — `chronology.md`
One H2 per chapter (`## Chapter 070 — <date>`, or `date not stated`), one H3 per scene
(`### 070.03 — <title>`), each with its synopsis and a provenance line. Where a
`Session-End State` section exists, it is copied verbatim under its chapter.

### MemorableMoments — `memorable_moments.md`
The exact body of each `## Memorable Moments` H2, under `## Chapter NNN` with a
provenance line. A chapter without the section is listed in the manifest and is
not an error.

### CorpusManifest — `manifest.json`
`kind: "summary_native"`, `schema: 1`, `range`, `files: [{path, chapter, sha256}]`,
`counts` (scenes, observations per category, dossiers),
`absent_optional_sections`, `unknown_sections`, `canon` (`{registry_sha256, canon_sha256}`: the sha256 of the registry
and `canon.yaml` read). It contains no timestamps.

## Duplicate detection (fix at source)

Headings are combined into one dossier only by **identical text within a category**
or by an **exact registry alias** whose entity type matches the category (npc,
location, item). Nothing else merges, and spells are never registry-grouped.

### PossibleDuplicate (a non-blocking finding, code `possible-duplicate`)
`category`, `a`, `b`, `reason: similarity|qualifier`, `ratio`, and
`locations: {a: [file:line…], b: [file:line…]}`. It is listed in
`validation_report.{md,json}` under "Possible duplicates — fix in the summaries".
Pairs are excluded if they are recorded in `canon.yaml`, or listed in the registry's
`distinct`/`rejected_aliases`.

### DuplicateRulings — `canon.yaml` (hand-authored; the tool never writes it)
```yaml
not_duplicates:
  - {category: item, a: "Staff of Power", b: "Staff of Frost"}
```
Validation: the only top-level key is `not_duplicates`. Unknown keys are refused
(so `accepted:`/`aliases:`-style merges cannot be written). A ruling whose headings
no longer occur in the range is reported as stale.

Lifecycle of a pair: `flagged → (GM edits summary) gone` or
`flagged → (GM records not_duplicates) suppressed`.

## Synthesis

### Selection — `runs/<doc>/<run_id>/selection.json`
`range_end`, `recent_chapters`, `recurring_min`, and
`selected: [{dossier, reason: recent|recurring|named, last_chapter, n_observations}]`.

### SynthesisRecord — `runs/<doc>/<run_id>/`
Every synth invocation, `--dump-only` included, writes a NEW directory;
`run_id` is the UTC start time `YYYYMMDDTHHMMSSZ`, with `-<k>` appended if that
directory already exists. A run never overwrites or deletes another run's directory,
so a draft's `record:` pointer stays valid. A single-part run after a `--parts 3`
run leaves two directories, the new one holding only `part-1.*`.
- `part-<k>.system.md` and `part-<k>.user.md`: the exact prompts (FR-024).
- `part-<k>.out.md`: the raw response.
- `record.json`: `doc`, `backend` (the effective backend: `--backend`, else `CG_BACKEND`, else `anthropic`), `model`, `max_tokens`, `parts`, `range`, the
  input file digests (corpus manifest sha, upstream drafts, audit files, party and
  planning configs), the outline, the completeness-check result (per part when `--parts` > 1), and the started and
  finished times.

### DraftDocument — `drafts/<doc>.draft.md` | `drafts/<doc>.incomplete.md`
`<doc>` is one of `world_state`, `campaign_state`, `party`, `planning`.
`.draft.md` is written only if the outline check passes. It opens with a
provenance comment giving the range, the record path (`runs/<doc>/<run_id>/record.json`)
and the corpus manifest sha. An incomplete run writes `.incomplete.md` (its header
names its own run), replacing any earlier `.incomplete.md` and leaving an existing
`.draft.md` untouched. The outline check also rejects any H2 not in the outline, and
with `--parts` checks each part against only its assigned headings.
It never overwrites a live `docs/*.md` (FR-025). An existing draft needs `--force`
(FR-027).

## Output layout

```text
<out_root>/                         # default docs/summary_native/
├── canon.yaml                      # human-authored not-a-duplicate rulings, range-independent
└── ch002-070/                      # one directory per range: ch<since>-<until>, 3-digit
    ├── manifest.json
    ├── validation_report.{json,md}
    ├── chronology.md
    ├── memorable_moments.md
    ├── dossiers/*.md
    ├── runs/<doc>/<run_id>/…
    └── drafts/<doc>.draft.md (+ .vs-live.diff)
```
Different ranges never share a directory (FR-005e).
