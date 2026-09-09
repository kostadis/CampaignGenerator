# Contract — the block model, the record, and the gate

Everything here is deterministic. No model is called anywhere in this layer, and that is checked
rather than asserted.

## Parsing — P

| # | Guarantee |
|---|---|
| **P1** | Reading a narration's blocks in order and rejoining them reproduces the narration exactly. |
| **P2** | A gap block is a paragraph consisting solely of the marker; everything else is prose. |
| **P3** | Block ids are stable for a given narration: parsing the same file twice yields the same ids. |
| **P4** | A narration with no markers yields one prose block and parses without error. |

P1 is the load-bearing one — it is what makes composing safe. A parser that loses a blank line
produces a `.composed.md` that differs from the narration everywhere, not just at the gaps.

## The record — R

| # | Guarantee |
|---|---|
| **R1** | `extra="forbid"`. An unrecognised key is a refusal, naming it. |
| **R2** | An unknown `version` is refused, naming the version this build understands. |
| **R3** | Two entries for one block id are refused — which wins would depend on file order. |
| **R4** | The record stores only what the human contributed. A block nobody touched has no entry. |
| **R5** | `mine` and `authored` are distinct stored values, never inferred from whether `text` is present. |
| **R6** | A `critique` never changes the composed document. |

## Composing — C

| # | Guarantee |
|---|---|
| **C1** | Deterministic: the same narration and record produce byte-identical output. |
| **C2** | `authored` and `edited` place the human's text; `cut` removes the block; `mine` and absent leave the gap standing. |
| **C3** | A record whose `generated_sha256` does not match the narration **refuses**, naming both. |
| **C4** | The output carries a generated-file marker. |
| **C5** | Composing a narration with an empty record reproduces the narration. |

C3 is the whole of v1's staleness handling. Anchors are stored and matched by nothing
([research](../research.md) D2), so there is no partial-match path and no way to land an authored
block on prose it was not written for.

## The gate — G

| # | Guarantee |
|---|---|
| **G1** | With the gate on, a scene file still containing a gap marker refuses assembly. |
| **G2** | The refusal names **every** scene responsible, not the first. |
| **G3** | The gate reads the assembled documents, never the records. |
| **G4** | With the gate off, today's behaviour is unchanged. |

G3 means the gate holds for a scene composed by hand, by `#456`, or by anything else.

## Variant collision — V

| # | Guarantee |
|---|---|
| **V1** | One stem with both a `.scrubbed.md` and a `.composed.md` **refuses**, naming both files. |
| **V2** | The refusal names `--use`, and `--use` resolves it. |
| **V3** | The message distinguishes this from `#429`'s collision — one scene with two final variants, not two scenes with one number. |

## Re-narrate — N

| # | Guarantee |
|---|---|
| **N1** | Narrating over a scene whose record has authored content refuses, naming the record. |
| **N2** | `--reroll` lifts the refusal and states what becomes of the record **before** doing it. |
| **N3** | A record with no authored content does not block a re-run. |

`--reroll` is a refusal-lift in v1, not a merge. Merge review is `#456`'s, with its UX.

## The reviewer — W

| # | Guarantee |
|---|---|
| **W1** | One file. No network request of any kind: no external `src`/`href`, no `fetch`, no remote import. |
| **W2** | The schema version the page understands equals the exporter's constant — checked in CI. |
| **W3** | An export whose version the page does not understand is reported, not rendered. |
| **W4** | An export that is truncated or malformed is reported, never rendered as a partial scene. |
| **W5** | Two progress figures — ruled and written — neither masking the other. |
| **W6** | Every block is editable: gaps and the model's prose alike. |
| **W7** | Copy produces text a model with no other context can draft from. |

W1 and W2 are the two that get build-breaking tests. The rest are verified by using the page,
which is honest: no headless browser is in this repo, and adding one to test a review page is a
poor trade.

## What must not exist

| # | Guarantee |
|---|---|
| **X1** | No module in this layer imports an API client or calls one. Enforced by AST walk, in the style of `tests/test_provenance_no_llm.py`. |
| **X2** | The marker string has one definition, and a test ties it to the prompt fragment that emits it. |

X1 is not a style preference. A model asked to decide which gaps matter, or to resolve one, is
the failure on disk in `experiments/20260907-phandalin-gm-gaps-selffill`: given its own 11
markers it discarded nothing and handed both of the GM's Order-of-the-Gauntlet lines to a player
character, on the one passage the markers had protected.
