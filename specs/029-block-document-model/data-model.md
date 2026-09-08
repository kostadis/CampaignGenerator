# Phase 1 — Data model

Three files per scene, one export format, one record schema. No database, and the only new state
on disk is a file the human writes.

## The three files

```
session_doc_scene_NN_<slug>.md             generated — sd_narrate, with markers
session_doc_scene_NN_<slug>.authored.yaml  AUTHORED — the only file a human touches
session_doc_scene_NN_<slug>.composed.md    generated — the two merged
```

The rule is `transcript_corrections.yaml`'s, one layer up: **the record is the source of truth
and the composed document is output.** The narration is the archive and is never written by hand.

## Block

One span of a narration. Blocks alternate; reading them in order reproduces the narration.

| Field | Meaning |
|---|---|
| `id` | `{kind}-{ordinal}`, 1-based within kind — `gap-3`, `prose-7` |
| `kind` | `prose` or `gap` |
| `anchor` | first ~80 characters of the text this block was read from |
| `text` | the prose, or the gap's one-sentence statement |

A **prose block is a run** of paragraphs between two gaps (research D1) — 9 to 25 blocks per
scene on the corpus, 4 to 12 of them gaps.

`anchor` is written in v1 and matched by nothing (research D2). It exists so a record authored
today survives into `#456`'s matcher without a migration.

## Disposition

What the human decided about one block. **`unruled` is the absence of an entry**, not a stored
value (research D6).

| Disposition | Stored | Composes to |
|---|---|---|
| *(absent)* | — | the gap, unchanged |
| `mine` | yes | the gap, unchanged |
| `authored` | yes, with `text` | the human's prose |
| `cut` | yes | nothing |
| `edited` | yes, with `text` | the human's prose, replacing the model's |

`mine` and `authored` are stored distinctly rather than inferred from whether `text` is present:
"ruled mine, not yet written" and "ruled mine, wrote an empty string" are different states, and
inferring would merge them. `edited` applies to a `prose` block; the others to a `gap`.

**Two completions, not one.** *Ruled* counts entries; *written* counts `authored` + `edited` +
`cut`. A finished mobile session drives the first to 100% and leaves the second short — that is
success, not a partial result.

## Critique

Optional, orthogonal, and **never reaches the composed document**.

| Value | Means |
|---|---|
| `wrong-scope` | the gap's boundary was wrong |
| `model-should-have-written` | this was not GM narration; the model should have written it |

Feedback on the *contract*, not on the chapter. It is what a GM would have used to say the
marking was wrong — all 31 accepted gaps came back "right gap, mine to write", so this axis is
the one that carries a dissent when there is one.

## Authored record — `.authored.yaml`

Strict (`extra="forbid"`), versioned, refuses an unknown version — the
`TranscriptCorrectionRecord` shape (research D5).

| Field | Meaning |
|---|---|
| `version` | `1`. An unknown value is refused, not ignored |
| `narration` | the `.md` this was authored against |
| `generated_sha256` | digest of that file's bytes |
| `blocks[]` | one entry per block the human touched |

Per entry: `id`, `disposition`, optional `text`, optional `critique`, optional `note`, `anchor`,
`recorded`, `recorded_by`.

**Validation.** Two entries for one `id` is a refusal, not a last-one-wins — the same reason two
corrections on one cue are refused: which wins would depend on file order.

## Composed document — `.composed.md`

Generated. Carries the narration's frontmatter, the blocks in order with dispositions applied,
and a generated-file marker so it is visibly not a thing to hand-edit.

Composing against a narration whose digest does not match `generated_sha256` **refuses**
(research D2).

## Session export — the reviewer's input

The versioned JSON a reviewer renders. **This is an interface**, because the page is no longer
generated per session and the two now drift independently.

| Field | Meaning |
|---|---|
| `version` | integer, checked by both sides (research D7) |
| `narration` / `generated_sha256` | so a review can be tied back to its draft |
| `scene` | session, index, name, narrator, and the stat line |
| `blocks[]` | id, kind, anchor, text — the same ids as the record |
| `source_gm_turns[]` | line, label, note, quote — what the foot table renders |

**One scene per file by default**: 14–26 KB each on the corpus, against 82 KB for all four
(research D9).

## Reviewer output — the clipboard

Two payloads, neither of which is a file this feature writes:

- **the drafting prompt** — scene so far, outstanding gaps, their source GM turns. For any chat.
- **the review** — the record's content, for the GM to place by hand.

The round trip stops here. No paste-back command, no upload route.

## State transitions

A block moves only by a human acting in the reviewer or editing the record:

```
absent ──rule──> mine ──write──> authored
   │                                 │
   └──rule──> cut                    └──edit──> authored   (text replaced)

prose ──edit──> edited
```

Nothing moves a block automatically, and nothing moves one backwards except a human deleting the
entry. There is no transition a model can cause — that is FR-022, and it is guarded statically.
