# Continuation note — local-LLM fact extraction pipeline

Paused before building `synthesise_world_state.py`. Resume here.

## Where we are

A 5-pass local-LLM ensemble + Claude polish pipeline is built and validated on `chapter_03_escape.md`. Architecture:

```
session.md
  ↓ ensemble_extract.py            (5 local-LLM passes on DGX)
merged.json                         (atomic facts, deterministic merge)
  ↓ synthesise_polish.py            (Claude, grounded in inventory.md)
polished.md                         (extract_NNN.md-shape, per session)
```

Polish output is **competitive with `distill_extractions/extract_004.md`** on chapter_03 content. The hand-taking (Stool/Grygum) and round-trip transformation (Topsy/Turvy → rats → gnomes) gaps are closed after the no-abstract rule and gesture-category fix landed.

## Pipeline components (all checked in)

- `ensemble_extract.py` — 5-pass driver, deterministic merge
- `synthesise_facts.py` — Layer-1 deterministic grouping (atomic facts → bulleted profiles)
- `synthesise_polish.py` — Layer-2 Claude render, supports `--inventory` and `--aliases`
- `extract_facts.py` — single-pass extractor used by ensemble; supports `--agent NAME`; has `_salvage_objects` fallback for malformed JSON
- `config/agents/extract_facts.md` — generalist (small + large passes), has no-abstract rule
- `config/agents/extract_facts_sweep.md` — breadth/exhaustive lens
- `config/agents/extract_facts_temporal.md` — dates, counts, distances, values
- `config/agents/extract_facts_interiority.md` — thoughts/feelings/refusals + gesture category #9

Schema: 8 types — `npc`, `faction`, `event`, `location`, `object`, `monster`, `thread`, `date`.

## Validated outputs

- `runs/chapter03/merged.json` — 223 facts, includes hand-taking + round-trip transform
- `runs/chapter03/polished_v5.md` — extract_004-shape, hand-taking landed, round-trip partially landed (Turvy profile has it; Topsy profile and World Events bullet drop it)

## The strategic pivot we just made

`extract_004.md` (in `distill_extractions/`) is NOT the goal — it's distill.py's pass-1 intermediate. The actual goal is `world_state.md` (cumulative campaign canon), then `party.md`, then `campaign_state.md`.

`synthesise_polish.py` produces per-session prose; it parallels distill.py's pass-1 output. For the world_state goal, polish is a detour. The cleaner architecture skips polish and synthesizes world_state directly from atomic facts:

```
session_NN.md → ensemble_extract.py → merged_NN.json
                                           ↓ (accumulate across all sessions)
                          synthesise_world_state.py  (one Claude call)
                                           ↓
                                      world_state.md
```

## Where we paused

About to build `synthesise_world_state.py`. **Three design questions to answer before coding:**

### Q1: Corpus scope for the first test

We have `chapter_03/merged.json` only. Twenty+ chapter source files exist but haven't been through the ensemble. Options:

- **A.** Build synthesizer, test on chapter_03 alone — fast shape validation, thin content
- **B.** Run ensemble on all chapters first — slow upfront, meaningful first output
- **C.** Bootstrap with existing `distill_extractions/extract_*.md` files as substitute corpus — immediate fuller test of synthesizer prompt without committing to 20 ensemble runs

Recommended: **A first, then C, then B as the long-tail backfill.**

### Q2: Full regeneration vs. incremental update

- **Full regen** every run: all merged.json → fresh world_state.md. Simple, ~200K input tokens for a 20-session campaign (~$0.60/run with prompt caching).
- **Incremental**: prior world_state.md + new session → patched output. Cheaper but risks state drift.

Recommended: **full regen for v1**, optimize later.

### Q3: Other grounding context to feed Claude

Required:
- merged.json corpus
- `inventory.md` (canon spellings/identities)
- `party.yaml` (PC roster — anchors PC sections)

Optional but probably yes:
- Per-PC backstory docs (`daz_backstory.md`, etc.) — contain campaign-level facts session extracts don't capture
- **NOT** the prior `world_state.md` (would anchor regen to old content)

## Proposed script signature

```bash
python synthesise_world_state.py \
  --corpus 'runs/*/merged.json' \
  --inventory ~/campaigns/out-of-the-abyss/notes/sessions/out_of_the_abyss_module_inventory.md \
  --party docs/party.yaml \
  --backstories 'docs/*_backstory.md' \
  --output docs/world_state.md
```

## After world_state.md works

Same pattern for the other two goals:
- `synthesise_party.py` → `party.md` (collective party state, resources, obligations, reputation)
- `synthesise_campaign_state.py` → `campaign_state.md` (completed encounters, NPC state changes, world consequences)

Both consume the same merged.json corpus + their own additional grounding context.

## Open tasks

1. **#1: Add vLLM guided decoding** for fact extraction. Would prevent the few invented-type / malformed-JSON failures we've seen. Schema is now 8 types.
2. **#2: Parallelise ensemble across two DGX Sparks.** Run sweep on Spark A while small/large/temporal/interiority run on Spark B. Approximately halves wall-clock. Need second Spark's IP.

## Useful files for tomorrow

- Source: `~/campaigns/out-of-the-abyss/docs/chapters/chapter_03_escape.md` (the test session)
- Inventory: `~/campaigns/out-of-the-abyss/notes/sessions/out_of_the_abyss_module_inventory.md`
- Party roster: `~/campaigns/out-of-the-abyss/docs/party.yaml`
- Current canonical world state: `~/campaigns/out-of-the-abyss/docs/world_state.md` (reference for shape only)
- Existing per-session extracts: `~/campaigns/out-of-the-abyss/docs/distill_extractions/extract_*.md` (potential bootstrap corpus for Q1 option C)
- Test outputs: `runs/chapter03/merged.json` and `runs/chapter03/polished_v5.md`
