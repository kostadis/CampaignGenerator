# Implementation Plan: Two-Phase Extraction Agent

**Branch**: `feat/dgx-two-phase-extraction` | **Date**: 2026-08-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-two-phase-extraction/spec.md`

## Summary

The Session Doc Editor's two extraction stages both instruct the model to quote
dialogue verbatim, and neither checks that it did. Running Stage 1 against
DeepSeek on the DGX Spark produced fabricated quotes that nothing detected.

Add a **deterministic, zero-token quote verifier** over the Stage 1 summary and
Stage 2 scene extractions, plus a **stage-scoped orchestrator** that runs
generation followed by that stage's checks as one action.

Research (D1) changed the design materially: measured on a real session, only
**64% of quotes are exact verbatim** even from Claude — the other 36% are
mostly *disfluency edits* (`"I do cross promotions."` vs the VTT's `"I do, like,
cross promotions."`), not fabrications. A binary verbatim check would emit 186
findings for one session, ~90% benign. So verification classifies into **three**
buckets — `verified` / `near` / `unverified` — and only the third is the
fabrication signal.

Nothing is auto-corrected: the verifier flags and reports, and the GM applies
fixes in Claude.

## External dependency — D13 ✅ RESOLVED

`session_doc/scene_extract.py` used to feed the model an **alias-rewritten VTT**
(`input_normalizer=` from `build_alias_normalizer`), so Stage 2 quotes were
verbatim against a transformed source rather than against what was said.

**Fixed upstream in `6e00f54` (PR #231).** Verified on `origin/main`:
`input_normalizer=` is gone from `scene_extract.py`, the canonical roster still
reaches the model as knowledge via `format_npc_roster`, and `campaignlib/npc.py`
carries an idempotency guard for the remaining consumers.

**Action required**: this branch (`feat/dgx-two-phase-extraction`) was cut from
`7a27a8c` and must **rebase onto `6e00f54`** before Phase 4. Until it does, the
worktree still contains the defect.

The rule this came from outlives the fix — *pass the equivalence set as
knowledge, never as a transform* (`research.md` D13). Note also that extractions
generated **before** `6e00f54` remain corrupt on disk; the remedy is
re-extraction, not repair.

## Technical Context

**Language/Version**: Python 3.11+ (repo baseline); TypeScript/Vue 3 for the UI surface

**Primary Dependencies**: stdlib only for the verifier core (`re`, `difflib`,
`pathlib`). No new third-party dependency. Existing: `pydantic` (config schema),
`FastAPI` (router), `PyYAML`.

**Storage**: Files on disk. Input: session `.vtt`, `session-summary.md`,
`scene_extractions_new/NN_*.md`. Output: `quote_report.md` in the session's
narration directory, alongside the existing `consistency_report.md`.

**Testing**: `pytest` (`tests/`). Fixture-based unit tests plus a differential
test guarding the `locate_quote` refactor (D10).

**Target Platform**: Linux / WSL2, CLI-first; FastAPI + Vue web UI as a face.

**Project Type**: CLI tools with a web UI over them (repo Principle VI).

**Performance Goals**: Full-session verification (522 quotes × ~3,400 VTT cues)
in **under 30 s** (SC-004). Measured prototype: **< 5 s**.

**Constraints**: Zero LLM calls in verification (FR-003). Zero modification of
quote text (FR-006). Idempotent annotation (FR-007).

**Scale/Scope**: One session at a time; ~500 quotes, ~12 scene files, ~150KB VTT.

## Constitution Check

*GATE: passed before Phase 0; re-checked after Phase 1 design below.*

| Principle | Gate | Verdict |
|---|---|---|
| I — Disk is Truth | Report is a file; VTT never modified | ✅ |
| II — Human Checkpoint | Orchestrator is **stage-scoped** (D12) and stops at the existing Stage 1→2 gate. No LLM consumes another LLM's unreviewed output as structure — `sd_consistency` writes a report *for a human* | ✅ |
| III — Retrieval/Render Separated | Verifier neither retrieves nor renders; `sd_agent` makes no `stream_api`/`call_api` call at all, so `tests/test_retrieve_render_isolation.py` stays green | ✅ |
| IV — Verbatim is Sacred | **This is the feature.** Enforcement for a contract that had none. FR-006/SC-007 forbid touching quote text | ✅ |
| V — One Seam per Boundary | No new external boundary. The verifier crosses none — it calls no model | ✅ |
| VI — CLI is the Engine | `sd_verify_quotes` + `sd_agent` are CLIs; the router shells out via `stream_subprocess` | ✅ |
| VII — Extract Once, Synthesize Deliberately | No pass collapsed; a check is added beside existing passes | ✅ |
| VIII — State is Discoverable | `quote_report.md` on disk; staleness in `/pipeline-status`; the report states what it did **not** check (D5) | ✅ |
| IX — UI Mechanizes, Claude Converses | UI runs the steps and shows counts; judging findings and applying fixes happens in Claude | ✅ |
| X — Selection is Explicit | Resolved in **D11** — the principle governs token-spending scope decisions; a free read-only check is outside it | ✅ |

**Post-Phase-1 re-check**: no new violations. One item to watch — D10's
`locate_quote` refactor touches the live ensemble pipeline for a feature that
does not require it. Justified as reuse-over-duplication, and gated on a
differential test proving it inert. If that test cannot be made to pass, **drop
the refactor and duplicate the matcher** rather than risk the ensemble corpus.

## Project Structure

### Documentation (this feature)

```text
specs/007-two-phase-extraction/
├── plan.md              # This file
├── spec.md              # /speckit-specify output
├── research.md          # Phase 0 — D1–D12 + measurements
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/           # Phase 1 — CLI + HTTP contracts
│   ├── sd_verify_quotes.md
│   ├── sd_agent.md
│   └── http_editor_verify.md
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks output — NOT created here
```

### Source Code (repository root)

```text
campaignlib/
└── textproc.py                  # + locate_quote()  (shared matcher, D10)

session_doc/
├── verify_quotes.py             # NEW — engine: parse, classify, report
├── sd_verify_quotes.py          # NEW — CLI entry point
├── sd_agent.py                  # NEW — stage-scoped orchestrator
├── io.py                        # reuse parse_vtt, _split_scene_body
├── enhance_summary.py           # unchanged (Stage 1 generator)
├── scene_extract.py             # unchanged (Stage 2 generator)
└── sd_consistency.py            # unchanged (grounding check)

pipelines/ensemble/
├── extract_facts.py             # verify_quotes() rewired to locate_quote
└── ensemble_merge.py            # quote_offset() rewired to locate_quote

server/
├── routers/scene_editor.py      # + GET /verify (SSE), + verify in /pipeline-status
└── session_editor_config_shared.py  # + VerifyKnobs

frontend/src/                    # + Verify action & findings count in the editor

config/agents/                   # unchanged — no new prompt (verification uses no model)

tests/
├── test_verify_quotes.py        # NEW — classification, parsers, idempotency
└── test_locate_quote_parity.py  # NEW — differential guard for the D10 refactor

docs/cli/session_doc_pipeline.md # + the verify stage and report format
pyproject.toml                   # + [project.scripts] entries
```

**Structure Decision**: Follows the existing `session_doc/` split — a module
holding logic (`verify_quotes.py`) beside a thin `sd_*.py` CLI, mirroring
`sd_consistency.py`/`check_consistency.py`. The shared matcher goes to
`campaignlib/textproc.py` because two pipelines already implement it
independently (D10). No new package or service tier.

## Design

### Classification — the three buckets (D1, D2, D7)

For each parsed quote, against the speaker-stripped VTT text (D6):

1. **exempt** — content is wholly an editorial marker (`[inaudible]`,
   `(paraphrase)`, `(truncated)`). Not checked, counted separately. (D3)
2. **unscored** — fewer than 4 tokens. Reported, never accused. (D7)
3. **verified** — exact, or whitespace-normalised, substring. (~64% expected)
4. **near** — best coverage score ≥ threshold (default **0.85**, D8).
   Informational. Carries the nearest VTT line so the GM sees the edit.
5. **unverified** — below threshold. **The fabrication signal.**

Scoring is containment-biased:
`max(SequenceMatcher.ratio(), longest_common_block / len(quote))` (D2).
Bracketed spans inside a quote are stripped before matching (D3).

### Parsing (D4, D5)

- **Stage 1** `session-summary.md`: `> "…"` blockquote lines only. Inline
  `"…"` is **not** dialogue-reliable and is out of scope — the report says so.
- **Stage 2** `NN_*.md`: `_split_scene_body` → `## Verbatim moments` only.
  The `## Scene summary` section is human-authored gm-assist content.

### Orchestration (D12)

```
sd_agent --stage summary  →  enhance_summary  →  sd_verify_quotes  →  sd_consistency  →  STOP
sd_agent --stage scenes   →  scene_extract    →  sd_verify_quotes                     →  STOP
```

Subprocess only; a **small enumerated** flag set is forwarded; every command is
printed before it runs so a dropped flag is visible. A check reporting findings
does not abort the run (FR-019); only a failure to produce the artifact does.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| `locate_quote` refactor touches the live ensemble pipeline, which this feature does not require | Two independent implementations of the same whitespace-tolerant match already exist (`extract_facts.verify_quotes`, `ensemble_merge.quote_offset`); adding a third in `session_doc/` guarantees drift | Duplicating the matcher is genuinely simpler and stays the **fallback** if the differential test (D10) cannot prove the rewire inert. Reuse is preferred only because it is provable here |
| Three classification buckets instead of the two the spec described | Measured: a binary check flags 36% of quotes on a clean Claude session, ~90% of them benign disfluency edits (D1) | Binary was the original design. Rejected on data — a report that is 90% false positives is worse than none, because it trains the GM to ignore it |
