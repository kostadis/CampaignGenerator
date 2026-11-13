# Implementation Plan: Review Card Contract

**Branch**: `043-review-card-contract` | **Date**: 2026-11-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/043-review-card-contract/spec.md` (#643 slice 1 and #655, under #618)

## Summary

CampaignGenerator takes ownership of both ends of the review-page interface.

**New module.** `pipelines/summary_native/review/cards.py` builds a **card packet** from an NPC review's undecided items, and stores it immutably in the review at `packets/<packetId>.json`. The id is content-addressed (R1). The module also applies a page's **decisions file** against that stored packet. It:

- refuses any contract violation outright (R7);
- expands each card verdict into one decision per member, through one expansion function that `review noise decide` now also uses (R3);
- maps verdicts to dispositions in one table (R4);
- diffs against the store, so a re-save is a no-op or a listed supersede (R5);
- re-checks sign-off drafts and custody per card (R7);
- produces a plan, and records exactly that plan when `--write --plan-sha256` is given (R8);
- submits in card-aligned batches, with structured partial-save reporting (R9).

**Provenance** rides in the request id, so the store's on-disk shape is unchanged (R6).

**The two commands** are `review cards export` and `review cards decide`.

**#655.** `_validate_action_decision` declares pairs for every action the code produces, and fails closed on any other (R4).

**Publication.** The packet and decisions shapes are published as JSON Schemas generated from strict models, with golden fixtures (R11).

**Web face.** Two thin routes and a "Card packet" fieldset in `ReviewLauncher.vue` (R13).

**mytools** (a separate pull request):

- The NPC builder and reader become shims over the two commands.
- The Codex `review-page` fork is merged into one `review-artifact` kit, linked into both agents' trees, with Codex's local save and serving kept (R12).

## Technical Context

**Language/Version**: Python 3.14 (`~/.venv`; pyproject `>=3.10`). Vue 3 and TypeScript for the launcher.

**Primary Dependencies**: stdlib and pydantic, both already used, for the models; schemas come from `model_json_schema()`. `jsonschema` is added to the `test` extra only. It is already installed (4.26.0) but undeclared. There is no new runtime dependency.

**Storage**: the existing file review store under `docs/reviews/<review>/`. The new `packets/` directory is written through the existing journaled transaction under `authority_lock`. Decisions are ordinary `DecisionEvent`s via `save_decisions`.

**Testing**:

- pytest:
  - new `tests/test_summary_native_review_cards.py` (US1–US3 acceptance, scale);
  - new `tests/test_summary_native_review_cards_contract.py` (US4: schemas, goldens, version, text);
  - new `tests/test_summary_native_review_action_table.py` (#655, SC-004);
  - extended: noise CLI, delegated, routes and no-LLM suites;
  - fixtures: `tests/_custody_fixture.py` and new `tests/fixtures/review_cards/`.
- Vitest: `ReviewLauncher.test.ts`.
- mytools: kit pytest, plus `check-skill-sync.sh` and `test-codex-links.sh`.

**Target Platform**: Linux CLI and the local FastAPI app. The kit pages run in a Claude artifact or are served locally by Codex.

**Project Type**: a CLI pipeline with a thin web face, plus an external skill kit.

**Performance Goals**: SC-007, export and full decide under 60 s each for about 800 items. Single snapshot read; one draft hash per NPC; ⌈n/100⌉ transactions (R14).

**Constraints**:

- No model call. The review package is already AST-guarded.
- No on-disk shape change.
- No write to `~/storm-giant/stormgiants`.
- The GM's uncommitted mytools edits are never touched (R12).

**Scale/Scope**: about 800 items, about 165 NPCs and noise classes of up to several hundred members per review. Nine Codex skills and about 15 Claude skill references to the kits.

## Constitution Check

*GATE: checked before Phase 0 and re-checked after Phase 1.*

| Principle | Status | How |
|---|---|---|
| I. Disk is truth | ✅ | The packet is a file in the review. Decide re-reads it and the live store every time. Echoes in the decisions file are compared, never trusted (R10). |
| II. Human checkpoint | ✅ | This is the feature's purpose. Every recorded decision traces to an explicit GM card verdict. Unmarked stays unmarked, and the packet has no pre-filled verdict (FR-004). The plan is shown, and `--write` must present its hash (R8). Scope, identity and expansion are computed by CampaignGenerator code, not by a page or an agent. No model is involved. |
| III. Retrieval/render separation | ✅ n/a | No retrieval or render calls. |
| IV. Verbatim is sacred | ✅ | A sign-off is recorded only for the exact draft bytes the page showed: echo equals packet equals the current file (R7, FR-014). |
| V. One seam per boundary | ✅ | One expansion function (R3). One verdict-to-disposition map and one action table (R4). The noise membership rule is reused, not copied. The kit reaches the store only through the two commands (FR-020). |
| VI. CLI is the engine | ✅ | Both routes run a fixed argv. The plan and the refusals are built only in the CLI. |
| VII. Extract once | ✅ n/a | |
| VIII. State discoverable | ✅ | Packets are listed in the review directory. Decisions name their packet via `request_id` (R6). A partial save reports exactly what was recorded (R9). |
| IX. UI mechanizes | ✅ | The launcher invokes export, plan and confirm. Deciding verdicts happens on the page or with the GM in chat. The decisions file stays on disk and is passed by path. |
| X. No silent "all" | ✅ | Decide records only explicitly marked cards. Export decides nothing: it is an offer, and an empty filter means "all undecided items offered", which records nothing. |
| XI. Every CLI capability has a face | ✅ | `cards export` (with its `--item` / `--action` filters, as two optional inputs) and `cards decide` (plan and write) are in `ReviewLauncher.vue` (R13). The GM chose a minimal face, and ruled on 2026-11-12 that the filter inputs ship in this feature. |
| XII. One spelling per option | ✅ | `--write` (dry run by default), `--reviewer`, `--plan-sha256` (as in `review migrate`), `--item` and `--decisions FILE\|-` are reused spellings. `--action` is new to `review` but matches the kit flag it replaces. |
| XIII. Breaking state changes migrate | ✅ no trigger | No existing file changes shape. `packets/` is a new optional directory. The stricter action table validates new writes only. Existing events are never re-validated. |

**Post-design re-check (after Phase 1)**: no violations.

## Project Structure

### Documentation (this feature)

```text
specs/043-review-card-contract/
├── spec.md
├── plan.md                 # this file
├── research.md             # R1–R15
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cards-cli.md                  # export / decide: args, codes, data, recorded decision
│   ├── card-files.md                 # packet + decisions shapes, rules for page authors
│   ├── cards-routes-and-launcher.md  # two routes, status mapping, launcher fieldset
│   └── kit.md                        # mytools kit after the feature; the NPC loop
├── checklists/requirements.md
└── tasks.md                # /speckit-tasks
```

### Source Code (CampaignGenerator)

```text
pipelines/summary_native/review/
├── cards.py          # NEW: models (packet, decisions, plan), build_packet, store/load packet,
│                     #      expand (shared), DISPOSITION_FOR, plan_decide, apply (batches)
├── schemas/          # NEW: card-packet.v1.schema.json, card-decisions.v1.schema.json (generated)
├── store.py          # _validate_action_decision: full table, fail closed (#655)
├── delegated.py      # plan_noise_class uses cards.expand; submit_decisions: structured partial
│                     #   detail, optional card-aligned batching
└── cli.py            # `review cards export|decide` nested subparser + text rendering

server/routers/review_routes.py            # two routes, status codes
frontend/src/components/ReviewLauncher.vue # "Card packet" fieldset
frontend/src/components/ReviewLauncher.test.ts
pyproject.toml                              # jsonschema in [test]; force-include schemas
docs/cli/summary_native_review.md           # cards export/decide, the page contract, #655 table

tests/
├── fixtures/review_cards/                  # NEW: golden packet + decisions files
├── test_summary_native_review_cards.py     # NEW
├── test_summary_native_review_cards_contract.py  # NEW
├── test_summary_native_review_action_table.py    # NEW
├── test_summary_native_review_noise_cli.py # extended: noise unchanged via shared expansion
├── test_summary_native_review_delegated.py # extended: structured partial detail
├── test_summary_native_review_routes.py    # extended: argv + status codes
└── test_summary_native_no_llm.py           # + explicit cards.py assertion
```

### Source Code (mytools, separate worktree and PR)

```text
dotfiles/shared/skills/_shared/review-artifact/   # canonical (moved from claude/skills/_shared/)
├── build_review.py      # + --save artifact|local
├── read_decisions.py    # + --in (Codex) mode, normalize(); + --npc mode; class expansion removed
├── npc_review_items.py  # shim over `review cards export`
├── serve_review.py      # moved from the Codex fork, unchanged
├── CONTRACT.md          # merged
└── tests/               # merged + shim/reader/local-save tests
dotfiles/claude/skills/_shared/review-artifact -> link
dotfiles/codex/skills/_shared/review-artifact  -> link
dotfiles/codex/skills/_shared/review-page/       # DELETED
dotfiles/skill-layout.json                       # manifests updated
dotfiles/codex/skills/**                         # review-page → review-artifact, --save local
```

**Structure Decision**: extend the existing `pipelines/summary_native/review` package with one new module. There is no new package. The mytools changes ship as their own PR alongside, as with spec 041.

## Phasing (for /speckit-tasks)

1. **Foundation.**
   - The #655 action table and its tests. Run the full suite immediately, and stop and ask on any failure (R4).
   - The `cards.py` models and generated schemas.
   - The shared `expand`, with `plan_noise_class` switched to it and the noise suite unchanged.
   - `submit_decisions`' structured partial detail.
2. **US1 (P1)**: `cards export` and `cards decide` (plan and write), card-aligned batching. Acceptance tests come first.
3. **US2 (P1)**: every whole-file and per-card refusal, each with a store-unchanged assertion.
4. **US3 (P2)**: diff and supersede, plus idempotent re-apply.
5. **US4 (P2)**: goldens, the schema-regeneration test, version refusal and plain-text carriage.
6. **US6 (P3)**: routes and the launcher fieldset.
7. **US5 (P3), mytools**: the kit merge, the shims, the Codex retirement and the layout manifests.
   - Branch from mytools `main` at `5c5e5d5` or later. The GM's formerly uncommitted edits landed there via mytools #114 (GM ruling, 2026-11-12), so the mytools checkout is clean and the vtt-spell-pass SKILL.md conflict (R12) is gone.
   - The US4 kit-side assertions (no store reads, escaping) land here.
8. **Polish**:
   - docs;
   - the full suite and the quickstart;
   - one code-review pass;
   - follow-up issues for the third latest-decision copy (R3) and slice 2.

## Complexity Tracking

No violations to justify.
