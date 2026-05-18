# Dossier merge workflow & cross-pipeline alias propagation

## Why it exists

`planning.py --build-dossiers` splits on exact `## <name>` section headers, so name variants in the summaries ("Captain Tolubb" vs "Tolubb", typos like "Xalvos" vs "Xalvosh") produce duplicate files. Merge them manually, then record the variants in the surviving file's `aliases:` frontmatter so synthesis can resolve references in raw session extracts back to the canonical NPC.

Every dossier is created with frontmatter:

```markdown
---
name: Tolubb
aliases: []
---

# Tolubb
...
```

## Merge rules

1. Pick the canonical file (usually the cleanest name or the one with the most data).
2. For each file folded in: append its `name` value **and** all entries in its `aliases:` list into the canonical file's `aliases:` list.
3. Reconcile the body per duplicate type:
   - **Pure duplicate, no unique data** → delete loser, no body edit needed.
   - **One file has most data** → keep the richer body, just fold the name into aliases.
   - **Both have unique data** → merge the bodies (manually, or ask Claude) before deleting.
4. Delete the folded-in files.

**After-merge example** — `captain_tolubb.md` and `cap_tolubb.md` folded into `tolubb.md`:

```markdown
---
name: Tolubb
aliases:
  - Captain Tolubb
  - Cap. Tolubb
---

# Tolubb
[reconciled body]
```

**Why this matters:** `run_synthesize()` in `planning.py` parses each dossier's `aliases:`, compiles a case-insensitive longest-first regex, and rewrites every occurrence of a variant in session extractions, arc-scores, and context files to the canonical name **before the LLM sees them**. It also prepends an `# ENTITY RESOLUTION` block to the system prompt listing canonical ↔ alias pairs. Aliases not recorded in frontmatter = synthesis treats the variant as a distinct NPC, re-fragmenting exactly what the merge was supposed to fix.

Dossiers without frontmatter (pre-existing files) still work — `parse_dossier()` falls back to the filename stem as name and empty aliases — but they can't contribute aliases. Add frontmatter to any dossier that has known variants.

## Cross-pipeline alias propagation

Every extractor that calls the shared pipeline accepts `--dossier-dir` and plumbs the dossier alias map through both passes:

| Script | How it uses `--dossier-dir` |
|---|---|
| `distill.py` | `input_normalizer` rewrites aliases in summaries before extract + synthesize; roster appended to both system prompts. |
| `campaign_state.py` | Same as distill. |
| `party.py` | Legacy flat-flag path uses `run_synthesize_pipeline`'s kwargs; `--party-config` path routes the normalizer through `_render_party_block` / `_render_source_group` and appends the roster to `SYNTHESIZE_SYSTEM` manually. Both extract and synthesize passes covered. |
| `vtt_summary.py` | Both extract passes (summary + roleplay) and both synthesize passes. Reference summaries are normalized along with the VTT dialogue. |
| `session_doc.py` | `--dossier-dir` loads the alias map once at the top of `main()`. Shared inputs (recap, roleplay extractions, summary extractions, session summary) are normalized once before the per-scene loop; the roster is appended to `CHAR_EXTRACT_SYSTEM` when the per-scene prompt is built. |
| `planning.py --build-dossiers` | Self-seeds: reads its own `--dossier-dir` to assemble the roster, passes it as `system_suffix` to the Phase 1 extract prompt so re-builds don't re-fragment NPCs already merged. |

Underlying machinery lives in `campaignlib.py`:

- `load_alias_map(dossier_dir)` — scans `*.md`, skips `.new_notes.*.md` sidecars, returns `{canonical: [aliases]}`. Empty dict for missing/empty dirs.
- `build_alias_normalizer(alias_map)` — returns `(normalize, entries)`. `normalize` is a case-insensitive longest-first regex rewrite; empty map yields identity.
- `format_npc_roster(alias_map)` — renders the "Known NPCs" block; empty map yields `""`.
- `run_extract_pipeline` / `run_synthesize_pipeline` accept `input_normalizer` and `system_suffix` kwargs; defaults are no-ops.

All helpers collapse cleanly when no dossier dir is provided — every extractor is safe to call without a planning workflow. Intentionally excluded: `query.py` (search-side expansion ≠ canonicalization) and `prep.py` (reads pre-normalized grounding docs; nothing to canonicalize at its layer).
