# Source Tree Restructure — Proposal

Status: **proposal, decisions locked** (no code changed yet — pending review; see §6)
Adjacent docs: [architecture.md](../core/architecture.md), [SessionDocRefactor.md](SessionDocRefactor.md), [CLAUDE.md](../../CLAUDE.md)

## 1. Why

The repo root currently holds **62 Python scripts, 24,207 lines**, all as flat siblings with no subpackaging:

```
apply_ingest_manifest.py  arc_triggers.py       assemble.py          build_recent_events.py
campaign_state.py         check_consistency.py  configure_mcp.py     convert_book.py
distill.py                dnd_sheet.py          dossier_proposer.py  enhance_recap.py
enhance_summary.py        ensemble.py            ...                (58 more)
```

Consequences observed while reading the tree, not hypothetical:

- **`CLAUDE.md`'s own "Project structure" table is already stale.** It lists ~25 of the 62 root scripts. 37 scripts — `polish.py`, `registry.py`, `spell_canon.py`, the whole `kanka_*` family, `ensemble_extract.py`/`ensemble_merge.py`, `synthesise_*.py`, `arc_triggers.py`, `build_recent_events.py`, `voice_lint.py`, `vtt_voice_compare.py`, `normalize_bible_headings.py`, `split_chapters.py`, `query_rpg_lib.py`, `suggest_conversion.py`, `apply_ingest_manifest.py`, `assemble.py`, `check_consistency.py`, `configure_mcp.py`, `transform.py`, `dnd_sheet.py`, `npc_table.py`, `make_tracking.py` — aren't mentioned at all. A flat root has no structure to keep the doc honest against; directory names would.
- **A real naming collision already exists and is undocumented as a collision.** Root `registry.py` ("CLI for the campaign entity registry") is, by its own docstring, "the write side of `campaignlib.registry`" (the loader/validator library, `campaignlib/registry.py`). Two different files named `registry.py` in two different import namespaces, intentionally paired, is exactly the kind of thing a flat root hides.
- **Two tracked top-level directories don't belong to this project's subject matter:** `llm-wiki/` (three unrelated blog-post drafts — "LinkedIn: the loop", "rich plots for GMs") and `scabard_sdk/` (a semi-independent vendored SDK with its *own* `CLAUDE.md`, its own test file, and integration memos addressed to "the Scabard API dev"). Both currently read as first-class citizens of the CampaignGenerator source tree because there's nothing about root-level placement that says otherwise.
- **Cross-script coupling is invisible until grepped for.** e.g. `fivetools_ingest.py` imports `fivetools_copy`, `fivetools_render`, `resolve_refs`, and `mempalace_client`; `rpg_retriever.py` imports `dossier_proposer` and is imported by it; `registry.py` imports `spell_canon`. None of this is visible from `ls .`.

None of this blocks any single task — but every "which file has X" question currently requires either `grep -l` over 62 files or asking someone who already knows the layout. The precedent for fixing this already exists in-repo: **`campaignlib.py` was already split into `campaignlib/` (a package with `config.py`, `textproc.py`, `npc.py`, `scenes.py`, `pipelines.py`, `util.py`, `api/`), with `__init__.py` re-exporting the full public surface so `from campaignlib import X` kept working unchanged.** This proposal is that same move, applied to the 62 CLI scripts, grouped by pipeline.

## 2. Goals and non-goals

### Goals

- Replace "62 flat scripts" with **subsystem packages** whose names match how the docs already describe the system (session prep, session-doc pipeline, grounding docs, ensemble, RLM retrieval, content ingest, entity registry, external integrations).
- Make `CLAUDE.md`'s project-structure table accurate again — directory names carry information the flat root discards today.
- Keep the migration mechanical and independently reversible per cluster — no behavior changes, same CLI flags, same on-disk artifacts, same prompts.

### Non-goals

- **No logic changes.** This is a `git mv` + import-path exercise, not a rewrite. Anything that looks like a bug or dead code along the way gets a note in §6, not a fix.
- **No changes to `campaignlib/`, `session_doc/`'s existing helper modules, `server/`, `frontend/`, `config/`, `docs/`, `specs/`.** They're already organized; this proposal only touches the 62 flat root scripts (and, derivatively, whatever imports them).
- **No move for `llm-wiki/` or `scabard_sdk/`/`scabard_sync.py`.** Decided in §6 — both stay exactly where they are; not part of this restructure.

## 3. Target package layout

Every one of the 62 files, grouped by the pipeline it belongs to (per `docs/core/architecture.md` and the CLI docs under `docs/cli/`), with line counts to show this isn't an even split — some clusters are much larger than others:

| Cluster | Files | LOC | Home |
|---|---:|---:|---|
| `session_prep` | 2 | 478 | ✅ moved to `pipelines/session_prep/` |
| session-doc pipeline | 14 | 3,783 | **absorbed into the existing `session_doc/` package**, not a new one |
| `grounding` | 9 | 2,664 | ✅ moved to `pipelines/grounding/` |
| `ensemble` | 11 | 4,697 | ✅ moved to `pipelines/ensemble/` |
| `rlm` | 12 | 5,472 | ✅ moved to `pipelines/rlm/` |
| `content_ingest` | 5 | 3,339 | ✅ moved to `pipelines/content_ingest/` |
| `entity_registry` | 2 | 2,106 | ✅ moved to `entity_registry/` (top-level sibling to `campaignlib/`, see naming note below) |
| `integrations/kanka` | 4 | 885 | ✅ moved to `pipelines/integrations/kanka/` |
| `workspace` | 2 | 476 | ✅ moved to `pipelines/workspace/` |
| **Migrated total** | **61** | **23,900** | |
| `scabard_sync.py` | 1 | 307 | **not migrated** — stays at root alongside `scabard_sdk/`, per §6 decision |
| **Repo total** | **62** | **24,207** | |

### File-level mapping

**`pipelines/session_prep/`** — `prep.py`, `transform.py` (NotebookLLM dossier → prep.py input)

**`session_doc/`** (existing package, extended — see §4) — `sd_consistency.py`, `sd_plan.py`, `sd_narrate.py`, `assemble.py`, `narrative.py`, `quote_ledger.py`, `scene_extract.py`, `enhance_recap.py`, `enhance_summary.py`, `check_consistency.py`, `voice_lint.py`, `vtt_voice_compare.py`, `vtt_summary.py`, `scrub_mechanics.py` — these are the CLI entry points around the post-session pipeline described in `docs/cli/session_doc_pipeline.md`; the existing `session_doc/` package (`io.py`, `voice.py`, `roster.py`, `narrate.py`, `examples.py`) is already their shared-helper layer, so this is extension, not a new sibling with a colliding name.

**`pipelines/grounding/`** — `distill.py`, `campaign_state.py`, `planning.py`, `party.py`, `npc_table.py`, `make_tracking.py`, `arc_triggers.py`, `build_recent_events.py`, `normalize_bible_headings.py` — the four grounding docs (`campaign_state.md`, `world_state.md`, `planning.md`, `party.md`) and their supporting tools.

**`pipelines/ensemble/`** — `ensemble.py`, `ensemble_batch.py`, `ensemble_extract.py`, `ensemble_merge.py`, `extract_facts.py`, `facts_to_state.py`, `synthesise_facts.py`, `synthesise_polish.py`, `synthesise_world_state.py`, `split_chapters.py`, `polish.py` — the chapters → batch extraction → synthesis workflow in `docs/cli/ensemble_workflow.md`.

**`pipelines/rlm/`** — `rpg_retriever.py`, `fivetools_catalog.py`, `dossier_proposer.py`, `proposal_loader.py`, `mempalace_client.py`, `mcp_server.py`, `resolve_refs.py`, `launch_5etools_mcp.py`, `suggest_conversion.py`, `query.py`, `query_rpg_lib.py`, `apply_ingest_manifest.py` — retrieval, MCP tools, and the proposal-gate machinery in `docs/rlm/`.

**`pipelines/content_ingest/`** — `convert_book.py`, `fivetools_ingest.py`, `fivetools_copy.py`, `fivetools_render.py`, `dnd_sheet.py` — PDF/JSON → structured content converters.

**`entity_registry/`** — `registry.py`, `spell_canon.py` (imported by `registry.py`) — sibling to `campaignlib/`, not under `pipelines/`, because per `CLAUDE.md` this is a cross-cutting authority consumed by nearly every render pipeline, not a single-purpose pipeline itself. Decided in §6: this package name resolves the literal collision with `campaignlib.registry`; the read/write pairing itself is not renamed.

**`pipelines/integrations/kanka/`** — `kanka_client.py`, `kanka_mcp.py`, `kanka_push.py`, `kanka_sync.py`

**Not migrated:** `scabard_sync.py` and `scabard_sdk/` stay at repo root — decided in §6. There is no `pipelines/integrations/scabard/` in this pass.

**`pipelines/workspace/`** — `new_workspace.py`, `configure_mcp.py`

### Why `pipelines/` as an umbrella, not 8 new top-level directories

Flattening each cluster straight into repo root (`grounding/`, `ensemble/`, `rlm/`, …) trades "62 flat files" for "~18 flat top-level directories" once `campaignlib/`, `session_doc/`, `server/`, `frontend/`, `config/`, `docs/`, `tests/`, `specs/` are counted alongside. One `pipelines/` umbrella keeps the root listing roughly the same size it is today while still eliminating the flat-file sprawl inside it. `entity_registry/` is the one exception, placed as a `campaignlib/`-sibling rather than under `pipelines/`, because it's infrastructure other pipelines depend on, not a pipeline in its own right — this mirrors where `campaignlib/` already sits.

## 4. Coupling points that must move together

This is not a simple `git mv`. Four things currently depend on every one of these 62 files living at repo root; the first two exist for the same reason: **a script's own directory is what makes its sibling imports (`from campaignlib import X`) resolve, because Python puts a script's directory at `sys.path[0]`.** Today every root script's directory *is* the repo root, so `import campaignlib` / `import session_doc` just works with zero path configuration anywhere. Moving a script into a subdirectory breaks that invariant for exactly that script.

**1. Subprocess invocation from the web UI (29 call sites, `server/routers/*.py`) *and* from the MCP server (4 more call sites, `mcp_server.py`).** e.g. `server/routers/grounding.py:88`: `cmd = [python_exe(), str(SCRIPT_DIR / "campaign_state.py")]`, where `SCRIPT_DIR` is the repo root. `mcp_server.py` has the identical pattern via its own `_run_script()` helper for `query.py` (line 546), `prep.py` (line 563), `arc_triggers.py` (line 585), and `npc_table.py` (line 603) — easy to miss because it isn't under `server/routers/`. Some router call sites run with `cwd=str(Path.cwd())` (repo root), but several in `server/routers/scene_editor.py` run with `cwd=CONFIG.get("work_dir")` — the **campaign workspace directory**, not the repo. That matters: switching a moved script's invocation from `python <path>.py` to a bare module path would only resolve correctly if the repo root is separately reachable, since resolution depends on `sys.path`, not `cwd`. Resolved in §6: the editable install (`pip install -e .`) plus console-script entry points sidesteps this entirely — `campaign-state` (or whatever the entry point is named) resolves via the venv's `bin/`, independent of both the subprocess's `cwd` and the script's own location.

**2. Test imports (~100+ files under `tests/`).** Every test file does its own `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` then a bare `import prep` / `import registry` / `import quote_ledger`. Moving the target module means every test importing it needs its import line changed (mechanical, one line per file typically, but real churn across the suite — a scriptable rename, not a hand edit). The editable install removes the *need* for the `sys.path.insert` line going forward, but existing test files keep working with it in place, so this is a "clean up opportunistically," not "must fix" item.

**3. Documentation (15 files under `docs/`) with `python <script>.py` shell-fence examples** that reference scripts by root-relative name: `docs/cli/cli_tools.md`, `planning_pipeline.md`, `ensemble_extraction.md`, `fact-to-state-data-files.md`, `session_prep_workflow.md`, `session_doc_pipeline.md`, `post_session.md`, `grounding_docs.md`; `docs/rlm/rlm_pipeline.md`, `rlm_architecture.md`, `retrieval_architecture.md`, `refs_yaml_reference.md`; `docs/archive/local_grounding_docs.md`, `rlm_integration_plan.md`, `voice_fix_plan.md`. Not executable, so nothing breaks, but every one goes stale the moment the underlying script moves and its invocation changes. Covered by the "Final pass" step in §5.

**4. Cross-script imports within the 62 files themselves.** Confirmed by grep, not assumed:

| Imported module | Imported by |
|---|---|
| `dossier_proposer` | `proposal_loader` |
| `rpg_retriever` | `dossier_proposer`, `suggest_conversion` |
| `mempalace_client` | `rpg_retriever`, `fivetools_ingest` |
| `resolve_refs` | `fivetools_ingest`, `fivetools_catalog`, `launch_5etools_mcp` |
| `fivetools_copy`, `fivetools_render` | `fivetools_ingest` |
| `spell_canon` | `registry` |
| `synthesise_world_state`, `ensemble_merge` | `facts_to_state` |
| `vtt_summary` | `scene_extract` |
| `split_chapters` | `normalize_bible_headings` |
| `kanka_client`, `kanka_push`, `kanka_sync` | `kanka_mcp` |

Almost all of these edges stay inside one proposed cluster (e.g. the whole `kanka_*` chain lands in `pipelines/integrations/kanka/`). Three edges cross cluster boundaries and need real cross-package imports: `mempalace_client` (used by both `rlm` and `content_ingest`), `resolve_refs` (used by `content_ingest` and `rlm`), and `spell_canon` (`entity_registry`, conceptually bible-processing). None of these are a problem — they're just not free, and worth listing before someone hits a `ModuleNotFoundError` mid-migration and assumes they made a mistake.

**Decided in §6:** add `pyproject.toml` (build backend `hatchling`, flat — not `src/` — layout) and run `pip install -e .`. `~/src/mempalace/` is the only sibling repo with a `pyproject.toml` already (hatchling + flat layout, no `src/`); `~/src/mytools/` has no packaging at all. Matching mempalace's convention rather than inventing a third pattern. This makes every subpackage importable regardless of a script's own location or a subprocess's `cwd` — the robust fix for (1)–(4) instead of threading `PYTHONPATH` through 33 call sites by hand.

## 5. Migration phases

Each phase is independently shippable and testable; nothing later depends on later phases starting.

**Execution model:** the orchestrating conversation coordinates, reviews diffs, and runs the test suite between phases; it does not write the moves itself. Each cluster in Phase 1 (and the doc sweep in §7) is delegated to a subagent via the `Agent` tool, one per cluster, so the actual `git mv` / import-fix / doc-update work happens in a subagent rather than the main thread — consistent with this project's "Opus orchestrates, Sonnet codes" convention for approved multi-file plans.

1. **Phase 0 — add `pyproject.toml` (hatchling, flat layout) and `pip install -e .`.** Decided in §6. Nothing moves yet; this just makes the environment ready so every later phase can define console-script entry points as it goes rather than batching them at the end.
2. **Phase 1 — one cluster at a time, smallest first:** `workspace/` (2 files, 476 LOC) as a dry run, then `integrations/kanka/`, `session_prep/`, `content_ingest/`, `grounding/`, `entity_registry/`, `ensemble/`, `rlm/`, `session_doc/` absorption last (largest, most subprocess call sites). `scabard_sync.py` is not in this list — it stays at root (§6).
3. **Per-cluster steps:** `git mv` the files → fix intra-cluster relative imports → fix the cross-cluster edges from §4's table → add a `[project.scripts]` entry per moved script (entry-point name = original stem, e.g. `campaign_state = "pipelines.grounding.campaign_state:main"`) → update the cluster's subprocess call sites in `server/routers/` **and `mcp_server.py`** to invoke the console script instead of `python <path>.py` → update the cluster's test imports → update the cluster's **Tier-1 docs** from §7 → `python -m pytest tests/` green before moving to the next cluster.
4. **Final pass:** rewrite `CLAUDE.md`'s project-structure table, `docs/README.md`, and `docs/core/architecture.md` (heaviest edits — see §7); sweep remaining Tier-1 docs for anything missed per-cluster; batch the Tier-2 prose-only mentions from §7 into one pass.
5. **Follow-up (separate from this migration):** file the `scrub_mechanics.py` deletion issue described in §6 — not executed as part of Phases 0–4.

## 6. Decisions

Each of these was an open question in an earlier draft of this proposal; all six are now settled.

- **`llm-wiki/`** — leave in place, untouched. Not part of this restructure.
- **`scabard_sdk/` and `scabard_sync.py`** — leave both untouched. Neither moves; there is no `pipelines/integrations/scabard/` in this pass. Revisit separately if `scabard_sdk/` is ever split into its own repo.
- **`registry.py` naming** — leave as the documented read/write pairing. `entity_registry/` (root `registry.py` + `spell_canon.py`) resolves the literal package-name collision with `campaignlib/registry.py`; the pairing itself is not renamed.
- **`scrub_mechanics.py`** — confirmed deprecated: it's the old autonomous scrub pass, already superseded by the `/scrub` skill's propose→review→apply flow, tracked by the already-open **issue #151**. It is **not migrated** as part of this restructure. Follow-up: file a new issue referencing/closing #151 to delete `scrub_mechanics.py`, as separate work — not filed yet, pending review of this plan (filing a GitHub issue is a visible action outside the scope of "just write a proposal doc").
- **Packaging** — add `pyproject.toml` (`hatchling` build backend, flat layout) and `pip install -e .`, matching `~/src/mempalace/`'s existing convention (the only sibling repo with packaging already; `~/src/mytools/` has none).
- **Root CLI invocation surface** — clean cut. `python campaign_state.py` (etc.) stops working once a script moves; each migrated script gets a `[project.scripts]` console-script entry point instead (name = original stem, no shim files left behind). The 33 subprocess call sites (`server/routers/*.py` + `mcp_server.py`), ~100 test-file imports, and the 15-file docs list in §4 all update to match, per cluster, as each phase in §5 lands.

## 7. Keeping documentation in sync

A repo-wide sweep for the 62 script basenames (with/without `.py`, bare and backtick-quoted) across `docs/**/*.md`, `specs/**/*.md`, `CLAUDE.md`, and `TODO.md` hit **74 of 76 candidate files** — but a raw hit count overstates the real risk. Several basenames double as ordinary English words in this domain (`party`, `query`, `planning`, `polish`, `distill`) and match unrelated prose (a TODO about "the party" of PCs, not `party.py`). Treating every hit as a required edit would make the doc-sync step balloon past the migration itself. Splitting by what actually breaks vs. what merely goes stale:

**Tier 1 — breaks or actively misleads; update in the same pass as the cluster that moves:**
- **`CLAUDE.md`** (repo root) — not just the already-stale "Project structure" fence: the "Entity registry", "Retrieval/render separation", and "LLM renders, humans decide" prose sections all name specific scripts (`registry.py`, `prep.py`, `sd_narrate.py`, `planning.py`, `rpg_retriever`, `party.py`, `dossier_proposer.py`, …) that move.
- **`docs/core/architecture.md`** — the heaviest file in the repo for this: mermaid diagrams with scripts as node labels, an on-disk-state ASCII tree, six "Script | Role" tables, and a "common task → start here" table full of `[script.py](../../script.py)` relative links that 404 the moment the target moves.
- **`docs/README.md`** — the top-level nav index; inline script mentions throughout, lower link-density than architecture.md but still the front door.
- **Markdown files with literal relative links to a script** (not just prose mentions) — these are outright broken links once a target moves, not just stale text: `docs/design/SessionDocRefactor.md`, `docs/cli/session_doc_pipeline.md`, `docs/archive/plan_alias_pipeline.md`.
- **The 15 files with `python <script>.py` shell-fence examples** already listed in §4 point 3 — a copy-pasted stale command is worse than a stale sentence, since it fails silently differently (wrong error) rather than obviously.
- **This document itself.** `docs/design/SourceTreeRestructure.md`'s own §3 file-mapping table is the migration checklist — update its "Home" column per cluster as each one actually lands (e.g. "new package under `pipelines/`" → "✅ moved"), so it stays a live tracker through Phase 1 rather than going stale the moment Phase 1 starts.

**Tier 2 — real but lower-urgency prose/table mentions; batch into the Phase 4 final pass, not per-cluster:** `docs/cli/*`, `docs/config/*`, `docs/system/*`, `docs/rlm/*`, `docs/web/*`, and the other `docs/design/*` files. These describe scripts as system components in tables and prose — accurate in spirit after the move, just referencing the old bare name.

**Explicitly excluded — do not update:**
- **`docs/archive/**`** — `docs/README.md` already documents this directory as "shipped plans, deprecated docs, and one-time audits — kept for rationale, not currency." Editing archived docs to reflect a restructure they predate would contradict their own stated purpose.
- **`specs/001-ensemble-workflow-ui/**`** — a shipped, historical spec; leave as the historical record it is.
- **`specs/002-ensemble-run-observability/**`** — this one is the *currently active* plan per `CLAUDE.md`'s own pointer, so treat it differently from 001: update it only if the `ensemble` cluster migration actually changes an invocation it documents (e.g. `ensemble_batch.py`, `facts_to_state.py`), not as a blanket pass.
- **`TODO.md`** — mostly noisy matches (generic words, not script references). Spot-check rather than sweep.

## 8. Out of scope (deliberately)

- No changes to `campaignlib/`'s internal module split — it's already done and already the precedent this proposal follows.
- No changes to `frontend/`, `server/`'s own internal structure (only the call sites that reference moved script paths), `config/`, `docs/` content beyond updating stale script references, or `specs/`.
- No move for `llm-wiki/` or `scabard_sdk/`/`scabard_sync.py` — decided in §6 to leave both alone.
- No deletion of `scrub_mechanics.py` itself — only filing the tracking issue is contemplated here (§6), and that hasn't happened yet either; the delete is separate follow-up work after the issue is filed.
