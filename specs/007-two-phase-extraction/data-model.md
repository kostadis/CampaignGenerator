# Data Model: Two-Phase Extraction Agent

**Feature**: `specs/007-two-phase-extraction` | **Date**: 2026-08-03

All entities are in-memory except the **Verification Report**, which is the
only durable artifact this feature creates. There is no database, no cache, and
no new state file — consistent with Principle I (disk is truth) and the
"every new database is a recurring tax" clause.

---

## Entities

### `SourceTranscript`

The record of what was actually said. Read-only, never modified.

| Field | Type | Notes |
|---|---|---|
| `path` | `Path` | The exact `.vtt` used; recorded in the report (D9) |
| `raw` | `str` | File contents as read |
| `lines` | `list[str]` | `parse_vtt(raw).splitlines()` — speaker-prefixed |
| `spoken` | `list[str]` | `lines` with a leading `^[^:]{1,40}:\s*` prefix stripped (D6) |
| `speakers` | `list[str]` | The stripped prefix per line, `""` when absent — lets the report name who said the nearest line |
| `haystack` | `str` | `" ".join(spoken)`, whitespace-normalised, lowercased — the match target |

**Validation**: construction fails if the path is missing or unreadable
(FR-011). An empty `lines` list is a hard error, not an empty corpus — a VTT
that parses to nothing means the wrong file was passed.

---

### `Quote`

A span of text in a checked artifact presented as something a person said.

| Field | Type | Notes |
|---|---|---|
| `text` | `str` | Quote content **exactly as it appears**. Never mutated (FR-006) |
| `match_text` | `str` | Derived: bracketed spans stripped, whitespace-normalised, lowercased (D3). Matching input only |
| `artifact` | `Path` | File it came from |
| `line_no` | `int` | 1-indexed line in that file |
| `section` | `str \| None` | Nearest enclosing heading — `"Memorable Moments"`, `"Verbatim moments"` … Gives the report a location (FR-004) |
| `speaker_hint` | `str \| None` | From the enclosing `**[Speaker]**` block (Stage 2) or the `> — Name` attribution line (Stage 1). Informational only — attribution is out of scope |

**Invariant**: `text` is the identity of the quote. `match_text` exists solely so
matching can be tolerant without ever writing the tolerance back.

---

### `Finding`

The result of classifying one `Quote`. Every quote produces exactly one.

| Field | Type | Notes |
|---|---|---|
| `quote` | `Quote` | |
| `verdict` | `Verdict` | See state values below |
| `score` | `float \| None` | Best coverage score, `None` for `verified`/`exempt`/`unscored` |
| `nearest_line` | `str \| None` | The VTT line that scored best — the thing that makes a finding actionable at a glance |
| `nearest_speaker` | `str \| None` | Who said `nearest_line` |
| `offset` | `int \| None` | Position in the transcript, from `locate_quote`. Present for `verified` |

#### `Verdict` — the five values (D1, D3, D7)

| Value | Meaning | Counted as a problem? |
|---|---|---|
| `verified` | Exact or whitespace-normalised substring of the transcript | No |
| `near` | Not verbatim, but best score ≥ threshold. Overwhelmingly disfluency edits | No — informational |
| `unverified` | Best score < threshold. **The fabrication signal** | **Yes** |
| `unscored` | Fewer than 4 tokens; no reliable signal either way (D7) | No — reported, never accused |
| `exempt` | Wholly an editorial marker: `(paraphrase)`, `(truncated)`, `[inaudible]` (D3, FR-005) | No |

**Transitions**: none. A `Finding` is computed once per run and never mutated;
re-running recomputes from the artifact and the transcript. This is what makes
the operation idempotent (FR-007) — there is no accumulated state to drift.

---

### `VerificationReport`

The durable artifact (FR-009). Markdown, written next to
`consistency_report.md`.

| Field | Type | Notes |
|---|---|---|
| `artifacts` | `list[Path]` | What was checked |
| `transcript` | `Path` | Which VTT — differs between raw and `.cleaned` (D9) |
| `threshold` | `float` | The value that produced this result (D8) — stated so a re-tuned run is comparable |
| `counts` | `dict[Verdict, int]` | Totals per verdict |
| `findings` | `list[Finding]` | Sorted: `unverified` first (ascending score), then `near`, then `unscored` |
| `not_checked` | `list[str]` | Explicit limitations, e.g. *"inline `\"…\"` spans in prose were not checked"* (D5) |
| `generated_at` | `str` | ISO timestamp |

**Validation**:
- `counts` must sum to the total number of quotes parsed. A report that
  silently drops a quote is worse than one that flags it.
- `not_checked` is **never empty** — D5 guarantees at least the inline-quote
  limitation. Principle VIII: state what you did not do.
- Distinguishes "no quotes found" from "all verified" (FR-010).

---

### `VerifyKnobs` (config)

New group in `<config>/session_doc.yaml`, `extra="forbid"` like its siblings.

| Field | Type | Default | Notes |
|---|---|---|---|
| `threshold` | `float` | `0.85` | `near`/`unverified` boundary. **Uncalibrated for DeepSeek** — see D8 |
| `min_tokens` | `int` | `4` | Below this, `unscored` (D7) |
| `report_only` | `bool` | `false` | Suppress in-place annotation (FR-008) |

No `enabled` flag: a check you can turn off in config is a check that is off
when it matters. The GM chooses per-run by not invoking it.

---

## Artifact annotation (FR-006, FR-007)

The only permitted write to a checked artifact is an additive marker appended
to an `unverified` quote's line:

```
> "Some quote the transcript does not contain."   <!-- cg:unverified -->
```

**Rules**:
- HTML comment — invisible in rendered markdown, greppable, and unambiguous to
  strip.
- Applied only to `unverified`. Never to `near` (that would re-import the
  false-positive problem the three-bucket design exists to solve).
- **Idempotent**: a line already carrying the marker is left byte-identical.
  Re-running produces no diff (FR-007, SC-006).
- Quote text between the delimiters is never touched (FR-006, SC-007).
- Written via `campaignlib.util.atomic_write_text`, as `narrate_chapter` and
  `scrub_mechanics` do.

**Removal**: markers are stripped by re-running after the GM fixes the quote —
the verdict changes and the marker is not re-applied. A stale marker is
therefore impossible to leave behind by accident.
