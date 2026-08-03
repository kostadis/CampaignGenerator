---

description: "Task list for Two-Phase Extraction Agent"
---

# Tasks: Two-Phase Extraction Agent

**Input**: Design documents from `/specs/007-two-phase-extraction/`

**Prerequisites**: plan.md, spec.md, research.md (D1–D13), data-model.md, contracts/

**Tests**: Included. Not a TDD preference — `research.md` D10 makes a differential
test the **gate** on refactoring the live ensemble pipeline, and FR-006/FR-007
(never modify quote text, idempotent annotation) are safety properties that are
worthless unasserted.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

Repo root is the worktree. Python packages: `campaignlib/`, `session_doc/`,
`pipelines/ensemble/`, `server/`; tests in `tests/`; frontend in `frontend/src/`.

---

## Phase 1: Setup

**Purpose**: Confirm the environment is testing *this* worktree, not main.

- [ ] T001 Verify import shadowing before any other work: run `python -c "import campaignlib, session_doc; print(campaignlib.__file__, session_doc.__file__)"` from the worktree root and confirm both paths are inside `.claude/worktrees/dgx-two-phase-extraction/`. If either resolves to `/home/kroussos/src/CampaignGenerator/`, stop and fix the venv — a green test run would otherwise prove nothing (see `quickstart.md` Prerequisites)
- [ ] T002 [P] Create empty module skeletons `session_doc/verify_quotes.py`, `session_doc/sd_verify_quotes.py`, `session_doc/sd_agent.py` with docstrings only, so later tasks have files to edit
- [ ] T003 [P] Create the fixture session used by every test in `tests/fixtures/verify_quotes/` — `s.vtt` plus `session-summary.md` carrying one exact, one disfluency-edited, one fabricated and one `[inaudible]` quote, transcribed from `quickstart.md` Scenario 1

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared matcher, transcript model, scorer, classifier, reporter
and annotator. **Every user story depends on this phase.** US1 and US2 differ
only in their parser and surface.

### The D10 refactor and its gate

- [ ] T004 Add `locate_quote(quote: str, document: str) -> int | None` to `campaignlib/textproc.py`, lifted from `pipelines/ensemble/ensemble_merge.py:271 quote_offset` (exact `find`, then whitespace-tolerant regex). Export it from `campaignlib/__init__.py` alongside the existing `textproc` exports
- [ ] T005 Write `tests/test_locate_quote_parity.py` **before** rewiring anything: assert `locate_quote` returns identical results to the current `ensemble_merge.quote_offset` and that `bool(locate_quote(...) is not None)` matches the current `extract_facts.verify_quotes` flag, over the fixture corpus **and** a sample of real facts from an existing `merged.json`
- [ ] T006 Rewire `pipelines/ensemble/ensemble_merge.py:271 quote_offset` to delegate to `campaignlib.textproc.locate_quote`, keeping the public name and signature
- [ ] T007 Rewire `pipelines/ensemble/extract_facts.py:230 verify_quotes` to derive `quote_verified` from `locate_quote(...) is not None`, preserving the empty-quote-is-unverified rule
- [ ] T008 Run `tests/test_locate_quote_parity.py` and the existing ensemble tests. **GATE — if parity fails, revert T006/T007 and instead duplicate the matcher inside `session_doc/verify_quotes.py`.** Per `plan.md` Complexity Tracking the ensemble corpus is not worth risking for a tidiness win; record the decision in `research.md` D10

### Transcript, types, scoring, classification

- [ ] T009 [P] Implement `SourceTranscript` in `session_doc/verify_quotes.py` per `data-model.md`: read the `.vtt`, call the existing `session_doc.io.parse_vtt`, strip a leading `^[^:]{1,40}:\s*` speaker prefix per line into `spoken`/`speakers` (D6), and build the normalised lowercased `haystack`. Raise on missing/unreadable/empty — never return an empty corpus (FR-011)
- [ ] T010 [P] Implement `Verdict`, `Quote` and `Finding` in `session_doc/verify_quotes.py` per `data-model.md`. `Quote.text` is immutable and is the identity; `match_text` is derived (bracketed spans stripped, whitespace-normalised, lowercased) and used only for matching (D3)
- [ ] T011 Implement `score_quote(match_text, transcript)` in `session_doc/verify_quotes.py`: candidate prefilter on token overlap, then containment-biased scoring `max(SequenceMatcher.ratio(), longest_common_block / len(quote))` (D2). Return best score plus the winning line and its speaker
- [ ] T012 Implement `classify(quote, transcript, threshold, min_tokens)` in `session_doc/verify_quotes.py` returning a `Finding` with one of the five verdicts, in the order specified in `plan.md` § Classification: `exempt` (wholly `[inaudible]`/`(paraphrase)`/`(truncated)`, D3) → `unscored` (< `min_tokens` tokens, D7) → `verified` (via `locate_quote`) → `near` (≥ threshold) → `unverified`
- [ ] T013 [P] Write `tests/test_verify_quotes.py` classification cases against the T003 fixture: exact ⇒ `verified`, disfluency-edited ⇒ `near`, fabricated ⇒ `unverified`, `[inaudible]` ⇒ `exempt`, two-token quote ⇒ `unscored`. This is the acceptance test for SC-001 and SC-002

### Report and annotation

- [ ] T014 Implement `render_report(report: VerificationReport) -> str` in `session_doc/verify_quotes.py` matching the markdown layout in `contracts/sd_verify_quotes.md`: header with transcript path and threshold, counts table, **`## Not checked`** section, then `unverified` (ascending score) before `near`. Assert in code that counts sum to the number of quotes parsed (`data-model.md` validation)
- [ ] T015 Ensure `## Not checked` is never empty — it always states the inline-`"…"` limitation (D5), the speaker-attribution limitation, and for Stage 2 the `## Scene summary` exclusion (D4). Principle VIII: naming what was not checked is part of the answer
- [ ] T016 Implement `annotate(path, findings, report_only)` in `session_doc/verify_quotes.py`: append `<!-- cg:unverified -->` to `unverified` quote lines only, skip lines already carrying the marker, never touch text between the quote delimiters, and write via `campaignlib.util.atomic_write_text` (FR-006, FR-007)
- [ ] T017 [P] Add idempotency and non-mutation tests to `tests/test_verify_quotes.py`: annotate twice and assert the file is byte-identical the second time (SC-006), and assert every `"…"` span is unchanged versus a pristine copy (SC-007)

**Checkpoint**: engine complete and tested. No CLI yet.

---

## Phase 3: User Story 1 — Catch invented quotes in the generated summary (P1) 🎯 MVP

**Goal**: The GM runs one command against a generated `session-summary.md` and
gets a report naming each quote absent from the transcript, with the nearest
real line beside it.

**Independent test**: `quickstart.md` Scenarios 1–3 — classification correctness,
non-mutation/idempotency, and refusal without a transcript.

- [ ] T018 [US1] Implement `parse_summary_quotes(text) -> list[Quote]` in `session_doc/verify_quotes.py`: extract `> "…"` blockquote lines **only**, tracking the enclosing `##`/`###` heading as `Quote.section` and the following `> — Name` line as `speaker_hint`. Inline `"…"` spans are deliberately **not** parsed (D5 — `the "liberators of the Ordning"` is a label, not speech)
- [ ] T019 [P] [US1] Add Stage 1 parser tests to `tests/test_verify_quotes.py`: a `> "…"` quote is found with its section; an inline `"…"` in prose is **not** returned; a `> — Name` attribution becomes `speaker_hint` and is not itself treated as a quote
- [ ] T020 [US1] Implement the `sd_verify_quotes` CLI in `session_doc/sd_verify_quotes.py` per `contracts/sd_verify_quotes.md`: `--vtt`, `--summary`, `--out`, `--threshold`, `--min-tokens`, `--report-only`, `--verbose`. Deliberately **no** `--backend/--model/--fast/--batch` — the tool calls no model and offering those flags would imply otherwise (FR-003)
- [ ] T021 [US1] Implement the exit-code contract in `session_doc/sd_verify_quotes.py`: `0` ran with no `unverified`, `1` ran with findings, `2` could not run. The `1`/`2` split is what lets `sd_agent` continue on findings but stop on breakage (FR-019)
- [ ] T022 [US1] Implement the stdout summary block in `session_doc/sd_verify_quotes.py` with per-verdict counts **and percentages** — a bare "8" does not tell the GM whether the run was healthy (`contracts/sd_verify_quotes.md`)
- [ ] T023 [US1] Add `sd_verify_quotes = "session_doc.sd_verify_quotes:main"` to `[project.scripts]` in `pyproject.toml`, then run `uv pip install -e . --python "$VIRTUAL_ENV/bin/python"` into the server's venv (CLAUDE.md — otherwise the later UI button fails with "Stream error — check terminal")
- [ ] T024 [P] [US1] Add a CLI-level test to `tests/test_verify_quotes.py` asserting exit code `2` and a clear message when `--vtt` points at a missing file — **not** a report claiming every quote is unverified (FR-011, Scenario 3)
- [ ] T025 [US1] Run `quickstart.md` Scenarios 1–3 end to end and confirm every expected verdict and both PASS lines

**Checkpoint**: US1 is independently usable. A GM can verify any generated
summary by hand. **This is the MVP** — it is the failure that prompted the
feature, and it is not blocked by D13.

---

## Phase 4: User Story 2 — Catch invented quotes in scene extractions (P2)

**Goal**: Verify Stage 2 `scene_extractions_new/NN_*.md` before narration
consumes them as authoritative.

> ### ✅ UNBLOCKED — D13 resolved in `6e00f54` (PR #231)
>
> `session_doc/scene_extract.py` no longer passes `input_normalizer=`, so the
> model now sees the true VTT and the canonical roster reaches it as knowledge
> via `format_npc_roster`. `campaignlib/npc.py` also gained an idempotency guard
> for the remaining consumers.
>
> **This branch was cut from `7a27a8c` and must rebase onto `6e00f54` first** —
> T026 is that gate. Pre-`6e00f54` extractions on disk are still corrupt; the
> remedy is re-extraction, not repair.

- [ ] T026 [US2] **GATE**: rebase `feat/dgx-two-phase-extraction` onto `origin/main` at `6e00f54` or later, then confirm `grep -c "input_normalizer=" session_doc/scene_extract.py` returns `0` and that `format_npc_roster` still supplies the roster to the system prompt. See `research.md` D13 for the rule and the blast radius — **7 call sites in 6 files** still use the transform (`sd_narrate.py:191` is the verbatim-critical one); out of scope here, but the reason the guard was added
- [ ] T027 [US2] Implement `parse_scene_quotes(path) -> list[Quote]` in `session_doc/verify_quotes.py`: use the existing `session_doc/io.py:53 _split_scene_body` to take the `## Verbatim moments` section **only**, then extract `> "…"` lines, carrying the enclosing `**[Speaker]**` block as `speaker_hint`. The `## Scene summary` section is human-authored gm-assist content and must never be flagged (D4)
- [ ] T028 [US2] Add `--scene-extractions DIR` to `session_doc/sd_verify_quotes.py`: sweep `NN_*.md` sorted, skipping `.prev`, `.reviewed` and `.scaffold.md` — mirroring the filter already used by `server/routers/scene_editor.py:834 api_pipeline_status`. Permitted alongside `--summary`; at least one is required
- [ ] T029 [P] [US2] Add Stage 2 parser tests to `tests/test_verify_quotes.py`: quotes inside `## Verbatim moments` are found; quotes inside `## Scene summary` are **not**; `*"italic"*` quotes in the summary section are ignored; the sidecar suffixes are skipped
- [ ] T030 [US2] Extend `render_report` so per-file findings are grouped under the source filename with line numbers, keeping `unverified` ahead of `near` across the whole run rather than per file
- [ ] T031 [US2] Run `quickstart.md` Scenario 4 against `~/campaigns/Phandalin/summaries/20260623/`. Expect ≈336 `verified` (64%), ≈148 `near`, single-digit `unverified`, wall clock < 30 s (SC-004). **A materially different `verified` share means the parser regressed** — the D1 measurement is the baseline

**Checkpoint**: both extraction stages verifiable.

---

## Phase 5: User Story 3 — One action instead of three (P3)

**Goal**: `sd_agent --stage {summary,scenes}` runs generation then that stage's
checks, and stops at the stage boundary.

**Independent test**: `quickstart.md` Scenario 6 — dry run, then a real run
asserting order, continue-on-findings, and the hard stop.

- [ ] T032 [US3] Implement the `sd_agent` argument surface in `session_doc/sd_agent.py` per `contracts/sd_agent.md`: `--stage`, `--session-dir`, `--vtt`, `--gmassist`, `--context`, `--threshold`, `--report-only`, `--skip-generate`, `--dry-run`, plus backend flags via the existing `campaignlib.add_backend_args`
- [ ] T033 [US3] Implement step construction in `session_doc/sd_agent.py` for both stages — `summary` ⇒ `enhance_summary` → `sd_verify_quotes` → `sd_consistency`; `scenes` ⇒ `scene_extract` → `sd_verify_quotes`. Resolve `--vtt` **once** and pass the same path to generation and verification so they cannot disagree (D9/D13)
- [ ] T034 [US3] Forward only the **enumerated** flag set — no `--extra-args` passthrough — and print each fully-resolved command before running it, secret-free, per the `/ensemble/setup` command-bar pattern. `ensemble_batch` silently dropped `--similarity` for a month (D12); make the hop visible
- [ ] T035 [US3] Implement `--dry-run` in `session_doc/sd_agent.py`: print the numbered command list and exit 0 without executing. This is the "what will this spend" affordance before a DGX run
- [ ] T036 [US3] Implement failure semantics in `session_doc/sd_agent.py` per `contracts/sd_agent.md`: generation non-zero ⇒ stop; verify exit `1` (findings) ⇒ continue; verify exit `2` ⇒ continue but mark the run degraded and name the check that did not happen; final exit `0`/`1`/`2` (FR-019)
- [ ] T037 [US3] Implement the closing summary block in `session_doc/sd_agent.py`, including the two load-bearing lines: that **nothing was auto-corrected**, and that the run **stopped at the stage boundary** because scene extraction is a separate, human-gated step (FR-018, Principle II)
- [ ] T038 [US3] Add `sd_agent = "session_doc.sd_agent:main"` to `[project.scripts]` in `pyproject.toml` and reinstall into the server venv
- [ ] T039 [P] [US3] Add `tests/test_sd_agent.py`: assert `--dry-run` prints three steps for `--stage summary` and two for `--stage scenes`; assert no command contains an API key; assert a stubbed verify exit `1` does not prevent the consistency step; assert `--stage summary` never emits a `scene_extract` command (FR-018)
- [ ] T040 [US3] Assert `session_doc/sd_agent.py` contains no `stream_api`/`call_api` call and run `python -m pytest tests/test_retrieve_render_isolation.py` to confirm the isolation test still passes

**Checkpoint**: all three user stories delivered at the CLI.

---

## Phase 6: UI Surface (cross-cutting)

**Purpose**: FR-023 — expose verification in the Session Doc Editor. Serves all
stories; requires the CLIs to exist.

- [ ] T041 [P] Add `VerifyKnobs` (`threshold: float = 0.85`, `min_tokens: int = 4`, `report_only: bool = False`) to `server/session_editor_config_shared.py` with `extra="forbid"`, and register it as `verify:` on `SessionEditorConfig`. No `enabled` flag — a check you can switch off in config is off when it matters (`data-model.md`)
- [ ] T042 Add `_build_verify_cmd(request, cfg, target)` to `server/routers/scene_editor.py` returning the `sd_verify_quotes` argv, resolving paths through the existing `_vtt_path` / `_session_summary_path` / `_scene_extractions_dir` helpers. Do **not** call `_selection_args` — there is no model and therefore no backend or batch to forward
- [ ] T043 Add `GET /verify` to `server/routers/scene_editor.py` per `contracts/http_editor_verify.md`, mirroring `api_enhance` (`:1011`): `stream_subprocess` + `StreamingResponse` with the same SSE headers, and `_record_activity(cfg, stage="verify", …)` on completion
- [ ] T044 Extend `api_pipeline_status` in `server/routers/scene_editor.py` with a `verify` entry: `_stage_status(report, [vtt, summary, *scene_files])` plus `unverified`/`near`/`verified` parsed from the report's counts table. `warn` when stale **or** when `unverified > 0`; counts `null` and status `warn` when the report cannot be parsed — an unreadable report is not a passing one
- [ ] T045 [P] Add the Verify action and status dot to the Session Doc Editor in `frontend/src/`, beside Enhance and Extract, showing the `unverified` count when non-zero and linking the report through the existing Typora integration. **No accept/reject control** — accepting a finding would mean rewriting a quote, which FR-006 forbids (Principle IX)
- [ ] T046 [P] Add `tests/test_editor_verify_routes.py`: `GET /verify` streams and records activity; `/pipeline-status` reports `cold` with no report, `warn` with findings, `ok` when clean and fresh; an unknown key under `verify:` fails config validation

---

## Phase 7: Polish & Calibration

- [ ] T047 **Calibrate the threshold against DeepSeek output** (D8). Generate a summary via `sd_agent --stage summary --backend dgx --model deepseek-…`, hand-label ~40 quotes as genuine-but-edited vs fabricated, and sweep the threshold for the precision-first value. **The shipped 0.85 is derived from Claude output and is a starting point, not a measurement** — the repo has been burned by exactly this (`--embed-threshold 0.93` measured on a model that was later replaced). Record the sweep in `research.md` D8
- [ ] T048 [P] Document the verify stage in `docs/cli/session_doc_pipeline.md`: where it sits in the stage diagram, the `sd_verify_quotes` and `sd_agent` invocations, the three-bucket meaning, and why `near` is informational rather than a failure
- [ ] T049 [P] Document the UI surface in `docs/web/web_ui.md` under § Session Doc Editor — the Verify action, the status dot semantics, and that judging findings happens in Claude
- [ ] T050 [P] Add the `verify:` group to the session-editor config reference in `docs/config/session-editor-isolation.md`
- [ ] T051 Re-run the full suite `python -m pytest tests/` after re-confirming T001's import check, and run `quickstart.md` § End-to-end acceptance mapping every SC-/FR- item to its scenario

---

## Dependencies & Execution Order

```
Phase 1 Setup  (T001–T003)
      ↓
Phase 2 Foundational  (T004–T017)      ← BLOCKS every user story
      ↓
      ├─────────────────────────────┬──────────────────────────┐
      ↓                             ↓                          ↓
Phase 3 US1 (P1)             Phase 5 US3 (P3)          Phase 4 US2 (P2)
T018–T025  🎯 MVP            T032–T040                 T026–T031
independent                  needs US1's CLI            needs rebase ≥ 6e00f54
      └─────────────┬───────────────┘                          │
                    ↓                                          │
             Phase 6 UI  (T041–T046)  ←──────────────────────── ┘
                    ↓
             Phase 7 Polish  (T047–T051)
```

**Story independence**:

- **US1** depends only on Phase 2. Ships alone as the MVP.
- **US2** depends on Phase 2 **and on the external D13 fix**. Independently
  testable once unblocked; its parser shares nothing with US1's.
- **US3** depends on US1's CLI existing (it shells out to it). It can orchestrate
  `--stage summary` before US2 exists; `--stage scenes` needs US2.

**Critical path to MVP**: T001–T003 → T004–T017 → T018–T025. **25 tasks.**

## Parallel Opportunities

Within Phase 2: T009 and T010 are independent (different classes, same new
file — coordinate or land sequentially if editing conflicts); T013 and T017 are
test-only and parallel with each other once their subjects exist.

Within Phase 3: T019 and T024 (tests) run parallel to each other.

Within Phase 6: T041, T045 and T046 touch different trees (config schema,
frontend, tests) and are fully parallel. T042→T043→T044 are sequential — all
edit `server/routers/scene_editor.py`.

Within Phase 7: T048, T049, T050 are three different docs, fully parallel.

**Cross-phase**: once Phase 2 lands, Phase 3 (US1) and Phase 5 (US3 scaffolding
+ tests) can proceed concurrently by different implementers.

## Implementation Strategy

**Ship US1 first and use it.** It is 25 tasks to the failure that prompted the
feature, it is not blocked by D13, and running it against a real DeepSeek summary
is what produces the calibration data T047 needs. Everything after it is
leverage on a thing already proven to work.

Then either:

- **US3** (orchestration) if the toil is in invoking the steps, or
- **US2** (scene extractions) once D13 clears — and note that US2's first real
  run doubles as a regression test for the alias-substitution fix, since
  `Lord Lord Cassian Meliamne` would surface as an unverified quote.

**Do not build Phase 6 (UI) before US1 has been used at the CLI for a real
session.** The status semantics in T044 encode judgments — when `warn` is right,
what an unparseable report means — that are cheap to change after using the tool
and expensive to change after the frontend depends on them.
