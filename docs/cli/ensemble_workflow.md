# Ensemble extraction workflow

End-to-end guide: from a set of chapter files to reviewed dossiers ready for synthesis into the four grounding docs (`world_state.md`, `campaign_state.md`, `party.md`, `planning.md`).

The core insight is that **extraction is expensive and should happen once**. Running the Claude API inside each grounding-doc tool (the old path) re-extracts the same chapter text three or four times, spending 2.5–3.4M metered tokens per full refresh. The local ensemble approach extracts once on Spark hardware (~free), aggregates to per-entity dossiers, lets a human review scope, then calls the API only for the final synthesis per doc (~280K tokens total).

For a description of the individual tools used here, see [`ensemble_extraction.md`](ensemble_extraction.md) (ensemble.py flags) and [`local_grounding_docs.md`](../archive/local_grounding_docs.md) (provenance of the first two full runs).

---

## Pipeline at a glance

```
docs/chapters/chapter_*.md
  ↓  ensemble_batch.py  (local, Spark)
docs/ensemble/per_chapter/<stem>/merged.json   — atomic facts per chapter
  ↓  facts_to_state.py --list                  — HUMAN CHECKPOINT: scope review
  ↓  facts_to_state.py                         (local, Spark)
docs/ensemble/state_dossiers/*.md              — per-entity current-state dossiers
  ↓  synthesise_world_state.py                 (API or subscription)
docs/world_state_draft.md

  ↓  campaign_state.py --synthesize-only       (API — staging trick)
docs/campaign_state_draft.md

  ↓  party.py --synthesize-only                (API — staging trick)
docs/party_draft.md

  ↓  planning.py --npc <cut>                   (API)
docs/planning_draft.md
```

Outputs always land in `*_draft.md`. Diff against the live doc and promote by hand after review.

---

## Prerequisites

**Corpus layout** — one `docs/chapters/chapter_NN_<title>.md` file per chapter, named so that `glob('chapter_*.md')` returns them in chapter order. A single concatenated file works too (pass it directly to `ensemble.py`), but the batch driver assumes per-chapter files.

**Spark hardware** — see [`HOWTO_122B.md`](../ensemble/HOWTO_122B.md) for the 122B Ray-cluster setup. The 80B dual-endpoint setup is the default and needs no extra steps beyond having both Spark containers running. Spark host names: `spark` (192.168.1.147) and `spark2` (192.168.1.121).

**Known-names sources** (for Stage 2 entity disambiguation):
- `docs/background/*inventory.md` — bold-marked proper nouns from module PDFs
- `notes/neverwinter/*inventory.md` — same for region lore
- `docs/npcs/.dedup_state.json` — confirmed alias clusters from a prior npc-dedup pass

All three are optional but strongly recommended. Without them, `facts_to_state.py` cannot distinguish "Aldric" (named NPC) from "guard" (anonymous encounter label) and will produce one merged dossier for every guard in the campaign.

**Aliases file** (`docs/ensemble/aliases.json`) — optional spelling-variant map produced by `ensemble_merge.py`'s alias proposals and reviewed manually or with `review_aliases.py`. Pass it to `facts_to_state.py` with `--aliases` to canonicalise subject names before bundling.

---

## Stage 1 — Ensemble extraction

### 1a. Plan YAML

The plan YAML lives alongside the ensemble workspace and controls which extraction lenses run on each chapter. The Phandalin plan:

```yaml
# docs/ensemble/plan.yaml
passes:
  - name: small
    agent: extract_facts
    chunk_size: 6000
    annotate_pov: true
  - name: large
    agent: extract_facts
    chunk_size: 15000
    annotate_pov: true
  - name: sweep
    agent: extract_facts_sweep
    chunk_size: 15000
    annotate_pov: true
  - name: temporal
    agent: extract_facts_temporal
    chunk_size: 15000
    annotate_pov: true
  - name: interiority
    agent: extract_facts_interiority
    chunk_size: 15000
    annotate_pov: true
```

`annotate_pov: true` prepends a `[Continuing — Date: X, Speaker: Y]` banner to any chunk that doesn't open with its own `##`-level heading. The chapters use `### Speaker` headings to mark POV sections; without this, chunking at character boundaries drops the heading and the model invents generic labels ("Narrator", "Speaker") as dossier subjects.

To target different files per pass (e.g. a GM-assist doc for the interiority lens), add a `document:` key per pass:

```yaml
passes:
  - name: interiority
    agent: extract_facts_interiority
    chunk_size: 15000
    annotate_pov: true
    document: gm-assist.md     # relative to the plan file
```

### 1b. Batch driver

`ensemble_batch.py` iterates over all chapter files, runs `ensemble.py` per chapter in parallel, and concatenates the results. It is the generalised replacement for campaign-local `run.py` scripts.

```bash
# Run from the ensemble directory (where plan.yaml lives)
cd ~/Phandalin/Phandalin/docs/ensemble

python ~/src/CampaignGenerator/ensemble_batch.py \
  --chapters '../chapters/chapter_*.md' \
  --per-chapter-dir per_chapter \
  --out merged.json \
  --plan plan.yaml \
  --endpoints http://spark:8001/v1 http://spark2:8001/v1 \
  --model Qwen/Qwen3-Next-80B-A3B-Instruct-FP8 \
  --chunk-parallel 4 \
  --unit-timeout 0 \
  --embed-endpoint http://spark2:8000 \
  --embed-model Qwen/Qwen3-Embedding-0.6B \
  --embed-threshold 0.93 \
  --chapter-parallel 3
```

The run is **resumable**: chapters whose `per_chapter/<stem>/merged.json` already exists are skipped. If a chapter fails, fix and re-run; completed chapters are not re-extracted.

**Key batch flags:**

| Flag | Default | Purpose |
|---|---|---|
| `--chapters GLOB` | required | Glob for chapter files |
| `--per-chapter-dir DIR` | `./per_chapter` | Root for per-chapter workdirs |
| `--out FILE` | `./merged.json` | Combined output file |
| `--chapter-parallel N` | 3 | Chapters in flight at once |
| `--plan YAML` | `./plan.yaml` if it exists | Passed through to `ensemble.py` |

All `ensemble.py` endpoint and model flags (`--endpoints`, `--model`, `--chunk-parallel`, `--speculative`, `--unit-timeout`, `--embed-endpoint`, etc.) are accepted and passed through verbatim.

**Key ensemble flags to know:**

| Flag | Default | Purpose |
|---|---|---|
| `--samples N` | 1 | Re-run each pass N times; union results. Improves recall on nondeterministic extraction. `n_samples` per fact is recorded in merged.json for human review. |
| `--dry-run` | off | Print resolved plan only (which file each pass reads). Use before committing to a long run. |
| `--skip NAME` | none | Skip one named pass (repeatable). Use when iterating on a single-lens prompt fix. |
| `--unit-timeout SEC` | 600 | Kill a stalled unit and re-queue. Set to 0 for reasoning models (122B) that emit 10K–30K thinking tokens before JSON output. |
| `--speculative` / `--no-speculative` | on | When one endpoint stalls, a free endpoint re-runs its unit; first to finish wins. Use `--no-speculative` for attended runs where you may grab a Spark mid-job. Needs 2+ endpoints. |

### 1c. Output layout

After a successful run, `per_chapter/` contains one directory per chapter:

```
per_chapter/
  chapter_02_arrival_in_phandalin/
    small.jsonl          ← per-pass raw facts
    large.jsonl
    sweep.jsonl
    temporal.jsonl
    interiority.jsonl
    manifest.json        ← maps each pass to source file
    merged.json          ← deduplicated facts for this chapter
  chapter_03_to_find_a_shapeshifter/
    ...
merged.json              ← all chapters concatenated (with source_chapter field)
```

`merged.json` (the root one) is the input to Stage 2.

---

## Stage 1a — Alias review (optional, recommended)

`ensemble_merge.py` generates alias proposals (spelling variants of the same entity) alongside each chapter's `merged.json`. The Phandalin workspace includes `review_aliases.py` as a local interactive reviewer; alternatively, edit `aliases.json` by hand.

Pass the reviewed file to `facts_to_state.py --aliases` in Stage 2 so variant spellings ("Bupido" / "Buppido") are collapsed before bundling. Without this step, one entity ends up in two separate bundles that never merge.

The alias file lives at `docs/ensemble/aliases.json` in the Phandalin workspace.

---

## Stage 2 — Fact bundling

`facts_to_state.py` is the compression layer between raw atomic facts and the per-entity dossiers that synthesis consumes. It groups every fact about one `(type, subject)` pair in chapter order, then asks the local model to collapse them into a single current-state dossier.

### 2a. The `--list` checkpoint (always run first)

Before spending model time on aggregation, run `--list` to see the full entity coverage and the known/location-scoped split:

```bash
cd ~/Phandalin/Phandalin

python ~/src/CampaignGenerator/facts_to_state.py \
  --corpus 'docs/ensemble/per_chapter/*/merged.json' \
  --aliases docs/ensemble/aliases.json \
  --known-names docs/background/dragon-of-icespire-peak-inventory.md \
                notes/neverwinter/neverwinter-inventory.md \
                docs/npcs/.dedup_state.json \
  --min-facts 3 \
  --list
```

This prints something like:

```
Known names: 860 normalised entries from 3 source(s)
Corpus:   45 file(s)
Entities: 1886 of types ['npc', 'faction', 'location', 'object', 'monster']
          (212 known / 1674 location-scoped) (>= 3 facts: 439)
Selected: 439 for aggregation

  [known]     930  npc        Vukradin  (ch 2-45)
  [known]     590  npc        Soma  (ch 2-45)
  [known]     512  npc        Valphine  (ch 2-45)
  ...
  [location]   37  npc        Prutha (Circle of Thunder)  (ch 40-41)
  [location]   20  monster    manticore (windmill)  (ch 5-5)
```

**This is the human scope checkpoint.** Review:
- Are the PCs tagged `[known]`? (They should be.)
- Are major recurring NPCs tagged `[known]`? (Adabra, Harbin, Falcon, etc.)
- Are obviously anonymous labels (`guard`, `bandit`, `orc`) scoped to location? (They should be.)
- Is the `--min-facts` floor reasonable? (3 is the lower bound for anything worth a dossier; 10 is a good synthesis floor.)

`--list` does not call the model. Use it freely.

### 2b. `--known-names`: named vs anonymous entity splitting

Without `--known-names`, `facts_to_state.py` produces one global bundle per `(type, subject)` key — every orc encounter in the campaign collapses into a single "Orc" dossier. With `--known-names`, entities whose normalised name appears in any of the source files are treated as named individuals (global bundle); everything else is scoped to its chapter location (e.g. `Orc (Phandalin)`, `Orc (Wayside Inn)`).

Sources can be:
- **Inventory `.md` files** — bold-marked proper nouns are extracted. First word of a multi-word name (≥ 4 chars) is also added as a short-form match.
- **`.dedup_state.json`** — `clusters_confirmed` aliases, canonical filename stems, and `pc_files_skipped` stems. This covers short forms like "Adabra" (from `adabra.md`) and PC names like "Soma" (from `soma.md`).

### 2c. Aggregation — known entities only

Run aggregation with `--known-only` to skip anonymous location-scoped bundles. They appear in `--list` tagged `[location]` and can be addressed in a later dedup pass if needed.

```bash
python ~/src/CampaignGenerator/facts_to_state.py \
  --corpus 'docs/ensemble/per_chapter/*/merged.json' \
  --aliases docs/ensemble/aliases.json \
  --known-names docs/background/dragon-of-icespire-peak-inventory.md \
                notes/neverwinter/neverwinter-inventory.md \
                docs/npcs/.dedup_state.json \
  --known-only \
  --min-facts 3 \
  --out-dir docs/ensemble/state_dossiers \
  --endpoints http://spark:8001/v1 http://spark2:8001/v1 \
  --model Qwen/Qwen3-Next-80B-A3B-Instruct-FP8
```

The run is **resumable**: entities whose dossier file already exists in `--out-dir` are skipped automatically.

**`--min-facts` floors:**

| Floor | Dossiers (Phandalin 45ch) | Use |
|---|---|---|
| ≥ 3 | ~193 | Everything worth having a dossier at all |
| ≥ 10 | ~88 | Good synthesis floor — broad enough for factions, recurring locations, minor NPCs |
| ≥ 20 | ~37 | Tight floor — core cast only |

Use ≥ 3 for the aggregation run (don't discard facts at this stage). The synthesis tools have their own `--dossier-min-facts` filter that you apply per-doc.

### 2d. Threads track (zero model tokens)

Plot threads and mysteries are factual and don't need synthesis — render them directly:

```bash
python ~/src/CampaignGenerator/facts_to_state.py \
  --corpus 'docs/ensemble/per_chapter/*/merged.json' \
  --aliases docs/ensemble/aliases.json \
  --types thread \
  --min-facts 2 \
  --render-only docs/ensemble/threads.md
```

This writes a chapter-tagged markdown file with no model call. Feed it to `synthesise_world_state.py --threads` if thread coverage looks thin from dossier bodies alone.

### 2e. Fallback: `--split-gap` (no inventory files)

If no inventory or dedup-state files exist, use `--split-gap N` to split bundles where consecutive chapter gaps exceed N. This is a mechanical heuristic — it won't distinguish a named NPC who stops appearing for 10 chapters from two different orcs encountered 10 chapters apart. Prefer `--known-names` when inventory files are available.

---

## Stage 3 — Synthesis

Two paths: **API** (`ANTHROPIC_API_KEY`) or **Subscription** (claude.ai, no key needed). The subscription path is available for `world_state` today; the other docs use the API via their `--synthesize-only` staging trick.

### 3a. world_state — API path

```bash
cd ~/Phandalin/Phandalin

python ~/src/CampaignGenerator/synthesise_world_state.py \
  --dossiers 'docs/ensemble/state_dossiers/*.md' \
  --dossier-min-facts 10 \
  --party config/party.yaml \
  --backstories 'docs/Backstory - Brewbarry.md' \
               'docs/Backstory - Valphine Sotorra.md' \
               'docs/Soma - Backstory.md' \
  --threads docs/ensemble/threads.md \
  --output docs/world_state_draft.md \
  --model claude-opus-4-8
```

`--dossier-min-facts 10` filters at synthesis time — you can re-run with a different floor without re-aggregating. Add `--threads` if you ran the threads track in 2d; omit it if not (thread coverage will come from dossier bodies).

**Token cost estimate (Phandalin, ≥10 facts, 88 entities):** ~128K metered tokens.

### 3b. world_state — Subscription path (claude.ai)

`--dump-input` + `--dump-only` assemble the full prompt and write it to disk without making an API call:

```bash
python ~/src/CampaignGenerator/synthesise_world_state.py \
  --dossiers 'docs/ensemble/state_dossiers/*.md' \
  --dossier-min-facts 10 \
  --party config/party.yaml \
  --backstories 'docs/Backstory - Brewbarry.md' \
               'docs/Backstory - Valphine Sotorra.md' \
               'docs/Soma - Backstory.md' \
  --threads docs/ensemble/threads.md \
  --dump-input /tmp/world_state_prompt.md \
  --dump-only
```

This writes:
- `/tmp/world_state_prompt.md` — the user turn (all dossiers assembled)
- `/tmp/world_state_prompt.md.system.md` — the system prompt

Open claude.ai, start a new conversation, paste the system prompt first, then the user prompt. Copy the response to `docs/world_state_draft.md`.

`campaign_state.py` and `party.py` do not have `--dump-only` yet; for those, use the API path below.

### 3c. campaign_state — staging trick

`campaign_state.py` expects its synthesis input as `extract_*.md` files. Stage the world_state and threads as extracts:

```bash
mkdir -p /tmp/phandalin-cstate/extracts
cp docs/world_state_draft.md /tmp/phandalin-cstate/extracts/extract_001_world_state.md
cp docs/ensemble/threads.md  /tmp/phandalin-cstate/extracts/extract_002_threads.md

python ~/src/CampaignGenerator/campaign_state.py \
  --synthesize-only \
  --extract-dir /tmp/phandalin-cstate/extracts \
  --output docs/campaign_state_draft.md \
  --model claude-opus-4-8
```

**Caveat:** `campaign_state_draft.md` is a derivation of `world_state_draft.md`, not a fresh extraction from raw event facts. Its "completed encounters" coverage is only as rich as world_state captured.

### 3d. party — staging trick

Stage the four PC dossiers as extracts:

```bash
mkdir -p /tmp/phandalin-party/extracts

# Copy each PC's dossier; glob handles the slug suffix
cp docs/ensemble/state_dossiers/npc_valphine*.md  /tmp/phandalin-party/extracts/extract_001_valphine.md
cp docs/ensemble/state_dossiers/npc_brewbarry*.md /tmp/phandalin-party/extracts/extract_002_brewbarry.md
cp docs/ensemble/state_dossiers/npc_soma*.md      /tmp/phandalin-party/extracts/extract_003_soma.md
cp docs/ensemble/state_dossiers/npc_vukradin*.md  /tmp/phandalin-party/extracts/extract_004_vukradin.md

python ~/src/CampaignGenerator/party.py \
  --synthesize-only \
  --extract-dir /tmp/phandalin-party/extracts \
  --backstory 'docs/Backstory - Brewbarry.md' \
              'docs/Backstory - Valphine Sotorra.md' \
              'docs/Soma - Backstory.md' \
  --output docs/party_draft.md \
  --model claude-opus-4-8
```

**Caveat:** `party_draft.md` has no D&D Beyond-sourced class/level/arc-scores — it's the narrative/role half only. If you need those, run the full `party.py` pass with character sheet PDFs.

### 3e. planning — importance cut

`planning.py` consumes NPC dossier files directly with `--npc`. Feed only the entities worth forward-looking planning; the full dossier set produces a bloated, unprioritized doc.

Importance cut: **≥10 facts AND (spans ≥5 chapters OR seen since chapter 40)**. The inline Python below filters the dossier directory and writes matching filenames into a bash array:

```bash
cd ~/Phandalin/Phandalin

mapfile -t NPC_FILES < <(python3 - <<'PY'
import glob, re
nf = re.compile(r'^n_facts:\s*(\d+)', re.M)
se = re.compile(r'^source_extracts:\s*\[([^\]]*)\]', re.M)
nm = re.compile(r'^name:\s*(.+)$', re.M)
for f in sorted(glob.glob('docs/ensemble/state_dossiers/npc_*.md')):
    t = open(f).read()
    m = nm.search(t)
    if not m or m.group(1).strip().lower() in ('narrator', 'speaker', 'i'):
        continue
    n = int(nf.search(t).group(1)) if nf.search(t) else 0
    chs_m = se.search(t)
    chs = [int(x) for x in chs_m.group(1).split(',') if x.strip()] if chs_m else []
    if n >= 10 and (len(chs) >= 5 or (chs and max(chs) >= 40)):
        print(f)
PY
)

python ~/src/CampaignGenerator/planning.py \
  --npc "${NPC_FILES[@]}" \
  --output docs/planning_draft.md \
  --model claude-opus-4-8
```

**Caveats:**
- Fact-count is a recurrence proxy, not narrative importance. A pivotal one-scene NPC can fall below the cut; sanity-check the list before running.
- The planning doc has no real arc-scores — the Threat Tracker is the model's judgement from dossier content, not tracked scores. This is a known limitation.
- The `narrator` / `speaker` filter above removes POV-label artifacts (entities where `annotate_pov` wasn't enough to prevent the model from using the banner text as a subject name). Check for those in `--list` output.

---

## Stage 4 — Review and promotion

All outputs land in `*_draft.md`. **Never write directly to the live docs.**

Review each draft:
- Each dossier has an `## Uncertainty` block listing facts the model flagged as ambiguous. Skim these before trusting synthesis — scope/ordering/attribution are the model's weak spots.
- Diff `world_state_draft.md` against `world_state.md` before promoting. The diff is the edit surface; don't copy blindly.
- For `planning_draft.md`, check the NPC list against your own sense of who matters — the importance cut may miss forward-looking significance (an NPC who appeared rarely but is about to become central).

Promote by hand:

```bash
diff docs/world_state.md docs/world_state_draft.md | less
cp docs/world_state_draft.md docs/world_state.md
```

---

## Token cost summary

| Stage | Where | Metered tokens (Phandalin) |
|---|---|---|
| Ensemble extraction (45 ch × 5 lens) | Spark (local) | ~0 metered |
| Fact bundling + dossier aggregation | Spark (local) | ~0 metered |
| world_state synthesis | API / subscription | ~128K |
| campaign_state synthesis | API | ~50K |
| party synthesis | API | ~15K |
| planning synthesis | API | ~85K |
| threads track | Spark (deterministic) | 0 |
| **Total** | | **~280K** |

Old per-tool API path (distill / planning / party / campaign_state each re-extracting from the chapter bible): **~2.5–3.4M metered tokens** per full refresh. The gap widens with each additional doc, since extraction is shared here but repeated there.

---

## See also

- [`ensemble_extraction.md`](ensemble_extraction.md) — single-file extraction, merge options, `--samples` and `--dry-run` patterns
- [`local_grounding_docs.md`](../archive/local_grounding_docs.md) — provenance and notes from the OotA and Phandalin full runs
- `docs/ensemble/HOWTO_122B.md` — 122B Ray-cluster setup and `run.py` configuration for the denser model
