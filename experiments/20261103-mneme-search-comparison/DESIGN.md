# Retrieval comparison design

## Question

Can mneme's existing semantic/hybrid search supply the evidence that our contextual identity experiment was handed directly? Retrieval, interpretation and authority are different stages. This trial measures the first stage plus optional opening of retrieved source files. It makes no entity merge, disjointness, subset or approval predictions.

## Inputs and fixed protocol

Use the frozen final payload from the Terra/Sol comparison: 16 case pairs, 22 marked references, 14 raw passage blocks from seven summaries. The prior draft relation expectations are not read by the runner or evaluator. The model experiment was given all 14 selected passages; mneme instead searches the existing 59-file declared summary corpus. It is therefore a retrieval-stage comparison, not matched-context model accuracy.

After one exploratory connectivity/search probe, freeze `queries.json` before the scored requests. For each case use a human-authored context query built from encounter clues in the target source, and compare it with `ogres` or `orcs` depending on the reference surface. Shared bare queries are deduplicated: two bare requests plus sixteen contextual requests, all `--wing summaries --results 10`, with no chapter/date/room filter. These are favorable known-context queries, not blind queries from independent users. There were no query revisions after scoring and no failed-request retries.

The CLI returns ranked verbatim drawers followed by a separately labeled related-theme block. Parse only verbatim results. Preserve raw output, warnings, request argv, return code, elapsed time and hashes. Local embedding inference is used at query time; no generative inference is launched by the harness. Theme tags already stored in the palace may have been generated earlier and are excluded from evidence scoring.

## Measures

- **Both sources:** at least one returned verbatim drawer from each expected chapter's unique prefixed source basename. This coarse measure can succeed with irrelevant text from the right chapter.
- **Both target neighborhoods:** returned text contains the exact marked occurrence's local context, up to 60 characters before/after its surface, after whitespace normalization, in the expected chapter. This narrow positional proxy is stricter than merely returning a helpful paraphrase or another description of the same event; it is not a semantic support judgment.
- **After source expansion:** open only the unique source basenames actually returned, resolve them through the current declared summaries TOC, verify source hashes, and check the same target neighborhoods against those full files. Gold/source targets are used only to score availability, never to select additional files to open.

Report each measure at top 1, 5 and 10. A pair can require two files; many pairs use two targets in the same chapter. Thus the 16 measurements are correlated and not a statistical accuracy estimate. The chosen 60-character window is a diagnostic of exact target context and may cross drawer boundaries. Full-file expansion trades more input text for greater evidence availability.

## Freshness and limits

The declared embedder is Ollama `qwen3-embedding:0.6b` at `192.168.56.1:11434`, with a matching 1024-dimensional palace. The successful live status check reports a healthy store but a globally stale corpus: 52 unmined and 15 stale files. The seven chapters used by this fixture match the current source hashes in the mined record; all 22 target neighborhoods are present in their current flat summaries. This bounds the freshness observation to the fixture, without proving complete stored-drawer parity.

Every fixed search emits a warning that historical embedder identity was not recorded. Dimensional agreement does not establish which historical model produced every vector. The experiment preserves that uncertainty and does not set identity, re-mine, or regenerate the palace. The initial sandboxed status could not verify the endpoint; the successful network-enabled status is the recorded environment observation.

The promising integration is search → source/neighbor expansion → evidence-backed identity proposals → review → stored relationship lookup. This trial implements only the retrieval/expansion measurement, not the downstream model or review integration. Comparing mneme coverage percentages directly to Terra's 13/13 relation score would mix different tasks.
