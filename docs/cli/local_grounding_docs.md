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

# 7. planning.md (Opus 4.8) — planning.py's plain synthesis over a CUT of the
#    npcs. planning is forward-looking, so restrict to the "important & in play"
#    NPCs rather than all 221: >=10 facts AND (spans >=5 chapters OR seen since
#    ch47). source_extracts (chapter list) lives in each npc's frontmatter;
#    n_facts in the matching oota-state/ dossier. Drop the "I" pronoun-leak junk.
mapfile -t FILES < <(python3 - <<'PY'
import glob, re
se=re.compile(r'^source_extracts:\s*\[([^\]]*)\]',re.M); nf=re.compile(r'^n_facts:\s*(\d+)',re.M)
nm=re.compile(r'^name:\s*(.+)$',re.M)
for f in sorted(glob.glob('scratch_output/oota-planning/npcs/*.md')):
    t=open(f).read()
    if nm.search(t).group(1).strip().lower()=='i': continue
    m=se.search(t); chs=[int(x) for x in m.group(1).split(',') if x.strip()] if m else []
    try: n=int(nf.search(open(f.replace('oota-planning/npcs/','oota-state/npc_')).read()).group(1))
    except Exception: n=0
    if n>=10 and (len(chs)>=5 or (chs and max(chs)>=47)): print(f)
PY
)
python planning.py --npc "${FILES[@]}" \
  --output scratch_output/planning_local.md --model claude-opus-4-8   # 65 npcs
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
- **`planning.md` built from an importance CUT (65 npcs), not all 221** — planning
  is forward-looking, so feeding every NPC makes a bloated, unprioritized doc.
  Cut = ≥10 facts AND (spans ≥5 chapters OR seen since ch47). Two artifacts to
  fix in review: it has **no real arc-scores** (the Threat Tracker is the model's
  judgement from dossier content, not tracked scores), and the first-person
  "narrator/I" leak produced a couple of conflated entries (e.g. Narrator /
  Librarian / Yvenne merged). Fact-count is a recurrence proxy, not narrative
  importance — a pivotal one-scene NPC can fall below the cut; sanity-check it.
- **Significance floors used:** world_state `--dossier-min-facts 20` (89
  entities; ≥10 = 191, ≥40 = 42 ≈ the existing doc's scope). planning: the
  ≥10-facts + breadth/recency cut above (65 npcs).
- **Models:** extraction/aggregation on local Qwen Instruct (a reasoning-model
  A/B with Nemotron was deferred); all synthesis on Opus 4.8.

## Token cost vs the old per-tool path
Old (`distill`/etc., all API): each doc re-extracts → ~2.5–3.4M metered tokens
for the full set. New: extract once locally (~9M local tokens, ~free) +
per-doc synthesis ≈ **~280K metered tokens total** (world_state ~128K,
campaign_state ~50K, party ~15K, planning ~85K, npcs 0). ~10–12× less API; the
gap widens with each additional doc, since extraction is shared not repeated.
