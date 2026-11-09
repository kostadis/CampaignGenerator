# The contextual identity result held on 100 new comparisons

Terra medium matched all 84 clearer source-based relation expectations, with 83/84 also passing the unchanged exact-target evidence validator. There were no false coidentity proposals among these 84 and no coidentity-versus-distinctness contradictions in the combined graph. This extends the earlier small-fixture result to these selected new cases; it does not establish production accuracy or authorize canon merges.

| Measure | Original Terra trial | Larger no-mneme trial |
| --- | ---: | ---: |
| All comparison pairs | 16 | 100 |
| Source chapters | 7 | 17 new chapters |
| Clearer scored relations matched | 13/13 | 84/84 |
| Scored relation plus valid exact-target evidence | 13/13 | 83/84 |
| False coidentity among scored cases | 0 | 0 |
| Words-only abstentions | 16/16 | 100/100 |
| Exploratory cases, excluded from scored denominator | 3 | 16 |

The larger context arm emitted 39 coidentity proposals, 35 distinctness proposals, 16 membership proposals, three separate-scope results and seven abstentions across all 100 cases. Its 16 exploratory labels matched 13 draft expectations. Those weaker cases must be read separately from the 84 clearer expectations.

## Scored categories

| Draft relation | Label agreement | Agreement with valid evidence |
| --- | ---: | ---: |
| Same referent | 33/33 | 33/33 |
| Distinct referents | 34/34 | 33/34 |
| Overlap or membership | 15/15 | 15/15 |
| Separate scope | 1/1 | 1/1 |
| Explicit ambiguity | 1/1 | 1/1 |

This tests same-label combatants, renamed captives, shapeshifting identity, genuine versus disguised animals, members versus groups, reinforcements, life-state differences and selected cross-chapter continuity. The strict set contains very few scope/ambiguity cases, and there are no new corrected-nonreferent cases; the broad label agreement should not obscure that imbalance.

## The evidence failure and exploratory disagreements

- **q007, Zeleen versus two offered wererats:** the relation was correctly distinct, but a quotation did not cover the exact nominated Zeleen occurrence. It is from the source and concerns the same named character, yet fails the positional evidence contract. This remains an 83/84 result under the stronger check; no repair or rerun was performed.
- **q006, one wounded Rift Weaver versus the later already-wounded spider killed by a spell:** Terra linked them. The draft expectation retained ambiguity because multiple spiders had been wounded. This plausible discourse inference needs adjudication before treating it as a canonical identity link.
- **q021, rat familiars in two chapters:** Terra returned separate scope where the draft expectation was ambiguity. Both avoid equating the summonings; this disagreement concerns the relation vocabulary and temporal scope rather than a demonstrated false merge.
- **q073, severed head versus retained body:** Terra returned coidentity, taking a whole-person reading. The exploratory draft distinguished the separately handled physical parts. This exposes an entity-granularity policy question; neither interpretation is independently GM-adjudicated.

The cases, expected labels and prompts remained frozen. Disagreements were not removed or reclassified after generation. Compact per-case outcomes and evidence errors are in [comparison.json](results/comparison.json); private full responses and source-bound reports are retained locally.

## What the control shows

Without the narrative context, Terra abstained on all 100 pairs. This is appropriate under the instruction that bare names and combat numbers are not globally unique. Its one strict expectation match in that arm is simply the case whose expected relation was already ambiguous; it should not be advertised as a one-percent identity-accuracy estimate. The contrast supports the conclusion that context enabled the distinctions on this fixture.

## Validation and limits

Ten planned model-arm requests completed: five independent 20-case context batches and five matching words-only controls, through the existing CampaignGenerator adapter. Four new scoring tests and ten unchanged evidence/graph/target tests passed. Fresh preparation reproduced all 31 frozen preparation files byte for byte. All 17 campaign source hashes stayed unchanged. No mneme, automatic retrieval, registry writes, index refresh, or canonical publication was used.

The model receives manually selected targets and full narrative Summary sections, rather than extracting mentions itself. The longer context and batch layout differ from the original paragraph fixture. Cases share sources and entities and are not statistically independent; expectations are researcher-authored, not independent GM gold. There is one run per arm. The next useful challenge is independent GM adjudication plus more ambiguous/overlapping groups and automatic candidate/context selection, rather than treating 84/84 as a general guarantee.

See [DESIGN.md](DESIGN.md), [protocol.json](results/protocol.json), and [validation.json](results/validation.json).
