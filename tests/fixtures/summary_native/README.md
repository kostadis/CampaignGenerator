# summary_native fixtures

Synthetic corpora in the real OOTA summary shape. Each is a summaries directory;
the fixture directory itself is used as the campaign root in tests.

| Dir | Seeds |
|---|---|
| `clean/` | Chapters 002, 003, 005 (gap at 004). 7 scenes (3+2+2). "Manshoon" is an NPC in 002 and 005. No findings. |
| `multi_error/` | One instance of every per-file blocking code, 5 files. `session-notes.md`: no-numeric-prefix. `010-title-mismatch.md`: title-chapter-mismatch (title says 11) + empty-scenes. `011-no-title.md`: missing-title + missing-scenes. `012-bad-scenes.md`: bad-scene-id, scene-chapter-mismatch (013.01), duplicate-scene-id (012.02 twice). `012-duplicate.md`: duplicate-chapter with `012-bad-scenes.md`, plus an unknown `## Foreshadowing` section (unknown-section, non-blocking). |
| `out_of_range/` | `clean/` plus `008-late-session.md` whose title says Chapter 6 (title-chapter-mismatch, outside a range ending at 5). |
| `aliases/` | NPCs "Manshoon" (001), "Manshoon (Simulacrum)" (002), "Manshon" (003), "Lord Manshoon" (003, a registry alias), "Kazryn" (001; registry has "Kazryn Nyantani", so first-token inference would wrongly group it). "Staff of Power" under both Items and Spells in 002. "Staff of Frost" in 003. `entity_registry.yaml` has one npc alias (Lord Manshoon -> Manshoon). |
| `dup_chapter/` | Two files with prefix 003 (duplicate-chapter). |
