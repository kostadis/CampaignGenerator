# Frozen design and evaluation protocol

## Scope

The task tests mention-pair identity with manually supplied context. It does not test automatic candidate discovery, retrieval, extraction, approved registry mutation, or natural-language question answering. No mneme command or search index is used. The model is the same `gpt-6.1-terra` at medium effort as the prior 13/13 strict trial, with the exact original system instruction bytes.

The new fixture has 100 unique unordered reference pairs across 136 prepared marked occurrences from Chapters 9, 11, 14, 22, 24, 25, 26, 28, 29, 32, 33, 34, 36, 45, 48, 55 and 56. Of those occurrences, 135 participate in the selected pairs; one unused selector remains in the root preparation record and is excluded from model batches. These chapters exclude the original Chapters 3, 4, 5, 18, 39, 42 and 46. They are new to this experiment, not a claim that the campaign or people are unknown to the broader system.

Inputs come only from the top-level authored `summaries/20*-chapter_*/session-summary.md` files for the explicit chapter allowlist, never `attempts/` or generated flat copies. Every source and span is hash-bound. Full narrative Summary sections preserve alternative candidates and continuity prerequisites that paragraph-only selection could omit. Scenes/NPC appendix restatements are excluded to avoid duplicating the narrative. Models receive exact target surfaces and local marked excerpts alongside the original text.

## Case construction

The researcher selected source-based contrasts before generation: transformations, nicknames/renaming, first/second and numbered combatants, members versus entire groups, genuine versus disguised boars, reinforcements, life-state differences, representations, scope and uncertain cross-chapter continuity. Exact reverse duplicates and identical marked-occurrence pairs are refused.

There are 84 clearer scored expectations: 33 coidentity, 34 distinctness, 15 membership, one separate scope and one explicit ambiguity. Sixteen exploratory cases cover weaker continuity, underspecified individual selection, part/whole readings and representation. Their expectation agreement is reported separately and never added to the strict denominator. Only five relation classes appear; this fixture does not expand the original corrected-nonreferent test.

Cases are shuffled with seed 20261103 and orientations randomly reversed before assigning q-IDs. Five fixed 20-case batches receive the narrative sections for their referenced chapters. Each batch gets a context arm and a words-only arm. Surface-only references retain only ID and exact surface; narrative passages are removed. Ten model-arm requests are planned. No post-response case, prompt, gold, or budget tuning is allowed. Successful response retention uses the original runner's guards; failures are preserved for inspection rather than silently repaired or rerun.

## Blindness and checks

`prepare.py` writes root and per-batch gold, payload, source hashes and registrations before inference. The generation runner reads payload only, not gold or researcher case code. Gold is used after generation by the evaluator. `selection.json` binds the final protocol, root gold and unchanged blind runner before the first request.

The aggregate evaluator checks root/batch source identities, case membership, reference spans, narrative bytes, expectation parity, model/effort, unchanged system hash and all 100-case coverage before scoring. It reuses the prior exact-quote/target-span validator and adds a global graph check across batches.

Primary metrics are strict exact relation agreement and strict agreement with valid evidence. Report failures and false coidentity explicitly. Secondary results include all-case evidence failures, exploratory decisions, expected-ambiguity nonabstentions, per-category and per-relation results, words-only abstentions, and global coidentity/distinctness contradictions. A quote check establishes byte/target coverage, not semantic truth. A conflict-free graph need not be correct.

## Interpretation limits

The expectations are researcher-authored, not independently GM-adjudicated. The same research process selected the cases and interprets their text, so selection and interpretation bias remain. Several cases share passages or individuals; 100 pairs are not 100 independent trials. Only one generation per arm is planned, without repetition/randomization estimates.

The longer full-chapter narrative context and five batches differ from the original 14 selected paragraph blocks. A larger score can test whether the observed behavior extends to these new cases, but cannot isolate corpus size as the only changed factor or establish a general accuracy guarantee. The strict set has only one explicit ambiguity and one scope case; exploratory results are essential to assess overconfident inference. Automatic registry merges remain outside the experiment.
