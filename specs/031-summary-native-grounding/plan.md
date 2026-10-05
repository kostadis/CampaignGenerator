# Implementation Plan: Summary-Native Grounding Docs

**Branch**: `031-summary-native-grounding` | **Date**: 2026-10-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/031-summary-native-grounding/spec.md` (issue #499)

## Summary

This adds a fourth grounding-doc rendering path. It reads a directory of
already-reviewed structured session summaries, validates the whole directory in one
pass, and refuses on any blocking problem. Chapter identity disagreement is a hard
failure. Within a chosen chapter range, it builds a lossless, byte-stable evidence
corpus (chronology, verbatim memorable moments, per-entity dossiers) with no model
call. Canonicalization is GM-ruled and category-aware. The pipeline then renders
world state, campaign state, party and planning **drafts** through the standard
`campaignlib` seam, checks each against a declared outline, and retains every prompt
and selection. It is delivered as one CLI (`summary_native`) with a matching
Grounding page, plus a CLI how-to in `docs/cli/`.

## Technical Context

**Language/Version**: Python 3.12 (backend/CLI); TypeScript + Vue 3 (frontend page)

**Primary Dependencies**: existing only. `pyyaml`, `pydantic`, `fastapi`, and stdlib
`difflib`/`hashlib`/`re`. No new third-party packages.

**Storage**: Markdown/YAML/JSON files under `<campaign>/docs/summary_native/`, plus a
new group in the existing `<config>/grounding.yaml`.

**Testing**: pytest (`tests/test_summary_native_*.py`) with synthetic fixture corpora
in `tests/fixtures/summary_native/`. There is an opt-in `-m oota` test against the
real corpus. Synthesis is tested with a fake client; there are no live calls in CI.

**Target Platform**: Linux, single-user local install. The web UI is served by the
existing FastAPI app.

**Project Type**: CLI pipeline + web UI face (Principles VI and XI).

**Performance Goals**: the deterministic stages finish in under 2 minutes for 67
files and 409 scenes (SC-001). The prototype did it in seconds.

**Constraints**: no model call in any deterministic stage. The deterministic outputs
must be byte-identical across runs. Live `docs/*.md` must never be written. Summary
files must never be written. Corpora must never be mixed.

**Scale/Scope**: about 70 summaries, about 900 dossiers, and about 1,600
observations per campaign. Four draft documents.

## Constitution Check

*GATE: checked before Phase 0 and re-checked after Phase 1 design.*

| # | Principle | How this plan complies | Status |
|---|---|---|---|
| I | Disk is truth, model is a draft | The input is the summaries on disk, and they are never written. Every model output is a `drafts/*.draft.md`. Promotion is manual. The corpus can be rebuilt from disk | ✅ |
| II | Human checkpoint | The deterministic stages make no decisions. Merges are proposed and the GM rules on them in `canon.yaml`. Each draft feeds the next only through an explicit `--world-state`/`--campaign-state` file the GM names (FR-020). Tracking files are audit questions, not evidence | ✅ |
| III | Retrieval/render separation | There are no retrieval calls. Context assembly (`context.py`) and rendering (`synth.py`) are separate functions, so `test_retrieve_render_isolation.py` applies unchanged. The dossier-proposal gate does not apply: there is no `rpg_retriever` input (research R10) | ✅ |
| IV | Verbatim is sacred | Memorable moments, observation bodies and scene synopses are copied verbatim with provenance. Drafts claim to be derived, not verbatim. The campaign-state audit traces claims to chapter and scene | ✅ |
| V | One seam per boundary | Model calls go only through `campaignlib` (`client_from_args`/`stream_api`), and nothing imports `anthropic`. The registry is read through `campaignlib.registry` | ✅ |
| VI | CLI is engine | `server/routers/summary_native.py` only builds argv and streams it | ✅ |
| VII | Extract once, synthesize deliberately | There is no extraction: the summaries are already a reviewed extraction. The corpus is cached on disk and synthesis is per document. Long output is staged by declared parts, never collapsed | ✅ |
| VIII | State is discoverable | Stage state is visible from disk: `validation_report.*` → `manifest.json` → `drafts/`. The UI reads those files | ✅ |
| IX | UI mechanizes | There is no promote button and no canon editor in the UI. The GM edits `canon.yaml` and diffs/promotes at the CLI or in chat | ✅ |
| X | No silent "all" | UI runs refuse an unset range, and "All chapters" writes explicit bounds. On the CLI, a typed `--summaries DIR` is the explicit act | ✅ |
| XI | Bidirectional parity | Every subcommand and flag has a route parameter and page control in this feature. The canon *ruling* is deliberately file-edited (Principle IX), but its *invocation* (`canon`, `build --force`) is reachable | ✅ |
| XII | One spelling per option | Reused spellings: `--config --registry --backend --endpoint --model --max-tokens --force --dump-only --party-config --planning-config`. Defaults are declared once in `SummaryNativeRun`, with a router default-literal guard test | ✅ |
| XIII | Breaking state migrates out of band | No existing shape changes. `grounding.yaml` gains an optional group with defaults, which old files load unchanged. All new files are new paths. No migration document is needed, and that is recorded here | ✅ |

**Gate result: PASS.** No violations, so Complexity Tracking is empty.

**Post-design re-check (after Phase 1 artifacts):** still PASS. One item was
tightened during design: the registry's first-token inference is excluded from
automatic grouping (research R7), because applying it would be a merge that no exact
alias or GM ruling supports (Principle II).

## Project Structure

### Documentation (this feature)

```text
specs/031-summary-native-grounding/
├── plan.md              # this file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── cli.md           # summary_native subcommands, flags, exit codes
│   └── http.md          # /api/grounding/summary-native routes + config group
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
pipelines/summary_native/
├── __init__.py
├── schema.py        # recognised H2s, category map, finding codes, regexes
├── parse.py         # SummaryFile / Section / Entry / Scene (deterministic)
├── validate.py      # scan() → ValidationReport; ChapterRange resolution
├── corpus.py        # chronology, moments, dossiers, manifest; corpus-kind guard
├── canon.py         # registry-by-type aliases, canon.yaml, proposals
├── select.py        # recent/recurring selection → selection.json
├── context.py       # prompt assembly per doc (string building only)
├── synth.py         # render_part() via campaignlib; outline completeness check
├── compare.py       # draft vs live report + diff
├── cli.py           # argparse subcommands; main()
└── prompts/
    ├── world_state.system.md      + world_state.outline.yaml
    ├── campaign_state.system.md   + campaign_state.outline.yaml
    ├── party.system.md            + party.outline.yaml
    └── planning.system.md         + planning.outline.yaml

campaignlib/registry.py              # + Registry.explicit_aliases_by_type()
pyproject.toml                       # + summary_native console script (prompts/ ship automatically: hatch wheel includes pipelines/ resources)
server/grounding_config_shared.py    # + SummaryNativeRun group on GroundingConfig
server/routers/summary_native.py     # new router (argv builders + read-only routes)
server/main.py                       # include_router(..., prefix="/api/grounding/summary-native")
frontend/src/views/grounding/SummaryNative.vue
frontend/src/router.ts               # + /grounding/summary-native
frontend/src/components/layout/AppSidebar.vue   # + 4th RenderingPath 'summary-native'

tests/fixtures/summary_native/{clean,multi_error,out_of_range,gaps,aliases}/
tests/test_summary_native_parse.py
tests/test_summary_native_validate.py
tests/test_summary_native_corpus.py       # byte-stability, read_dossiers compat, separation
tests/test_summary_native_canon.py
tests/test_summary_native_select.py
tests/test_summary_native_synth.py        # fake client; outline check; audit/threat-tracker guards
tests/test_summary_native_cli.py
tests/test_summary_native_no_llm.py       # AST guard over deterministic modules
tests/test_summary_native_routes.py
tests/test_summary_native_config_defaults.py

docs/cli/summary_native_howto.md     # user-requested CLI how-to
docs/README.md, CLAUDE.md (Detailed docs table), docs/core/architecture.md  # links + 4th path
```

**Structure Decision**: a self-contained package under `pipelines/` beside
`pipelines/ensemble/` and `pipelines/grounding/`. It is a sibling rendering path, so
it imports nothing from `pipelines/ensemble/`. The one exception is a test that loads
its dossiers through `read_dossiers` to prove FR-012 compatibility. The server and UI
follow the existing grounding router/page/sidebar patterns.

## Implementation Phases & Delivery Process

**Roles (user directive):**
- **Orchestrator — Opus 5.5 (this session).** Writes each phase brief, reviews diffs,
  runs the test suite, commits, and drives review fixes.
- **Coder — Sonnet 5.5 (`claude-sonnet-5-5`).** Implementation is done by an `Agent`
  subagent with `model: "sonnet"`, one per phase. The phase brief names the files,
  the FRs, the tests to write first, and the codebase-memory-mcp entry points to read.
  Phases with no shared files may run in parallel.
- **Review after every commit.** `/code-review` runs on each commit. Confirmed
  findings are fixed by a Sonnet subagent and committed before the next phase starts.
  Findings judged not worth fixing are recorded in the commit message, not dropped
  silently.
- **Branch.** Work goes on a feature branch, never `main`. A PR is opened at the end,
  and merging waits for the user's explicit go-ahead.

| Phase | Scope | FRs | Commit |
|---|---|---|---|
| P1 | `schema`, `parse`, `validate` (collector, range, codes), `cli validate`, fixtures, tests | 001–005f | "summary_native: whole-directory validation + chapter range" |
| P2 | `corpus` (chronology/moments/dossiers/manifest, separation guard), `cli build`, byte-stability + `read_dossiers` tests, no-LLM AST guard | 006–012 | "summary_native: deterministic corpus build" |
| P3 | `Registry.explicit_aliases_by_type`, `canon` (mapping + proposals), `cli canon`, rebuild with mapping | 013–016 | "summary_native: GM-ruled canonicalization" |
| P4 | `select`, `context`, `synth` (outline check, parts, records), prompts + outlines for world_state & campaign_state, `compare`, `cli synth/compare` | 017–020, 022–027 | "summary_native: world/campaign state drafts" |
| P5 | party & planning prompts/outlines, threat-tracker guard | 018, 021 | "summary_native: party + planning drafts" |
| P6 | config group, router, Vue page, sidebar 4th path, route + defaults tests | 028–030, US5 | "summary_native: grounding UI page" |
| P7 | `docs/cli/summary_native_howto.md` + doc index/CLAUDE.md/architecture links; quickstart Q1–Q6 run on OOTA | — | "docs: summary_native CLI how-to" |

P5 depends on P4. P6 can start once the P4 CLI contract is frozen. P7 is last, so
the how-to documents what actually shipped. The real-corpus quickstart (Q4, and Q7
with model calls) is run by the orchestrator and reported to the GM. SC-008 is the
GM's judgment and is not claimed by the implementer.

## Complexity Tracking

No constitution violations to justify.
