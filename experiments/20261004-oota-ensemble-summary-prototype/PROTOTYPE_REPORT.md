# Direct `docs/summaries` Ensemble Prototype

## Scope

This prototype reads the 67 structured Markdown files in `docs/summaries/`
without replacing the existing chapter-based ensemble corpus. All generated
inputs live under `docs/ensemble_summary_prototype/`, and the final review
drafts use separate filenames:

- `docs/world_state_summary_draft.md`
- `docs/campaign_state_summary_draft.md`

The live `docs/world_state.md` and `docs/campaign_state.md` were not modified.

## Implementation checkout

- Worktree: `/tmp/campaigngenerator-direct-summary-prototype`
- Branch: `prototype/direct-summary-ensemble`
- Coding model: `gpt-5.6-terra`
- Orchestration model: `gpt-5.6-sol`

The worktree contains both the direct-summary ensemble input prototype and the
deterministic summary-native aggregator. The latter is the path used for the
full-corpus drafts.

## Full-corpus result

`summary_native` parsed all source files in numeric filename order and wrote:

- `summary_native/manifest.json`
- `summary_native/chronology.md`
- `summary_native/memorable_moments.md`
- `summary_native/dossiers/*.md`
- `summary_native/synthesis_context.md`

Coverage and validation:

- 67 of 67 summary files
- 409 scene headings
- 868 entity dossiers
- 590 NPC entries
- 319 location entries
- 394 item entries
- 301 spell entries
- 1 ability entry
- 60 memorable-moment sections preserved as exact H2 bodies
- 1 identity mismatch recorded: `070-session-untitled.md` has filename chapter
  70 but H1 chapter 66; filename identity remains authoritative
- all 868 dossiers load through `read_dossiers`, with zero missing chapter ranges
- 8 focused tests pass
- `git diff --check` passes in the prototype worktree

The synthesis calls used Claude Code model `claude-opus-5-5` at medium effort.
World-state synthesis selected all 75 entities touched in chapters 67–70 and
10 recurring background entities with at least 10 source entries. It also
received the complete compact 409-scene chronology and exact memorable-moment
corpus. Campaign-state synthesis used the resulting world-state draft plus that
same complete summary-native context and the three configured tracking files.

## Comparison with the live documents

The live documents stop at chapter 63. The drafts are current through chapter
70 and include the vault sequence, both destroyed Manshoon simulacra, Edvaldo's
escape, the opened Obsidian Door, and Daz's contact with the Book of Vile
Darkness.

| Document | Live | Summary draft | Main difference |
|---|---:|---:|---|
| World state | 27,393 bytes / 204 lines | 32,573 bytes / 337 lines | Adds a separate vault, Manshoon, and key-items view plus ch64–70 events |
| Campaign state | 14,473 bytes / 140 lines | 41,523 bytes / 706 lines | Adds detailed chapter coverage and a 443-item evidence audit |

The campaign-state draft marks 51 requested tracking claims as `NOT FOUND` in
the summaries rather than promoting the tracking files to canon. This is useful
evidence that tracking targets and observed campaign facts need distinct source
roles.

## DGX experiment

A four-lens extraction attempt was stopped after throughput projected roughly
7–10 hours on the one reachable endpoint. Partial small-lens outputs for
chapters 002–005 and prepared lineage inputs for 002–013 remain under
`per_summary/`; they were not used for the final drafts. On structured
summaries, deterministic scene/entity aggregation produced full source coverage
quickly and avoided asking a model to rediscover headings already present in
the documents.

## Design lessons

1. Treat numeric filenames as stable chapter identity and preserve an explicit
   mismatch field for conflicting H1 headings.
2. Parse the summary schema directly. Scene H3s provide the chronological
   spine; NPC, location, item, spell, and ability appendices provide dossier
   observations with exact provenance.
3. Keep summary-derived artifacts in their own corpus. Mixing them with chapter
   ensemble outputs would double count the same sessions and blur provenance.
4. Apply recency and recurrence selection only at synthesis time. The lossless
   868-dossier corpus remains reviewable while the world-state prompt stays
   within a practical context budget.
5. Preserve tracking files as questions to audit, not evidence. The 51
   `NOT FOUND` results exposed planned or module-default events that never
   appeared in the summaries.
6. Add category-aware canonicalization before production. Exact registry alias
   matching is safe for a prototype, but the 868 dossiers still contain nearby
   headings that a reviewed normalization layer could merge.
7. Stage long synthesis inputs. The world-state call hit Claude Code's per-turn
   output ceiling and auto-continued once; the concatenated file is structurally
   complete, but a production workflow should budget or stage output explicitly.

## Reproduction commands

```bash
python -m pipelines.ensemble.summary_native \
  --summaries 'docs/summaries/*.md' \
  --out-dir docs/ensemble_summary_prototype/summary_native \
  --registry docs/entity_registry.yaml

python -m pytest -q \
  tests/test_summary_native.py \
  tests/test_ensemble_direct_summary_prototype.py
```

The exact synthesis prompts were retained as
`summary_native/world_state_synthesis_prompt.md` and
`summary_native/campaign_state_synthesis_prompt.md`, with their corresponding
`.system.md` files.

## Party and planning follow-up

The same summary-native corpus was subsequently used to produce two more
review drafts without modifying the live documents:

- `docs/party_summary_draft.md`
- `docs/planning_summary_draft.md`

Both calls used Claude Code model `claude-opus-5-5` at medium effort. Their
exact inputs remain in `summary_native/party_synthesis_prompt.md` and
`summary_native/planning_synthesis_prompt.md`, with corresponding `.system.md`
files.

The party call used `config/party.yaml`, its four character sheets and
backstories, the promoted summary-derived world/campaign state, and the full
summary-native context. The result is current through chapter 70 and keeps all
four PCs intentionally trackless, as configured.

`config/planning.yaml` contains no active NPC, faction, or arc-score entries.
The planning call therefore used a deterministic current/recurrent selection
of 23 summary-native NPC dossiers: every NPC last seen in chapters 67–70 plus
older NPCs with at least 10 observations. The selection and its reasons are
recorded in `summary_native/planning_dossiers_manifest.json`. The output keeps
the Threat Tracker empty instead of inventing scores.

Comparison with the live chapter-63 documents:

| Document | Live | Summary draft | Main difference |
|---|---:|---:|---|
| Party | 9,468 bytes / 64 lines | 13,980 bytes / 251 lines | Advances every PC through ch70 and corrects the unsupported level-9 claim to level 8 |
| Planning | 29,211 bytes / 319 lines | 14,252 bytes / 273 lines | Replaces stale broad coverage with a current-scene plan centered on the Book, Edvaldo, the Avowed, and Manshoon |

The live `docs/party.md` and `docs/planning.md` hashes remained unchanged.
