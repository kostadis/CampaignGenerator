# The tested local model fell short of the hosted baseline

Completed 2026-11-04. The comparison used the exact frozen systems, user prompts,
target-marked passages, case order and hidden draft expectations from the
orc/ogre summary experiment. Local inference ran on the user's live
`qwen3.8-flash-next` DGX endpoint; the hosted baseline was gpt-6.1-sol/medium.
Neither campaign data nor the production registry was changed.

## Results

| Configuration | Clear-case labels | Clear cases with matching labels and valid evidence | Words-only control |
|---|---:|---:|---|
| gpt-6.1-sol / medium | 13/13 | 13/13 | 16/16 abstentions |
| Local Qwen, thinking off | unscoreable: malformed JSON | unscoreable | 16/16 abstentions |
| Local Qwen, thinking on | unscoreable: empty final text | unscoreable | not run after context failure |
| Local Qwen, thinking off + native JSON schema | 11/13 | 9/13 | 16/16 abstentions |

Native schema enforcement produced parseable output. It did not resolve the
remaining interpretation and evidence problems. Across all 16 contextual cases,
that configuration had three evidence-check failures: two in the stricter cases
and one exploratory case. There were no strict false-coidentity labels or
internal coidentity/distinctness graph contradictions, but one exploratory
identity proposal was too aggressive for the available evidence.

The normal-mode context response took 108.42 s and returned 4,609 completion
tokens with finish reason `stop`; its JSON was malformed, not truncated. Its
control took 39.78 s. Native-schema context took 101.72 s and 4,703 completion
tokens; its control took 25.34 s. Both context inputs used 8,503 prompt tokens.
These are observed shared-server request times, not isolated benchmarks or a
latency comparison with Codex, for which timing was not recorded.

## Material differences

- **Separate scopes became unsupported membership.** For the early fallen orcs
  and the later ranch corpses, Qwen selected `overlap_or_membership` instead of
  retaining separate encounter scopes. Its explanation also did not consistently
  agree with its selected label.
- **Different locations became asserted distinctness.** For the Shrine of
  Savras and Falcon's Lodge occupants, Qwen selected `distinct_referents` where
  the source establishes separate location scopes without proving exact
  membership continuity or disjointness. The hosted result preserved that limit.
- **Evidence anchoring failed.** Two stricter decisions had the expected label
  but failed the exact marked-reference evidence requirement. The other failure
  concerned the exploratory cross-chapter ogre continuation. The checker found
  a quotation that did not cover its marked occurrence and quotations absent
  from their specified passages. It performed no quotation repair.
- **An uncertain subgroup became the entire group.** Qwen equated the three
  recruited orcs with the allied orcs as a whole. The hosted model proposed
  membership instead, which itself remained insufficiently established. Neither
  proposal is a GM ruling; the local exact-identity merge is the more aggressive
  assertion in this unresolved case.

## What the modes establish

The default fast configuration was not a usable replacement under this output
contract. Its failed raw response was preserved rather than parsed piecemeal or
repaired to improve its score. The control remained appropriately cautious.

The reasoning configuration returned no final answer under the configured
16,000-token cap. The original driver did not persist the transport observation
before the client raised its empty-output error, so actual usage, finish reason,
served-model echo and exact elapsed time are unavailable. Token exhaustion is
not proven. Its recovered failure record marks those fields unknown, and no
control call was made. The harness now preserves such metadata and has a
regression test for the empty-final-text path.

The final follow-up used the server's advertised JSON-schema mechanism. This
changed decoding constraints while keeping task text and expected answers
unchanged. It enforced the same output fields and relation choices already
requested by the prompt; it supplied no answer labels. That removed the syntax
failure while leaving substantive differences visible.

## Recommendation and limits

The tested local configuration can propose contextual relationships, but it is
currently less reliable on this fixture for final identity decisions and exact
source evidence. Use native structured output and retain deterministic evidence
checks plus human review if using it as a candidate proposer. A lack of graph
contradictions does not establish semantic correctness: the subgroup merge
passed that consistency check.

This is one served, quantized local model and three configurations on a small,
researcher-scored fixture, not a general ranking of local models. The 13 clearer
expectations and three exploratory cases have not received independent GM
adjudication. Thinking modes, temperature controls and compute budgets are not
equivalent across the local and hosted backends. No other local checkpoint,
fine-tune, prompt tuning, smaller per-pair batch, or constrained citation-selection
method was tested. NVIDIA Auto Ontology's runtime was not involved.

`results/comparison.json` retains compact metrics, per-case differences and
transport measurements without the raw narrative or generated deliberation.
`results/validation.json` binds source/code/result identities and the eleven passed
local harness tests. Full private run artifacts remain in the named `/tmp`
directories from the README. Five model-arm requests were launched: two normal,
one reasoning, and two native-schema calls; resuming the normal run did not
repeat its failed context request.
