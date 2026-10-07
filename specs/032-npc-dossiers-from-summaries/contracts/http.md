# HTTP Contract: `/api/npc-dossiers`

- **Router:** `server/routers/npc_dossiers.py`, included in `server/main.py`.
- **Run routes:** shell out to `console_script("summary_native")` with an explicit argv and stream the result through the existing SSE helper (`stream_subprocess`, Principle VI). argv is built only in `_build_link_cmd`, `_build_draft_cmd`, `_build_verify_cmd`, `_build_compose_cmd` and `_build_publish_cmd`.
- **No hardcoded flags:** every CLI flag the GM can choose is a route parameter (Principle XI).
- **Defaults:** resolved at the route edge from `NpcDossiersConfigService.resolved()` and `GroundingConfigService.resolved().summary_native`. There are no default literals in the router (Principle XII), and `tests/test_npc_dossiers_config_defaults.py` enforces that.

## Config — `<config>/npc_dossiers.yaml` (strict, `extra="forbid"`)

```yaml
npc_root: docs/npcs/summary_native
recent_chapters: 4
recurring_min: 10
max_tokens: 16000
draft:
  backend: dgx
  model: qwen3.8-flash-next
  mode: chunked          # chunked | one-shot
  chunk_chars: 60000
```

- `GET /config` returns the resolved config.
- `PUT /config` validates and saves it (a 422 response for an unknown key).
- `summaries_dir`, `out_root`, `registry`, `canon_file` and the range defaults are **not** here. They are read from `grounding.yaml summary_native`, the one place they are spelled.

## Read-only

| Method & path | Returns |
|---|---|
| `GET /chapters?summaries_dir=` | Same shape as `/api/grounding/summary-native/chapters` (shared helper) |
| `GET /state?since=&until=` | `{range, linked: bool, link_stale: bool, warnings: {ambiguous, generic_unruled}, npcs: [{stem, subject, global, exclusion, n_entries, n_scenes, n_moments, first_seen, last_seen, draft: none\|drafted\|incomplete\|stale, published: bool, verify: none\|pass\|fail, authored: bool, composed: bool}]}` |
| `GET /report/link?since=&until=` | `link_report.json` (404 if not linked) |
| `GET /report/verify/{stem}?since=&until=` | That NPC's verification result |
| `GET /file?since=&until=&kind=evidence\|draft\|gm\|published&stem=` | The file's text, for display only. No write route exists for any of these |

## Runs (SSE, `GET`)

| Path | argv |
|---|---|
| `/run/link?summaries_dir&since&until&force` | `summary_native npc-link --summaries-dir … --since … --until … [--force]` |
| `/run/draft?…&select=all\|narrowed&name[]&recent_chapters&recurring_min&dump_only&force&model&backend…` | `summary_native npc-draft … (--all \| [--name …] [--recent-chapters N] [--recurring-min N]) [--dump-only] [--force]` + `selection_cli_args(resolve_selection(..., service_name="npc_dossiers"))` |
| `/run/verify?…&name[]` | `summary_native npc-verify … [--name …]` |
| `/run/compose?…&name[]&init[]` | `summary_native npc-compose … [--name …] [--init …]` |
| `/run/publish?…&select=named\|all\|authored_all&name[]&source&force` | `summary_native npc-publish … (--name … \| --all \| --authored-all) [--source …] [--force]` |

**Refusals before spawning:**
- No range given: a 400 response. "All chapters" must be chosen deliberately (Constitution X).
- `/run/draft` without `select`: a 400 response. "Every global NPC" must be chosen deliberately.
- `/run/publish` without `select`: a 400 response. Publishing is always an explicit choice.
- None of these refusals spawns a process.
- The migration has no route. It follows the existing `server/migrate_*.py` precedent: a one-shot operator CLI documented in `migration.md`, and Constitution XIII says it runs deliberately, out of band.

## Frontend

- **View:** `frontend/src/views/npcs/NpcDossiers.vue`, at route `/npcs/dossiers`.
- **Sidebar:** a new top-level "NPCs" path in `AppSidebar.vue`, separate from Grounding. The GM ruled that NPCs and grounding documents are different things.
- **Sections:**
  1. range picker;
  2. Link (run, plus a warning badge and the link report table);
  3. Draft (explicit selection, backend/model, dump-only/force);
  4. a per-NPC table from `/state`;
  5. Verify;
  6. Compose GM dossiers (after a Secrets-only edit) and `--init` for chosen NPCs;
  7. Publish (named, all, or all hand-built; shows each refusal and its reason).
- **Display only:** the page shows draft, GM and published dossiers read-only, and lists dropped manual edits per NPC. Editing authored files, drafts and rulings happens in files, the CLI or chat (Principle IX).
- **Guard:** `frontend/e2e/sidebar-navigation.spec.ts` gains the new path, and the Grounding → summary-native page is asserted to have no NPC stages.
