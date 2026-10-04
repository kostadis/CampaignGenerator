# Implementation Plan: Installable CampaignGenerator package

**Branch**: `main` (setup reports feature identifier `030-installable-package`; no branch hook ran) | **Date**: 2026-10-04 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/030-installable-package/spec.md`; issue [#494](https://github.com/kostadis/CampaignGenerator/issues/494). The operator ruled that installed mode is CLI-only and external wiring defaults to `~/.config/campaigngenerator/wiring.yaml`.

## Summary

Make a built, non-editable CampaignGenerator distribution usable from outside its checkout. Bundle read-only prompts and the reviewer page inside importable packages; resolve shipped resources through package access while preserving campaign overrides. Remove source-root assumptions from command dispatch and operator guidance. Keep mutable campaign data in workspaces and mneme wiring in the chosen user config location. Provide a deliberate wiring migration, coordinate mneme's render target, and prove the wheel in a fresh environment. Installed mode is CLI-only; `./start` remains the source-checkout web path.

## Technical Context

**Language/Version**: Python `>=3.10` in `pyproject.toml`; reproduce the issue and smoke installation on Python 3.14. The previous `>=3.9` declaration was unusable: the `mcp` dependency requires 3.10+ and an installed 3.9 wheel raised on existing type annotations. Existing checkout UI is Vue 3 and FastAPI.

**Primary Dependencies**: Python standard-library `importlib.resources`, current Hatchling wheel builder, current CLI entry points, existing `campaignlib` config/wiring modules, mneme hypostasis renderer. No new runtime service or model call.

**Storage**: Shipped read-only files in package data; campaign overrides and generated output in campaign workspaces; host wiring at `~/.config/campaigngenerator/wiring.yaml`. One-time migration moves legacy rendered wiring from checkout. No database.

**Testing**: Existing pytest suite plus resource precedence and wiring unit tests; wheel content inspection; fresh isolated non-editable wheel installation and subprocess smoke from unrelated CWD on Python 3.10 and 3.14; an installed `new_workspace` write check that leaves installed files unchanged; checkout `./start` smoke. Mneme render/status integration check at the new target.

**Target Platform**: Existing Linux operator environment and supported Python versions. No installed web UI assets are required.

**Project Type**: Multi-package CLI application with a checkout-only web UI and an external configuration producer.

**Performance Goals**: No additional network calls or LLM calls during import, resource resolution, or migration; user can complete documented install verification in under 10 minutes excluding environment creation and dependency download.

**Constraints**: Preserve campaign-first prompt precedence; explicit paths fail clearly when absent; no writes into `site-packages`; no runtime migration or fallback to retired wiring; `./start` continues to work; packaged file access must work for Python 3.10 onward; mneme may be under a different user only when an explicit shared wiring path is configured.

**Scale/Scope**: The 17 identified lookup sites across 16 modules, current seven wheel package trees plus shipped resources, representative installed imports and CLI entry points, one host-global wiring move, one mneme render-target change, and documentation. Dependency bounds in #493 remain separate.

## Constitution Check

*Gate before Phase 0: PASS. Rechecked after Phase 1 design: PASS, with the coordination boundary and migration UI noted below.*

| Principle | Assessment |
|---|---|
| **I — Disk is Truth, the Model is a Draft** | PASS. Prompt bytes, overrides, and rendered wiring remain files; the wheel is the shipped read-only copy. No model-generated state is promoted. |
| **II — The Human Checkpoint is Non-Negotiable** | PASS. This feature changes packaging and file resolution, not campaign scope, order, or attribution. The operator explicitly chose wiring location and installed-mode scope. Migration is manually invoked. |
| **III — Retrieval and Render are Separated** | PASS. No retrieval/render function or model call is added or merged. |
| **IV — Verbatim is Sacred** | PASS. Shipped prompt text is copied byte-for-byte into the distribution, and campaign overrides continue to win. The plan changes resource access, not artifact claims or quote provenance. |
| **V — One Seam per Boundary** | PASS. `campaignlib/config.py` owns shipped prompt resolution; `campaignlib/wiring.py` remains the single mneme-wiring accessor. Mneme's renderer changes its target without adding another CampaignGenerator integration path. |
| **VI — CLI is the Engine, UI is a Face** | PASS. Migration and diagnostics live in the CLI; any checkout UI invocation shells out to it. Existing web routes do not implement resource logic. |
| **VII — Extract Once, Synthesize Deliberately** | N/A. No extraction or synthesis pass changes. |
| **VIII — State is Discoverable** | PASS. Resource origin and wiring location are diagnosable; migration status is visible from files, errors, and operator documentation. No state exists only in the UI. |
| **IX — The UI Mechanizes; Claude Converses** | PASS. The checkout UI only invokes the one-shot migration and shows its result; the operator chooses when to migrate. |
| **X — Selection is Explicit; There is No Silent All** | PASS. Migration names one source checkout and one destination; no implicit scan of all workspaces or host directories. |
| **XI — Parity is Bidirectional; Every CLI Capability Has a Face** | PASS with explicit ruling. On 2026-10-04 the operator chose an installed CLI-only distribution with `./start` retained for the web UI. For the new migration capability, the checkout Settings page will expose invocation and result via a thin CLI-backed route; installed mode has no UI by the operator's ruling. |
| **XII — One Spelling per Option; No Configuration Drift Across CLIs** | PASS. Existing `MNEME_WIRING` and explicit `load_wiring(path)` retain their meanings. The host-global migration uses `--source-checkout`, optional `--target`, and established `--force` semantics; `--campaign-dir` is inapplicable because wiring is not campaign-owned. The default target is declared once in `campaignlib/wiring.py`; the migrator imports it and the UI reads it through `GET /api/config/wiring/default`. |
| **XIII — Breaking State Changes Migrate Out of Band and Ship a Migration Document** | PASS. Legacy checkout wiring moves only through a separate one-shot CLI; no startup rewrite or dual-location fallback. `migration.md` in this feature and operator-facing documentation are required implementation outputs. The migrator must preserve unknown fields, refuse accidental overwrite, report what it did, and receive focused tests. |

**Gate result**: No constitutional violation requiring a waiver. The chosen CLI-only installed scope is an explicit user ruling, not an inferred exemption. The host-global migrator is an intentional variant of the campaign `--campaign-dir` convention and is documented above.

**Post-Phase-1 re-check**: The proposed contracts keep resource ownership and override order singular, with no hidden fallback. The one-shot migration and checkout UI face meet XIII and XI. No new stateful service or undocumented package location is introduced. Gate remains PASS.

## Project Structure

### Documentation (this feature)

```text
specs/030-installable-package/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── migration.md                 # Required during implementation by Principle XIII
├── checklists/requirements.md
└── contracts/
    ├── resources.md
    └── wiring-migration.md
```

### Source Code (repository root)

```text
pyproject.toml                  # wheel package selection and data inclusion
requirements.txt               # remove duplicate unbounded dependency source
campaignlib/
├── config.py                   # prompt/default resource resolver
├── wiring.py                   # sole external wiring accessor and target default
└── resources/                 # shipped prompt and config defaults
session_doc/review/             # reviewer.html package resource
pipelines/
├── workspace/new_workspace.py  # portable generated config and next-step text
├── grounding/                  # source-root subprocess/import shims
├── ensemble/                   # package module subprocess targets
└── rlm/mcp_server.py           # remove dead root dispatch branch
server/
├── migrate_wiring.py           # one-shot host wiring migration CLI
├── routers/config_routes.py    # thin checkout UI migration invocation
└── main.py                     # checkout UI remains source-bound
frontend/src/views/Settings.vue # migration input, invoke, result
tests/                          # resolver, migration, wheel smoke, checkout regression
docs/                           # installed-mode and migration operator guidance
```

**Structure Decision**: Keep existing package boundaries and the current CLI/UI split. The only new runtime resource location is a package-owned read-only tree; the only new mutable location is the operator-approved host wiring target. Coordinate mneme changes in its repository (`hypostasis.example.yaml`, renderer-facing documentation/tests) rather than copying the renderer here.
