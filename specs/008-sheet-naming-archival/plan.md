# Implementation Plan: Roster-Named Sheets & Level Archival

**Branch**: `worktree-feat-dnd-sheet-party-names` (spec dir `008-sheet-naming-archival`) | **Date**: 2026-08-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/008-sheet-naming-archival/spec.md`

## Summary

`dnd_sheet` converts a D&D Beyond PDF and writes `<pdf-stem>.md` into an output
directory, knowing nothing about the campaign. This feature makes `config/party.yaml`
the naming and player authority for that conversion: the converted sheet is attributed
to exactly one roster entry by an **exact** character-name match, the player field is
overwritten from the roster (the export stamps the downloader's name into every sheet),
the output is written as `<char-name>.md` at the roster's declared sheet directory, and
any sheet already there is moved to `old/level/<N>/` keyed by the level *it* recorded.

Technical approach: two new pure modules in `campaignlib` (identity parsing, naming +
archival), `dnd_sheet.py` as the orchestrator that calls them around the existing
`call_api`, one additive `player` field on `PartyCharacter` threaded through the
hand-built loader/saver and the party API, and flag-forwarding only in
`server/routers/setup.py`. Every disagreement between the roster and the sheet is a
loud refusal that names the one-line fix — no fuzzy matching, no automatic edit of the
hand-authored roster.

The order of operations is load roster → convert → attribute → resolve destination →
archive → substitute player → write. Conversion happening *before* any filesystem
mutation is what satisfies FR-015 for free: nothing moves until the new content is in
hand.

## Technical Context

**Language/Version**: Python 3.11+ (engine), TypeScript / Vue 3 (UI)

**Primary Dependencies**: `pydantic` (roster models), `PyYAML`, `PyMuPDF` (`fitz`, text
extraction — unchanged), `anthropic` via `campaignlib` only, FastAPI (routes), Vue 3 +
Pinia (two existing components)

**Storage**: Files. `<campaign>/config/party.yaml` (roster), `<campaign>/docs/party/*.md`
(sheets), `<campaign>/docs/party/old/level/<N>/*.md` (archive). No database.

**Testing**: `pytest` (`python -m pytest tests/`). New: `tests/test_sheet_naming.py`,
`tests/test_dnd_sheet.py`. Extended: `tests/test_party_config.py`,
`tests/test_party_routes.py`, `tests/test_sheet_frontmatter.py`. Guard suites that must
stay green: `tests/test_layering.py`, `tests/test_retrieve_render_isolation.py`.

**Target Platform**: Linux (WSL2), single-user local deployment; server and campaign
files share a filesystem.

**Project Type**: CLI engine + thin FastAPI/Vue face over it (existing repo layout).

**Performance Goals**: Not a factor. One API call per PDF, as today; everything this
feature adds is local file I/O and regex on a document already in memory.

**Constraints**: No new model call and no new token cost — every value this feature
writes is deterministic. `campaignlib` must not import `server` or `pipelines`. The
converter's body must not gain a retrieval call. Roster paths resolve against the
campaign root (cwd), per #291.

**Scale/Scope**: 5 campaigns, ≤6 characters each, ~19 sheets total. Batch size is a
party, not a corpus.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Verdict | Basis |
|---|---|---|
| I. Disk is Truth, the Model is a Draft | **PASS** | The roster on disk overrides the model's transcription of the player field. Archive is a directory, not a record. Nothing this feature decides lives in memory. |
| II. The Human Checkpoint is Non-Negotiable | **PASS with a tracked deviation** | Every disagreement refuses and names the fix (FR-003a, FR-006, FR-013, FR-014). The deviation: attribution keys on a model-extracted name — GM-ruled, see Complexity Tracking. |
| III. Retrieval and Render are Separated | **PASS** | No retrieval call is added. `pdf_to_markdown` keeps `call_api`/`run_single_batch` and gains nothing; roster loading happens in `main`, and the naming/archival helpers call no API. `tests/test_retrieve_render_isolation.py` stays green. |
| IV. Verbatim is Sacred | **PASS** | No VTT, no quotes. The one rewrite of model output is a deterministic substitution of two fields whose source value is known-wrong, not an edit of anything anyone said. |
| V. One Seam per Boundary | **PASS, improved** | `parse_identity_fields`/`sheet_name` move to `campaignlib/sheet_identity.py` so `sheet_frontmatter` and `dnd_sheet` share one Identity parser instead of growing a second. |
| VI. CLI is the Engine, UI is a Face | **PASS** | `run_dnd_sheet` gains parameters it forwards as flags. No attribution, naming, level or archive logic in `server/`. |
| VII. Extract Once, Synthesize Deliberately | **N/A** | Not a grounding-doc generator. |
| VIII. State is Discoverable | **PASS** | The archive is self-describing on disk (`old/level/<N>/`); every move, match and skip is reported in the run output (FR-002b, FR-016). |
| IX. The UI Mechanizes; Claude Converses | **PASS** | Each UI action maps to one CLI invocation producing the same files (FR-024). The UI adds no judgment step — the judgment (which spelling is canonical) happens in the roster file, reachable from both surfaces. |
| X. Selection is Explicit; No Silent "All" | **PASS** | Roster mode requires an explicit `--party-config`; there is no auto-discovery fallback, and no invocation expands to "every character in the roster". PDFs are always named explicitly. |

**Post-Phase-1 re-check**: unchanged. The design added no server-side logic, no
config-file probing, and no second implementation of any operation.

## Project Structure

### Documentation (this feature)

```text
specs/008-sheet-naming-archival/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output — decisions D1–D12
├── data-model.md        # Phase 1 output — entities, fields, validation, state
├── quickstart.md        # Phase 1 output — runnable validation scenarios
├── contracts/
│   ├── cli-dnd-sheet.md # CLI surface: flags, exit codes, every message
│   └── http-api.md      # /api/setup/run/dnd-sheet + /api/party/characters
└── checklists/
    └── requirements.md  # Spec quality checklist (complete)
```

### Source Code (repository root)

```text
campaignlib/
├── sheet_identity.py    # NEW — Identity-block + frontmatter reading, level parsing
│                        #   (parse_identity_fields, sheet_name, SheetParseError move
│                        #    here from pipelines/content_ingest/sheet_frontmatter.py)
├── sheet_naming.py      # NEW — attribution, destination, archive path, player rewrite
├── party_config.py      # CHANGED — PartyCharacter.player + ResolvedCharacter.player,
│                        #   named in the hand-built loader AND saver
├── npc.py               # UNCHANGED — player_map_from_config keeps reading the sheet
│                        #   (see research D10)
└── constants.py         # UNCHANGED — config_path() is the declared roster location

pipelines/content_ingest/
├── dnd_sheet.py         # CHANGED — orchestration + --party-config; SYSTEM_PROMPT untouched
└── sheet_frontmatter.py # CHANGED — re-imports the moved parsers from campaignlib

server/
├── routers/setup.py     # CHANGED — forward --party-config; --output-dir only when set
└── party_config_service.py  # UNCHANGED — models carry the new field through

frontend/src/
├── views/setup/DndSheet.vue                 # CHANGED — roster path field + mode notice
└── components/shared/PartyConfigEditor.vue  # CHANGED — player column

tests/
├── test_sheet_naming.py      # NEW — attribution, level, archive, player rewrite
├── test_dnd_sheet.py         # NEW — orchestration order, refusals, exit codes
├── test_party_config.py      # EXTENDED — player survives a save/load round-trip
├── test_party_routes.py      # EXTENDED — player persists through PUT /characters
└── test_sheet_frontmatter.py # EXTENDED — still green after the parser move
```

**Structure Decision**: The repo's existing four-layer layout is kept exactly —
`campaignlib` (shared engine primitives), `pipelines` (CLI engines), `server` (thin
router), `frontend` (face). No new top-level directory. The only structural move is
lifting the Identity parser out of a `pipelines/` module into `campaignlib` so both
consumers share it; that direction is the one `tests/test_layering.py` enforces
(`campaignlib` may not import `pipelines` or `server`), and it mirrors the precedent
where `server/party_config_shared.py` became `campaignlib/party_config.py`.

## Complexity Tracking

> Filled because the Constitution Check records one tracked deviation.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Principle II: a model-extracted value (the character name read out of the converted sheet) selects which roster entry is used, and therefore which file gets archived — a precision decision keyed on unreviewed model output | GM ruling, 2026-08-13. The GM converts a handful of sheets whose names they already know; requiring a per-PDF flag makes the common case (a whole party at once) tedious enough to bypass | An explicit `--character NAME` per PDF was offered and declined. The residual risk is bounded structurally, not by a threshold: the roster is a closed hand-authored candidate set, so a misread name matches *nothing* rather than the wrong character; anything but exactly one exact match refuses (FR-002a/FR-003); and every accepted match is printed with the file it wrote (FR-002b), so a wrong attribution is reviewable after the run. No fuzzy matching exists anywhere in the feature |
