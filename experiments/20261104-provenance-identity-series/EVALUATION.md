# Evaluation protocol and reproduction

## What was held constant

The final real-text fixture uses seven authored summaries (Chapters 3, 4, 5, 18, 39, 42 and 46), 14 passage blocks, 22 exact marked references, and 16 fixed comparison pairs. Thirteen pairs have clearer literal-source draft expectations. Three cross-session/group-continuity cases are exploratory. The expectations are researcher interpretations, not independent GM rulings.

Sol medium, Terra medium, and local Qwen received the same final prompt/system bytes and payload. Gold stayed separate. Each model/configuration had a context arm and, where actually run, a words-only control. Qwen's schema configuration additionally used a native decoding constraint with no gold labels. Models/settings, source hashes, response hashes, failures and available transport observations are retained.

The earlier offset-only Sol trial is separately archived. Target presentation changed for the final trial; source spans and draft expectations did not. Do not pool the two trials into an accuracy estimate.

## Scoring

Primary metrics are exact relation agreement on 13 scored cases and agreement together with valid exact-target evidence. Secondary checks cover all 16 cases: evidence coverage, false coidentity proposals, graph contradictions, exploratory decisions, and words-only abstentions. Missing/malformed output is a protocol failure rather than a guessed answer. A valid quote confirms source bytes/target coverage, not the full semantic inference. A consistent graph need not be correct.

Synthetic tests cover ambiguous/missing/conflicting facts, movement, location hierarchy, same-label entities, groups, time bounds and cross-campaign isolation. Provenance tests exercise transitive impact, historical bindings, source drift, missing coverage and deterministic rebuilds. Reuse tests exercise snapshot dependency changes, persistence, ambiguity, corruption and the proposal/authority boundary.

## Offline reproduction from the private archive

Run from CampaignGenerator's root. `ARCHIVE` below is a task-local shell variable; the archive is ignored by Git. Use the repository's existing environment, for example `/home/kostadis/.venv/bin/python`.

```sh
ARCHIVE=experiments/20261104-provenance-identity-series/private-runtime

# Replay saved outputs; these commands make no model calls.
python experiments/20261103-summary-entity-resolution/evaluate.py \
  --run "$ARCHIVE/orc-identity-real-20261103-marked"

python experiments/20261104-local-entity-resolution/compare.py \
  --baseline "$ARCHIVE/orc-identity-real-20261103-marked" \
  --local "$ARCHIVE/orc-identity-qwen-off-20261104" \
  --local "$ARCHIVE/orc-identity-qwen-on-20261104" \
  --local "$ARCHIVE/orc-identity-qwen-schema-20261104" \
  --out /tmp/replayed-local-comparison.json

python experiments/20261104-terra-entity-resolution/compare_terra.py \
  --baseline "$ARCHIVE/orc-identity-real-20261103-marked" \
  --terra "$ARCHIVE/orc-identity-terra-medium-20261104" \
  --local-comparison /tmp/replayed-local-comparison.json \
  --out /tmp/replayed-terra-comparison.json

python experiments/20261104-resolution-reuse/run_experiments.py \
  --runtime "$ARCHIVE/orc-identity-terra-medium-20261104" \
  --out /tmp/replayed-reuse.json
```

Evaluators regenerate detailed `report.json` files in their supplied runtime directories. To retain the archive's exact byte inventory, first copy the relevant runtime directories to a fresh scratch directory and use those copies in these commands. Regenerated reports may contain different absolute paths while preserving measured outcomes.

The synthetic bugbear trial can be regenerated without private inputs:

```sh
python experiments/20261103-contextual-entity-resolution/run_experiment.py \
  --out /tmp/contextual-identity-reproduction-new
```

Rebuilding artifact provenance requires the declared campaign registry and original Chapter 59–60 bundle inputs; the private text archive is not a full campaign backup. Use the provenance directory's README and explicit workspace argument. Fresh output paths are required where documented.

## New model trials

Use the per-experiment README commands with a fresh runtime directory, an explicit model/effort or local endpoint configuration, and the same authorized input scope. The verifier and offline tests never contact a model. No new generation was performed merely to package this series. Hosted timing/token usage was not recorded, and the initial local thinking failure lost transport metadata; those unknowns remain unknown.

## Package verification

`verify_archive.py` checks the package's SHA-256 inventory and local Markdown targets, plus the private archive inventory if installed. `results/package-validation.json` records the actual packaging checks and test outcome. Historical validation files remain unchanged and bind their original runs; the package manifest binds the current archived code. Hashes establish byte identity, not reviewer authority or semantic truth.
