# Implementation Plan: NPC Review Noise Resolution

**Branch**: `041-npc-review-noise-resolution` | **Date**: 2026-11-12 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/041-npc-review-noise-resolution/spec.md` (issue #621, under #618)

## Summary

The summary_native NPC number/ordinal and status checks will resolve the noise they can prove on their own, and name exactly what they object to. A new pure module, `pipelines/summary_native/noise.py`, provides:

- sentence-scoped citation binding;
- one tokenizer that handles comma-grouped numbers, spelled-out numbers and ordinals, and recognises chapter/scene labels;
- two reviewed data tables: ordinal idioms and status synonyms;
- detection of not-established sentences;
- one classifier that sorts every examined occurrence into exactly one of supported, a noise class, or a GM-facing finding.

Each noise occurrence becomes its own review item with a single legacy code `noise-<class>`. That makes the existing `review policy` the standing auto-approve with no change.

A new `review noise` / `review noise decide` CLI gives the GM one batch verdict per class (Q1 = B), written as one ordinary decision per occurrence through the existing validated decision path. The review routes expose it as a UI face. The shared review-artifact kit in mytools renders it as one card per class (see the GM ruling needed under Constitution XI).

## Technical Context

**Language/Version**: Python 3.12 (repo standard; `~/.venvs/main`)

**Primary Dependencies**: stdlib `re`; PyYAML (already a dependency) for the two data tables; the existing pydantic review models. No new dependency.

**Storage**: the existing review store under the campaign (`review` events and items). Two new YAML data files in `pipelines/summary_native/data/`.

**Testing**: pytest (`tests/`). New `tests/test_summary_native_noise.py` and `tests/test_summary_native_review_noise_cli.py`; extensions to the adapter, npc_verify and no-LLM guard tests.

**Target Platform**: Linux CLI plus the FastAPI review routes

**Project Type**: CLI pipeline with a thin web face

**Performance Goals**: classification adds linear work per draft line. A 177-draft review should verify in the same order of time as today (seconds).

**Constraints**: deterministic, no model call (FR-018), AST-guarded; never infer a GM verdict; no silent resolution.

**Scale/Scope**: about 780 review items per large campaign build; six noise classes; two checks.

## Constitution Check

*GATE: checked before Phase 0 and re-checked after Phase 1.*

| Principle | Status | How |
|---|---|---|
| I. Disk is truth, model is a draft | ✅ | No model involved. Noise records are derived and re-derivable from draft and evidence bytes. |
| II. Human checkpoint | ✅ | Classification removes *reading*, not *deciding*. Every noise occurrence needs a GM verdict: a class batch card or a GM-authored standing policy. Unmarked stays unmarked (FR-016, FR-017). |
| III. Retrieval/render separation | ✅ n/a | No retrieval or render calls. |
| IV. Verbatim is sacred | ✅ | The checks get *better* at traceability. A true positive per class boundary is required (FR-019, SC-004). Synonyms come only from a reviewed table, so there is no fuzzy support. |
| V. One seam per boundary | ✅ | One `noise.py` serves both checks (research R1). |
| VI. CLI is the engine | ✅ | `review noise` is CLI-first. Routes shell out. |
| VIII. State discoverable | ✅ | `review noise --json` plus the `verify.md` "Classified noise" section with accounting (SC-005). |
| IX. UI mechanizes | ✅ | The UI only invokes `noise` / `noise decide`. |
| X. No silent "all" | ✅ | `--class` is required and there is no all-classes form. An empty class refuses. |
| XI. Every CLI capability has a face | ⚠️ **GM ruling needed** | The in-repo face (`review_routes.py`) is planned. The page the GM actually uses is the mytools review-artifact kit (#616). This plan includes the kit change (render the class card, expand the class verdict on read-back) as tasks. **If the GM rules it out of scope, record the ruling here and file a follow-up issue.** |
| XII. One spelling per option | ✅ | Reuses `--reviewer`, `--note`, `--write`, `--json` and the dry-run default exactly as `carry`/`policy` do. |
| XIII. Breaking state changes migrate | ✅ no trigger | Additive only: a new `FindingCategory` member, new legacy codes and new diagnostic detail keys. Existing reviews keep their items and decisions (spec Edge Cases). No migration document is needed. |

**Post-design re-check (after Phase 1)**: unchanged. XI is still awaiting the GM's ruling. No other violations, so Complexity Tracking stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/041-npc-review-noise-resolution/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R13
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli-review-noise.md
│   └── noise-diagnostic.md
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
pipelines/summary_native/
├── noise.py                         # NEW: sentences, tokens, labels, idioms, synonyms, negation, classify, accounting
├── data/ordinal_idioms.yaml         # NEW: reviewed table
├── data/status_synonyms.yaml        # NEW: reviewed table
├── npc_verify.py                    # check_status_words → noise.classify_status; verify.md "Classified noise" section
└── review/
    ├── models.py                    # + FindingCategory.CLASSIFIED_NOISE
    ├── verification.py              # number check → noise.classify_numbers; noise items; sentence/token details
    ├── delegated.py                 # + plan_noise_class (sibling of plan_policy)
    └── cli.py                       # + review noise / review noise decide

server/routers/review_routes.py      # + GET noise, POST noise/decide

docs/cli/summary_native_review.md    # + noise verbs, classes, policy keys
docs/cli/npc_dossiers_howto.md       # + "reading classified noise" note

tests/
├── test_summary_native_noise.py                 # NEW: unit + #617/#618 fixtures
├── test_summary_native_review_noise_cli.py      # NEW: CLI contract + refusals
├── test_summary_native_review_verification_adapter.py  # extended
├── test_summary_native_npc_verify.py            # extended
└── test_summary_native_no_llm.py                # + "noise" in the guarded set

# cross-repo (pending the GM's XI ruling)
~/src/mytools/dotfiles/claude/skills/_shared/review-artifact/
├── npc_review_items.py              # one card per noise class
└── read_decisions.py                # expand a class verdict to member item ids
```

**Structure Decision**: a single-project CLI layout, extending the existing `pipelines/summary_native` package and its review subpackage. No new package.

## Phasing (for /speckit-tasks)

1. **Foundation**: `noise.py` (sentence split, tokenizer, labels, the data tables and their loaders, negation), with unit tests. US1, US2 and US3 all depend on it.
2. **US1 + US2, number check**: rewire `_deterministic_semantic_advisories` and `same-citation-inconsistency` onto noise. Noise items. Sentence and token details and messages.
3. **US3, status check**: rewire `check_status_words`. Synonym and negation classes. The `verify.md` section.
4. **US4, audit and decide**: `FindingCategory.CLASSIFIED_NOISE`; the `review noise` and `noise decide` CLI; policy-compatibility test; routes.
5. **Kit face** (mytools, pending the XI ruling).
6. **Docs and polish**: the two docs, the no-LLM guard, the full suite.

## Complexity Tracking

No violations to justify.
