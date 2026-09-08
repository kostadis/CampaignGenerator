# Implementation Plan: The block document model, and a reviewer that works on a phone

**Branch**: `feat/455-block-document-model` | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/029-block-document-model/spec.md`

Tracking: [#455](https://github.com/kostadis/CampaignGenerator/issues/455), a sub-issue of
[#418](https://github.com/kostadis/CampaignGenerator/issues/418).

## Summary

`sd_narrate --gap-marking` writes markers where the GM's description belongs, and **nothing
consumes them**. This is the layer that does: a block parser, a hand-authored record, a composed
document, a gate that stops a chapter assembling with markers in it — and a reviewer the GM can
use on a phone at work, because that is where the ruling actually happens.

The approach follows the tape one layer down. `transcript_corrections.yaml` is the same artifact:
a hand-authored record from which a generated file is produced, existing because 74 unrecorded
substitutions once reached a transcript. Its shape — strict, versioned, refusing an unknown
version, refusing two entries for one target — transfers directly.

The reviewer **inverts** the workflow that produced the 31 accepted rulings. That page was
published per session; this one is versioned once, saved to the device, and fed versioned JSON.
That makes the export an interface, which is why it carries a version checked on both sides.

No model call anywhere in this layer, guarded statically.

## Technical Context

**Language/Version**: Python 3.14. The reviewer is one hand-authored HTML file — no framework, no
build step, no TypeScript.

**Primary Dependencies**: none new. Pydantic and PyYAML (already used by
`campaignlib/transcript_corrections.py`), stdlib `hashlib`/`json`/`re`.

**Storage**: files. One new hand-authored file per scene (`.authored.yaml`), one new generated
file per scene (`.composed.md`), one versioned static asset. No database.

**Testing**: pytest. Round-trip and determinism properties, an AST guard for the no-model rule, a
self-containment check on the reviewer, and the four confirmation scenes as the real-data corpus.

**Target Platform**: Linux for the CLIs; **a mobile browser, offline, from local storage** for the
reviewer. That second one is a hard constraint, not a preference — the GM cannot rely on their own
machine being reachable from work.

**Performance Goals**: not a factor. Tens of blocks per scene, one pass, no network.

**Constraints**: deterministic; zero tokens; no network anywhere, including in the reviewer. A
single scene's export must stay pasteable on a touch keyboard — measured at 14–26 KB
([research](./research.md) D9).

**Scale/Scope**: 9–25 blocks per scene, 4–12 gaps, 12–47 source GM turns.

## Constitution Check

*GATE: passed before Phase 0. Re-checked after Phase 1 — see below.*

| Principle | Assessment |
|---|---|
| **I — Disk is Truth, the Model is a Draft** | PASS, and this feature is an application of it. The narration is a **draft**; the record is what a human decided about it; the composed document is generated from both. Nothing in this layer produces a claim a human did not make. |
| **II — The Human Checkpoint is Non-Negotiable** | PASS — this *is* the checkpoint. The gap markers exist because attribution is a precision decision; this is where a human makes it. The reviewer is the surface, and copy-out is explicitly not auto-resolution: a human copies one gap out, a human pastes one passage back. The evidence for why that boundary matters is on disk (`gm-gaps-selffill`), and X1 guards it. |
| **III — Retrieval and Render are Separated** | PASS. No retrieval and no render call anywhere in the layer. |
| **IV — Verbatim is Sacred** | PASS. Nothing here rewrites a quoted span. The record stores the human's own prose; composing places it and copies nothing else. The reviewer *displays* the source GM turns beside a gap so it can be ruled against the source — display, not adaptation. |
| **V — One Seam per Boundary** | PASS. No external dependency reached at all. The marker string gets one definition with two consumers, which is the seam discipline applied to a vocabulary rather than a service (research D8). |
| **VI — CLI is the Engine, UI is a Face** | PASS, with a deliberate shape worth naming. Parsing, composing, exporting and the gate are all CLI; the reviewer is a **face with no engine behind it** — it renders an export and produces text. It cannot act on the repo, which is why the round trip stops at the clipboard. |
| **VII — Extract Once, Synthesize Deliberately** | N/A. No extract or synthesize passes. |
| **VIII — State is Discoverable** | PASS, improved. Three files per scene with fixed names say, from disk alone, whether a scene has been reviewed and whether it is composable. |
| **IX — The UI Mechanizes; Claude Converses** | PASS, and the reviewer is the clearest example of it in the repo. It mechanizes *reading a scene in order and recording a decision per gap*. The judgement — is this the right gap, what should the passage say — stays entirely with the GM, and the drafting happens in a conversation the GM chooses. |
| **X — Selection is Explicit; No Silent "All"** | PASS. Export defaults to **one scene**, and a whole session requires asking. The one place a silent "all" could appear is the assembly gate, which names every scene rather than the first. |
| **XI — Parity is Bidirectional** | PASS with a **recorded ruling**. The reviewer is not reachable from the web UI and does not need to be — it exists precisely because the web UI's machine is unreachable from where the review happens. `#456` brings the desk-side editor. Every CLI capability here (parse, compose, export, gate) is a command; none is UI-only. |
| **XII — One Spelling per Option** | PASS. `--use` is reused for the variant collision rather than a second flag with the same meaning (research D4); `--scene`, `--force` and `--config` keep their existing meanings. The record's `version` field matches `transcript_corrections`' spelling. |
| **XIII — Breaking State Changes Migrate Out of Band** | PASS, no migration. Two **new** files per scene, both additive; no existing file changes shape, no key is retired or relocated, and a workspace that never adopts this behaves exactly as it does today. `assemble`'s new gate is opt-in, so existing runs are unaffected. |

**Gate result: pass, no violations.** Complexity Tracking omitted.

**Post-Phase-1 re-check**: unchanged, with two things stated rather than left implicit.

*First*, Principle XI's exemption is a real ruling and is recorded above rather than being an
omission: the reviewer is deliberately not in the web UI, because the constraint that created it
is that the web UI cannot be reached. That is the narrow exemption the principle allows —
recorded, with its reason, in the feature that takes it.

*Second*, the reviewer is the first thing in this repo that is a **face with no engine**. It
produces text for a human to carry, not a call to a command. That is why the round trip stops at
the clipboard (spec Assumptions): giving it a write path would either put it on the network — the
thing it exists to avoid — or make it the only UI in the system that edits the repo without a CLI
underneath, which is Principle VI's exact prohibition.

## Project Structure

### Documentation (this feature)

```text
specs/029-block-document-model/
├── plan.md                      # This file
├── spec.md                      # Feature specification, with the two rulings
├── research.md                  # Phase 0 — nine decisions, measured
├── data-model.md                # Phase 1 — three files, block, disposition, export
├── quickstart.md                # Phase 1 — validation, deterministic first
├── contracts/
│   └── block-model.md           # Phase 1 — P, R, C, G, V, N, W, X
├── checklists/
│   └── requirements.md          # Spec quality checklist (16/16)
└── tasks.md                     # Phase 2 — NOT created by /speckit-plan
```

### Source Code (repository root)

```text
session_doc/
├── blocks.py                     # NEW: parse_blocks / join_blocks, the marker constant,
│                                 #   the block model. Round-trip is its contract (P1).
├── authored.py                   # NEW: the .authored.yaml schema and loader — strict,
│                                 #   versioned, mirroring campaignlib/transcript_corrections.
├── compose.py                    # NEW: narration + record -> .composed.md, deterministic,
│                                 #   refusing on a digest mismatch.
├── sd_compose.py                 # NEW CLI: compose a scene, or a whole narration dir.
├── sd_review.py                  # NEW CLI: `export` a scene to the reviewer's JSON.
├── review/
│   └── reviewer.html             # NEW: one self-contained file. No network, no build.
├── assemble.py                   # CHANGE: --require-composed; variant collision via the
│                                 #   existing SceneCollision + --use (research D4).
└── sd_narrate.py                 # CHANGE: refuse over a record with authored content;
                                  #   --reroll lifts it (N1-N3).

tests/
├── test_block_model.py           # NEW: P, R, C — round-trip, refusals, determinism.
├── test_assemble_gate.py         # NEW: G, V.
├── test_reviewer_selfcontained.py# NEW: W1 (no network) and W2 (version agreement).
├── test_block_model_no_llm.py    # NEW: X1, AST walk, after tests/test_provenance_no_llm.py.
└── test_gap_marker_pairing.py    # NEW: X2, the marker tied to the prompt that emits it.

experiments/20260907-phandalin-gm-gaps-confirm/   # UNCHANGED, read-only: the corpus.
```

**Structure Decision**: existing layout, one new subdirectory for a static asset. The reviewer
lives under `session_doc/` rather than `frontend/` because it is not part of the web app — it
ships no build output, imports nothing, and is copied to a phone by hand.

## Phasing

| Phase | What | Independently useful? |
|---|---|---|
| **A — the parser** | `blocks.py`, round-trip, the marker constant and its pairing guard | Nothing else works without it |
| **B — the reviewer** | `sd_review export`, `reviewer.html`, self-containment and version tests | **Yes** — the whole mobile review, with the result kept on the clipboard |
| **C — the record** | `authored.py`, `compose.py`, `sd_compose`, staleness refusal | Yes — hand-author a record and compose |
| **D — the gate** | `--require-composed`, the variant collision | Yes — stops a marker reaching a chapter |
| **E — the refusal** | `sd_narrate` over authored work, `--reroll` | Yes — protects the only hand-written thing here |

B is the MVP and it is deliberately ahead of C: the GM can do the whole mobile review, and hold
the output, before anything can write it back. That matches the ruling that the round trip stops
at the clipboard — building C first would produce a record with no way to fill it.

## Risks

| Risk | Mitigation |
|---|---|
| The parser loses whitespace, so every composed document differs from its narration everywhere | P1 round-trip asserted on all four corpus scenes, not on a fixture. It is the first thing built and the first thing tested. |
| Anchor matching lands an authored block on the wrong prose | Not built. v1 refuses on a digest mismatch and matches nothing (research D2). This is the feature's highest-risk work and it is deferred whole. |
| The reviewer and the exporter drift, because the page is no longer regenerated | W2 — the version the page declares is compared to the exporter's constant in CI. This is the specific cost of never regenerating the page, and the only guard against it. |
| Rulings lost to a page reload on `file://` | Named as an open risk in research. Implement storage, verify on the GM's real device, keep the warning honest until it has been verified. A GM who loses twenty rulings will not use this twice. |
| The export silently truncates on a mobile clipboard and renders half a scene | W4 — malformed or truncated input is reported, never rendered as a partial scene. One scene per file keeps the paste at 14–26 KB. |
| A cheap-looking "resolve all gaps" button appears in six months | X1, an AST guard, plus the evidence file it points at. A paragraph would not have stopped it; this is why the principle gets a test. |
| The variant refusal is confused with `#429`'s | Same exception and flag by design (Principle XII), different sentence — V3 asserts the message distinguishes them. |
