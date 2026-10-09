# Implementation Plan: Chunked, Code-Checked Party and Planning Documents

**Branch**: `worktree-034-chunked-party-planning` | **Date**: 2026-10-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/034-chunked-party-planning/spec.md`

## Summary

party and planning move off spec 031's one-shot path onto spec 033's chunked build. One cached extraction now feeds all four grounding documents. The model writes only prose. Code and the GM's records make every precision decision.

1. **Extraction gains a party subject** (research R1). Party bullets name their subject (`**Daz**` or `**Party**`), and a level is its own `[LEVEL]` row that code confirms against the cited text, so spell levels can't pass. Every chunk is re-extracted once, because the prompt is in the cache key.
2. **party.**
   - **Code** attributes each party note to a player character, a companion or "unattributed", by exact registry/roster name (R2). It writes each character's level line from the latest confirmed level row (R3) and builds `reference/party.md`.
   - **The model** writes one call per character (that character's notes, sheet and backstory only), plus Party Overview and Party Dynamics, within budgets.
3. **planning.**
   - **Threat Tracker:** built by code from `planning.yaml`.
   - **NPC Dossiers:** from published dossiers, through world_state's Key NPCs machinery. It reads Identity, Motivations, Last Observed State and Relationships, never Secrets. It refuses on a missing dossier unless `--fallback-npc-lines` is given.
   - **Faction States:** selected by code and written by the model per faction.
   - **Active Plots:** in two layers. First the open threads of the **GM's thread registry**, which are attached, judged open or closed, and ordered by code. Then every unratified thread note, verbatim, labelled as not yet ruled on.
   - **DM Notes:** model-written and labelled as suggestions.
4. **Thread identity** comes from the GM's registry (GM decision 2026-10-08, after the survey: approach 9 retargeted, F8 "identity is the precision decision"; R4–R7).
   - A new model step, `summary_native thread-propose`, groups the unattached checked thread notes into proposals.
   - Code checks the proposals: real members, no double claims, valid targets.
   - The GM ratifies, splits or rejects them on the existing Threads page.
   - Ratification stores the member names as aliases, so later runs attach by exact match with no model involved.
5. **Arc-score candidates** (R10) are model-listed and code-checked: each must cite a checked note and quote its trigger verbatim, and none may state a value.
6. **Shared with spec 033:** reading contract (per document), reference files, annotation (never a rewrite), run records, backends, refusals.
7. **The one-shot path is deleted** (R11). Its flags are refused with replacement messages.

## Technical Context

**Language/Version**: Python 3.12; TypeScript + Vue 3 for the pages

**Primary Dependencies** (existing only):
- PyYAML, Pydantic, FastAPI.
- `campaignlib`: `client_from_args`, `add_backend_args`, `registry`, `players_config`, `party_config`, `planning_config`, `util.atomic_write_text`.
- Spec 033 modules: `notes`, `state_sections`, `key_npcs`, `annotate`, `freshness`, `synth.run_state_synth`.
- Spec 032: `npc_check`.
- The thread registry's `norm_title`, `match_thread`, `load_registry` and `check_registry`. These move from `pipelines/grounding/thread_registry.py` to `campaignlib/thread_registry.py`, and the CLI imports them back.

**Storage**: Files only. Additions under `<range>/state/` are listed in `data-model.md`. The registry and proposals file are the existing ones.

**Testing**: pytest with the fake model client.
- **New:** `tests/test_summary_native_{party,planning,threads}.py` and `tests/test_thread_registry_groups.py`.
- **Extended:**
  - `test_summary_native_{notes,cli,routes,synth,config_defaults,no_llm}.py`;
  - `test_state_docs_no_secrets.py` and `test_annotate_never_rewrites.py`;
  - `test_thread_registry.py`, plus the Threads route tests.
- **Playwright:** the Threads "Propose groupings" step and the group ratify editor.

**Target Platform**: Linux, single-user CLI plus FastAPI/Vue; Sparks on the LAN for extraction; `claude -p` for prose and proposals

**Project Type**: CLI pipeline plus web UI (existing layout)

**Performance Goals**:
- **SC-007:** party + planning from cached notes in under 10 min, with no extraction calls.
- **`thread-propose`:** OOTA's ~560 notes in one or two calls of about 150K characters, a few minutes.
- **Code steps:** attach, check, attribution and sections in under 10 s.

**Constraints**:
- Zero model calls in `party_notes`, `thread_attach`, `thread_check`, `arc_check` and the extended `key_npcs`.
- No Secrets text in any prompt or output.
- No tool writes to `docs/`, except ratification writing the registry (a GM act).
- One build path per document.

**Scale/Scope** (OOTA):
- 4 player characters;
- ~430 party notes;
- ~560 thread notes;
- 0 configured arc scores, NPCs or factions in `planning.yaml` (S5 uses a scratch config);
- ~30 selected NPCs;
- tens of faction subjects (capped at 20 written).

## Constitution Check

*GATE: checked before Phase 0 and re-checked after Phase 1 design.*

| # | Principle | How this plan complies | Status |
|---|---|---|---|
| I | Disk is truth, model is a draft | Every output is a draft under `state/`, and promotion is manual. Proposals are drafts on disk: pending until a GM ruling, and never read as identity | ✅ |
| II | Human checkpoint | Removed from the human: prose, candidate arc events (checked, GM judges), and candidate thread groupings (checked, GM ratifies). Identity (registry), attribution (exact roster/registry match), ordering (latest activity), open/closed (registry status or latest tag) and scope (selection, caps) are all code or GM. **Model → model:** none unchecked. Extraction → prose is gated by 033's check. Proposals feed no model: they reach a document only after ratification, as aliases matched by code. No model output feeds another model call: each `thread-propose` batch sees checked notes and ratified threads only | ✅ |
| III | Retrieval / render separation | No retrieval calls. Attachment and selection are deterministic functions, separate from render calls | ✅ |
| IV | Verbatim is sacred | Notes, unratified thread notes, failed-check substitutions and annotations are verbatim. Level rows and arc triggers are verified against source text. Prose claims derivation: traceability is enforced and non-verbatim quotes are annotated | ✅ |
| V | One seam per boundary | Model calls go through `client_from_args`. Thread identity is reached through `campaignlib/thread_registry.py`, moved there so the summary-native package does not import a CLI. Registry and roster go through `campaignlib` | ✅ |
| VI | CLI is engine | `synth`, `thread-propose` and `thread_registry ratify|rule` hold all the logic. Routes build argv | ✅ |
| VII | Extract once, synthesize deliberately | One extraction feeds four documents. Grouping is its own narrow pass, not folded into extraction. The party-grammar change deepens an existing section rather than consolidating passes | ✅ |
| VIII | State is discoverable | `attach.json`, `propose_report.md`, `threads_report.md`, `party_report.md`, `arc_report.md`, run records and the proposals file are all on disk. `/state` reads only files | ✅ |
| IX | UI mechanizes | The pages run steps and show results. Ratifying is a GM edit of a plan, with no one-click accept. Review and promotion stay in files and chat | ✅ |
| X | No silent "all" | A range is required for `synth` and `thread-propose`. The faction cap is a reported code cut, not a silent drop. `thread-propose` acts on the unattached notes of the chosen range | ✅ |
| XI | Bidirectional parity | Every flag has a route parameter (`contracts/http.md`), and the Threads page gains propose and group-ratify. `--fallback-npc-lines` stays per-run-only by the 2026-10-07 ruling. Config-only by earlier rulings: `--out-root --registry --canon --npc-root` | ✅ |
| XII | One spelling per option | Reused spellings: `--since --until --force --dump-only --max-tokens --name --recent-chapters --recurring-min --fallback-npc-lines --party-config --planning-config`, the backend flags, and the registry's `--key`-style verbs alongside `--norm`. New: `--max-input-chars`. New config keys `party_budgets` / `planning_budgets` sit beside `budgets`, with defaults declared once in `schema.py` and covered by the config-defaults test | ✅ |
| XIII | Breaking state migrates out of band | **No stored state changes shape.** The registry schema is unchanged; an optional `cite` on log rows is additive. Group proposals are a new entry shape in the proposals file, and existing entries are untouched. The notes cache is invalidated by its own key (a cache, not state). Old one-shot drafts are plain files. Retired flags are refused with the replacement named | ✅ |

**Guard tests** (new or extended):
- `test_summary_native_no_llm.py`: `party_notes`, `thread_attach`, `thread_check` and `arc_check` join `GUARDED`.
- `test_state_docs_no_secrets.py`: covers `planning_view` and the planning draft and prompts.
- `test_annotate_never_rewrites.py`: covers party and planning.
- `test_thread_registry_groups.py`: no code path writes the registry except `ratify` / `rule` / `log` / `set-status` / `alias`. `thread-propose` never opens the registry for writing.
- `test_summary_native_config_defaults.py`: the new budget blocks and defaults.

**Gate result: PASS** before Phase 0. **Re-check after Phase 1: PASS.** The design kept identity with the GM (registry), and attribution, ordering, open/closed and scope with code. The one new model step, `thread-propose`, produces candidates that feed nothing until the GM ratifies them.

## Project Structure

### Documentation (this feature)

```text
specs/034-chunked-party-planning/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R16
├── data-model.md
├── quickstart.md        # S0–S7 on the OOTA copy
├── contracts/
│   ├── cli.md           # extract (prompt), synth party|planning, thread-propose, thread_registry group verbs
│   └── http.md          # routes + pages
├── checklists/requirements.md
└── tasks.md             # Phase 2 ($speckit-tasks)
```

### Source Code (repository root)

```text
campaignlib/
└── thread_registry.py        # NEW: norm_title, match_thread, load_registry, check_registry (moved, single seam)

pipelines/summary_native/
├── schema.py                 # + DEFAULT_PARTY_BUDGETS, DEFAULT_PLANNING_BUDGETS, DEFAULT_MAX_FACTIONS,
│                             #   DEFAULT_THREAD_PROPOSE_MAX_INPUT_CHARS, PARTY_SUBJECT, LEVEL tag; STATE_DOCS = DOCS
├── notes.py                  # party subject + [LEVEL] row grammar and checks; note ids (R6)
├── party_notes.py            # NEW, deterministic: attribution, level lines, reference/party.md, party_report.md
├── thread_attach.py          # NEW, deterministic: attach notes to ratified threads, open/closed, order, threads_report.md
├── thread_check.py           # NEW, deterministic: check model groupings, singles fallback, proposals merge
├── thread_propose.py         # NEW, model step: batched grouping calls, record
├── arc_check.py              # NEW, deterministic: arc candidate checks
├── key_npcs.py               # + planning_view (4 sections, no Secrets), planning entry check/assembly
├── state_sections.py         # + per-doc reading contract, PROSE_SECTIONS/BRIEFS for party & planning, threat table,
│                             #   Active Plots assembly, faction selection
├── annotate.py               # + SKIP_SECTIONS for planning; PC-in-NPC scope
├── synth.py                  # one-shot run_synth body DELETED; run_state_synth handles all four docs
├── context.py                # prompt-block renderers DELETED; structured party/planning config loaders kept
├── cli.py                    # synth flags (retired → refusals), thread-propose subcommand
└── prompts/
    ├── state.extract.system.md         # Party grammar (R1)
    ├── state.party.system.md           # NEW: character / overview / dynamics sections
    ├── state.planning.system.md        # NEW: faction, active-plot and DM-notes sections
    ├── state.planning_npcs.system.md   # NEW
    ├── state.arc.system.md             # NEW
    ├── state.thread_propose.system.md  # NEW
    ├── party.system.md, planning.system.md      # DELETED
    └── party.outline.yaml, planning.outline.yaml # kept (headings unchanged)

pipelines/grounding/thread_registry.py   # imports the moved helpers; ratify/rule --key; group derive_plan; split

server/
├── grounding_config_shared.py           # prose.party_budgets / planning_budgets (strict)
└── routers/
    ├── summary_native.py                # synth params for party/planning; /state, /drafts extended
    └── projections.py                   # /threads/run/group-propose, /threads/plan, ratify/rule by key

frontend/src/views/grounding/
├── SummaryNative.vue                    # party/planning use the chunked step component; Parts/upstream pickers removed
└── Threads.vue                          # Propose groupings step; group proposals; member-editing ratify

docs/cli/summary_native_howto.md          # party/planning builds, thread proposals, refusals, exit codes
docs/cli/state_projection_howto.md        # Threads page: group proposals from summary-native
docs/core/architecture.md                 # four documents, one build; thread identity

tests/
├── fixtures/summary_native/              # party/thread/registry/arc fixtures (R16)
├── test_summary_native_{party,planning,threads}.py, test_thread_registry_groups.py   # NEW
└── (extended as listed under Testing)
```

**Structure Decision**: extend `pipelines/summary_native` and its CLI, router and page, as specs 031–033 did. Thread identity reuses the state-projection thread registry, its verbs and its page rather than adding a second store (no split-brain). Only its pure helpers move to `campaignlib` so both packages reach them through one seam.

## Implementation order (for `/speckit-tasks`; Opus orchestrates, Sonnet implements per phase)

1. **Foundation:**
   - schema defaults;
   - the `campaignlib/thread_registry.py` move;
   - note ids;
   - the party grammar and checks in `notes.py` and the extraction prompt;
   - fixtures.
2. **US1 party:** `party_notes`, party prose calls, the reading contract per document, `reference/party.md`.
3. **US3 threads:** `thread_attach`, `thread_check`, `thread_propose` CLI, `thread_registry` group verbs.
4. **US2 planning:** threat table, planning NPC entries (`key_npcs`), factions, Active Plots layers, DM Notes.
5. **US4 arc candidates:** `arc_check` and the calls, wired into party and planning.
6. **US5 annotation:** extended to both documents, plus guards.
7. **US6 surfaces:**
   - one-shot deletion and refusals;
   - routes;
   - `SummaryNative.vue` and `Threads.vue`;
   - config;
   - Playwright tests.
8. **Polish:**
   - how-tos and architecture;
   - quickstart S0, run on main **before** step 7's deletion merges;
   - S1–S7 on the OOTA copy.

## Complexity Tracking

No constitution violations to justify.

## Follow-ups (outside this feature)

- **#530 (done):** campaign_state's thread sections read the thread registry (`thread_attach`, `active_plots_md` and a new `resolved_threads_md`), replacing the model reading the whole ledger. The registry digest is in its run record; an absent registry leaves the unratified pointer. The old `threads` route is removed.
- **Thread proposals:**
  - **#524:** a pending group spanning the range edge loses its out-of-range notes.
  - **#525 (done):** a ratified member left unattached by a removed alias is reported ("ratified but no longer attached (alias removed?)") and offered again as a pending single.
  - **#529 (done):** a split-off note that shares a ratified name attaches anyway. `ratify --key` records the left-out notes as the thread's `excluded_notes`; `thread_attach` honours them before the name; an alias carried only by a left-out member is refused; an excluded id found on no disk is reported, never removed.
- **#526:** the arc-score "states a value" check is an untuned regex. Tightened with a verdict table (`arc_value_check.md`); measuring it on real Out of the Abyss output is still open.
- **#527 (done):** subject-less prose in Party Overview and Dynamics now takes the `Party` subject and is stale-checked against the whole-party notes; it is not paired by the cross-section check.
- **#528 (done):** Annotate follows the document picker, and `GET /state` carries `budgets` for world_state, party and planning, shown in one panel.
- **kostadis/campaigns#385:** drops `parts: 0` from OOTA's `grounding.yaml`. Merge it before or with this feature.
- **#512:** incremental rebuild (extract cache across ranges). **#515:** a chunk missing a section passes the check. Both are inherited.
- The ensemble-fact harvest (`thread_registry propose --corpus`) stays for campaigns on the ensemble path; retire it when no campaign uses it.
