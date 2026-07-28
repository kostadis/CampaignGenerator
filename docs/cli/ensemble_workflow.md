# Ensemble extraction workflow

> **Run this from the UI.** The Ensemble Workflow page (`/ensemble` in the web UI)
> mechanizes this whole sequence — Setup → Extract → Bundle → Synthesize — with the
> scope-review, alias-correction, and diff-before-promote checkpoints kept as gates
> you satisfy in the CLI or a Claude chat. Each LLM-bearing stage is backend-selectable
> (Anthropic / DGX-Spark / **OpenRouter**), chosen independently for extraction and
> synthesis. The UI only invokes the same CLI commands documented below; nothing here
> is bypassed. See `docs/web/web_ui.md` and `specs/001-ensemble-workflow-ui/`.

End-to-end guide: from a set of chapter files to reviewed dossiers ready for synthesis into the four grounding docs (`world_state.md`, `campaign_state.md`, `party.md`, `planning.md`).

The core insight is that **extraction is expensive and should happen once**. Running the Claude API inside each grounding-doc tool (the old path) re-extracts the same chapter text three or four times, spending 2.5–3.4M metered tokens per full refresh. The local ensemble approach extracts once on Spark hardware (~free), aggregates to per-entity dossiers, lets a human review scope, then calls the API only for the final synthesis per doc (~280K tokens total).

For a description of the individual tools used here, see [`ensemble_extraction.md`](ensemble_extraction.md) (ensemble flags) and [`local_grounding_docs.md`](../archive/local_grounding_docs.md) (provenance of the first two full runs).

---

## Pipeline at a glance

```
docs/chapters/chapter_*.md
  ↓  ensemble_batch  (local, Spark)
docs/ensemble/per_chapter/<stem>/merged.json   — atomic facts per chapter
  ↓  facts_to_state --list                     — HUMAN CHECKPOINT: scope review
  ↓  facts_to_state                            (local, Spark)
docs/ensemble/state_dossiers/*.md              — per-entity current-state dossiers
  ↓  (Stage 2e: merge type-duplicate dossiers — human step)
docs/ensemble/merged_dossiers/*.md             — type-merged dossiers, ready for synthesis
  ↓  synthesise_world_state                    (API or subscription)
docs/world_state_draft.md

  ↓  campaign_state --synthesize-only          (API — auto-stages world_state + threads)
docs/campaign_state_draft.md

  ↓  party --party-config config/party.yaml    (API — human-authored roster, no staging)
docs/party_draft.md

  ↓  planning --npc <cut>                      (API)
docs/planning_draft.md
```

Outputs always land in `*_draft.md`. Diff against the live doc and promote by hand after review.

---

## Prerequisites

> **Batch mode:** with `--backend anthropic --batch`, `extract_facts` (and
> `ensemble`, which forwards the flag) groups all cache-miss chunks into one
> Message Batch at 50% token cost — block-and-poll, atomic per-chunk cache
> writes, non-zero exit on any failed chunk with the rest cached. The
> synthesis CLIs (`synthesise_world_state`, `synthesise_polish`,
> `facts_to_state`) accept it too; `polish` accepts but ignores it (agentic
> tool-use loop — prints a notice). Unrelated to `ensemble_batch`, the local
> multi-chapter dispatcher. See `docs/cli/cli_tools.md` § Shared flag.


### Spelling / proper-noun consistency pass (always run before Stage 1)

AI transcription services (Zoom, Otter, Whisper) mangle proper nouns differently session to session. The ensemble model will create a separate entity for each surface variant — `Xenophon`, `Xenobon`, and `Zenvon` all become independent subjects — and the alias-review step (Stage 1a) can only collapse variants that appeared in the *same corpus run*. Correcting them upstream before extraction is cheaper and more reliable.

Before running Stage 1:
1. **Identify canonical spellings** — cross-reference character sheets (`characters/`), name glossaries (`docs/background/*inventory.md`), and published module names against the actual text of each source file.
2. **Correct in the authoritative source first** — for campaigns using session summaries as input, edit `summaries/*/zoom_summary.md` (or equivalent) and then re-copy to `docs/chapters/`. For campaigns with hand-written chapter files, edit in place.
3. **Check the notes directory too** — prep docs and improv logs written during early sessions often inherit the same misspellings.

Common categories of transcription error: PC name variants (one per session), sidekick name truncation (`Mela` for `Maela`), NPC surname garbling (`Edermeth` for `Edermath`), and proper nouns from the published module (`Nethrel` for `Netheril`, `Tribor Trail` for `Triboar Trail`).

After correcting, re-copy any `docs/chapters/` files that were generated from the originals before re-running the batch.

---

**Corpus layout** — one `docs/chapters/chapter_NN_<title>.md` file per chapter, named so that `glob('chapter_*.md')` returns them in chapter order. A single concatenated file works too (pass it directly to `ensemble`), but the batch driver assumes per-chapter files.

**Spark hardware** — see [`HOWTO_122B.md`](../ensemble/HOWTO_122B.md) for the 122B Ray-cluster setup. The 80B dual-endpoint setup is the default and needs no extra steps beyond having both Spark containers running. Spark host names: `spark` (192.168.1.147) and `spark2` (192.168.1.121).

**Known-names sources** (for Stage 2 entity disambiguation):
- `docs/background/*inventory.md` — bold-marked proper nouns from module PDFs
- `notes/neverwinter/*inventory.md` — same for region lore
- `docs/npcs/.dedup_state.json` — confirmed alias clusters from a prior npc-dedup pass

All three are optional but strongly recommended. Without them, `facts_to_state` cannot distinguish "Aldric" (named NPC) from "guard" (anonymous encounter label) and will produce one merged dossier for every guard in the campaign.

**Aliases file** (`docs/ensemble/aliases.json`) — optional spelling-variant map produced by `ensemble_merge`'s alias proposals and reviewed manually or with `review_aliases.py`. Pass it to `facts_to_state` with `--aliases` to canonicalise subject names before bundling.

### Keep aliases.json generated, not hand-maintained

Name corrections tend to **fragment across stores** — a spelling table in a notes
file, the `vtt-spell-pass` skill's corrections glossary, the module
`name_glossary.md`, and a hand-edited `aliases.json` — and they silently drift:
a fix made in one never reaches the others. Pick **one source of truth** and
*generate* `aliases.json` from it.

The natural SoT is the `vtt-spell-pass` skill's corrections glossary,
`notes/vtt_transcription_corrections.md` (`add_to_glossary.py` writes it;
sections `## PCs / ## NPCs and creatures / ## Items / ## Locations / ## …`, rows
`| wrong, forms | **Right** |`). A small generator inverts those wrong→right rows
into `{canonical: [variants]}` and writes `aliases.json`:

```python
# docs/ensemble/build_aliases.py  — run after editing the corrections glossary
import json, re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]
CORRECTIONS = ROOT / "notes/vtt_transcription_corrections.md"
OUT = ROOT / "docs/ensemble/aliases.json"

# variant -> canonical. Bundling-only forms that must NOT be substituted into
# transcript text (the word-boundary applier would double-expand a short form,
# e.g. "Sildar Hallwinter" -> "...Hallwinter Hallwinter"). The ONLY hand-edited list.
BUNDLING_ALIASES = {
    "Sildar": "Sildar Hallwinter",
    "Nikhil Reddy": "Zenvon",   # player -> character
}

row_re, bold_re = re.compile(r"^\|\s*(.+?)\s*\|\s*(.+?)\s*\|\s*$"), re.compile(r"\*\*(.+?)\*\*")
edges = {}
def add(v, c):
    v, c = v.strip(), c.strip()
    if v and c and v.lower() != c.lower(): edges[v] = c
for ln in CORRECTIONS.read_text().splitlines():
    m = row_re.match(ln)
    if not m or m.group(1).strip().lower() == "wrong" or set(m.group(1).strip()) <= set("-:| "): continue
    bm = bold_re.search(m.group(2)); canon = re.sub(r"\s*\(.*\)\s*$", "", (bm.group(1) if bm else m.group(2))).strip()
    for w in m.group(1).split(","): add(w, canon)
for v, c in BUNDLING_ALIASES.items(): add(v, c)
def resolve(n, seen=None):           # collapse chains: Toblin -> Toblen -> Toblen Stonehill
    seen = seen or set()
    while n in edges and n not in seen: seen.add(n); n = edges[n]
    return n
out = defaultdict(set)
for v in edges: out[resolve(v)].add(v)
OUT.write_text(json.dumps({c: sorted(s) for c, s in sorted(out.items())}, indent=2, ensure_ascii=False) + "\n")
```

**Two classes, one direction of flow:**
- **Garbles** (`Xenophon → Zenvon`, `Ruth exceeds → Ruxithid`) live in the
  corrections glossary — they are safe to substitute into transcript text *and*
  feed `aliases.json`.
- **Bundling-only aliases** (short forms, titles, player→character) live in the
  generator's `BUNDLING_ALIASES` — they must never be written into transcripts,
  only collapsed during fact bundling.

Replace any per-campaign "spelling corrections" table in notes with a pointer to
the glossary, and re-run the generator after each spell-pass. `name_glossary.md`
stays a separate concern: module canon, identity, and GM rulings — not a pipeline
input.

### New or small campaign (no inventory / dedup sources yet)

This guide is written against a **mature campaign** (e.g. Phandalin: 45 chapters,
~1900 entities, an 860-entry known-names set). The known-names sources above
(`*inventory.md`, `.dedup_state.json`) are artifacts that only exist *because* of
that scale and prior dedup passes. A brand-new campaign (a handful of sessions, a
few hundred facts) has none of them — pass the doc's literal `--known-names` paths
and every entity falls through to `[location]`-scoped, fragmenting each recurring
character into one dossier per location.

For a small or fresh campaign, **build the two inputs by hand from the `--list`
output** — it's a 10-minute pass, not a pipeline:

1. Run Stage 2a `--list` with no `--known-names` to print the entity universe.
2. Write `docs/ensemble/known_names.md` — a markdown file with every named
   individual / faction / place in **bold** (bold proper nouns are what the
   extractor reads; the first word of a multi-word name ≥4 chars is auto-added as
   a short-form). This is the small-scale substitute for the inventory files.
3. Write `docs/ensemble/aliases.json` — `{canonical: [variants]}` — to merge name
   variants (`Sildar` / `Sildar Hallwinter`) and fold any player-name → PC
   attribution the extractor produced (`Nikhil Reddy` → `Zenvon`).
4. Re-run `--list` with both; confirm the cast is now `[known]` and only
   anonymous labels (goblins, guards) remain `[location]`-scoped.

**If the campaign runs a published module, you already have half of input #2.** The
`gm-module-inventory` skill produces `docs/background/<module>-inventory.md` — a
bold-marked proper-noun list of the module's NPCs/locations/items/factions. Pass it
directly as a `--known-names` source; it covers the canon cast for free. Your
hand-written `known_names.md` then only needs the **homebrew** additions the module
inventory deliberately omits — the PCs, renamed/campaign-original NPCs, and
campaign-original items. Worked example (Hillsfar/DDEX34, 15 sessions): staged each
per-session `gm-assist.md` as `docs/chapters/chapter_NN_*.md`, passed the module
inventory *and* a ~30-line campaign `known_names.md`, plus an `aliases.json` that
folded title/spelling variants (`High Inquisitor Veris` → `Veris`, `Mezzoloth` →
`Mezzaloth`) and the PC character-sheet *typo* spellings into the authoritative
narrative spellings (`Akrita` → `Akritas`, `Daien` → `Daein`). Because the
`gm-assist.md` files are human-authored (not raw Zoom dumps), the out-of-character
DM/player-entity scan came up clean — no table-talk re-homing was needed.

Also note that at this scale several downstream stages are near-trivial rather
than the heavy passes they are for a mature campaign: **2e (type-merge)** may be a
single entity (e.g. one NPC also extracted as a monster), and the **`--min-facts`**
floors (≥3 / ≥10 / ≥20) barely change the selected set across a few dozen
entities — just use ≥3.

**Watch for out-of-character entities.** Small-campaign transcripts come straight
from VTT/Zoom AI summaries, which capture table talk: the DM and players appear as
"NPCs" (`Kostadis served as the Dungeon Master`; `Nikhil Reddy chose Short Sword as
his Weapon Mastery`). Before aggregating, scan the `--list` for real names / table
chatter and decide per entity: **drop the label but keep in-world content** by
re-homing each fact to its true subject (DM narration about an NPC → that NPC),
and drop only the pure rules/pacing/logistics lines. This is a precision
(attribution) decision — do it as a reviewed corpus edit, not silently.

---

## Stage 1 — Ensemble extraction

### 1a. Plan YAML

The plan YAML lives alongside the ensemble workspace and controls which extraction lenses run on each chapter. `annotate_pov: true` is now the built-in default for all 5 lenses (`ensemble_extract`'s `PASSES`), so a plan.yaml only needs to mention it to *override* that default, e.g. to turn it off, or to add a custom pass. The Phandalin plan, written before that default existed, still spells it out explicitly:

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

`annotate_pov: true` prepends a `[Continuing — Date: X, Speaker: Y]` or `[Continuing — Speaker: X, Scene: Y]` banner to any chunk that doesn't open with its own `##`-level heading. Two chapter-heading conventions are recognized:

- **Legacy** (Phandalin and OOTA's earlier chapters): `### Speaker` headings mark POV sections, `## date` marks date boundaries (two tiers).
- **Current** (`assemble`, OOTA's later chapters): `## Speaker — Scene` marks both the speaker and scene in one `##`-level heading, with no `###` tier.

Without this annotation, chunking at character boundaries drops whichever heading is in scope, and the model invents generic labels ("Narrator", "Speaker", or literal "I") as dossier subjects.

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

`ensemble_batch` iterates over all chapter files, runs `ensemble` per chapter in parallel, and concatenates the results. It is the generalised replacement for campaign-local `run.py` scripts.

```bash
# Run from the ensemble directory (where plan.yaml lives)
cd ~/Phandalin/Phandalin/docs/ensemble

ensemble_batch \
  --chapters '../chapters/chapter_*.md' \
  --per-chapter-dir per_chapter \
  --out merged.json \
  --plan plan.yaml \
  --endpoints http://spark:8001/v1 http://spark2:8001/v1 \
  --model Qwen/Qwen3-Next-80B-A3B-Instruct-FP8 \
  --chunk-parallel 4 \
  --unit-timeout 0 \
  --embed-endpoint http://192.168.1.121:11434 \
  --embed-model qwen3-embedding:0.6b \
  --embed-threshold 0.94 \
  --chapter-parallel 3
```

The run is **resumable**: chapters whose `per_chapter/<stem>/merged.json` already exists are skipped. If a chapter fails, fix and re-run; completed chapters are not re-extracted.

**Facts carry a `quote_offset`** — the character position of their `source_quote` inside the chapter, stamped at merge time ([#195](https://github.com/kostadis/CampaignGenerator/issues/195)). This is the within-chapter event sequence: `facts_to_state` orders every bundle by `(chapter, quote_offset)`, so a dossier narrates an entity's arrival before its death rather than in the merge's alphabetical order. `null` means the quote could not be located in the source — usually a fabricated or `...`-stitched quote, the same signal `quote_verified` carries — and those sort *last* within their chapter. **Corpora merged before this exists have no offsets and degrade to chapter-only ordering; re-running the merge adds them without re-extracting** (the per-lens `*.json` are already on disk, so it costs seconds, not GPU hours).

**The `--embed-*` flags are not optional polish.** Omit `--embed-endpoint` and the merge falls back to `--method subject`, which groups on `(type, subject)` and therefore *never compares facts filed under different subjects* — a whole class of cross-subject duplicate and contradiction is invisible to it. Since [#197](https://github.com/kostadis/CampaignGenerator/issues/197) that fallback prints a warning and marks its method line `[fallback — no embed endpoint]`; pass `--method subject` explicitly to choose it deliberately and silence the warning. From the web UI the endpoint comes from `merge.embed_endpoint` in `config/ensemble.yaml`, set on `/ensemble/setup`.

> **⚠ The embed endpoint moved on 2026-06-30 and this doc pointed at the dead one until 2026-07-28.** It was `vllm-embed` on `:8000` serving `Qwen/Qwen3-Embedding-0.6B`; it is now **Ollama on `:11434` serving `qwen3-embedding:0.6b`** (lazy-load — it unloads after 5 minutes idle, so the first call after a pause is slow, not broken). Always take the live endpoint from `~/src/dgx/current-setup.md` rather than from this file. Anything extracted between those dates was almost certainly merged with the `subject` fallback.
>
> **The default `--embed-threshold` is 0.94, calibrated on `qwen3-embedding:0.6b` (2026-07-28, closing the loose end in [#197](https://github.com/kostadis/CampaignGenerator/issues/197)).** A 45-pair labeled sweep with `calibrate_embed` against the live corpus showed the dup/distinct bands *overlap* on this model — paraphrase duplicates score ~0.91–0.95 (Grey/Gray Ghosts 0.9157, Metalworkers Guild 0.9528) while the worst distinct pair, two **different in-world dates**, scores **0.9375** — so no threshold separates them cleanly. 0.94 is the precision-first choice: zero false merges on the labeled set, identical recall to the old nomic-era 0.93 (which *would* have merged the two dates). Cost: paraphrase dups below 0.94 stay unmerged — they surface as duplicates in review rather than corrupting facts. The threshold is **model-specific**: whenever the embed sidecar changes model, re-run `calibrate_embed --bootstrap` + a labeling pass before trusting the merge (labeled pairs from this calibration: `scratch_output/calib_pairs_oota_qwen3embed.yaml`).

> **Operational gotchas (these will silently waste an hour if ignored):**
>
> 1. **Use the Spark's IP address, not the `spark` / `spark2` hostnames.** The
>    hostnames resolve on the workstation but **not** in every shell that runs this
>    command (notably WSL2, containers, and cron). When they don't resolve, the
>    OpenAI client hangs on connection with *no error and no output* until it times
>    out — looking exactly like a stalled model. Pass `--endpoints
>    http://192.168.1.147:8001/v1` and `--embed-endpoint http://192.168.1.121:11434`
>    (check `~/src/dgx/current-setup.md` for the live IPs — it is authoritative and
>    these change). Note that the example
>    above shows a two-endpoint setup; current single-box serving uses one
>    `--endpoints` value.
>
> 2. **Run long jobs under `tmux`, and never relaunch without killing the old run
>    first.** A full extraction is tens of minutes. In some shells a backgrounded
>    job (`&`, `nohup`, even `setsid`) does not survive the parent's exit, so the
>    job appears to "die" mid-pass. The robust fix is a detached `tmux` session:
>    `tmux new-session -d -s ensemble`, send the command, then `tmux attach`/
>    `capture-pane` to watch. **Critically:** if a run seems dead, confirm with
>    `pgrep` *before* relaunching — each stray relaunch adds another worker on the
>    **same** per-chapter workdir, and concurrent writers corrupt the chunk cache
>    (wiping each other's partial passes) and flood the endpoint with N× the
>    intended concurrency. A pile of orphaned workers reads exactly like "the tool
>    keeps crashing." Kill all of them, wipe `per_chapter/`, and start one clean run.
>    (When grepping for workers, match the python executable, not the
>    `ensemble_extract` string — your own grep command contains that string and
>    will match itself.)

**Key batch flags:**

| Flag | Default | Purpose |
|---|---|---|
| `--chapters GLOB` | required | Glob for chapter files |
| `--per-chapter-dir DIR` | `./per_chapter` | Root for per-chapter workdirs |
| `--out FILE` | `./merged.json` | Combined output file |
| `--chapter-parallel N` | 3 | Chapters in flight at once |
| `--plan YAML` | `./plan.yaml` if it exists | Passed through to `ensemble` |

All `ensemble` endpoint and model flags (`--endpoints`, `--model`, `--chunk-parallel`, `--speculative`, `--unit-timeout`, `--embed-endpoint`, etc.) are accepted and passed through verbatim.

**Key ensemble flags to know:**

| Flag | Default | Purpose |
|---|---|---|
| `--samples N` | 1 | Re-run each pass N times; union results. Improves recall on nondeterministic extraction. `n_samples` per fact is recorded in merged.json for human review. |
| `--dry-run` | off | Print resolved plan only (which file each pass reads). Use before committing to a long run. |
| `--skip NAME` | none | Skip one named pass (repeatable). Use when iterating on a single-lens prompt fix. |
| `--unit-timeout SEC` | 600 | Kill a stalled unit and re-queue. Set to 0 for reasoning models (122B) that emit 10K–30K thinking tokens before JSON output. |
| `--speculative` / `--no-speculative` | on | When one endpoint stalls, a free endpoint re-runs its unit; first to finish wins. Use `--no-speculative` for attended runs where you may grab a Spark mid-job. Needs 2+ endpoints. |

> **Reasoning models — disable thinking for extraction.** As of 2026-06 the Spark's
> default chat slot is a *reasoning* model (`Qwen/Qwen3.5-122B-A10B-FP8`, a single
> cross-box endpoint). Extraction is a recognise-and-list task, so the model's
> `<think>` trace is pure waste — 10K–30K tokens burned per chunk before any JSON,
> and on a `max_tokens`-bounded call the whole budget can land in `reasoning` with
> `content: null` (a silently empty extraction). **Turn thinking off.** The DGX
> backend resolves `enable_thinking` per model from `~/src/dgx/dgxlib/models.yaml`;
> the 122B entry already sets `thinking_default: false`, so the ensemble path
> inherits no-think automatically. Force it for any model with `DGX_NO_THINKING=1`
> in the run's environment (belt-and-suspenders). Verify before a long run:
>
> ```bash
> curl -s http://192.168.1.147:8001/v1/chat/completions -H 'Content-Type: application/json' \
>   -d '{"model":"Qwen/Qwen3.5-122B-A10B-FP8","messages":[{"role":"user","content":"List two names as JSON. Output only JSON."}],"max_tokens":120,"chat_template_kwargs":{"enable_thinking":false}}' \
>   | python3 -c 'import sys,json;m=json.load(sys.stdin)["choices"][0]["message"];print(repr(m["content"]),"reasoning=",m["reasoning"])'
> # want: content is clean JSON, reasoning=None, finish_reason=stop
> ```
>
> With thinking off, `--unit-timeout` can stay at its default — the JSON is bounded
> and fast; the "set to 0 for reasoning models" note above only applies if you
> *keep* thinking on. Single live endpoint → pass one `--endpoints` URL plus
> `--no-speculative` (speculative needs 2+ endpoints). This path was validated on
> Hillsfar/DDEX34 (15 chapters, 5,242 facts) and survived a mid-run Spark restart
> via the per-chunk cache resume.

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

`ensemble_merge` generates alias proposals (spelling variants of the same entity) alongside each chapter's `merged.json`. The Phandalin workspace includes `review_aliases.py` as a local interactive reviewer; alternatively, edit `aliases.json` by hand.

Pass the reviewed file to `facts_to_state --aliases` in Stage 2 so variant spellings ("Bupido" / "Buppido") are collapsed before bundling. Without this step, one entity ends up in two separate bundles that never merge.

The alias file lives at `docs/ensemble/aliases.json` in the Phandalin workspace.

### Known limitation — type duplicates

`facts_to_state` groups facts by `(type, subject)` pair, not by subject alone. The same entity extracted as both `npc` and `monster` in different scenes (e.g. Boney, Cryovain, The Carver, Talos, Gorthok) will produce two separate dossiers: `npc_boney.md` **and** `monster_boney.md`.

**These are not a bug** — the type facets often capture genuinely different information (combat stats vs. personality). But synthesis tools must be told to treat them as the same entity, and reviewers should be aware that important facts may be split across two files.

**Alias review does not fix this** — aliases collapse name variants, not type variants. Run Stage 2e after aggregation to produce a `merged_dossiers/` directory where type-duplicates are concatenated into one file each. Use `merged_dossiers/` as input to all synthesis steps in Stage 3.

**What alias review does fix** — name variants where the same entity was extracted under two different surface forms (e.g. "Adabra" vs. "Adabra Gwynn", "Don-Jon" vs. "Don-Jon Raskin"). After adding the alias and re-running Stage 2b (resumable), delete the orphaned short-form dossier file by hand — the pipeline will not remove it automatically.

**Distinct failure mode — different entities colliding on one `(type, subject)` key.** The case above is the *same* entity split across *different* types (`npc_glabbagool` + `monster_glabbagool`); the fix is to merge. The opposite symptom is *different* entities that collapse into *one* dossier because they normalise to the same `(type, subject)` string — e.g. two unrelated things each extracted as `object_spores`, wrongly aggregated into a single `object_spores.md`. That is a registry/normalisation defect (a first-token collision), not a type-duplicate, and merging is exactly the wrong response — the entities need to be kept apart, not joined. If a single dossier reads as two unrelated subjects fused together, you are looking at this failure mode, not the type-duplicate one above.

---

## Stage 2 — Fact bundling

`facts_to_state` is the compression layer between raw atomic facts and the per-entity dossiers that synthesis consumes. It groups every fact about one `(type, subject)` pair in chapter order, then asks the local model to collapse them into a single current-state dossier.

### 2a. The `--list` checkpoint (always run first)

Before spending model time on aggregation, run `--list` to see the full entity coverage and the known/location-scoped split:

```bash
cd ~/Phandalin/Phandalin

facts_to_state \
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
- Is the `--min-facts` floor reasonable? (3 is the lower bound for anything worth a dossier; 10 is a good synthesis floor.) This floor is **waived for entities in `--known-names`/`--registry`** — once a source enumerates the known-entity universe, even a single-fact hit for a known entity gets a dossier (the floor exists to filter noise out of the unscoped pool, not to second-guess a ground-truth roster). The `Selected:` line reports how many were pulled in below the floor this way.

`--list` does not call the model. Use it freely.

### 2b. `--known-names`: named vs anonymous entity splitting

Without `--known-names`, `facts_to_state` produces one global bundle per `(type, subject)` key — every orc encounter in the campaign collapses into a single "Orc" dossier. With `--known-names`, entities whose normalised name appears in any of the source files are treated as named individuals (global bundle); everything else is scoped to its chapter location (e.g. `Orc (Phandalin)`, `Orc (Wayside Inn)`).

Sources can be:
- **Inventory `.md` files** — bold-marked proper nouns are extracted. First word of a multi-word name (≥ 4 chars) is also added as a short-form match.
- **`.dedup_state.json`** — `clusters_confirmed` aliases, canonical filename stems, and `pc_files_skipped` stems. This covers short forms like "Adabra" (from `adabra.md`) and PC names like "Soma" (from `soma.md`).

### 2c. Aggregation — known entities only

Run aggregation with `--known-only` to skip anonymous location-scoped bundles. They appear in `--list` tagged `[location]` and can be addressed in a later dedup pass if needed.

**`object` and `monster` bundles are exempt from the `--known-only` skip** — they are always aggregated when selected (still subject to `--min-facts`), even when location-scoped. Per-occurrence tracking is the intended behavior for those types: ten different `object` dossiers named "spores" from ten chapters is correct — each is a distinct time the party interacted with spores, not noise to collapse. For `npc`/`faction`/`location`, an anonymous location-scoped bundle really does mean skippable noise (`Orc (Phandalin)`), so those still honor `--known-only`.

```bash
facts_to_state \
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

**Single endpoint?** Stage 2c fans one worker per endpoint by default, so a lone
live endpoint aggregates serially. Add `--entity-parallel N` (e.g. 8) to run N
entities concurrently against the one endpoint — keep N under the server's
`--max-num-seqs`. Entities are processed largest-fact-first, so the opening wave
(the PCs and major NPCs) is the slowest; smaller dossiers land quickly after. Set
`DGX_NO_THINKING=1` here too — aggregation is also recognise-and-collapse, not a
reasoning task.

**`--min-facts` floors:**

| Floor | Dossiers (Phandalin 45ch) | Use |
|---|---|---|
| ≥ 3 | ~193 | Everything worth having a dossier at all |
| ≥ 10 | ~88 | Good synthesis floor — broad enough for factions, recurring locations, minor NPCs |
| ≥ 20 | ~37 | Tight floor — core cast only |

Use ≥ 3 for the aggregation run (don't discard facts at this stage). The synthesis tools have their own `--background-min-facts` filter that you apply per-doc — and note it applies only *outside* the recency window (see 3a).

### 2d. Threads track (zero model tokens)

Plot threads and mysteries are factual and don't need synthesis — render them directly:

```bash
facts_to_state \
  --corpus 'docs/ensemble/per_chapter/*/merged.json' \
  --aliases docs/ensemble/aliases.json \
  --types thread \
  --min-facts 2 \
  --render-only docs/ensemble/threads.md
```

This writes a chapter-tagged markdown file with no model call. Feed it to `synthesise_world_state --threads` if thread coverage looks thin from dossier bodies alone.

### Recent events — short-term world state (zero model tokens)

**There are two timescales of world state, and the fact-count filter silently picks one.**

- **Long-term world state** (`world_state.md`, from Stage 3 synthesis over dossiers with a `--background-min-facts` floor): only entities that *persist* across chapters survive. A one-session combatant — say an unnamed goblin boss killed at a cave entrance — has a burst of facts in a single chapter and never recurs, so it correctly **ages out**. This is the "what is true across the whole campaign" view.
- **Short-term world state** (`recent_events.md`): a **mechanical, full-fidelity, chapter-ordered render of every `event` fact** in a recent window. No synthesis — *synthesis is exactly the step that drops low-persistence facts*, so the short-term record must bypass it. This is the "what happened in chapter N" view, where that goblin boss IS material.

Fact-count is a **proxy for persistence**, and the right threshold scales with the query window: whole-campaign window → high threshold (long-term); few-recent-chapters window → threshold ≈ 0 (short-term). The two docs are one mechanism at two settings, not two separate pipelines.

**The proxy only works backwards.** Fact count says nothing about persistence for an entity that has not had time to recur yet — a character introduced last session has few facts *because it is new*, not because it is transient, and the two are indistinguishable by counting. Applied to the newest chapters, the floor therefore deletes the present: this is [#194](https://github.com/kostadis/CampaignGenerator/issues/194), which shipped a Chapter-61 `world_state.md` stamped Chapter 62. So `synthesise_world_state` scopes the floor by recency (`--recent-window N`): entities touched in the last N chapters are included whatever their count, and the floor governs only what came before. Sequence is not frequency — and the sequence is already in each dossier's `chapters: lo-hi` frontmatter.

This resolves a real failure mode: if you only build the long-term doc, "what happened in Chapter 1" has no correct home, and a synthesis model asked for a timeline will either drop the transient entity (silent information loss) or mis-attribute its events to a surviving neighbour. Don't patch transient entities into `world_state.md` — that's the long-term doc where their absence is correct. Give them the short-term doc instead.

```bash
build_recent_events \
  --corpus 'docs/ensemble/per_chapter/*/merged.json' \
  --output docs/recent_events.md \
  --window 0            # 0 = all chapters; N = keep only the last N (slide forward as the campaign grows)
```

**Dual use — it also anchors synthesis.** Per-entity dossiers are organised by *entity* and threads by *plot*; neither carries a timeline, so the synthesis model has to *reconstruct* chapter order from current-state snapshots — exactly the step LLMs are unreliable at (mis-dated rescues, two distinct bosses fused into one). Feeding this chapter-ordered render to `synthesise_world_state --threads` (concatenated with `threads.md`) hands the model the ordering instead of making it guess. Use `--window 0` for the synthesis spine (it must see all chapters) even when the human-facing `recent_events.md` is windowed.

> **Input contract — the timeline render assumes *narrative* chapters.** "Chapter-
> ordered" means facts are ordered by their position in the source text, which equals
> chronology **only when the chapter is linear narrative prose**. That is the normal
> input contract (and what the `docs/chapters/chapter_*.md` corpus is expected to be).
> A *structured* session doc breaks it — e.g. a `gm-assist.md` laid out as `## Summary`
> → `## Scenes` → `## Locations / NPCs / Items / Spells` appendices. The entity-indexed
> appendix sections re-state earlier events near the **end** of the file, so byte-
> position no longer tracks time: an event quoted in the Items appendix sorts *after*
> the chapter's true last scene. The synthesis model then reads the tail of the spine
> for "where are they now" and places the party at the wrong location.
>
> **Observed (Hillsfar/DDEX34, Ch16):** the "present the severed tentacles at
> **Sporedome**" beat is quoted under `## Items → Mind Flayer Tentacles` (offset
> 19292), which sorts *after* the genuinely-final `## Scenes → A Strategic Dinner in
> **Hillsfar**` (offset 13677). So `world_state` / `campaign_state` / `party` all
> reported the party at Sporedome when they had ended the session in Hillsfar.
> (Inside the `## Scenes` block alone, order was correct — "Return to Sporedome" *did*
> precede "Dinner in Hillsfar".)
>
> **Two ways to satisfy the contract:**
> - **Feed narrative chapters** (the normal flow) — position == chronology; nothing to do.
> - **Using structured session docs?** Scope timeline extraction to the chronological
>   region — the `## Summary` / `## Scenes` sections, where order *is* time — and treat
>   the `## Locations/NPCs/Items/Spells` appendices as dossier-fuel (entity state), not
>   timeline. ~96% of facts are locatable via `text.find(source_quote)` → char-offset →
>   enclosing-section lookup, so this needs **no re-extraction** (the `temporal` lens
>   currently reads the whole doc, appendices included, so it inherits the same scramble).
>
> Entity extraction is order-independent, so dossiers — and the NPC/faction/location
> bulk of `world_state` — are unaffected either way; only the time-ordered "current
> location / current objective" fields are at risk. **Verify those by hand in Stage 4.**

### 2e. Merge type-duplicate dossiers (before synthesis)

Run this after Stage 2c to produce `merged_dossiers/` — a directory where every type-duplicate group is collapsed into one file, used as input to all Stage 3 synthesis steps instead of `state_dossiers/`.

**Use the `/ensemble-type-merge` skill for this, not a blind script.** A shared subject name across types is
not always the same entity — grouping by filename alone and merging every match is unsafe: e.g. a 539-fact
`npc_daz.md` (a PC) next to a 1-fact `faction_daz.md` is almost certainly extraction noise, not a real
second facet, while `npc_glabbagool.md` + `monster_glabbagool.md` genuinely are the same entity. This is an
identity decision, not a rendering one, so it needs the same human-checkpoint treatment as
`ensemble-alias-review`. The skill walks every type-duplicate candidate group one at a time, reads the
dossier bodies (not just fact counts), recommends merge/keep-separate/uncertain with reasoning, and only
then runs the deterministic concatenation — persisting decisions to
`docs/ensemble/.type_merge_decisions.json` so re-runs are resumable.

```
/ensemble-type-merge [campaign-dir]
```

Under the hood it's still the same deterministic concatenation this section used to document as a raw
heredoc: group `state_dossiers/*.md` by subject, concatenate confirmed type-duplicates (primary file's name
wins, each source kept verbatim behind an HTML-comment marker), copy everything else through unchanged. The
merged file takes the name of the highest-fact-count member; all sources are listed in HTML comments at the
top of each section for traceability. The skill just adds the human confirmation step before any merge
actually happens.

**Deity entities — annotate, do not exclude.** Deities (Talos, Lolth, etc.) produce thin dossiers (< 20 facts) because extraction only sees how characters *talk about* them — their divine nature is not captured, only campaign-specific mentions. A synthesis model reading them cold will not know what it is looking at. As the party gains levels, direct divine interaction (avatars, omens, divine challenges) becomes plausible, so these dossiers become increasingly important.

After the merge step, open each deity dossier and add:
1. `subtype: deity` to the YAML frontmatter of the primary section.
2. A `> **DEITY — synthesis note:**` blockquote at the top of the body, explaining: the deity's canonical identity, that the facts below are campaign-presence only, that full lore/stats are in 5etools, and how the deity is likely to interact with the party as they level up.

Example preamble:

```markdown
> **DEITY — synthesis note:** Talos is a D&D 5e god (the Stormlord), not a mortal NPC.
> The facts below reflect only his campaign presence as perceived by characters — cult worship,
> claimed territory, Vukradin's tactical declaration of victory. Full lore and stat blocks
> are in 5etools. As the party levels up, direct divine interaction (avatars, omens, divine
> challenges) becomes plausible. Treat him as an off-screen force; his cultists are the
> primary interaction surface.
```

Deity dossiers that pass the `--background-min-facts` floor (or fall inside `--recent-window`) will be included in synthesis. The preamble ensures the synthesis model weights them correctly and does not treat them as addressable mortals.

### 2f. Fallback: `--split-gap` (no inventory files)

If no inventory or dedup-state files exist, use `--split-gap N` to split bundles where consecutive chapter gaps exceed N. This is a mechanical heuristic — it won't distinguish a named NPC who stops appearing for 10 chapters from two different orcs encountered 10 chapters apart. Prefer `--known-names` when inventory files are available.

---

## Stage 3 — Synthesis

Two paths: **API** (`ANTHROPIC_API_KEY`) or **Subscription** (claude.ai, no key needed). All four synthesis scripts now support `--dump-input` / `--dump-only`, so the subscription path works for every doc.

### 3a. world_state — API path

```bash
cd ~/Phandalin/Phandalin

synthesise_world_state \
  --dossiers 'docs/ensemble/merged_dossiers/*.md' \
  --background-min-facts 10 \
  --recent-window 4 \
  --party config/party.yaml \
  --backstories 'docs/Backstory - Brewbarry.md' \
               'docs/Backstory - Valphine Sotorra.md' \
               'docs/Soma - Backstory.md' \
  --threads docs/ensemble/threads.md \
  --output docs/world_state_draft.md \
  --model claude-opus-4-8
```

`--background-min-facts 10 --recent-window 4` filters at synthesis time — you can re-run with a different floor or window without re-aggregating. The two are a pair: the window says how far back "current" reaches (everything inside it is included regardless of fact count), the floor trims one-scene noise from everything older. `--recent-window 0` means *every* chapter is current, so the floor applies to nothing. Add `--threads` if you ran the threads track in 2d; omit it if not (thread coverage will come from dossier bodies). **For correct timeline ordering, pass the chronological spine here too** — concatenate `recent_events.md` (built with `--window 0`, see "Recent events" above) ahead of `threads.md` and feed the combined file via `--threads`. Without it the model reconstructs chapter order from entity snapshots and mis-dates events.

**Token cost estimate (Phandalin, ≥10 facts, 88 entities):** ~128K metered tokens.

### 3b. world_state — Subscription path (claude.ai / Claude Code CLI)

`--dump-input` + `--dump-only` assemble the full prompt and write it to disk without making an API call:

```bash
synthesise_world_state \
  --dossiers 'docs/ensemble/merged_dossiers/*.md' \
  --background-min-facts 10 \
  --recent-window 4 \
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

**Option A — Claude Code CLI (recommended).** Pipe the user prompt to `claude -p` with the system prompt on the command line. Uses your claude.ai subscription; no `ANTHROPIC_API_KEY` needed:

```bash
claude -p \
  --system-prompt "$(cat /tmp/world_state_prompt.md.system.md)" \
  < /tmp/world_state_prompt.md \
  > docs/world_state_draft.md
```

**Option B — Manual (claude.ai web).** Open claude.ai, start a new conversation, paste the system prompt first, then the user prompt. Copy the response to `docs/world_state_draft.md`.

> **Gotcha — `claude -p` inside a project can write the *live* doc, not stdout.**
> Run from a campaign directory, the headless `claude` inherits the project's tool
> permissions. `synthesise_world_state` and `planning` system prompts ask for
> a document *body*, so the agent prints it to stdout (→ your `>` redirect — correct).
> But `campaign_state` and `party` system prompts say "write
> `docs/campaign_state.md`" / "write `docs/party.md`", so the agent **uses the Write
> tool and overwrites the live grounding doc**, emitting only a summary to stdout —
> your `*_draft.md` ends up holding the summary while the live doc is clobbered with
> no diff. (Observed on the Hillsfar run: world_state/planning → drafts; campaign_state/party
> → live files.) Fix: disable tools so every doc goes to stdout —
> `claude -p --allowedTools '' --system-prompt "$(cat …system.md)" < …prompt.md > …_draft.md`
> — or run `claude -p` from outside the campaign dir. If the headless agent did clobber
> a live doc, recover with `cp docs/<doc>.md docs/<doc>_draft.md` then
> `git checkout -- docs/<doc>.md`.
>
> **Also strip the API key.** When `ANTHROPIC_API_KEY` is exported in the shell,
> `claude -p` bills the metered API instead of the subscription. Prefix every call
> with `env -u ANTHROPIC_API_KEY` to force subscription billing.

`campaign_state`, `party`, and `planning` all support `--dump-input` / `--dump-only`; use the same pattern as above for those docs (sections 3c–3e show the subscription path for each). Note `--output` is required by argparse even with `--dump-only` (it is the eventual write target; the dump just stops before the API call).

### 3c. campaign_state — staging (now automatic)

`campaign_state` expects its synthesis input as `extract_*.md` files. Historically this required a manual `mkdir` + `cp` staging step; as of the auto-staging change, omitting `--extract-dir` with `--synthesize-only` stages `docs/world_state_draft.md` and `docs/ensemble/threads.md` for you (into `<output_dir>/state_staging/campaign_state/`, always re-copied from the current source files — run world_state synthesis and the threads stage first):

```bash
campaign_state \
  --synthesize-only \
  --output docs/campaign_state_draft.md \
  --model claude-opus-4-8
```

Pass `--extract-dir` explicitly to point at your own pre-staged extracts instead (e.g. to include the low-fact supplementary extract below).

**Subscription path.** Use `--dump-input` + `--dump-only` then pipe to `claude -p`:

```bash
campaign_state \
  --synthesize-only \
  --output docs/campaign_state_draft.md \
  --dump-input /tmp/campaign_state_prompt.md \
  --dump-only

claude -p \
  --system-prompt "$(cat /tmp/campaign_state_prompt.md.system.md)" \
  < /tmp/campaign_state_prompt.md \
  > docs/campaign_state_draft.md
```

**Caveat: the low-fact blind spot.** `campaign_state_draft.md` derives from `world_state_draft.md`, which applies `--background-min-facts 10` at synthesis time. Any entity with fewer than 10 extracted facts **and last seen before the recency window** is invisible to world_state — and by extension invisible to campaign_state if world_state is the only source. (Recently-touched low-fact entities are no longer affected: `--recent-window` exempts them, which is [#194](https://github.com/kostadis/CampaignGenerator/issues/194)'s fix. The blind spot now covers only the old and sparse, which is what the floor is for.) This hits the **Tracked Items Status** section hardest: an entity can be declared "NOT FOUND IN SUMMARIES" when a dossier with 3–9 facts exists in `merged_dossiers/`, proving the ensemble did extract something about it from the transcripts.

**Before finalising any "NOT FOUND" verdict**, check:

```bash
ls docs/ensemble/runs/<date>/merged_dossiers/ | grep -i "<entity name>"
```

If a dossier exists, read it and update the entry. Known false negatives from the 2026-06-17 run:

| Dossier | Facts | What it captured |
|---------|-------|-----------------|
| `npc_tibor_wester.md` | 5 | Wildcat logger (Harbin's brother); loggers agreed to report him ch39 |
| `npc_grannoc.md` | 5 | Active Talosian at Woodland Manse ch41; status after ch45 clearance unconfirmed |
| `npc_dazlyn.md` / `npc_norbus.md` | 3–4 | Gave sending stones as the Dwarven Excavation reward ch2 |
| `location_shrine_of_savras.md` | 9 | Uncleared; known to party; active objective pending Neverwinter |

**Structural fix for future runs:** stage a supplementary extract using `narrative_importance.yaml`'s `force_include` list plus any remaining below-threshold dossiers. This covers both GM-flagged entities and unknown-but-present ones. A third extract file means building your own `--extract-dir` by hand — this bypasses the two-file auto-staging above:

```bash
mkdir -p /tmp/phandalin-cstate/extracts
cp docs/world_state_draft.md /tmp/phandalin-cstate/extracts/extract_001_world_state.md
cp docs/ensemble/threads.md  /tmp/phandalin-cstate/extracts/extract_002_threads.md

python3 - <<'PY' > /tmp/phandalin-cstate/extracts/extract_003_low_fact_dossiers.md
import glob, re, yaml, os

RUN = 'docs/ensemble/runs/<date>/merged_dossiers'
NI  = yaml.safe_load(open('docs/ensemble/narrative_importance.yaml'))
force_in  = {e['file'] for e in (NI.get('force_include') or [])}

nf = re.compile(r'^n_facts:\s*(\d+)', re.M)
parts = []
seen = set()
# force_include first (in YAML order)
for fname in force_in:
    f = os.path.join(RUN, fname)
    if os.path.exists(f):
        parts.append(open(f).read()); seen.add(fname)
# then remaining below-threshold dossiers
for f in sorted(glob.glob(f'{RUN}/*.md')):
    fname = os.path.basename(f)
    if fname in seen: continue
    t = open(f).read()
    m = nf.search(t)
    if m and int(m.group(1)) < 10:
        parts.append(t)
print('\n\n---\n\n'.join(parts))
PY
```

Then run with `--extract-dir /tmp/phandalin-cstate/extracts` (the explicit path overrides the auto-stage). The synthesis prompt grows by ~50–80 KB but coverage of minor module NPCs becomes accurate.

### 3d. party — preferred: party.yaml config (now automatic)

`party` has a "characters-only" mode that needs neither an extract pass nor `--synthesize-only` when given `--party-config` — it goes straight from the config to synthesis. But characters-only means no session extracts either, so without `--context` it has no source for current location / active quests / party reputation and will correctly report them as absent. Pass `world_state_draft.md` (or `world_state.md`) and `campaign_state_draft.md` (or `campaign_state.md`) as context — whichever exists. The Ensemble UI's Synthesize button now does both of these automatically (party-config + context) whenever `config/party.yaml` (or `party.yaml`) exists at the campaign root; no staged extracts required:

```bash
party \
  --party-config config/party.yaml \
  --context docs/world_state_draft.md docs/campaign_state_draft.md \
  --output docs/party_draft.md \
  --model claude-opus-4-8
```

**Subscription path.**

```bash
party \
  --party-config config/party.yaml \
  --context docs/world_state_draft.md docs/campaign_state_draft.md \
  --output docs/party_draft.md \
  --dump-input /tmp/party_prompt.md \
  --dump-only

claude -p \
  --system-prompt "$(cat /tmp/party_prompt.md.system.md)" \
  < /tmp/party_prompt.md \
  > docs/party_draft.md
```

`party.yaml` maps each PC's name to a sheet + optional backstory + optional arc-score file + optional `dossier` (see `config/party.example.yaml`) — build it once via the Party Document page's config editor and every future ensemble run reuses it, no re-staging per run.

**`dossier:`** points at the PC's own ensemble-built current-state dossier (`docs/ensemble/merged_dossiers/npc_<name>.md`) — the narrative facts (relationships, decisions, arc progression) pulled from actual play that the static sheet/backstory don't carry, and the same category of information the old per-tool `party --summaries` extraction used to produce fresh each run. Rendered into the `# PARTY` block next to sheet/backstory/arc_score. Which dossier belongs to which PC is campaign-specific, so it's always an explicit mapping in `party.yaml` — never inferred by name-matching.

**Fallback — no party.yaml yet.** Stage each PC's dossier as an extract by hand instead (which dossiers count as PCs is campaign-specific, so this step isn't automated):

```bash
mkdir -p /tmp/phandalin-party/extracts

# Copy each PC's dossier; glob handles the slug suffix
cp docs/ensemble/merged_dossiers/npc_valphine*.md  /tmp/phandalin-party/extracts/extract_001_valphine.md
cp docs/ensemble/merged_dossiers/npc_brewbarry*.md /tmp/phandalin-party/extracts/extract_002_brewbarry.md
cp docs/ensemble/merged_dossiers/npc_soma*.md      /tmp/phandalin-party/extracts/extract_003_soma.md
cp docs/ensemble/merged_dossiers/npc_vukradin*.md  /tmp/phandalin-party/extracts/extract_004_vukradin.md

party \
  --synthesize-only \
  --extract-dir /tmp/phandalin-party/extracts \
  --backstory 'docs/Backstory - Brewbarry.md' \
              'docs/Backstory - Valphine Sotorra.md' \
              'docs/Soma - Backstory.md' \
  --output docs/party_draft.md \
  --model claude-opus-4-8
```

**Caveat:** `party_draft.md` (either path) has no D&D Beyond-sourced class/level/arc-scores — it's the narrative/role half only. If you need those, run the full `party` pass with character sheet PDFs.

### 3e. planning — importance cut

`planning` consumes NPC dossier files directly with `--npc`. Feed only the entities worth forward-looking planning; the full dossier set produces a bloated, unprioritized doc.

**PCs auto-excluded via `party.yaml`.** Ensemble extraction doesn't distinguish PCs from NPCs, so `merged_dossiers/` gets an `npc_<pc-name>.md` for every PC right alongside real NPCs. The Ensemble UI's planning auto-detect (`_all_planning_npc_files` / `_planning_npc_passthrough` in `server/routers/ensemble.py`) excludes any dossier bound to a PC via `party.yaml`'s `dossier:` field (§3d) — same "explicit, never inferred by name-matching" rule as the party-block attribution. A PC with no `dossier:` binding in `party.yaml` still shows up in the NPC list; either add the binding or drop them via `narrative_importance.yaml`'s `force_exclude` below.

Importance cut: **≥10 facts AND (spans ≥5 chapters OR seen since chapter 40)**.

**Field-name correction (verified 2026-06-17):** merged dossiers use `chapters: 20-39` range format in frontmatter, NOT `source_extracts: [20,21,...]`. The old `source_extracts` regex matches nothing and silently falls back to n_facts-only filtering. Use the `chapters:` parser below:

**narrative_importance.yaml — GM curation layer.** Before running the cut, create or update `docs/ensemble/narrative_importance.yaml` (see the Phandalin copy for the format). It holds two lists:

- `force_include` — entities below threshold that must appear (forward-looking threats, active objectives with few facts)
- `force_exclude` — entities above threshold that should be dropped (deceased / resolved NPCs)

Each entry has a `file` key (relative to `merged_dossiers/`) and a `reason` for later pruning.

Both scripts below skip any dossier named `narrator`/`speaker`/`i` — a backstop against exactly the POV-label leak that `annotate_pov` and the extraction prompts' pronoun-resolution rule now catch upstream. Kept as defense-in-depth; harmless if it never fires.

**Audit pass** — run this first to see what the threshold cut picks, overlaid with the curation file:

```bash
cd ~/Phandalin/Phandalin

python3 - <<'PY'
import glob, re, yaml, os

RUN = 'docs/ensemble/runs/<date>/merged_dossiers'
NI  = yaml.safe_load(open('docs/ensemble/narrative_importance.yaml'))
force_in  = {e['file'] for e in (NI.get('force_include') or [])}
force_out = {e['file'] for e in (NI.get('force_exclude') or [])}

nf = re.compile(r'^n_facts:\s*(\d+)', re.M)
ch = re.compile(r'^chapters:\s*(.+)$', re.M)
nm = re.compile(r'^name:\s*(.+)$', re.M)

for f in sorted(glob.glob(f'{RUN}/npc_*.md')):
    fname = os.path.basename(f)
    t = open(f).read()
    m = nm.search(t); name = m.group(1).strip() if m else '?'
    if name.lower() in ('narrator', 'speaker', 'i'): continue
    n = int(nf.search(t).group(1)) if nf.search(t) else 0
    ch_m = ch.search(t)
    if ch_m:
        parts = re.split(r'[-,]', ch_m.group(1).strip())
        nums = [int(x) for x in parts if x.strip().isdigit()]
        min_ch = min(nums) if nums else 0; max_ch = max(nums) if nums else 0
        span = max_ch - min_ch + 1
    else:
        min_ch = max_ch = span = 0
    threshold = n >= 10 and (span >= 5 or max_ch >= 40)
    if   fname in force_out:           verdict = 'EXCL '
    elif fname in force_in:            verdict = 'FORCE'
    elif threshold:                    verdict = 'PASS '
    else:                              verdict = 'skip '
    print(f"{verdict} | {name:35s} | n={n:4d} | ch={min_ch}-{max_ch} | span={span}")
PY
```

Replace `<date>` with the actual run date (e.g. `2026-06-17`). Review the output — add anything surprising to `force_include` or `force_exclude` in the YAML before building the final array.

**Build the NPC_FILES array** (threshold + curation):

```bash
mapfile -t NPC_FILES < <(python3 - <<'PY'
import glob, re, yaml, os

RUN = 'docs/ensemble/runs/<date>/merged_dossiers'
NI  = yaml.safe_load(open('docs/ensemble/narrative_importance.yaml'))
force_in  = {e['file'] for e in (NI.get('force_include') or [])}
force_out = {e['file'] for e in (NI.get('force_exclude') or [])}

nf = re.compile(r'^n_facts:\s*(\d+)', re.M)
ch = re.compile(r'^chapters:\s*(.+)$', re.M)
nm = re.compile(r'^name:\s*(.+)$', re.M)

emitted = set()
for f in sorted(glob.glob(f'{RUN}/npc_*.md')):
    fname = os.path.basename(f)
    if fname in force_out: continue
    t = open(f).read()
    m = nm.search(t)
    if not m or m.group(1).strip().lower() in ('narrator', 'speaker', 'i'): continue
    n = int(nf.search(t).group(1)) if nf.search(t) else 0
    ch_m = ch.search(t)
    if ch_m:
        parts = re.split(r'[-,]', ch_m.group(1).strip())
        nums = [int(x) for x in parts if x.strip().isdigit()]
        max_ch = max(nums) if nums else 0
        span = max(nums) - min(nums) + 1 if nums else 0
    else:
        max_ch = span = 0
    if fname in force_in or (n >= 10 and (span >= 5 or max_ch >= 40)):
        print(f); emitted.add(fname)

# force_include entries that aren't npc_*.md (e.g. location_*.md)
for e in (NI.get('force_include') or []):
    fname = e['file']
    if fname not in emitted:
        full = os.path.join(RUN, fname)
        if os.path.exists(full):
            print(full)
PY
)
```

**Passing arc score files and context docs.** The Threat Tracker quality improves significantly when you pass the threat arc score files and any hand-authored context docs (e.g. `KP.md`, `CounterForce.md`). The 2026-06-17 run used:

```bash
planning \
  --npc "${NPC_FILES[@]}" \
  --arc-scores \
    'docs/tracking/aletra-sortorra-arc.md' \
    'docs/tracking/echoes-score.md' \
    'docs/tracking/grundar_score.md' \
    'docs/tracking/splinter-colony.md' \
    'docs/tracking/Adabra quest line.md' \
  --context \
    'docs/KP.md' \
    'docs/CounterForce.md' \
  --output docs/planning_draft.md \
  --model claude-opus-4-8
```

**Subscription path.** Build the NPC_FILES array the same way, then dump and synthesize directly:

```bash
planning \
  --npc "${NPC_FILES[@]}" \
  --arc-scores \
    'docs/tracking/aletra-sortorra-arc.md' \
    'docs/tracking/echoes-score.md' \
    'docs/tracking/grundar_score.md' \
    'docs/tracking/splinter-colony.md' \
    'docs/tracking/Adabra quest line.md' \
  --context \
    'docs/KP.md' \
    'docs/CounterForce.md' \
  --output docs/planning_draft.md \
  --dump-input /tmp/planning_prompt.md \
  --dump-only
# Then synthesize as Claude Code — read /tmp/planning_prompt.md and
# /tmp/planning_prompt.md.system.md and write docs/planning_draft.md directly.
```

**Caveats:**
- Fact-count is a recurrence proxy, not narrative importance. A pivotal one-scene NPC can fall below the cut (e.g. Aletra: 59 facts but only a 3-chapter span); always sanity-check the PASS/skip list and add manual entries as needed.
- The `chapters:` field in merged dossiers is a `min-max` range, not a list. The span heuristic (`max - min + 1`) can overcount if the NPC appeared in only two widely-separated chapters. Cross-check suspicious entries against the dossier content.
- Threat arc scores in `--arc-scores` must match the `planning` binding format — the system prompt reads `<!-- Threat arc score: filename -->` comments to bind a score file to the NPC it tracks. If a score file has no corresponding NPC dossier in `--npc`, the Threat Tracker row will still appear but without dossier context.
- The `narrator` / `speaker` filter above removes POV-label artifacts. Check for those in the PASS/skip output.
- The `Fury of the Wild` score (Adabra) was not present as a formal arc score file in the 2026-06-17 run — it appears in CLAUDE.md but has no mechanic file. The Threat Tracker will be missing that row. Track it manually or create the file.

---

## Stage 4 — Review and promotion

All outputs land in `*_draft.md`. **Never write directly to the live docs.**

Review each draft:
- Each dossier has an `## Uncertainty` block listing facts the model flagged as ambiguous. Skim these before trusting synthesis — scope/ordering/attribution are the model's weak spots.
- **Check the "current location / current objective" fields first — they are the least reliable.** Synthesis often records the right *events* (the timeline entry is correct) yet sets the wrong *current state*, because it weights the campaign's high-salience base over the most-recent scene, and there is no `party` dossier to anchor the answer (the meta-label is excluded in Stage 2a). This is amplified if the corpus was structured session docs rather than narrative chapters (see the timeline "input contract" note in 2d). Verify the snapshot against the **last scene of the final chapter** in the authoritative source.
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

## Observability & abort

All ensemble stages (extraction, bundling, synthesis) support:

- **Copyable command**: Every UI-launched run emits the exact, secret-free invocation as the first SSE event. Paste it into a terminal in the campaign workspace to reproduce the run. No API key appears in the command — keys are inherited from the server environment, never on the command line.
- **Live streaming**: Output lines appear incrementally as each chapter/step completes. The UI shows a "Running…" state while the run is active.
- **Abort**: The Abort button (UI) closes the EventSource connection. The server observes the disconnect and group-kills the entire worker tree (SIGTERM → SIGKILL after ~4 s) — no orphaned `ensemble_extract` or `facts_to_state` subprocesses keep spending tokens.
- **Disconnect = implicit abort**: Closing the browser tab or dropping the network mid-run is treated identically to clicking Abort. The UI does NOT auto-reconnect during a running stage (that would silently restart the run). The server kills the process group when the connection drops.
- **Durable record**: Every run writes `<campaign>/logs/<timestamp>_<script>.md` with the command, full output, outcome (succeeded / failed / aborted), and duration. Recoverable after the browser is closed.
- **Cache integrity**: Per-chapter `merged.json` and per-entity `state_dossiers/*.md` are written atomically (temp-file + rename). A force-kill during write never leaves a truncated file at the resume-trusted path — the next run either finds a complete artifact (skip) or none (re-run), never a partial one.

## See also

- [`ensemble_extraction.md`](ensemble_extraction.md) — single-file extraction, merge options, `--samples` and `--dry-run` patterns
- [`local_grounding_docs.md`](../archive/local_grounding_docs.md) — provenance and notes from the OotA and Phandalin full runs
- `docs/ensemble/HOWTO_122B.md` — 122B Ray-cluster setup and `run.py` configuration for the denser model

---

## Future ideas

### All-Spark synthesis (Stages 3a–3d on the DGX)

Stages 1 and 2 already run on Spark (free, local). Stages 3a–3d call the Claude API (~280K metered tokens). In principle, synthesis is a **render task** — it takes verified, human-reviewed dossiers and renders them into a readable grounding doc. That's the part where a local model can plausibly do the job.

The `--dump-input --dump-only` flag already externalises the prompt to disk. The gap is piping that dump to a Spark endpoint instead of `claude -p`.

**Calibration finding (2026-06-18):** `Qwen3-Next-80B-A3B-Instruct-FP8` (3B active parameters) cannot handle synthesis — it can recognise and list, but not prioritise and organise across a multi-entity dossier set. `Qwen3.5-122B-A10B-FP8` (10B active, TP=2 cross-box) is the next candidate. Run `/spark-status` to confirm what's live before wiring up commands.

**Sketch — dump then hit Spark in parallel:**

```bash
# Dump all four synthesis prompts (no API call)
synthesise_world_state \
  --dossiers 'docs/ensemble/merged_dossiers/*.md' \
  --background-min-facts 10 --recent-window 4 \
  --party config/party.yaml --threads docs/ensemble/threads.md \
  --dump-input /tmp/ws_prompt.md --dump-only

campaign_state \
  --synthesize-only --extract-dir /tmp/cstate/extracts \
  --dump-input /tmp/cs_prompt.md --dump-only

party \
  --party-config config/party.yaml \
  --context docs/world_state_draft.md docs/campaign_state_draft.md \
  --dump-input /tmp/party_prompt.md --dump-only

planning \
  --npc "${NPC_FILES[@]}" \
  --dump-input /tmp/plan_prompt.md --dump-only

# Hit Spark with each prompt in parallel (they are independent)
SPARK=http://192.168.1.147:8001/v1
MODEL=Qwen/Qwen3.5-122B-A10B-FP8
for label in ws cs party plan; do
  curl -s $SPARK/chat/completions \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"$MODEL\",
         \"messages\": [{\"role\": \"user\", \"content\": $(jq -Rs . < /tmp/${label}_prompt.md)}],
         \"max_tokens\": 8192}" \
    | jq -r '.choices[0].message.content' \
    > docs/${label}_draft.md &
done
wait
```

**What to calibrate:** whether the 122B model can maintain a coherent NPC voice and plot-thread taxonomy across the full dossier input. At 3 sessions the context is small — a real test only emerges at 10–15 sessions when the dossier set grows.

### Per-synthesis-section fan-out

Instead of one large prompt per grounding doc, fan out by section — one Spark agent per NPC for `party.md`, one per faction for `planning.md`, one per location cluster for `world_state.md`. Merge the outputs in a final pass.

This mirrors Stage 1's per-chapter fan-out (`ensemble_batch`). A `synthesis_batch.py` along the same lines would:
- Fit larger campaigns in context (each agent sees only its slice)
- Allow parallel execution across both Spark nodes
- Make it cheap to re-run only the sections affected by new sessions

The shape is already proven at Stage 1; closing the loop on Stage 3 would make the full pipeline local.
