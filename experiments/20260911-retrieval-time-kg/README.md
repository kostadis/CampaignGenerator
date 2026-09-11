# 20260911-retrieval-time-kg

Frozen evidence for **[FINDINGS.md](FINDINGS.md)** — read that first.
Tracking issue: [CampaignGenerator#463](https://github.com/kostadis/CampaignGenerator/issues/463).
**Evidence only.** No campaign canon, no chapter revision, no production change.

**Do not execute these runners here.** They are preserved records, complete with
their original absolute paths (`/home/kostadis/cognee-local`,
`/home/kostadis/obelisk`, `/home/kostadis/src/cognee`,
`/home/kostadis/src/Mempalace`) and the environment they ran in. For another
trial, use a fresh directory and explicit paths.

## Campaign source is not copied

Per this repo's convention, campaign source material stays in the `campaigns`
repo. The following were used as **inputs** and are **not** here:

- `obelisk/docs/summaries/*.md` — the 12 session summaries, the corpus for every
  comparison
- `obelisk/docs/aliases.json` — the reviewed alias file used by the event KG
- the derived corpora rebuilt from those by the scripts below:
  `obelisk_events.json`, `obelisk_full.json`, `scene_docs/`, `entity_docs/`,
  `event_kg.sqlite3`

`scripts/kg/event_kg.py` rebuilds the event KG from the summaries in about a
second.

## Layout

| Path | Contents |
|---|---|
| `FINDINGS.md` | The write-up — what was tested and what happened |
| `STATE_GENERATION_METHOD.md` | **The method** — building the event-ordinal KG and generating `campaign_state` / `world_state` for LLM prep, with the issues found |
| `scripts/cognee/` | Ingest runners (ToEE, obelisk, tiered, scene/entity docs), provenance and strict-prompt tests, the 36-run trial harness |
| `scripts/retrieval/` | `verify.py` (tgrep claim checker), `pipeline.py` (cognee → tgrep) |
| `scripts/kg/` | `event_kg.py` (the §8 design), mempalace KG `populate_kg.py` / `query_kg.py` |
| `scripts/extract/` | Deterministic extractors — events, scene docs, entity docs, tier manifest, state delta |
| `scripts/prompt-exp/` | Extraction-prompt A/B: `run_arm.py`, `measure.py`, `stripped_prompt.txt` |
| `scripts/temporal/` | Abandoned `cognify(temporal_cognify=True)` run (superseded by §8) |
| `scripts/lb/` | Proposed nginx `least_conn` balancer for the two Sparks (not deployed) |
| `data/` | `trials.json` (36 runs), `pipeline_results.json`, `tier_manifest.json`, `strict_prompt.txt`, `prompt-exp-ab.txt` |
| `generated/` | `campaign_state.md` (hand-built), `.zg.md`, `.tgrep.md`, `world_state.md` |
| `evidence/` | `ingest_log_excerpts.md` (counts and sample lines from the multi-MB ingest logs) and the smaller test logs in full (as `.txt` — the repo `.gitignore` excludes `*.log`) |
| `skill/` | `campaign-recall.SKILL.md` — zg lookup + filename ordering + positive-control absence check |

## Environment

- vLLM `qwen3.8-flash-next` on spark1 (`192.168.1.147:8001`), `--max-num-seqs 8`
- Ollama `qwen3-embedding:0.6b` on spark2 (`192.168.1.121:11434`)
- cognee 1.5.3 (editable, `~/src/cognee` @ `e8dd3d93d`), Python 3.12
- mempalace editable from `~/src/Mempalace` @ `kostadis-dev`, isolated palace
  at `~/cognee-local/mempalace-exp/palace` (the default chat palace was never
  written)
- tgrep index rebuilt twice during the run; zg index over
  `obelisk/docs/summaries`, 12/12 coverage

Not copied: `prompt-exp/` graph databases (47 MB), `mempalace-exp/` venv and
palace (348 MB), cognee `.cognee_system/` stores. All reproducible from the
scripts.
