# Reusing resolved references

Ordinary identity lookups should read a stored index. Model inference belongs in ingestion or explicit re-resolution of new/changed evidence, rather than every lookup. This experiment implements a small persistent proposal cache to exercise that boundary; it is not integrated into the production registry or a natural-language question-answering service.

The earlier model experiment made one context request containing 16 pairs, plus one context-removed control request. Its runner already reuses complete matching saved arms on reruns. That is experiment resumption, not yet a production query cache.

## Offline experiment results

Fourteen assertions passed using the actual saved Terra medium responses, with **zero new model calls**:

| Experiment | Outcome |
| --- | --- |
| Empty cache | All 16 pairs require resolution |
| Save, close/reopen, repeat ten times | 160/160 proposal lookups reused the saved results |
| Request canonical results from proposals | All 16 require review |
| Change model, effort, instructions, registry revision, rulings revision, or campaign | All affected snapshot lookups miss |
| Edit a passage, add candidate context, or change a marked reference | All snapshot lookups miss |
| Repeat ambiguous q16 | Ambiguity retained; no new inference |
| Corrupt saved response digest | All 16 corrupt entries refused |

Each row grouping several mutations represents separate checks in [results/reuse.json](results/reuse.json). Misses return `resolution_required`; this prototype never launches inference automatically. The driver imports saved outputs whose response and payload hashes match the generation record. It never reads draft gold, invents approvals, or writes canonical records.

## Proposed operating design

1. Ingest a source revision and select candidate mentions with their surrounding context.
2. Resolve a new evidence snapshot with the model and retain the input, output, model/settings, and evidence dependencies.
3. Validate evidence and review identity proposals through the existing authority rules. A cached proposal remains a proposal.
4. Answer reference/registry lookups deterministically from the stored relationships and return the evidence and review status. A bare label can still produce several candidates.
5. New evidence, corrections, candidate-set changes, or relevant GM rulings trigger invalidation and selective re-resolution. Keep unresolved relationships ambiguous until new evidence or a ruling changes them.

This does not remove an optional model used to phrase a natural-language answer, synthesize several sources, or interpret a new free-text question. That is a separate step from deciding whether two stored mentions denote the same creature. The present tests concern the latter only.

## Invalidation boundary

The current Terra input includes all 14 passage blocks. Every block is consequently a dependency, including blocks outside a particular target pair. This conservative prototype keys the full payload, campaign, model, effort, system instructions, registry/rulings revisions, and pipeline version. A single changed passage invalidates all 16 cached results. The fixture had no registry or rulings input, so their revision fields explicitly say `not_supplied`; mutations test the mechanism rather than claim actual registry integration.

To invalidate less work, the next accuracy experiment should compare the full batch with smaller encounter/candidate bundles. Hashing just two target passages while the model actually sees the full corpus would understate its dependencies. Cache performance does not establish identity accuracy, and these offline checks are not new model-accuracy measurements.

## Reproduce

```sh
python experiments/20261104-resolution-reuse/run_experiments.py \
  --runtime /tmp/orc-identity-terra-medium-20261104 \
  --out experiments/20261104-resolution-reuse/results/reuse.json
```

SQLite data is created in a temporary directory and removed after the run. Compact results include hashes and outcomes, not campaign prose or model explanations. No production integration, canonical promotion, commit, or push was performed.
