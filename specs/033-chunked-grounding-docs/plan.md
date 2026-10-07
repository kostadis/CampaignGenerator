# Implementation Plan: Chunked, Code-Checked Grounding Documents

**Branch**: `033-chunked-grounding-docs` (worktree branch `worktree-033-chunked-grounding-docs`) | **Date**: 2026-10-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/033-chunked-grounding-docs/spec.md`

## Summary

This feature turns the experiment's prototype (`experiments/20261007-chunked-state-docs/`, PRs #507 and #508) into `summary_native` commands. It replaces the one-shot draft path for world_state and campaign_state with four steps. Steps 1 and 3 run with no model call.

1. **`extract`** (model step: map). Reads the full summaries for the range in groups of whole chapters (≤ `chunk_chars`). One call per group writes notes in a fixed grammar. **Code checks every note:**
   - each citation resolves inside the group (a section's own heading text counts as its key);
   - each quote is verbatim;
   - each note carries its tag and format.

   Failures go to `drops.md` with a reason, and outlier chunks are flagged. Groups are cached by key and can be spread over several Spark endpoints sharing one queue (`--endpoints`). No audit list is ever sent.
2. **`synth world_state | campaign_state`** (changed). Builds from the checked notes in three parts:
   - **Code-owned sections, built by code:** the timeline (its own file), completed encounters, the NPC current-status table (registry identity, player characters excluded, Unknown never overriding a known status), the reference files, and the audit section from `audit.json`.
   - **Prose sections, from a model:** one prose call per section, from the notes code routed to it; world_state sections have word budgets, and quotation marks are reserved for words in the summaries.
   - **Key NPCs:** rendered from **published, verified dossiers**, reading only Identity and Last Observed State. The build **refuses by default** when a selected NPC has none, and `--fallback-npc-lines` writes a code-built line instead (GM ruling, 2026-10-07).
3. **`annotate`** (deterministic). Runs automatically at the end of `synth`. The detectors append later evidence under a line (`⚠ later:`, `ℹ since:`, `⚠ unverified:`). The only line they remove is a player character in an NPC section. **No model rewrites a document.**
4. **`audit`** (model step: judge). For each tracking item, code picks up to 3 candidate chapters and the model judges against only those. A SUPPORTED verdict must carry a citation and a verbatim span that code confirms.

The session-prep contract (the documents are an index; the summaries are the authority; prep ends with "Doc errors found") is specified in `contracts/session-prep.md` for the gm-assistant skill to adopt.

**Defaults** (research R7):
- extraction runs on the Sparks;
- prose runs on `claude-code` with `claude-sonnet-5-5` at medium effort;
- both are configurable per run and in `grounding.yaml`, and nothing checks for an API key.

## Technical Context

**Language/Version**: Python 3.12 (repo standard); TypeScript + Vue 3 for the page

**Primary Dependencies**:
- Existing only: PyYAML, Pydantic, FastAPI.
- `campaignlib`: `client_from_args`/`stream_api`/`add_backend_args`, `registry`, `players_config`, `util.atomic_write_text`.
- Spec 031's `pipelines/summary_native`: `corpus`, `select`, `freshness`, `resolve`, `schema`, `synth.check_outline`.
- Spec 032's `npc_check` (citation and quote primitives), `npc_chunked.make_chunks` (generalised), `npc_forms` (generic word list).

**Storage**: Files only. Everything under `<out_root>/chNNN-NNN/state/`; layout in `data-model.md`. The live `docs/` is never written by a tool.

**Testing**: pytest with a fake model client.
- **New unit tests:** `tests/test_summary_native_{notes,state_sections,key_npcs,annotate,audit,extract}.py`; route tests in `tests/test_summary_native_routes.py`.
- **Guard tests:** listed under the Constitution Check.
- **Fixtures:** `tests/fixtures/summary_native/` extended with a 4-chapter range, a stale fact, a mentioned-NPC status change, a published dossier with a Secrets canary, and a tracking file.
- **Playwright:** `frontend/e2e` for the page steps.

**Target Platform**: Linux, single-user local CLI and FastAPI server; Spark endpoints on the LAN

**Project Type**: CLI pipeline plus FastAPI/Vue web UI (existing repo layout)

**Performance Goals** (SC-007):
- **Full build** of a 67-chapter campaign in under 45 min on two Spark boxes plus hosted prose (experiment: extraction 30.5 min with the audit list inside, prose 308 s).
- **Prose-only rebuild** in under 10 min.
- **Code steps** (check, sections, annotate) in under 30 s for 67 chapters.

**Constraints**:
- Code-owned sections are byte-identical for identical notes, registry and roster.
- Zero model calls in `notes`, `state_sections`, `key_npcs`, `annotate` and `audit_select`.
- No Secrets text in any prompt or output.
- No writes under `docs/` (live), `docs/npcs/` or the 031 corpus files.
- No dual paths: world_state and campaign_state have one build path.

**Scale/Scope**:
- **OOTA:** 67 chapters, 2.46 MB of summaries, 60 groups, ~3,000–5,000 kept notes, 30 selected Key NPCs, 443 tracking items.
- **Largest prose input:** ~160K characters (threads), within one call.

## Constitution Check

*GATE: checked before Phase 0 and re-checked after Phase 1 design.*

| # | Principle | How this plan complies | Status |
|---|---|---|---|
| I | Disk is truth, model is a draft | The summaries, registry, `players.yaml`, published dossiers and track files are read-only inputs. Every output is a draft under `state/`, and promotion is manual (FR-028). Notes are drafts too: code checks them, they are cached on disk, and they are never treated as fact (annotations quote them *as evidence with citations*) | ✅ |
| II | Human checkpoint | Removed from the human: prose only (spec Context). Scope, identity, ordering and attribution are decided by code from the summaries (chunking, routing, timeline order, registry identity, Key NPCs selection, audit candidates). **Model → model:** extraction output reaches the prose step only after a code check, which is spec 032's chunked-drafting precedent (T062), accepted at #504. The checked notes and `drops.md` are on disk for the GM before any prose call. The GM reviews every draft before promotion, and the missing-dossier refusal keeps the dossier review gate (032) in force | ✅ |
| III | Retrieval / render separation | No retrieval calls. Audit candidate selection is a deterministic scorer in `audit_select.py`, separate from the judge call in `audit.py`. `test_retrieve_render_isolation.py` applies unchanged | ✅ |
| IV | Verbatim is sacred | Notes and reference files are verbatim. Quoted spans are verified (exactness where claimed); every line carries a resolving citation (traceability everywhere). Prose sections claim to be derived: traceability is enforced, and any non-verbatim quote is annotated `⚠ unverified:`. Annotations quote evidence verbatim. The audit's SUPPORTED requires a verbatim span | ✅ |
| V | One seam per boundary | Model calls go only through `client_from_args`/`stream_api`. The registry through `campaignlib.registry`, the roster through `campaignlib.players_config`, quote matching through `npc_check` (shared with `npc_verify`), and per-model DGX behaviour through `dgxlib` (via the backend). No new `anthropic` import | ✅ |
| VI | CLI is engine | The four commands carry all the logic. `server/routers/summary_native.py` only builds argv and streams | ✅ |
| VII | Extract once, synthesize deliberately | **This feature applies it.** One cached extraction feeds both documents, the audit is a separate narrow pass (not folded into extraction, which round 6 showed degrading), and each prose section is its own call | ✅ |
| VIII | State is discoverable | Every step's state is on disk: `notes/manifest.json` and `*.checked.json`, `drops.md`, `runs/*/record.json`, `audit/*.json`, the drafts, `annotations.md` and `npc_status_report.md`. `/state` reads only these | ✅ |
| IX | UI mechanizes | The page runs extract, synth, audit and annotate, and shows reports. Reviewing drafts, fixing sources (summaries, registry, dossiers) and promoting stay in files, the CLI and chat. There is no edit control for drafts or notes | ✅ |
| X | No silent "all" | A range is required: the CLI takes explicit `--since`/`--until` and the UI refuses without a range. Key NPCs selection uses 031's explicit rules, and the audit runs on the named track files | ✅ |
| XI | Bidirectional parity | Every run-shaping flag has a route parameter (`contracts/http.md`), including `--endpoints`, `--parallel`, `--fallback-npc-lines`, `--track-file`, `--candidates` and `--dry-run`; the page gains the four steps. **Config-only by ruling:** `--out-root --registry --canon` remain config-set (031 ruling, kostadis 2026-10-05), and so does `--npc-root` on `synth world_state` (032 ruling, 2026-10-06). `--fallback-npc-lines` is deliberately **per-run only and never persisted** (GM ruling 2026-10-07): the page checkbox resets on reload | ✅ |
| XII | One spelling per option | Reused spellings: `--backend --model --endpoint --claude-code-effort` (`add_backend_args`), `--endpoints` (as `facts_to_state` / `ensemble_batch`), `--track-file` (as `campaign_state`), `--chunk-chars` (as `npc-draft`), `--parallel` (concurrent requests per endpoint, as `extract_facts.py`; `/speckit-analyze` C1 caught an earlier draft that coined `--workers` for the same meaning), `--dry-run` (as the ten existing CLIs that print what would happen and write nothing), and `--since --until --name --recent-chapters --recurring-min --max-tokens --dump-only --force` (031). New, with no existing sibling meaning: `--fallback-npc-lines`, `--candidates`. New defaults are declared once in `schema.py` (`DEFAULT_EXTRACT_*`, `DEFAULT_PROSE_*`, `DEFAULT_WORLD_BUDGETS`, `DEFAULT_AUDIT_CANDIDATES`), surfaced through `SummaryNativeRun.extract` / `.prose` in `server/grounding_config_shared.py`, and covered by `tests/test_summary_native_config_defaults.py` | ✅ |
| XIII | Breaking state migrates out of band | **No state changes shape.** `state/` is new; `grounding.yaml summary_native.extract` / `.prose` are new blocks with defaults; the old one-shot drafts are plain files that the next `--force` replaces. The CLI change is a refusal with the replacement command (`synth … --parts` / `--audit` for these two docs), not a silent ignore. No migration CLI or `migration.md` is needed. The new promoted files (`docs/reference/`, `docs/canon_events_timeline.md`) are additive | ✅ |

**Guard tests** (new or extended):
- **`tests/test_summary_native_no_llm.py`:** add `notes`, `state_sections`, `key_npcs`, `annotate` and `audit_select` to `GUARDED`. Assert `extract`, `synth` and `audit` are the model steps.
- **`tests/test_state_docs_no_secrets.py`:** the Secrets canary reaches no prompt and no output; `key_npcs.published_view` has no path to `## Secrets`.
- **`tests/test_annotate_never_rewrites.py`:** for every non-removed line, the annotated document's line text equals the pre-annotation text.
- **`tests/test_summary_native_config_defaults.py`:** extended for the new blocks; no default literal in the router.
- **`tests/test_no_credential_gate.py`:** unchanged and must stay green.

**Gate result: PASS** before Phase 0. **Re-check after Phase 1: PASS.** The design kept every precision decision in code. The only new model-to-model edge (extraction to prose) has a code check between, as in 032. The missing-dossier ruling tightened II, because no NPC line reaches a document without either a published dossier or an explicit per-run GM choice.

## Project Structure

### Documentation (this feature)

```text
specs/033-chunked-grounding-docs/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R14 decisions
├── data-model.md        # layout, entities, states
├── quickstart.md        # S1–S7 validation on an OOTA copy
├── contracts/
│   ├── cli.md           # extract | synth (changed) | annotate | audit
│   ├── http.md          # routes + page
│   └── session-prep.md  # the contract gm-session-prep adopts
├── checklists/requirements.md
└── tasks.md             # Phase 2 ($speckit-tasks)
```

### Source Code (repository root)

```text
pipelines/summary_native/
├── schema.py            # + DEFAULT_EXTRACT_*, DEFAULT_PROSE_*, DEFAULT_WORLD_BUDGETS, DEFAULT_AUDIT_CANDIDATES, citation targets, note grammar
├── cli.py               # + extract, annotate, audit; synth world/campaign_state rewired; refusals for --parts/--audit
├── notes.py             # NEW, deterministic: chunking (via generalised make_chunks), note grammar, code check, drops, cache keys, routing
├── extract.py           # NEW, model step: per-chunk calls, multi-endpoint queue + preflight, record
├── state_sections.py    # NEW, deterministic: timeline, completed, NPC status table (registry identity), reference files, reading contract, audit rendering
├── key_npcs.py          # NEW, deterministic: published-dossier view (no Secrets), selection, line checks, fallback lines, missing-dossier refusal
├── annotate.py          # NEW, deterministic: detectors + annotation writer + report
├── audit_select.py      # NEW, deterministic: track items, candidate chapters, verdict check
├── audit.py             # NEW, model step: judge calls
├── synth.py             # model step: + chunked path for world_state/campaign_state (prose + Key NPCs calls); one-shot kept for party/planning
├── npc_chunked.py       # make_chunks generalised to (number, text) sequences
└── prompts/
    ├── state.extract.system.md   # NEW (from experiment map.system.md, audit removed)
    ├── state.prose.system.md     # NEW (from reduce: campaign_state sections, with the quotation rule)
    ├── state.prose_world.system.md # NEW (from reduce_world: budgeted world_state sections, with the quotation rule)
    ├── state.npc_lines.system.md # NEW
    └── state.audit.system.md     # NEW

server/
├── grounding_config_shared.py   # SummaryNativeRun + extract/prose blocks (strict)
└── routers/summary_native.py    # + /run/extract, /run/annotate/{doc}, /run/audit; synth params; /state, /drafts extended

frontend/src/views/grounding/SummaryNative.vue   # + Extract, Audit, Annotate steps; fallback checkbox; reports

docs/cli/summary_native_howto.md                 # + chunked build, refusals, session-prep contract
docs/core/architecture.md                        # + state/ layout and the four steps

tests/
├── fixtures/summary_native/                     # extended (see Testing)
├── test_summary_native_{notes,extract,state_sections,key_npcs,annotate,audit}.py   # NEW
├── test_state_docs_no_secrets.py, test_annotate_never_rewrites.py                   # NEW guards
└── test_summary_native_{no_llm,cli,routes,synth,config_defaults}.py                # extended
```

**Structure Decision**: extend the existing `pipelines/summary_native` package and its CLI, router and page, matching specs 031 and 032. The experiment's prototype modules map one-to-one onto the new modules (`chunked_state.py` → `notes` + `extract` + `state_sections`; `npcs_from_dossiers.py` → `key_npcs`; `annotate.py`/`fixpass.py` detectors → `annotate`), with the model fixer dropped.

## Complexity Tracking

No constitution violations to justify.

## Follow-ups (outside this feature)

- **gm-assistant:** adopt `contracts/session-prep.md` in `gm-session-prep` (file an issue in that repo).
- **kostadis/campaigns#379:** add the `Edvaldo` registry alias. **#506:** the Manshoon dossier, and npc-verify's blindness to whether a citation supports its claim. Both were surfaced by this work and are fixed at their source.
