# Implementation Plan: Reviewed Source-Custody Rebase for Corrected Historical Summaries

**Branch**: `040-source-custody-rebase` | **Date**: 2026-11-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/040-source-custody-rebase/spec.md` (issue #606)

**Worktree**: `/home/kostadis/src/CampaignGenerator/.claude/worktrees/040-source-custody-rebase`

## Summary

A corrected historical summary makes every later delta refuse at claims selection (`CLAIMS_SOURCE_STALE`), and there is no supported way out. The fix is to treat a **rebase as a spec 039 delta plan of `kind: rebase`**:

- **Sources:** the explicitly selected corrected summaries.
- **Candidates:** the bound baseline's four documents, with only the GM-approved claim repairs or holds applied.
- **Path:** the existing check → preview/stage → claims → exact signoffs → journaled promotion. This publishes a new generation whose lineage parent is the old one. The staged range manifest lists the corrected chapters at their **new** digests (with explicit gaps), so the existing parent-first custody resolver picks up the new pins without change.

New code covers seven things:

- inspection, which lists every stale pin;
- verified old-byte recovery (snapshot store → git → explicit file) and content-addressed snapshots;
- deterministic impact (citations into changed entries, retained claim annotations, unknown-impact whole-file members, follow-up consumers);
- per-source decisions that refuse hash-only adoption of semantic changes;
- a `hold` decision;
- `delta plan rebind`, which moves a pending delta onto the new baseline while carrying its NPC bindings and receipts;
- CLI/UI parity.

Details are in [research.md](research.md) R1–R10.

## Technical Context

**Language/Version**: Python 3.12 (repo standard); TypeScript + Vue 3 for the page

**Primary Dependencies**: pydantic v2 (records), PyYAML, FastAPI (thin routes), Vue 3 / Pinia / Vitest; `git` CLI (read-only, subprocess) for old-byte recovery

**Storage**: Files only. Under `docs/summaries/delta/`: `custody/objects/`, `rebase/<id>/`, plan revisions and rebind records. Generations are written only by the existing promotion writer.

**Testing**: pytest with a git-initialised synthetic fixture (`tests/_rebase_fixture.py`), building on `tests/_delta_us2.py`. Model calls go through the existing injectable invoker seam with a deterministic stand-in. The claims/promotion boundary is never mocked. Vitest for the page.

**Target Platform**: Linux, the GM's workstation; the web UI is served by the local FastAPI server

**Project Type**: CLI engine + thin web face (existing `pipelines/summary_native`, `server/`, `frontend/`)

**Performance Goals**: Inspection is integrity-only. It hashes each pinned summary once (ToEE: ~43 files, well under a second). No model call outside `rebase propose` and the claims gate's explicitly selected chunks.

**Constraints**:
- No all-history parse or model input.
- Old generations stay byte-identical.
- Authored summaries are never written.
- Every gate is reused, not bypassed.
- Existing plan and lineage digests must stay byte-stable (R10).

**Scale/Scope**: Single user; a rebase covers a handful of chapters (ToEE: 4). There are about 7 new CLI leaves, 7 routes and 1 page.

## Constitution Check

*Gate before Phase 0; re-checked after Phase 1 design. Result: **PASS**, no violations to justify.*

| # | Principle | How this plan complies |
|---|---|---|
| I | Disk is truth, model is a draft | Every record is a file. Model repairs are proposals that need an explicit decision. Old bytes are retained on disk and verified by hash |
| II | Human checkpoint | Source adoption, repairs, holds and unknown-impact rulings are GM decisions with a required reviewer. Impact computation is deterministic (no model). A proposal never feeds another model call |
| III | Retrieval/render separated | `rebase propose` renders only from impact records already computed by a separate deterministic step. `test_retrieve_render_isolation` stays green |
| IV | Verbatim/traceability | Repairs carry their evidence (the diff of the corrected chapter). Holds are additive markers, never rewrites. Corrected summaries are untouched |
| V | One seam per boundary | Model calls go through `campaignlib` via the existing delta invoker. Git access sits in one module (`delta/custody_store.py`) |
| VI | CLI is the engine | All logic lives in `delta rebase *`; routes shell out through `build_delta_argv` |
| VII | Extract once | Claims extraction caching is reused by input digest. Only changed or repaired chunks re-extract |
| VIII | State discoverable | `rebase/<id>/` records, `delta run status` and `rebase show` expose every stage |
| IX | UI mechanizes | The page steps through inspect → review → decide → publish. Judgment stays with the GM, and every step is a CLI call writing files |
| X | Explicit selection | `--source` is required and has no "all". The UI preselects nothing, and an empty selection is refused at the route and the CLI |
| XI | Bidirectional parity | GM ruling 2026-11-09: CLI + UI in this feature. Every new leaf has a route |
| XII | One spelling | Reuses `--source`, `--plan`, `--reviewer`, `--decision`, `--backend/--model`, `--force` and the exit-code vocabulary. `hold` is added to the shared `DECISIONS` tuple, not to one leaf |
| XIII | Migration out of band | No breaking change. New files plus optional fields whose default is omitted from canonical digests, pinned by a test (R10). No migration CLI. The operator runbook ships in `docs/cli/` |

**Post-design re-check**: still PASS. The one tension is R6's NPC carry rule, which relaxes a staleness check. It is bounded: only for a recorded rebind, and only when the NPC projection is byte-equal. Tests cover the negative case (any NPC-relevant change → stale).

## Project Structure

### Documentation (this feature)

```text
specs/040-source-custody-rebase/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R10 decisions
├── data-model.md
├── quickstart.md
├── contracts/cli.md
├── contracts/http.md
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
pipelines/summary_native/
├── delta/
│   ├── custody_store.py     NEW  content-addressed snapshot store + providers (snapshot, git, file)
│   ├── rebase_inspect.py    NEW  chain-aware stale-pin report (uses baseline._custody_rows)
│   ├── rebase_impact.py     NEW  entry diff, citation/annotation impact, unknown members, follow-ups
│   ├── rebase.py            NEW  prepare (plan kind=rebase), repair, decisions + validation, candidate build
│   ├── rebind.py            NEW  plan rebind, edit re-application, invalidation, rebind record
│   ├── cli_rebase.py        NEW  handlers registered into DELTA_HANDLERS
│   ├── cli.py               EDIT add leaves; `hold` in DECISIONS; rebase/rebind flags
│   ├── plan.py              EDIT optional kind/rebase_id; digest omits defaults
│   ├── lineage.py           EDIT optional `rebase` block; digest-stable
│   ├── grounding_candidates.py EDIT stage gap-labelled range for kind=rebase; lineage rebase block
│   ├── grounding_edits.py   EDIT hold marker application; gm-origin repairs
│   ├── review_binding.py    EDIT NPC carry rule via rebind record
│   └── receipt.py           EDIT rebase receipt fields
├── claims/selection.py      EDIT actionable CLAIMS_SOURCE_STALE message
server/routers/summary_native_delta.py   EDIT /rebase routes + /plans/{id}/rebind
frontend/src/views/grounding/SourceRebase.vue (+ .test.ts)   NEW
frontend/src/router.ts                    EDIT route grounding-rebase
docs/cli/source_custody_rebase_howto.md   NEW runbook (FR-020); docs/README.md + CLAUDE.md table row
tests/_rebase_fixture.py, tests/test_rebase_*.py   NEW
```

**Structure Decision**: The feature extends the existing `summary_native delta` package and its router/page family. No new top-level package.

## Delivery phases (input to /speckit-tasks)

1. **Foundation.** Plan/lineage optional fields with digest-stability tests; the custody store and providers; the actionable `CLAIMS_SOURCE_STALE`; the fixture.
2. **US1 (P1).** Inspect, prepare and impact; repair, propose, `hold` and decide, with semantic-change refusal; `rebase show`.
3. **US2 (P1).** Candidate build and gap-labelled staging through the existing gates to a new generation; rebind with NPC carry; the end-to-end ch6 resume.
4. **US3 (P2).** Stale-boundary tests for each bound input; interrupted-apply recovery and idempotent retry.
5. **Parity and docs.** Routes, the page with Vitest, the runbook, and doc index rows.

Implementation is delegated per phase to Sonnet subagents. Opus reviews between phases. One code-review pass at the end, with leftover findings filed as GitHub issues.

## Complexity Tracking

No constitution violations; nothing to justify.
