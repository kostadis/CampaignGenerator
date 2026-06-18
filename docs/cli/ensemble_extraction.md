# Ensemble Extraction — How-To

`ensemble.py` (and its two sub-tools `ensemble_extract.py` + `ensemble_merge.py`)
run a multi-lens fact-extraction pass over session text using a local LLM endpoint.
This doc covers the common usage patterns — single file, multiple files, and the
flags that matter most.

See [`ensemble_workflow.md`](ensemble_workflow.md) for the full
extract-once-locally pipeline (ensemble_batch.py → facts_to_state → synthesis) that
builds all four grounding docs from local compute.

---

## Quickstart — single file, built-in 5-lens plan

```bash
python ensemble.py session-summary.md --workdir gen-ch01/
```

This runs 5 passes (small / large / sweep / temporal / interiority) against
`session-summary.md`, then merges them into `gen-ch01/merged.json`.

With both Sparks:

```bash
EP="--endpoints http://192.168.1.147:8001/v1 http://192.168.1.69:8001/v1 \
    --model Qwen/Qwen3-Next-80B-A3B-Instruct-FP8"
python ensemble.py session-summary.md --workdir gen-ch01/ $EP
```

---

## Extracting from multiple files — the `--plan` YAML

The positional argument is a single default document. To point different passes at
different files, write a plan YAML and pass it with `--plan`.

**Minimal example** — 5 lenses on the summary, interiority pass on the gm-assist doc:

```yaml
# plan.yaml
document: session-summary.md     # default for passes that don't set their own

passes:
  - name: small
  - name: large
  - name: sweep
  - name: temporal
  - name: interiority
    document: gm-assist.md       # overrides the top-level default for this pass
```

```bash
python ensemble.py --plan plan.yaml --workdir gen-ch01/ $EP
```

Relative `document` paths resolve against the plan file's directory, so you can
keep the YAML next to the session files and use short paths.

**Per-pass documents with no default** — every pass names its own file, no
positional argument needed:

```yaml
passes:
  - name: summary-small
    document: /path/to/session-summary.md
  - name: summary-large
    document: /path/to/session-summary.md
  - name: gmassist-interiority
    document: /path/to/gm-assist.md
  - name: notes-sweep
    document: /path/to/dm-notes.md
```

Pass names key the output files under `--workdir` — they must be unique.

---

## Key flags

| Flag | Default | What it does |
|---|---|---|
| `--samples N` | 1 | Run each pass N times and union the results. Re-sampling recovers facts a single run misses (extraction is nondeterministic). `n_samples` per fact is recorded in `merged.json` as a confidence signal for human review — nothing is auto-filtered. |
| `--dry-run` | off | Print the resolved plan (which file each pass reads) without extracting. Use this to verify your YAML before committing to a long run. |
| `--skip NAME` | none | Skip a named pass (repeatable). Useful when iterating on a prompt fix for one lens. Works with both built-in and plan passes. |
| `--chunk-parallel N` | 4 | In-flight chunk requests per endpoint. 4 matches the Sparks' `--max-num-seqs 4`; use 1 for sequential behaviour. |
| `--speculative` / `--no-speculative` | on | When one endpoint stalls, a free endpoint re-runs its unit; whichever finishes first wins. Use `--no-speculative` for attended runs where you may grab a Spark mid-job. Needs 2+ endpoints. |
| `--unit-timeout SEC` | 600 | Kill and re-queue a unit that exceeds this wall-clock cap. A degraded endpoint that dribbles tokens toward max_tokens usually recovers on a fresh connection. 0 disables the cap. |

---

## Separation of concerns

`ensemble.py` is a convenience wrapper that calls `ensemble_extract.py` then
`ensemble_merge.py`. When you need to iterate on merge settings without re-running
extraction (expensive), call them separately:

```bash
# 1. Run extraction only
python ensemble_extract.py --plan plan.yaml --workdir gen-ch01/ $EP

# 2. Merge separately, tweaking settings
python ensemble_merge.py --workdir gen-ch01/ --method embed --embed-threshold 0.88
```

`--plan` controls extraction (passes + documents).  
`--merge-config` / `--method` flags control merging.  
These are intentionally separate YAMLs — merge settings do not belong in the plan.

---

## Output

After a successful run, `--workdir` contains:

- `<pass-name>.jsonl` — per-pass raw facts
- `manifest.json` — maps each pass to its source document and output file
- `merged.json` — deduplicated fact list with `n_samples` confidence counts

`merged.json` is the input to `facts_to_state.py` for per-entity dossier
aggregation. Human review of dossiers is the checkpoint before any synthesis call.
