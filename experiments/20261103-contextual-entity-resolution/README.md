# Contextual entity identity experiment

The question is whether the same surface name, such as “the bugbear,” can refer
to different individuals on three dungeon levels without giving each a unique
canonical name. Read [FINDINGS.md](FINDINGS.md) for the result and limits.

This experiment is separate from the earlier artifact-dependency graph. Four
synthetic creatures share the identical label `bugbear`: one starts on each of
three levels, and a fourth belongs to another dungeon. Every individual has an
opaque persistent ID. A moving individual keeps its ID. Labels and location
are not identity keys.

The resolver proposes candidates from explicit, time-bounded facts and scene
or referent context. Queries contain no expected entity ID; gold answers live
only in the evaluator. Every fact carries a source hash, exact source quote,
validity interval and fixture JSON pointer. The context is hand-annotated, so
this tests disambiguation after context acquisition, not extraction from raw
transcripts or NVIDIA Auto Ontology's implementation.

## Reproduce

From the CampaignGenerator worktree:

```bash
python experiments/20261103-contextual-entity-resolution/run_experiment.py \
  --out /tmp/contextual-identity-new-run

python -m pytest experiments/20261103-contextual-entity-resolution/test_contextual_identity.py -q

python experiments/20261103-contextual-entity-resolution/contextual_identity.py \
  --world /tmp/contextual-identity-new-run/world.json \
  --mention /tmp/contextual-identity-new-run/example_mention.json
```

The output directory must be fresh. All inputs are synthetic, all graph queries
use an in-memory SQLite database, and there are no model or network calls.
The experiment does not read or change campaign files or registry entries.

`results/final/report.json` contains all 28 designed cases, evidence traces,
context-removal results, and the location/name composite-key comparison.
`world.json` is the complete synthetic world; `cases.json` contains query/gold
pairs, but the resolver receives only the query. `validation.json` binds the
tested code and result hashes.

## Outcome meanings

- `supported_candidate`: one known individual fits the supplied constraints;
  this remains a proposal, never a canon merge or proof against unknown individuals.
- `ambiguous`: multiple known individuals remain possible, including those with
  missing evidence that cannot safely be excluded.
- `insufficient_evidence`: one possible individual remains, but the required
  constraints are unsupported, expired, too coarse, or lack a time reference.
- `conflicting_evidence` / `conflicting_context`: sources or referent constraints
  disagree; the resolver chooses neither by ordering nor by invented confidence.
- `candidate_group`: a plural reference remains a group of possible individuals.
- `not_found` / `no_supported_candidate`: no registered candidate label, or no
  known candidate fits; neither outcome creates a new individual.

Production code and the existing registry schema are unchanged. The current
registry rejects identical names/aliases assigned to different entities; the
test suite verifies that boundary explicitly. These instance IDs and nonunique
labels are held only in the experimental graph.
