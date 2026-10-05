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
`start: int | None`, `end: int | None`, `present: list[int]`, `gaps: list[int]`.
- Both bounds unset means every file in the directory (CLI only; the UI always sets both).
- Refused if a bound matches no file, `start > end`, or the range holds no file (FR-005d).

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
| `heading` | the H3 as written (kept after canonicalization) |
| `canonical` | the subject after registry + `canon.yaml` |
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
canonicalized_by: [registry, canon.yaml]      # which passes contributed, if any
---
```
The body holds one block per observation in `(chapter, line)` order, each with
`source_file`, `chapter`, `scene` (`070.02` or `none`), `heading`, and the exact
body text.

A slug collision appends the first 8 hex characters of
`sha256(category\0subject)`, as the prototype did.

### Chronology — `chronology.md`
One H2 per chapter (`## Chapter 070`), one H3 per scene
(`### 070.03 — <title>`), each with its synopsis and a provenance line. Where a
`Session-End State` section exists, it is copied verbatim under its chapter.

### MemorableMoments — `memorable_moments.md`
The exact body of each `## Memorable Moments` H2, under `## Chapter NNN` with a
provenance line. A chapter without the section is listed in the manifest and is
not an error.

### CorpusManifest — `manifest.json`
`kind: "summary_native"`, `schema: 1`, `range`, `files: [{path, chapter, sha256}]`,
`counts` (scenes, observations per category, dossiers),
`absent_optional_sections`, `unknown_sections`, `canon` (the sha256 of the registry
and `canon.yaml` used, plus the counts applied). It contains no timestamps.

## Canonicalization

### CanonMapping — `canon.yaml` (hand-authored; the tool never writes it)
```yaml
accepted:
  - {category: npc, from: "Manshoon (Simulacrum)", to: "Manshoon"}
rejected:
  - {category: item, a: "Staff of Power", b: "Staff of Frost"}
```
Validation: unknown keys are refused. A `from` that is also a `to` elsewhere is
refused (no chains). A cross-category entry needs `category: "*"` plus `to_category`.

### CanonProposals — `canon_proposals.yaml` (generated; overwritten on each run)
`[{category, a, b, ratio, reason: similarity|qualifier}]`, sorted. Pairs that are
already accepted, rejected, merged by the registry, or listed in the registry's
`distinct`/`rejected_aliases` are excluded.

State per heading pair: `unseen → proposed → accepted | rejected`. Only `accepted`
changes grouping. `rejected` is permanent until the GM edits `canon.yaml`.

## Synthesis

### Selection — `runs/<doc>/selection.json`
`range_end`, `recent_chapters`, `recurring_min`, and
`selected: [{dossier, reason: recent|recurring|named, last_chapter, n_observations}]`.

### SynthesisRecord — `runs/<doc>/`
- `part-<k>.system.md` and `part-<k>.user.md`: the exact prompts (FR-024).
- `part-<k>.out.md`: the raw response.
- `record.json`: `doc`, `backend`, `model`, `max_tokens`, `parts`, `range`, the
  input file digests (corpus manifest sha, upstream drafts, audit files, party and
  planning configs), the outline, the completeness-check result, and the started and
  finished times.

### DraftDocument — `drafts/<doc>.draft.md` | `drafts/<doc>.incomplete.md`
`<doc>` is one of `world_state`, `campaign_state`, `party`, `planning`.
`.draft.md` is written only if the outline check passes. It opens with a
provenance comment giving the range, the record path and the corpus manifest sha.
It never overwrites a live `docs/*.md` (FR-025). An existing draft needs `--force`
(FR-027).

## Output layout

```text
<out_root>/                         # default docs/summary_native/
├── canon.yaml                      # human-authored, range-independent
└── ch002-070/                      # one directory per range: ch<start>-<end>, 3-digit
    ├── manifest.json
    ├── canon_proposals.yaml        # generated for this range's headings
    ├── validation_report.{json,md}
    ├── chronology.md
    ├── memorable_moments.md
    ├── dossiers/*.md
    ├── runs/<doc>/…
    └── drafts/<doc>.draft.md (+ .vs-live.diff)
```
Different ranges never share a directory (FR-005e).
