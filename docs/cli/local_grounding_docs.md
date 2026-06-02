# Building the grounding docs from local ensemble extraction

An alternative to the per-tool Claude-extraction path in
[`grounding_docs.md`](grounding_docs.md). Instead of each tool
(`distill`/`planning`/`party`/`campaign_state`) re-extracting from the bible on
the Claude API, you **extract once locally** (the DGX-Spark ensemble), aggregate
to per-entity current-state dossiers, and then run only a small **synthesis**
call per doc. The expensive extraction is done once and shared across all four
docs; only the finish-quality synthesis touches the API.

See `dgx-fun/local-compute-as-experiment-capital.md` for why (capex/opex,
iteration cost). This doc is the **how** + the provenance of the first full run.

## Pipeline

```
session chapters
  → ensemble_extract.py        (LOCAL, both Sparks)  → gen-chNN/merged.json   (atomic facts)
  → facts_to_state.py          (LOCAL)               → per-entity dossiers + threads track
  → synthesis (Opus 4.8, API)                        → world_state / campaign_state / party
  → to_planning_npcs.py        (deterministic)       → planning npcs/  (no model call)
```

Extraction + aggregation are **local** (~free, modulo power). Only the final
synthesis per doc is metered API. `npcs` cost **zero** API tokens.

## First full run — Out of the Abyss (2026-06-01)

Corpus: `scratch_output/full-oota/gen-ch*/merged.json` — 56 chapters, **22,240
atomic facts** (5-lens × 3-sample ensemble on Qwen3-Next-80B across spark1
`192.168.1.147:8001` + spark2 `192.168.1.69:8001`).

All commands run from the CampaignGenerator repo root. **Every output lands in
`scratch_output/` (gitignored)** — review, then promote to
`~/campaigns/out-of-the-abyss/docs/`.

```bash
EP="--endpoints http://192.168.1.147:8001/v1 http://192.168.1.69:8001/v1 --model Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
INV=~/campaigns/out-of-the-abyss/notes/sessions/out_of_the_abyss_module_inventory.md
DOC=~/campaigns/out-of-the-abyss/docs

# 1. Per-entity current-state dossiers (LOCAL) — 703 dossiers, ≥3 facts
python facts_to_state.py --corpus 'scratch_output/full-oota/gen-ch*/merged.json' \
  --min-facts 3 --out-dir scratch_output/oota-state $EP

# 2. Threads / mysteries track (LOCAL, deterministic — no model)
python facts_to_state.py --corpus 'scratch_output/full-oota/gen-ch*/merged.json' \
  --types thread --min-facts 2 --render-only scratch_output/oota-threads.md

# 3. world_state.md (Opus 4.8) — 89 dossiers (≥20 facts) + threads
python synthesise_world_state.py \
  --dossiers 'scratch_output/oota-state/*.md' --dossier-min-facts 20 \
  --threads scratch_output/oota-threads.md \
  --party $DOC/party.yaml --inventory "$INV" \
  --backstories "$DOC/*_backstory.md" \
  --output scratch_output/world_state_local.md --model claude-opus-4-8

# 4. npcs/ for planning.py (deterministic converter — no model)
python scratch_output/to_planning_npcs.py        # -> scratch_output/oota-planning/npcs/ (221)

# 5. campaign_state.md (Opus 4.8) — STAGE world_state + threads as extracts,
#    then run campaign_state.py's synthesize pass only (skips its Claude extract).
mkdir -p scratch_output/oota-campaign-state/extracts
cp scratch_output/world_state_local.md scratch_output/oota-campaign-state/extracts/extract_001_world_state.md
cp scratch_output/oota-threads.md      scratch_output/oota-campaign-state/extracts/extract_002_threads.md
python campaign_state.py --synthesize-only \
  --extract-dir scratch_output/oota-campaign-state/extracts \
  --output scratch_output/campaign_state_local.md --model claude-opus-4-8

# 6. party.md (Opus 4.8) — STAGE the 4 PC dossiers as extracts + backstories.
mkdir -p scratch_output/oota-party/extracts
i=1; for pc in daz zalthir thorin grygum; do \
  cp scratch_output/oota-state/npc_$pc.md scratch_output/oota-party/extracts/extract_00${i}_$pc.md; i=$((i+1)); done
python party.py --synthesize-only \
  --extract-dir scratch_output/oota-party/extracts \
  --backstory $DOC/daz_backstory.md $DOC/zalthir_backstory.md $DOC/thorin_backstory.md $DOC/grygum_backstory.md \
  --output scratch_output/party_local.md --model claude-opus-4-8
```

### The "staging" trick (steps 5–6)
`synthesise_world_state.py` learned `--dossiers`/`--threads` directly.
`campaign_state.py` and `party.py` did **not** get a dossier input — instead we
use their existing `--synthesize-only` path and copy our artifacts in as
`extract_*.md`, so they run their synthesis prompt over our distilled material
and skip their own (Claude) extraction pass.

## Caveats (read before promoting)
- **All outputs are in `scratch_output/` (gitignored).** Nothing is promoted to
  `docs/` automatically — diff against the existing docs and copy over by hand.
- **Human review is the precision checkpoint.** Each dossier ends with a
  `## Uncertainty` block; skim those (and the cross-entity roster hedges) before
  trusting the synthesis. Scope/ordering/attribution are the model's weak spots.
- **`campaign_state_local.md` is a derivation of a derivation** — built from
  `world_state` + threads, so its "completed encounters" detail is only as rich
  as world_state captured, not pulled fresh from the raw `event` facts.
- **`party_local.md` has no character sheets / arc-scores** — class/level/player
  fields are blank and there are no Candidate Arc Score Events. It's the
  narrative/role half of what `party.py` produces from D&D Beyond PDFs.
- **`planning.md` was NOT generated** — only the `npcs/` (its input). To finish:
  `planning.py --synthesize` over the npcs (+ arc-scores + context).
- **Significance floor:** world_state used `--dossier-min-facts 20` (89
  entities). ≥10 = 191, ≥40 = 42 (≈ the existing doc's scope).
- **Models:** extraction/aggregation on local Qwen Instruct (a reasoning-model
  A/B with Nemotron was deferred); all synthesis on Opus 4.8.

## Token cost vs the old per-tool path
Old (`distill`/etc., all API): each doc re-extracts → ~2.5–3.4M metered tokens
for the full set. New: extract once locally (~9M local tokens, ~free) +
per-doc synthesis ≈ **~193K metered tokens total** (world_state ~128K,
campaign_state ~50K, party ~15K, npcs 0). ~15× less API; the gap widens with
each additional doc, since extraction is shared rather than repeated.
