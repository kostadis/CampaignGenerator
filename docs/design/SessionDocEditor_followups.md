# Session Doc Editor — Follow-ups

The four-phase rebuild described in the now-removed `RebuildSpecSessionDocEditor.md` has shipped (PRs #48 → #49 → #50). This doc tracks the work that was **explicitly deferred** during that rebuild, plus the two **adjacent refactors** that have design docs but no code yet.

Treat the items below as the punch list for "what would I do next on the Session Doc Editor before declaring the rebuild fully done."

---

## Deferred from the rebuild

Each of these was flagged in the matching PR body. None block the editor's day-to-day usability; they're refinements that the spec called for but that I chose not to land in the same PR to keep blast radius small.

### ~~`session_doc.py` CLI flag cleanup~~ (DONE — Phase 5 of SessionDocRefactor)

- **What** — drop `--from-extractions`, `--by-scene`, `--roleplay-extract-dir` from the argparse surface, and the internal code paths that branch on them.
- **Status (Phase 5 of SessionDocRefactor):** `session_doc.py` has been deleted. The legacy flags went with it. Pass 1 / Pass 3 / Pass 5 are now `session_doc/sd_consistency.py` / `session_doc/sd_plan.py` / `session_doc/sd_narrate.py`.
- **Acceptance** — `python -c "from session_doc import main"` still works; running the CLI with the new flags only (`--scene-extractions`, `--per-scene-output`, `--scene N`, `--plan-only`) succeeds; no `args.from_extractions` / `args.by_scene` / `args.roleplay_extract_dir` references remain.

### Amber-when-stale per-scene lifecycle dots

- **What** — when a scene's predecessor stage is `warn` (stale), the scene's E/R/N/S dots in `SceneList.vue` should render amber instead of green, even when the dot's own work is "done."
- **Why deferred** — the header pipeline-status strip already conveys the global staleness signal; per-scene amber rendering needs `_load_scenes()` to return mtime-vs-predecessor data, which is a small but separate increment.
- **Acceptance** — touch `session-summary.md` on disk → reload the editor → scenes whose extraction is older than the new summary show amber E dots; scenes whose narration is older than their extraction show amber N dots.

### `bad` pipeline status (failed run)

- **What** — the `GET /api/editor/pipeline-status` endpoint defines a `bad` status but never returns it. Should mean "the last run of this stage exited with rc != 0."
- **Why deferred** — the data is already in `<session_dir>/.cg/activity.jsonl` (every row has `rc`); the endpoint just needs to consult it. The plumbing landed in Phase 3 but I didn't wire the read.
- **Acceptance** — fail a Stage 1 run (e.g. by deleting the input VTT mid-run) → `pipeline-status` returns `enhance.status: "bad"` until a subsequent successful run flips it back.

### "Edit profiles" management modal

- **What** — bulk rename / delete / reorder profiles. Today's UI only handles create / save / revert / pick.
- **Why deferred** — uncommon op; punted on the modal to ship the dropdown.
- **Acceptance** — clicking an "Edit profiles" item in the dropdown opens a modal listing every profile with rename + delete affordances and a Done button.

### Stale-edit detection for narrations

- **What** — flag a scene whose extraction was edited *after* the narration was generated. Today the Review screen only flags un-narrated scenes ("not narrated → blocks Assemble"). It does **not** flag "narrated, but extraction has been touched since."
- **Why deferred** — the more-subtle case. Needs a per-scene mtime check (extraction mtime > narration mtime) — easy to compute in `api_scene_roster`, just not wired.
- **Acceptance** — narrate scene 3, then save a change to its extraction → the Review screen shows a "stale narration" callout on scene 3 and disables Assemble until it's re-narrated.

---

## Adjacent refactors (separate design docs, no code yet)

These are first-class refactors that the user planned but that have nothing to do with the editor rebuild structurally. Their full design docs live in this directory.

### Cleaned-VTT config resolver

- **Design doc** — [`CleanedVttConfigResolver.md`](CleanedVttConfigResolver.md)
- **Problem** — `server/routers/scene_editor.py:_vtt_path()` and `server/config.py:derive_campaign_paths` use two different globs to pick a `.vtt`, and can silently disagree about whether `*.cleaned.vtt` or `*.transcript.vtt` is the one fed to the LLM. Every per-session Otter mishearing that `/vtt-spell-pass` fixed gets re-injected when the wrong file is picked.
- **Status** — design only, no code. One unified `resolve_session_vtt(session_dir, campaign_config)` helper, a new `vtt:` block in per-campaign `config.yaml`, and a fatal `MissingCleanedVTTError` when `require_cleaned: true` and the cleaned pass hasn't been run.

### Scene-extract canon preference

- **Design doc** — [`SceneExtractCanonPreference.md`](SceneExtractCanonPreference.md)
- **Problem** — `session_doc/scene_extract.py` produces per-scene files whose `## Verbatim moments` paraphrase bullets use the VTT's surface vocabulary (e.g. "the West Inner Ward theology library") even when the `## Scene summary` block immediately above uses the canonical name (e.g. "Immortal Chambers"). The narration LLM downstream then silently re-injects every drift term the recap layer's consistency check already corrected.
- **Status** — design only, no code. One-line prompt-level instruction in `session_doc/scene_extract.py`'s SYSTEM prompt, telling it to prefer the scene-summary's proper nouns in its own prose while leaving verbatim `> "..."` quote blocks untouched.

---

## Reference

- [`TheFlow.md`](TheFlow.md) — the end-to-end workflow doc (CG-CLI + CG-UI + skills + MemPalace + manual seams). Not a TODO, kept as the canonical map of how the whole system actually runs.
- [`rlm_paper_comparison.md`](rlm_paper_comparison.md) — older RLM design comparison; unrelated to the editor rebuild.
