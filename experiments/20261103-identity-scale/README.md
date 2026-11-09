# Larger contextual identity experiment, without mneme

Follow-up to the [original series](../20261104-provenance-identity-series/README.md): 100 new mention-pair comparisons, 136 marked occurrences, and 17 campaign chapters excluded from the original seven-chapter fixture. Terra medium receives full authored narrative Summary sections for the chapters referenced in each batch. There is no mneme, vector search, automatic mention extraction, or canonical registry update.

Read [DESIGN.md](DESIGN.md) for the frozen protocol and evaluation limits, and [FINDINGS.md](FINDINGS.md) for the completed results. Code selectors and compact outputs are eligible for Git; frozen campaign text, gold, prompts, raw responses and detailed reports belong in the Git-ignored `private-runtime/` archive.

## Code

- `cases.py`: exact source anchors and researcher-authored draft expectations. This file is never sent to the resolver.
- `prepare.py`: source allowlist, span provenance, deterministic case/orientation shuffle and five frozen 20-case batches.
- `run_large.py`: invokes the original blind `run_models.py` through CampaignGenerator's Codex adapter with `gpt-6.1-terra` / medium, sequentially across five context and five surface-only arms.
- `evaluate_large.py`: reuses the original evidence evaluator, validates batch/root bindings, aggregates strict/exploratory metrics, and checks global coidentity contradictions.
- `test_scoring.py`: counterexamples for aggregation/scoring boundaries.
- `results/`: frozen protocol, compact relation/evidence results and validation records.

## Reproduce

From CampaignGenerator's root, using the existing Python environment. New preparation paths must be fresh. Generation transmits the selected private campaign narratives to the explicitly selected Codex backend; offline evaluation makes no calls.

```sh
python experiments/20261103-identity-scale/prepare.py \
  --campaign-root /home/kostadis/phandalin/Phandalin \
  --out /tmp/identity-scale-new

python experiments/20261103-identity-scale/run_large.py --run /tmp/identity-scale-new

python experiments/20261103-identity-scale/evaluate_large.py \
  --run /tmp/identity-scale-new \
  --previous experiments/20261104-terra-entity-resolution/results/comparison.json \
  --out /tmp/identity-scale-new-report.json

python -m pytest -q experiments/20261103-identity-scale/test_scoring.py \
  experiments/20261103-summary-entity-resolution/test_evaluate.py
```

For offline rescoring, use a scratch copy of `private-runtime/identity-scale-20261103-full-narrative` as `--run`. The evaluator regenerates detailed batch reports, so a scratch copy preserves the archive's original inventory. The archive is local evidence, not a complete campaign backup. Historical validation records and source hashes do not establish reviewer authority.
