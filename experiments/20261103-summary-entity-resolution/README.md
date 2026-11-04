# Orc/ogre reference resolution in actual summaries

This is the real-text follow-up to the synthetic bugbear experiment. It compares
16 marked-reference pairs in 14 raw passage blocks from seven explicitly
selected authored Phandalin summaries: Chapters 3, 4, 5, 18, 39, 42 and 46.
Archived generation attempts and generated flat summary copies are not inputs.

The model receives raw prose and marked spans, not hand-labeled location,
identity or role features. The source-based draft expected answers are held in
a separate file, hashed before calls. Three cases involving cross-session
continuity or underspecified group membership are exploratory; the other 13
have stricter literal-source expectations. None is a GM canon ruling.

Two arms use the same gpt-6.1-sol/medium selection: raw context and reference
surfaces only. Outputs remain unreviewed proposals. Evidence checking verifies
exact source substrings; a separate graph checks coidentity/anti-merge
consistency and keeps subset membership distinct from equality. Production
registry and campaign sources are never written.

## Reproduce

From this CampaignGenerator worktree:

```bash
python experiments/20261103-summary-entity-resolution/prepare_cases.py \
  --campaign-root /home/kostadis/phandalin/Phandalin \
  --out /tmp/orc-identity-new-run

# Requires authorization to transmit the selected private passages.
python experiments/20261103-summary-entity-resolution/run_models.py \
  --run /tmp/orc-identity-new-run --model gpt-6.1-sol --effort medium

python experiments/20261103-summary-entity-resolution/evaluate.py \
  --run /tmp/orc-identity-new-run

python -m pytest experiments/20261103-summary-entity-resolution/test_evaluate.py -q
```

The first output directory must be fresh. Targets include exact surfaces and
marked local excerpts; `--offset-only` reproduces the initial weaker target
presentation. The model runner retains successful
arms and refuses incomplete/stale records. Gold is not read by the model
runner. Runtime excerpts, prompts, raw responses and detailed model reports
stay in the explicit `/tmp` run directory, not this repository. Input selectors,
evaluation code, source metadata and the resulting findings are reproducible
without vendoring the campaign narrative into CampaignGenerator.

## Prepared run

Runtime directory: `/tmp/orc-identity-real-20261103`. Payload: 20,822 characters,
22 marked references, 16 comparisons. `registration.json` freezes payload,
draft-gold and source-hash-list identities before any call.

Cases include the two Chapter 4 ogres, a prior-ogre reference inside the later
fight, Chapter 5 continuation, numbered orcs within one battle, different orc
encounter scopes, allies and enemies in the same place, three hesitant orcs
within a ten-orc group, the three recruited stewards, and an explicit source
correction from “ogres” to “oozes.”

The user approved transmission and both trials are complete. The original
offset-only run is retained in `/tmp/orc-identity-real-20261103`; the corrected,
matched-instruction comparison is in `/tmp/orc-identity-real-20261103-marked`.
Both versions of both arms ran, for four model calls in total. Source spans and
draft expected answers stayed unchanged between trials.

The final context arm matched all 13 stricter source-based expectations, while
the surface-only arm abstained on all 16 pairs. Every final evidence quotation
covers its exact marked reference. One of the three exploratory cases still
contains an unsupported membership inference. See [FINDINGS.md](FINDINGS.md).
The ten local evidence/graph/target-rendering tests pass. These are small
researcher-scored trials, not independently GM-adjudicated accuracy estimates.
