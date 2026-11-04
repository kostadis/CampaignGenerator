# Provenance relationship-index experiment — 2026-11-03

Read [FINDINGS.md](FINDINGS.md) for the result. This experiment tests the useful
part of an ontology layer for this workspace: explicit relationships among
versioned artifacts, checks, saved decisions, applications, and identities.

Inputs are the declared Phandalin entity registry and the Chapter 59–60 legacy
grounding-delta bundles. Campaign content remains in the campaign repository.
The SQLite file is a disposable projection; it grants no authority and cannot
write to a campaign. No model or network calls are made. NVIDIA Auto Ontology
was not installed: this is the small local experiment proposed in the preceding
discussion, not an evaluation of NVIDIA's runtime or natural-language SQL.

## Run

From the CampaignGenerator worktree, using an environment with its existing
dependencies installed:

```bash
python experiments/20261103-provenance-ontology/run_experiment.py \
  --workspace /home/kostadis/phandalin --campaign Phandalin \
  --out /tmp/ontology-experiment-new-run

python -m pytest experiments/20261103-provenance-ontology/test_relationship_index.py -q
```

The output directory must be fresh and outside the campaign workspace. The
runner builds twice, reverses bundle import order, compares canonical graph
digests, checks inputs remain unchanged, and records its coverage and gaps.

Queries against the built index open SQLite in read-only mode:

```bash
python experiments/20261103-provenance-ontology/relationship_index.py impact \
  --db /tmp/ontology-experiment-new-run/relationships.sqlite3 \
  --campaign Phandalin summaries/2026-10-20-chapter_59/session-summary.md

python experiments/20261103-provenance-ontology/relationship_index.py resolve \
  --db /tmp/ontology-experiment-new-run/relationships.sqlite3 \
  --campaign Phandalin Bimble
```

The lower-level `build` command accepts an explicit repeated `--bundle`; there
is no directory-wide history scan. It refuses an existing database. `impact`
returns paths through dependencies with evidence-record hashes and validated
JSON pointers. An unindexed path returns `not_covered`.

## Files

- `relationship_index.py`: SQLite graph, existing registry/provenance adapters,
  legacy grounding-bundle binding checks, dependency and identity queries.
- `test_relationship_index.py`: synthetic counterexamples; no live campaign
  files or external services are used by the tests.
- `run_experiment.py`: bounded real-input evaluation and deterministic rebuild.
- `results/final/report.json`: measurements, all 11 real-input cases, version
  status, source-drift hashes, limitations, and literal-search comparison.
- `results/final/examples.json`: readable dependency traces with evidence.
- `results/final/input_hashes.json`: all 51 campaign input hashes.
- `results/final/validation.json`: tested code identities and validation result.

SQLite databases, intermediate trials and bytecode are omitted from Git. The
reported graph can be rebuilt from the scripts and input identities. A future
source change will intentionally produce a different graph digest and may
change the observed freshness results.
