# Terra medium matched Sol on the scored cases

`gpt-6.1-terra` at medium effort completed both arms with valid structured responses. It matched all 13 clearer source-based expectations, and every one of those answers passed the quote/target evidence checks. All 16 context answers passed evidence validation. No internal coidentity contradictions were detected.

| Model/configuration | Correct labels, 13 scored cases | Correct labels with valid evidence | Words-only abstentions |
| --- | ---: | ---: | ---: |
| gpt-6.1-sol medium | 13/13 | 13/13 | 16/16 |
| gpt-6.1-terra medium | 13/13 | 13/13 | 16/16 |
| Local Qwen, nonthinking + JSON schema | 11/13 | 9/13 | 16/16 |

The other local Qwen modes produced malformed JSON or an empty final response; they cannot be scored as successful runs.

Terra differed from Sol on two of the three exploratory cases, which are excluded from the 13-case score:

- **q14, ranch corpses versus Big Al's account of slain raiders:** Sol proposed the same referent; Terra retained ambiguity. The draft expectation favors identity, but no independent GM ruling resolves this case.
- **q16, three hired orcs versus the broader allied orc group:** Sol proposed membership; Terra retained ambiguity, matching the cautious draft expectation. The text does not explicitly establish the membership link. Local Qwen instead merged the references as the same group.

For this small fixture, Terra therefore preserves Sol's scored performance while avoiding the unsupported q16 membership proposal. Its q14 abstention also illustrates the cost of caution. This does not establish a general model ranking or production accuracy.

Both Terra arms used exactly the same prompt/system/payload bytes as Sol. Hidden expectations were unchanged and were not sent to the model. The seven campaign summary files still match their frozen hashes. Ten shared evaluator tests passed. See [comparison.json](results/comparison.json) and [validation.json](results/validation.json).

This was one run per arm, with researcher-authored source expectations and three explicitly exploratory cases. Evidence validation checks exact quotation and target coverage; it does not independently prove semantic identity. Timing and token usage are not available in the adapter records, so this trial makes no cost or speed claim. Campaign documents and the canonical registry were not changed.
