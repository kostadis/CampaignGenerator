# mneme retrieval versus contextual identity

Executed November 3, 2026 (America/Los_Angeles), following the [provenance/identity series](../20261104-provenance-identity-series/README.md). See [FINDINGS.md](FINDINGS.md) for results and [DESIGN.md](DESIGN.md) for the evaluation boundary. No canonical records, index refresh, service configuration, or generative-model calls were made.

The experiment asks whether the existing `mneme mp search` can retrieve evidence for the same 16 frozen orc/ogre mention pairs. It does not pretend that similarity scores are identity predictions. It compares two species-only searches with 16 fixed encounter-context searches over the declared `summaries` wing, then separately expands only the returned sources through mneme's declared corpus TOC.

## Code and records

- `queries.json`: fixed encounter queries, without draft relation answers.
- `run_searches.py`: actual mneme CLI calls, private stdout/stderr and hash-bound request records.
- `retrieval.py`: verbatim-hit parsing and source/target-neighborhood coverage. Related model-tagged themes are excluded.
- `evaluate_searches.py`: offline top-1/5/10 coverage scoring, without reading gold.
- `expand_sources.py`: source expansion through the declared TOC, refusing ambiguous basenames and changed files.
- `test_retrieval.py`: coverage/attribution counterexamples.
- `results/`: compact coverage, expansion, environment and validation records.
- `private-runtime/`: Git-ignored frozen payload, raw retrieval outputs, source snapshots and readiness/TOC records, copied from `/tmp/orc-mneme-search-20261103`. This is local evidence, not a campaign backup.

## Reproduce

From CampaignGenerator's root, using its installed Python environment. New output directories must be fresh. The live searches use the embedder already declared by mneme; they require access to that local endpoint and existing palace.

```sh
python experiments/20261103-mneme-search-comparison/run_searches.py \
  --baseline experiments/20261104-provenance-identity-series/private-runtime/orc-identity-terra-medium-20261104 \
  --campaign-dir /home/kostadis/phandalin/Phandalin \
  --out /tmp/mneme-identity-new-run

python experiments/20261103-mneme-search-comparison/evaluate_searches.py \
  --run /tmp/mneme-identity-new-run \
  --out /tmp/mneme-retrieval-evaluation.json

mneme corpus toc Phandalin --kind summaries --json \
  --dir /home/kostadis/phandalin/Phandalin > /tmp/mneme-summaries-toc.json

python experiments/20261103-mneme-search-comparison/expand_sources.py \
  --run /tmp/mneme-identity-new-run --toc /tmp/mneme-summaries-toc.json \
  --campaign-root /home/kostadis/phandalin/Phandalin \
  --out /tmp/mneme-expanded-evaluation.json

python -m pytest -q experiments/20261103-mneme-search-comparison/test_retrieval.py
```

For offline evaluation of this completed trial, use `--run experiments/20261103-mneme-search-comparison/private-runtime/run`. Source expansion requires the declared source files still matching the archived TOC hashes; their contents are also retained privately for inspection. Do not force-add the private runtime to Git.
