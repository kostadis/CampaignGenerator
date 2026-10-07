# Implementation Plan: Summary-Native NPC Dossiers

**Branch**: `research/npc-dossiers-from-summaries` | **Date**: 2026-10-06 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/032-npc-dossiers-from-summaries/spec.md`

## Summary

This feature extends spec 031's `summary_native` tool with five stages and one migration.

1. **`npc-link`** (deterministic). For every NPC corpus dossier, attaches each whole scene and memorable moment that names the NPC, under a computed header.
   - Name forms are only headings and exact same-type registry strings.
   - Ambiguous forms are withheld, and so are generic ones (a single word in a pinned English list).
   - Withheld forms are reported in a fix list, with a warning at the end of the run.
2. **`npc-draft`**, the **only model step** (GM ruling, 2026-10-06). It makes one call per NPC and writes the finished, fixed-outline draft dossier for **global NPCs only** (registry `npc` + `persistent`). The input is the NPC's evidence plus the numbered Manual edits from its authored file; Secrets never enter the prompt. A manual edit wins over conflicting evidence and is cited `[manual N]`.
   - Re-drafts are incremental, keyed on evidence, Manual edits, prompt, backend and model. A Secrets-only edit re-composes the GM dossier with no model call.
   - Each run keeps the full prompts, the selection and the digests.
3. **`npc-verify`** (deterministic). Checks every citation against the corpus and the NPC's own evidence, every quote verbatim against the summaries, and **that every manual edit is cited at least once**. An uncited edit is reported as dropped, with its text.
4. **`npc-compose`** (deterministic). Builds the GM dossier: the draft dossier with the authored Secrets appended byte-for-byte. `npc-draft` runs it automatically; run it alone after a Secrets-only edit. `--init` scaffolds an empty authored file.
5. **`npc-publish`** (deterministic, an explicit GM act). The only writer of `docs/npcs/<slug>.md`, where the gm-assistant skills already read. It publishes the reviewed GM dossier (Secrets included, `[manual N]` rewritten to `[GM]`, chapter citations kept) or a hand-built `authored/<slug>.md` verbatim, under a provenance header. It refuses on failed verification, foreign targets and hand-edited targets without `--force`.

**Layout and migration:** `docs/npcs/` holds only published dossiers. `authored/` holds everything a person creates (`.authored.yaml` files, hand-built dossiers such as `gm-npc-build` output). `distilled/` and `summary_native/` hold generated and tool data only. A two-step migration proposes a disposition for every existing file from git evidence and the `source_extracts:` marker. The GM edits the classification, and `--apply` moves the files and rewrites config paths. Distilled-dossier readers are repointed, with a guard that refuses an unmigrated campaign or a config pointing at `docs/npcs/` itself. An NPC dossiers web page, separate from Grounding, exposes all five stages.

## Technical Context

**Language/Version**: Python 3.12 (repo standard); TypeScript + Vue 3 for the page

**Primary Dependencies**:
- Existing only: PyYAML, FastAPI, Pydantic.
- `campaignlib` (`registry`, `textproc.locate_quote`, `api.client.add_backend_args`/`client_from_args`, `util.atomic_write_text`) and 031's `pipelines/summary_native` (`parse`, `validate.scan`, `corpus`, `select`, `duplicates.load_rulings`, `resolve`, `synth.check_outline`).
- New data file: a vendored SCOWL size-35 word list (research R4).

**Storage**: Files only. Layout in `data-model.md`. The 031 corpus (`docs/summary_native/`) is read-only here.

**Testing**: pytest (`tests/test_summary_native_npc_*.py`, `tests/test_migrate_npc_dossiers.py`, `tests/test_npc_dossiers_routes.py`, guard tests below), fixture corpus under `tests/fixtures/summary_native_npc/`, and Playwright `frontend/e2e/sidebar-navigation.spec.ts`.

**Target Platform**: Linux, a single-user local server and CLI

**Project Type**: CLI pipeline + FastAPI/Vue web UI (existing repo layout)

**Performance Goals**:
- `npc-link` on OOTA (67 files, about 2,700 forms) in under 30 s.
- `npc-verify` and `npc-compose` in under 5 s for all NPCs.
- Draft time depends on the model; each call is bounded by one NPC's pack.

**Constraints**:
- Byte-identical deterministic outputs.
- Zero model calls in link, verify and compose.
- Drafting reads only the Manual edits from `docs/npcs/authored/` (through `npc_authored.load_manual()`). Secrets never reach a prompt.
- No writes under `docs/npcs/distilled/` or the 031 corpus.
- No dual-location fallbacks.

**Scale/Scope**:
- OOTA: 222 NPC corpus dossiers and 378 registry NPCs. At most 222 can be drafted.
- The largest pack is 81 entries plus about 94 whole scenes, under 60k tokens, so no chunking is needed.

## Constitution Check

*GATE: checked before Phase 0 and re-checked after Phase 1 design.*

| # | Principle | How this plan complies | Status |
|---|---|---|---|
| I | Disk is truth, model is a draft | Summaries, the registry, `canon.yaml` and authored files are inputs and never written. Draft dossiers are drafts until the GM reviews them. GM dossiers are regenerated output and never a source; hand-edits to them are reported as discarded | ✅ |
| II | Human checkpoint | Identity, ordering and attribution are decided by headings, exact registry strings, authored structure and GM rulings. Ambiguous forms are fixed by editing the summaries; the GM rules on generic forms. The publish call's inputs are human-reviewed summaries plus the GM's own Manual edits, and the precedence rule (manual edit beats evidence) is the GM's, stated in the prompt and checked by FR-018c's coverage check. Draft dossiers are a leaf (FR-023): planning keeps reading evidence | ✅ |
| III | Retrieval/render separation | There are no retrieval calls. The evidence-pack builder (`npc_link.py`) and the renderer (`npc_draft.py`) are separate modules, so `test_retrieve_render_isolation.py` applies | ✅ |
| IV | Verbatim is sacred | Linked scenes, moments and entries are copied verbatim, and mention lines are listed beside the text rather than marked inside it. GM dossiers reproduce Secrets byte-for-byte. Draft dossiers claim to be derived (Manual edits are paraphrased by design), so `npc-verify` enforces *traceability* everywhere (chapter citations exist; every manual edit is cited) and *exactness* only on quotes, which claim it | ✅ |
| V | One seam per boundary | Model calls go through `client_from_args`/`stream_api` only. The registry is read through `campaignlib.registry`. Quote matching goes through `campaignlib.textproc.locate_quote` | ✅ |
| VI | CLI is engine | `server/routers/npc_dossiers.py` builds argv and streams it, and implements no stage logic | ✅ |
| VII | Extract once, synthesize deliberately | No new extraction. Linking is a deterministic restatement of the 031 parse. One draft call per NPC is a deliberate, budgeted synthesis | ✅ |
| VIII | State is discoverable | Stage state is visible from disk: `link_manifest.json` → `evidence/` → `draft/index.json` → `*.verify.md` → `gm/` → `publish_log.json` and `docs/npcs/<slug>.md` headers. The migration's classification file is kept as a record. `/state` reads only those files | ✅ |
| IX | UI mechanizes | The page runs stages and shows files and reports. That includes a Publish button, which invokes `npc-publish` for an explicit selection with the CLI's refusals; publishing exists in both places by GM ruling (2026-10-06). The judgment (reviewing drafts, ruling on name forms, editing authored files) stays in files, the CLI or chat. There is no edit control for authored files, drafts or rulings | ✅ |
| X | No silent "all" | The UI refuses without a range or a draft selection mode. "Every global NPC" is an explicit `select=all` that becomes `--all`. The CLI default with no narrowing is FR-012's stated behaviour, and typing the command at the CLI is the explicit act (same convention as 031) | ✅ |
| XI | Bidirectional parity | The UI ships in this feature (GM ruling). Every run-shaping flag has a route parameter: for drafting `--name`, `--all`, `--recent-chapters`, `--recurring-min`, `--dump-only`, `--force` and backend/model/`--max-tokens`; for compose `--name` and `--init`; for publishing `--name`, `--all`, `--authored-all`, `--source` and `--force`. Publishing has a page button as well as the CLI command (GM ruling, 2026-10-06). The migration is the one CLI-only capability, following the `server/migrate_*.py` out-of-band precedent that Constitution XIII prescribes. **No-per-run-control ruling:** `--npc-root`, `--registry`, `--canon` and `--out-root` are campaign-layout paths set only in config (`npc_dossiers.yaml npc_root`; `grounding.yaml summary_native.*`). That is the GM's ruling: kostadis, 2026-10-05 (031) for the last three, and 2026-10-06 for `--npc-root`. Today they are reachable through the `PUT …/config` routes. A configuration-management UI page is filed as #502 | ✅ |
| XII | One spelling per option | Reuses 031's spellings (`--summaries-dir --since --until --out-root --registry --canon --config --name --recent-chapters --recurring-min --model --max-tokens --dump-only --force`) and its backend flags. `summaries_dir`, `registry` and `canon_file` stay in `grounding.yaml summary_native`, not re-declared. New defaults are declared once in `schema.py`, with a router default-literal guard test | ✅ |
| XIII | Breaking state migrates out of band | **This feature applies it.** The `docs/npcs/` layout change (distilled → `distilled/`, hand-built → `authored/`, decided per file by the GM from a git-evidence proposal) ships `server/migrate_npc_dossiers.py` (dry-run, `--force`, idempotent, reports unrecognised entries) and `tests/test_migrate_npc_dossiers.py`, plus `specs/032-…/migration.md` and `docs/cli/npc_dossiers_migration.md`. Retired locations are refused with the command (`refuse_unmigrated_dossier_dir`). `canon.yaml link_rulings` and `npc_dossiers.yaml` are additive or new, so they need no migration | ✅ |

**Gate result: PASS.**

**Re-check after the publishing and layout rulings (2026-10-06):** still PASS, and tighter on II. Model-driven consumers (the gm-assistant skills) read only `docs/npcs/`, which only an explicit GM publish writes, so no unreviewed draft reaches another model. The migration's file classification is an identity decision; the tool proposes from evidence and the GM decides.

**Re-check after the synthesis ruling (2026-10-06):** still PASS. Drafting now feeds GM-written Manual edits to the model. That is human-authored input, so no unreviewed output crosses a precision boundary (II). The precedence of manual edits over evidence is the GM's own rule. The coverage check catches an edit the model dropped. The remaining risk, a softened edit, is named in every verify report. No violations, so Complexity Tracking is empty.

**Post-design re-check:** still PASS. Two things were tightened during design:
- **R1:** a registry NPC whose scope is not `persistent` is not global. This keeps the next (local-NPC) feature's semantics open. Flagged to the GM.
- **R2:** the ambiguity index spans every entity type, and does not use `explicit_aliases_by_type`, whose first-wins collision handling would be a silent identity decision.

### Open items for the GM (not blocking `/speckit-tasks`)

1. ~~Global NPC and registry `scope`~~: **resolved.** Local scopes are kept out until this feature is finished (GM ruling, 2026-10-06; FR-012).
2. ~~`--npc-root` per-run control~~: **resolved.** Config file only; configuration-management page filed as #502.
3. ~~Manual edits as render input~~: **resolved.** Drafting is the only model step and synthesises evidence plus Manual edits, with a dropped-edit check (GM ruling, 2026-10-06; spec FR-013, FR-018–FR-018c).
4. **The GM dossier's shape.** I made it the draft dossier with `## Secrets` appended. It does not also show the raw Manual edits, because they are already folded in and cited. Say if you also want the raw list as an appendix for audit.

## Project Structure

### Documentation (this feature)

```text
specs/032-npc-dossiers-from-summaries/
├── plan.md              # this file
├── research.md          # R1–R15 decisions
├── data-model.md        # entities, on-disk layout, state transitions
├── quickstart.md        # validation scenarios S1–S7
├── contracts/
│   ├── cli.md           # npc-link / npc-draft / npc-verify / npc-compose / migration
│   ├── http.md          # /api/npc-dossiers + page
│   └── files.md         # authored file, link_rulings, evidence, draft / GM / published dossiers, citations
├── migration.md         # (implementation output, Constitution XIII)
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
pipelines/summary_native/
├── cli.py                     # + npc-link / npc-draft / npc-verify / npc-compose subparsers
├── schema.py                  # + DEFAULT_NPC_ROOT, citation regex, link finding codes, outline name
├── duplicates.py              # load_rulings accepts link_rulings (R5)
├── freshness.py               # NEW: _check_fresh factored out of synth.py (shared by synth / npc-link / npc-draft)
├── npc_forms.py               # NEW: name forms, ambiguity index, generic flag, rulings application (R2, R4, R5)
├── npc_link.py                # NEW: scan scenes and moments, evidence dossiers, link report, link manifest (R3, R6)
├── npc_draft.py             # NEW: global-NPC selection, prompt build (evidence + Manual edits), draft loop, index, record (R1, R8, R9)
├── npc_verify.py              # NEW: citation and quote checks (R10)
├── npc_authored.py            # NEW: the only module that opens docs/npcs/authored/ (load_manual / load_secrets / read_handbuilt / init_authored) (R7)
├── npc_compose.py             # NEW: GM dossier composition, hand-edit detection, --init via npc_authored (R7)
├── npc_publish.py             # NEW: explicit publish to docs/npcs/<slug>.md, [manual N]→[GM], hand-built path, refusals, publish_log (R16)
├── npc_slug.py                # NEW: canonical name → <slug> (gm-assistant convention) and <stem>; collision detection
├── data/english_words.txt     # NEW: SCOWL-35 lowercase, + LICENSE note (R4)
└── prompts/npc_dossier.system.md, npc_dossier.outline.yaml   # NEW

campaignlib/npc.py             # + refuse_unmigrated_dossier_dir(); load_alias_map calls it (R12)
pipelines/grounding/planning.py          # dossier_dir default and guard
entity_registry/resolve.py, entity_registry/registry.py   # docs/npcs/distilled + guard
server/
├── migrate_npc_dossiers.py    # NEW (R12): --propose (git + marker evidence) / --apply (follows the GM's classification)
├── npc_dossiers_config.py     # NEW strict model + service for <config>/npc_dossiers.yaml (R14)
├── routers/npc_dossiers.py    # NEW (contracts/http.md)
├── grounding_config_shared.py # DossierBuild.dossier_dir → docs/npcs/distilled/
├── platform_config_service.py # discover_campaign_paths → docs/npcs/distilled
└── main.py                    # include router
frontend/src/
├── views/npcs/NpcDossiers.vue # NEW
├── router.ts                  # /npcs/dossiers
├── components/layout/AppSidebar.vue  # new top-level "NPCs" path
├── composables/useGroundingRun.ts    # widen doc union (or sibling composable)
└── views/grounding/PlanningDocument.vue, views/prep/ConnectionGraph.vue  # docs/npcs/distilled fallbacks
docs/cli/npc_dossiers_howto.md, docs/cli/npc_dossiers_migration.md     # NEW operator docs
tests/
├── fixtures/summary_native_npc/          # seeded corpus: ambiguous name, generic word, mention-only chapter, moment outside scene
├── test_summary_native_npc_link.py       # FR-001–FR-011, byte-identity, warnings
├── test_summary_native_npc_forms.py      # ambiguity across types, generic flag, rulings refusal/stale/unneeded
├── test_summary_native_npc_draft.py     # selection and exclusions, no-registry refusal, incremental keys, incomplete, header insertion
├── test_summary_native_npc_verify.py     # invalid / outside-evidence / not-verbatim / uncited / manual dropped / manual invalid
├── test_summary_native_npc_compose.py    # Secrets byte-for-byte in GM dossier, --init refuses, hand-edit warning, Secrets-only edit ⇒ no re-draft
├── test_npc_draft_no_secrets.py        # guard: drafting reads authored files only via npc_authored.load_manual(); canary secret absent from prompts and draft dossiers (FR-018a)
├── (extended) test_summary_native_no_llm.py  # AST guard now also covers npc_forms/link/verify/compose/publish/slug/authored and freshness
├── test_no_loose_dossier_reads.py        # guard: every docs/npcs reader goes through refuse_unmigrated_dossier_dir; none rglob
├── test_migrate_npc_dossiers.py          # propose rules (marker, sidecars, never from commit wording), unknown blocks apply, sha drift refuses, git-less fallback
├── test_summary_native_npc_publish.py    # explicit selection, [manual N]→[GM], hand-built verbatim, refusals (failed verify / foreign / hand-edited / both sources / slug collision)
├── test_no_writes_to_authored.py         # guard: no stage writes, renames or deletes under docs/npcs/authored/ (except --init creating a new file)
├── test_npc_dossiers_routes.py, test_npc_dossiers_config_defaults.py
└── (updated) test_planning.py, test_registry*.py, test_resolve_name.py, test_platform_config_service.py, test_grounding_*config*.py
```

**Structure Decision**: Extend the existing `pipelines/summary_native` package, with one module per stage (CLI engine), plus the established server/router/frontend pattern of 031's summary-native page. The page is placed under a new top-level sidebar path, per the GM's ruling. Migration code follows the `server/migrate_*.py` pattern.

## Complexity Tracking

No constitution violations to justify.
