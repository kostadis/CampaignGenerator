# Provenance and contextual identity experiment series

Experiment record, 2026-11-03–04. This is the entry point for the complete investigation prompted by NVIDIA Auto Ontology: artifact provenance, nonunique creature labels, resolution from campaign prose, hosted/local model comparisons, and reuse of saved decisions. The six sibling directories retain their original code and results.

Read [DESIGN.md](DESIGN.md), [EVALUATION.md](EVALUATION.md), [RESULTS.md](RESULTS.md), and [NVIDIA-COMPARISON.md](NVIDIA-COMPARISON.md). [manifest.json](manifest.json) binds the packaged files by SHA-256. This package is experimental evidence, not a production integration or a canon update.

| Stage | Design, method and code | Evaluation and results |
| --- | --- | --- |
| Artifact dependency graph | [Provenance index](../20261103-provenance-ontology/README.md); `relationship_index.py`, `run_experiment.py` | [Findings](../20261103-provenance-ontology/FINDINGS.md); `results/final/` |
| Nonunique names with explicit context | [Synthetic bugbears](../20261103-contextual-entity-resolution/README.md); `contextual_identity.py`, `fixtures.py` | [Findings](../20261103-contextual-entity-resolution/FINDINGS.md); `results/final/` |
| Identity from raw summary passages | [Orcs and ogres](../20261103-summary-entity-resolution/README.md); `prepare_cases.py`, `run_models.py`, `evaluate.py` | [Findings](../20261103-summary-entity-resolution/FINDINGS.md); `results/summary.json` |
| Local model parity | [Qwen trial](../20261104-local-entity-resolution/README.md); `run_local.py`, `compare.py` | [Findings](../20261104-local-entity-resolution/FINDINGS.md); `results/comparison.json` |
| Terra medium parity | [Terra trial](../20261104-terra-entity-resolution/README.md); shared generator plus `compare_terra.py` | [Findings](../20261104-terra-entity-resolution/FINDINGS.md); `results/comparison.json` |
| Repeated queries and invalidation | [Reuse prototype](../20261104-resolution-reuse/README.md); `reuse.py`, `run_experiments.py` | `results/reuse.json`; 14 offline checks |

## Artifact layout

Code, synthetic fixtures, compact measurements, historical validation records, and design documents are eligible for Git. The existing run records retain original absolute runtime paths as historical metadata; these paths are not portable dependencies for the archive verifier.

`private-runtime/` is a local, Git-ignored archive of the frozen source payloads, draft expectations, prompts, raw responses, and detailed reports. Its own `inventory.json` records original locations and per-file hashes. These copies preserve failures and the original offset-only trial as well as successful runs. No private raw text is added to the Git-eligible package by this archive step. Previously authored compact experiment reports remain unchanged.

The private archive is required to rescore the real-text trials offline; code-only/synthetic tests do not require it. Do not force-add it to Git. Model calls remain explicit commands using CampaignGenerator's adapter and the original authorization scope, not a side effect of verification.

## Quick verification

From the CampaignGenerator repository root, using its existing Python environment:

```sh
python experiments/20261104-provenance-identity-series/verify_archive.py
python -m pytest -q \
  experiments/20261103-provenance-ontology/test_relationship_index.py \
  experiments/20261103-contextual-entity-resolution/test_contextual_identity.py \
  experiments/20261103-summary-entity-resolution/test_evaluate.py \
  experiments/20261104-local-entity-resolution/test_run_local.py
```

The verifier checks bytes, relative documentation links, and (when present) private archive integrity. It makes no model or network calls and does not approve any proposal. Reproduction and offline scoring commands are in [EVALUATION.md](EVALUATION.md).
