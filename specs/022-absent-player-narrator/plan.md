# Implementation Plan: A narrator must have been in the scene

**Branch**: `022-absent-player-narrator` | **Date**: 2026-09-06 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/022-absent-player-narrator/spec.md`

## Summary

`sd_plan` chooses a scene's first-person narrator from the whole campaign roster using scene *titles* only, under a prompt that rewards rotating narrators across characters. This plan replaces the eligibility half of that choice with two deterministic filters computed before the model call — session attendance from the VTT's player labels, and per-scene presence from the extraction's character labels — and hands the residue, a scene no eligible character can cover, back to the GM as three plans differing only in that scene's treatment.

Attendance also reaches Pass 5: `sd_narrate`'s roster block gains a marker for a character nobody voiced, so the renderer knows their dialogue would be invented while staying grounded enough to narrate the GM's placement of them.

No new model call is added for the filters. One additional small call is added only when a scene is uncoverable.

## Technical Context

**Language/Version**: Python ≥3.9 (`pyproject.toml`), Vue 3 + TypeScript for the editor surface

**Primary Dependencies**: existing only — `pydantic` (`campaignlib/players_config.py`), `pyyaml`, FastAPI (`server/`). No new dependency.

**Storage**: files on disk. Reads the session VTT, `config/players.yaml`, `scene_extractions/`. Writes `plan.md` (or `plan.a|b|c.md`) plus a new eligibility record, all under the session's `narration_dir`.

**Testing**: `pytest` (`tests/`). Every filter is a pure function over strings and is testable with no API key and no network.

**Target Platform**: Linux CLI + local FastAPI server

**Project Type**: CLI engine with a web face (Constitution VI/XI)

**Performance Goals**: filters add no model call and no measurable wall-clock cost; the whole eligibility pass is regex over files already read into memory by `load_scene_extractions()`.

**Constraints**: deterministic and reproducible — the same VTT and extractions must yield the same eligible sets every run. No LLM in the filter path.

**Scale/Scope**: one session at a time; 5–15 scenes, 3–6 roster characters, a VTT of ~1–2 MB.

### Phase 0 research — verified against the real artifacts, not assumed

Run against `~/phandalin/Phandalin/summaries/20260902`:

| Scene | Labels in `moments` | Eligible after both filters |
|---|---|---|
| 01 rumors_and_preparations | GM, Vukradin, Soma, Valphine Sotorra | Vukradin, Soma, Valphine |
| 02 the_sewer_stakeout | GM, Vukradin, Soma, Valphine Sotorra | Vukradin, Soma, Valphine |
| 03 encounter_in_the_sewers | GM, Vukradin, Soma | Vukradin, Soma |
| 04 the_stakeout_of_denvar | GM, Vukradin, Soma, Valphine Sotorra | Vukradin, Soma, Valphine |
| 05 the_dead_drop | GM, Vukradin, Soma, Valphine Sotorra | Vukradin, Soma, Valphine |

Four findings that shape the design:

1. **`load_scene_extractions()` already separates the two text bodies cleanly.** Every speaker label lives in `moments`; `summary` (the gm-assist prose) carries zero labels in all five scenes. Presence must be read from `moments` alone.
2. **A prose mention is not presence, and the two are trivially confusable.** "Brewbarry" appears in the *text* of `moments` in four of five scenes — as GM narration *about* him ("Brewbarry's already in the tavern") — while never appearing as a label. A substring search would mark him present in exactly the scene this feature exists to fix. The parser must anchor on `(?m)^\*\*Name\*\*`.
3. **No scene in this session is uncoverable**, so User Story 3 needs a synthetic fixture; it cannot be regression-tested from this session.
4. **Filter B is not inert here even after Filter A runs.** Valphine has no label in scene 03, so she becomes ineligible for it. The feature changes plans for sessions that had no absent player at all.

Both label spaces were confirmed distinct: the VTT carries player display names (`Kostadis Roussos`, `David Mendenhall`, `Wade Brown`, `Gary Young`), the extractions carry character names (`Vukradin`, `Soma`, `Valphine Sotorra`, `GM`).

## Constitution Check

*GATE: passes. Checked by name against all thirteen principles, per Governance.*

| # | Principle | Verdict |
|---|---|---|
| I | Disk is Truth, the Model is a Draft | **Reinforced.** Eligibility is read from the VTT and the extractions — files on disk — and the model's plan remains a draft the GM reviews. No derived state is cached as truth. |
| II | The Human Checkpoint is Non-Negotiable | **The point of the feature.** Narrator assignment is an attribution decision currently made by a model from a title. This removes the eligibility half from the model entirely, and where no deterministic answer exists (an uncoverable scene) it adds a checkpoint rather than a guess. FR-012 makes the choice blocking. |
| III | Retrieval and Render are Separated | **Held.** The filters are neither retrieval nor render. They are computed in pure helpers outside `main()`'s render path, so no function body mixes a retrieval call with `stream_api` and `tests/test_retrieve_render_isolation.py` stays green. |
| IV | Verbatim is Sacred | **Held.** Nothing rewrites a quote or a label. The filters read labels; the VTT and `scene_extractions/` are inputs only. |
| V | One Seam per Boundary | **Improved.** `_read_vtt_speakers` is currently private to `pipelines/workspace/players.py`; a second copy in `sd_plan` would be a second definition of "this label is present". It moves to `campaignlib/vtt.py` and both consume it. |
| VI | CLI is the Engine, UI is a Face | **Held.** All logic lands in `sd_plan` and `campaignlib`; the router only builds argv and presents the choice. |
| VII | Extract Once, Synthesize Deliberately | **N/A** — no extract/synthesize pipeline is touched. |
| VIII | State is Discoverable | **Extended.** FR-017's eligibility record makes "which pool was this plan drawn from" answerable from disk after the fact. The pending-choice state is the presence of `plan.a|b|c.md` without `plan.md` — visible in a directory listing, not held in the operator's head. |
| IX | The UI Mechanizes; Claude Converses | **Held.** The choice among three plans is a file (`plan.md`, written from the chosen alternate), never browser state. The GM may make the choice with `cp` at the CLI and lose nothing. |
| X | Selection is Explicit; No Silent "All" | **Directly applied.** The three-plan choice never defaults to the base plan; the next stage refuses until a choice is made. This is also why FR-003/004 refuse rather than falling back to the full roster — an unnarrowed pool is the implicit "all" this principle forbids. |
| XI | Parity is Bidirectional | **Held.** User Story 5 ships the UI surface in this feature, not a follow-up. No CLI-only exemption is claimed. |
| XII | One Spelling per Option | **Held, family-wide.** `--vtt` and `--players-config` reuse the existing family spellings (`sd_verify_quotes`, `scene_extract`, `enhance_summary`). `sd_narrate` gains `--vtt` — it had `--players-config` but no tape — so the attendance concept lands on both CLIs that consume it, not one. No new vocabulary. `--characters` keeps its current meaning (the campaign roster) and is narrowed inside `sd_plan` rather than redefined. |
| XIII | Breaking State Changes Migrate Out of Band | **N/A, deliberately.** No existing file changes shape. `plan.md` keeps its format (`parse_plan` is line-oriented and ignores unknown keys, so a new `pov:` line is additive). The eligibility record and the alternates are new files, not migrated ones. No migration CLI or `migration.md` is owed. |

**Reviewed 2026-09-06.** The draft plan proposed stopping at `sd_plan`, on the grounds that `sd_narrate` inherits the filter transitively through `plan.md`. Review rejected that: `sd_narrate` builds its roster block from `roster_from_config`, which names campaign-**active** players and says nothing about who was at the table, so Pass 5 was still being told Brewbarry is simply in the party. The GM ruled the family is two members. `sd_narrate` gains `--vtt` and the roster marker (US6, FR-022..026).

## Project Structure

### Documentation (this feature)

```text
specs/022-absent-player-narrator/
├── spec.md              # Phase -1 output (written)
├── plan.md              # This file
└── tasks.md             # $speckit-tasks output — NOT created here
```

`research.md`, `data-model.md` and `contracts/` are not warranted: Phase 0 fits in this file (above, verified against real artifacts), the data model is three derived sets over entities that already exist, and there is no new API contract — only two argv flags and one new file layout.

### Source Code (repository root)

```text
campaignlib/
├── vtt.py                    # + speaker_labels(text) -> set[str]   (moved from pipelines/workspace/players.py)
└── players_config.py         # + attending_players(cfg, labels), absent_characters(cfg, roster, labels)

session_doc/
├── io.py                     # + scene_speakers(moments) -> set[str]
├── plan_eligibility.py       # NEW — pure: pool, per-scene candidates, exclusion report
├── roster.py                 # roster_from_config: unvoiced marker (FR-022..024)
├── sd_narrate.py             # + --vtt; pass attendance to the roster block
└── sd_plan.py                # + --vtt / --players-config; filter before prompt; refusals; alternates; --choose

config/agents/session_doc/
└── plan.md                   # prompt: per-scene candidates replace the title list; rotation demoted; pov: line

pipelines/workspace/
└── players.py                # - _read_vtt_speakers (imports campaignlib.vtt instead)

server/routers/
└── scene_editor.py           # _build_plan_cmd + _build_narrate_cmd: pass --vtt
                              # _build_narrate_cmd: refusal names a pending choice
                              # + route to select an alternate

frontend/src/                 # Session Doc Editor: present the three plans, post the choice

tests/
├── test_plan_eligibility.py  # NEW — the filters, as pure functions
├── test_sd_plan_refusals.py  # NEW — no VTT, empty pool, all scenes uncoverable
├── test_sd_plan_alternates.py# NEW — three plans, differing only in the disputed scene
├── test_roster_unvoiced.py   # NEW — marker present, grounding retained, inert when all voiced
└── test_backend_seam_guardrails.py  # existing — extend UI-reachability entries
```

**Structure Decision**: no new top-level structure. The filters live in `campaignlib` (shared, per Principle V) and a new `session_doc/plan_eligibility.py` (feature-local, pure, no I/O beyond what it is handed) so that `sd_plan.py` stays a CLI shell. This keeps every filter testable with no API key, no network, and no fixture larger than a few strings.

## Design decisions

### D1 — Presence is label-anchored, never substring

`scene_speakers()` matches `(?m)^\*\*([^*]+)\*\*` against `moments` only, drops `GM`, and skips bracketed action-beat tags (`**[The Drow Spy Spotted]**`, which `config/agents/scene_extract.md` permits). Reading `summary` or doing a substring search would mark Brewbarry present in four of five scenes — Phase 0 finding (2). This is the single highest-risk detail in the feature.

### D2 — Two label spaces, two lookups

Filter A resolves *people*: VTT labels → `players.yaml` `display_names` → `plays` → characters. Filter B resolves *characters* directly from extraction labels. They are not the same mechanism applied twice and must not be merged into one helper.

### D3 — The alternates differ in one scene, so make one plan and vary that scene

Three independent planner runs on 20260902 produced a byte-identical narrator distribution, so re-sampling does not diversify. The three plans are therefore *constructed*, not sampled: one plan call covers the coverable scenes, a second small call proposes three treatments for the uncoverable scene, and the three files are assembled deterministically. Two model calls instead of three full plans, and the alternates are guaranteed comparable because everything except the disputed scene is identical.

*Amended at review:* a treatment that folds the uncoverable scene into a neighbour necessarily edits that neighbour's entry too, so the invariant is "identical except the uncoverable scene **and any scene a treatment explicitly absorbs it into**" — still deterministic, still a one-decision diff.

### D4 — The pending choice is the absence of `plan.md`

When a scene is uncoverable, `sd_plan` writes `plan.a.md`, `plan.b.md`, `plan.c.md` and **no** `plan.md`. `_build_narrate_cmd` already refuses when `plan.md` is missing (`server/routers/scene_editor.py:1406`), so the gate exists — only its message needs to name the pending choice. `sd_plan --choose {a,b,c}` writes the chosen alternate to `plan.md`. No new state machine, no status field, and the GM can make the choice with `cp` (Principle IX).

### D7 — The roster marker says *unvoiced*, not *absent*

Brewbarry's player was absent; Brewbarry was in the tavern because the GM put him there. A marker reading "not at this session" would make the "never contradict these" block assert something the scene-05 extraction contradicts — the fabrication risk pointed the other way. The marker is about voicing, the character keeps full grounding, and the block never speaks to presence in the fiction. Wording is the entire risk of US6.

### D5 — Refuse, don't fall back

No VTT, an empty pool, or every scene uncoverable are all refusals. A fallback to the unnarrowed roster is precisely today's defect, and Principle X forbids the implicit "all".

### D6 — `--characters` keeps its meaning

It stays the campaign roster. Narrowing happens inside `sd_plan`, so the flag is not silently redefined and `_roster_characters(cfg)` in the router is untouched.

## Implementation phases

**Phase 1 — deterministic core (no behaviour change).** Move `_read_vtt_speakers` to `campaignlib/vtt.py`; add `scene_speakers()` to `session_doc/io.py`; add `session_doc/plan_eligibility.py` computing the pool, the per-scene candidate sets, and the exclusion report. Tests: `test_plan_eligibility.py`, including the label-vs-prose case and the scene-03 case. Nothing wired in yet — the suite proves the filters before they can affect a plan.

**Phase 2 — wire into `sd_plan` (US1 + US2 + US4).** Add `--vtt` / `--players-config`; compute eligibility; print exclusions before the model call; write the eligibility record; carry per-scene candidates into the prompt; rewrite `config/agents/session_doc/plan.md`; fix the `missing` warning to use eligible sets (FR-014); add the refusals (D5). At the end of this phase, SC-001, SC-002, SC-003 and SC-008 pass.

**Phase 3 — uncoverable scenes (US3).** The second call, the three-file assembly, `--choose`, and the refusal message in `_build_narrate_cmd`. Synthetic fixture, since 20260902 has no uncoverable scene.

**Phase 3b — Pass 5 roster block (US6).** `sd_narrate` gains `--vtt`; `roster_from_config` takes the attendance set and marks unvoiced characters per D7. Independent of Phases 2–3 and testable on its own.

**Phase 4 — UI parity (US5).** Confirmed in scope at review 2026-09-06; no CLI-only exemption is claimed. Router passes the new flags to both `sd_plan` and `sd_narrate`; a route selects an alternate; the editor presents the three plans and their treatments. Extend `test_backend_seam_guardrails.py`'s reachability entries.

Phases 1–2 are shippable alone and fix the reported defect. Phase 3 is inert on any session where every scene has an eligible narrator. Phase 3b is inert on any session where everyone was voiced. Phase 4 is required by Principle XI before the feature is done.

## Risks

- **D1 is the whole feature.** A parser that reads prose instead of labels reintroduces the bug while appearing to fix it. The scene-05 Brewbarry case must be an explicit test, not an incidental one.
- **`scene_extract`'s speaker normalisation is trusted.** If a label arrives as `Vukradin (David)` rather than `Vukradin`, that character silently loses eligibility for the scene. Mitigation: report unrecognised labels in the exclusion output rather than dropping them, so the failure is visible (spec Assumptions).
- **Filter B has more reach than the reported bug.** It changes plans for sessions with no absent player (Phase 0 finding 4). Accepted deliberately by the GM when scope was widened on 2026-09-06; called out here so it is not discovered later as a regression.
- **The roster marker is a prompt change to the anchor block.** D7's wording is the mitigation, but any phrasing that reads as "was not in the scene" turns a fabrication guard into a fabrication cause. Test the marker's text, not just its presence.
- **The covered-PC misfire** is a known, accepted wrong answer under the no-override ruling. It is only correctable because exclusions are reported (US4), which makes US4 load-bearing rather than nice-to-have.

## Complexity Tracking

> No constitutional violations to justify. The Principle XII family question was the one open item and was resolved at review by widening the feature to `sd_narrate` rather than by claiming an exemption. No CLI-only ruling is recorded, because none was granted.
