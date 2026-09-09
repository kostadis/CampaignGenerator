# Phase 0 — Research: the block document model and the mobile reviewer

Nine decisions. Measurements are from the four confirmation scenes on disk, not estimated.

---

## D1 — A prose block is a **run** between gaps, not a paragraph

**Decision.** Splitting a narration yields alternating blocks: a gap is one marker; a prose block
is every paragraph between two gaps, joined.

**Measured on the corpus:**

| Scene | Blocks | Gaps | Source GM turns |
|---|---|---|---|
| brewbarry | 13 | 6 | 41 |
| soma | 25 | 12 | 47 |
| valphine | 9 | 4 | 12 |
| vukradin | 18 | 9 | 40 |

**Rationale.** It is the granularity the reviewed page already used — its `.prose` divs each held
several `<p>` — so the UX the GM validated is reproduced rather than reinterpreted. It also keeps
the count in the low tens, which is what makes a phone workable: paragraph-level blocks would put
40–60 edit targets on a touch screen.

**The cost, and why it is acceptable.** Editing one sentence means opening a textarea holding
eight paragraphs. That is coarse. But block **ids are an interface** — they appear in the export,
in the record, and in any future merge — so changing granularity later invalidates every record
written before the change. Coarse-and-stable beats fine-and-migrated, and the gap textareas
already work this way.

**Alternatives considered.** Per-paragraph blocks (finer edits, 3–5× the ids, worse on mobile);
sentence-level (unbounded ids, and sentence splitting is its own guessing game).

---

## D2 — Staleness is caught by a digest in v1; anchors are stored but not matched

**Decision.** The record carries `generated_sha256` of the draft it was authored against.
Composing against a different draft **refuses**. Per-block `anchor` values are written but
nothing matches on them yet.

**Rationale.** This is the issue's own v1 cut and it is the right one. Anchor matching exists to
survive a re-narrate, and an anchor that lands an authored block on the wrong prose is *the same
attribution error this entire feature exists to prevent* — committed by us instead of by a model.
A digest cannot make that mistake: it either matches or it does not.

Anchors are still written, because a record authored today must be usable by the matcher `#456`
brings. Storing them costs nothing; retrofitting them onto old records costs a migration.

**Alternatives considered.** Anchor matching in v1 — rejected as the highest-risk work in the
feature, for no v1 benefit. No anchors at all — cheaper now, a migration later.

---

## D3 — The assembly gate reads the **documents**, not the records

**Decision.** `--require-composed` refuses when an assembled scene file still contains a gap
marker. It does not consult `.authored.yaml` at all.

**Rationale.** More robust, and simpler. A composed document containing a marker is unfit for a
chapter *whatever any record says about it* — including when the record is missing, stale, or
describes a different draft. Reading records would make the gate's verdict depend on a second
file agreeing with the first.

It also means the gate works on a scene composed by hand, or by `#456`, or by anything else that
produces a document.

**Consequence.** The gate needs the marker string, which makes it a second consumer of the
contract's vocabulary — see D8.

---

## D4 — `.composed.md` beside `.scrubbed.md` reuses the existing collision machinery

**Decision.** `collect_scene_files` raises the existing `SceneCollision` when one stem has both a
`.scrubbed.md` and a `.composed.md`, naming both files and `--use`. No new exception, no new flag.

**Rationale.** Q2's ruling is "refuse and make the GM name one", and `assemble` already implements
exactly that shape for a different collision — two files claiming one `scene:` (`#429`). Reusing
`SceneCollision` and `--use` means one refusal vocabulary and one flag rather than two dialects
(Principle XII).

**The distinction to keep clear.** These are *two different collisions* and conflating them would
produce a confusing message: `#429`'s is **two scenes with one number**, this is **one scene with
two final variants**. Same exception type, same flag, different sentence.

**Alternatives considered.** Precedence (`composed` > `scrubbed`) — silently drops a scrub done
before composing, which is the quiet failure `#429` exists because of. Composing *from* the
scrubbed draft — removes the ambiguity but forces an ordering on the GM's workflow and
invalidates any review done before the scrub.

---

## D5 — The record is a strict, versioned Pydantic model, mirroring `transcript_corrections`

**Decision.** `.authored.yaml` is `extra="forbid"`, carries `version: int = 1` with a validator
that refuses unknown versions, and stores **only human contributions**.

**Rationale.** `campaignlib/transcript_corrections.py` is the same artifact one layer down — a
hand-authored record from which a generated file is produced — and it exists because 74
unrecorded substitutions reached a transcript. Its shape is already proven here:

- `version` with `_known_version` refusing anything else
- per-entry `id`, non-empty, so a human can refer to one
- `verified: bool` meaning *a question, not a fact*
- a model validator refusing two entries that address the same target, because which wins would
  depend on file order

All four transfer. The last one becomes: two entries for one block id is a refusal.

**What does not transfer.** `was`/`now` — a correction is a substitution and a ruling is not.
The digest does that job at document level instead (D2).

---

## D6 — Four dispositions, and `unruled` is absent rather than stored

**Decision.** `disposition` is one of `mine` / `authored` / `cut`. **`unruled` is the absence of
an entry** — a block nobody has touched has no record at all.

**Rationale.** FR-004 says the record stores only what the human contributed, and "I have not
looked at this" is not a contribution. It also keeps a part-way record small and makes "how much
is ruled" a count of entries rather than a scan for a sentinel.

The spec names four dispositions; three are stored and the fourth is the default for anything
absent. `mine` and `authored` differ by whether `text` is present — but they are **stored
distinctly rather than inferred**, because "I ruled this mine and have not written it" and "I
ruled this mine and wrote an empty string" are different states and inferring would merge them.

**Critique is orthogonal and never reaches compose.** `wrong-scope` / `model-should-have-written`
sit beside the disposition, are optional, and are read only by whatever harvests feedback on the
contract.

---

## D7 — The reviewer is one hand-authored file, and a test ties it to the exporter

**Decision.** `session_doc/review/reviewer.html` — a single self-contained file, versioned in the
repo, no build step. Two build-breaking tests:

1. **Self-containment**: no `src=`/`href=` to any external origin, no `fetch`, no `import` from a
   URL. This is what makes "works offline on a phone" a property rather than a hope.
2. **Version agreement**: the schema version the page declares equals the exporter's version
   constant. Page and data now drift independently — that is the cost of never regenerating the
   page — so the one thing that must not drift is checked.

**Rationale.** The repo already generates standalone review HTML (`build_comparison.py`,
`build_reader.py` in `experiments/`), but those *regenerate per run*, which is exactly what this
feature removes. Inverting it makes the JSON an interface, and an interface needs a version check
on both sides.

**What is not tested.** The page's behaviour in a browser. No headless browser is in this repo's
dependencies and adding one to test a review page is a poor trade; the page is small, its logic
is a render and a copy, and its failure mode is visible on first use.

**Alternatives considered.** A build step assembling the page from parts — reintroduces
generation. Serving it from the FastAPI server — needs the GM's machine reachable from work,
which is the constraint the whole design exists to avoid.

---

## D8 — Two consumers of the marker, one producer, one guard

**Decision.** The marker string lives in one constant. The parser (D1) and the assembly gate (D3)
both import it, and a test asserts it appears in
`config/agents/session_doc/narrate/gm_attribution_gap.md`.

**Rationale.** `#454` established this pairing for the prompt side; this is the other half.
`26ec5b0` deleted a prompt while leaving its stripper, tests and three out-of-repo skills
standing, and nothing failed — because nothing tied a marker to a producer. Here the exposure is
worse: two consumers would keep passing their own tests while the contract that feeds them was
edited away, and the visible symptom would be scenes that suddenly have no gaps.

---

## D9 — Export size confirms one scene per file

**Measured**, with blocks, anchors, gap text and the full source GM turns:

| Scene | Export |
|---|---|
| brewbarry | 13.9 KB |
| soma | 22.4 KB |
| valphine | 19.9 KB |
| vukradin | 25.6 KB |
| **all four in one paste** | **81.7 KB** |

**Decision.** Export is one scene per file by default. A whole session is available behind a flag
and is not what the GM pastes on a phone.

**Rationale.** 14–26 KB is a large but survivable clipboard paste; 82 KB is not something to hand
a touch keyboard, and a paste that silently truncates would render half a scene as if it were
whole — which is why FR's edge cases require a truncated export to be detected rather than
rendered.

---

## Open risk, carried into tasks

**Persistence on `file://`.** FR-016 allows either retaining work across a reload or saying
plainly that it will not. `localStorage` is available under `file://` on mobile browsers but its
origin rules are inconsistent — some treat every `file://` document as one origin, some as none.
The reviewed page already carried a warning for exactly this reason. The safe reading: implement
storage, verify it on the GM's actual device, and keep the warning honest until it has been. A
GM who loses twenty rulings to a tab reload will not use this twice.
