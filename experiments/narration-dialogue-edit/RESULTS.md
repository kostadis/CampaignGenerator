# Initial A/B/C editing results — 2026-09-06

Nine independent calls with `gpt-6-astra`, medium reasoning: three approaches on unchanged v1 drafts narrated by Zenvon, Vukradin, and Valphine. Within each case, the user payload was identical across approaches. This was a single-run qualitative comparison, not a blinded or repeated evaluation.

## Read

- **A, light dialogue copyedit:** followed the narrow scope in all three cases. Safe but often too superficial to remove the transcript-shaped roughness.
- **B, contextual dialogue edit:** the best starting point for a dedicated dialogue pass. It improved the unfinished questions and repeated calculation in the Vukradin draft while preserving all outside-dialogue prose in every case. A cadence regression in Zenvon's two-sentence “more effort / same output” line shows that preserving words and meaning does not guarantee preservation of performance.
- **C, integrated scene line edit:** produced useful overall passages for Zenvon and Valphine. It repaired awkward retrospective tense and integrated attribution without flattening their distinctive inner commentary. It was less consistent at cleaning dialogue; the repeated calculation remained in Vukradin's version.

There was no wholesale voice rewrite in these responses. No single approach won every scene. Recommend B for the separate dialogue-editing role; keep C available as a reviewed scene-level edit. Do not assume that stacking A, B, and C would improve the result; that was not tested.

## Measurements

| Narrator | Baseline words | A | B | C |
|---|---:|---:|---:|---:|
| Zenvon | 977 | 974 | 973 | 943 |
| Vukradin | 2311 | 2305 | 2304 | 2276 |
| Valphine | 1789 | 1787 | 1787 | 1780 |

Word counts are descriptive, not scores. A and B left the outside-dialogue text identical after replacing quoted spans and ignoring outer whitespace. C made modest, reviewable prose edits. The raw responses have not been repaired.

## Checks and limits

All nine backend identities match the requested model and effort. Hashes confirm that inputs and raw responses remain unchanged. The five experiment-runner tests pass. The reader's embedded JavaScript parses, local links resolve, and stored user-prompt hashes match across each A/B/C set.

Manual review of the complete diffs and affected source passages found no new events or loss of load-bearing narrative beats. The Valphine scene retains its final magical-disinterest exchange and knowledge boundaries. Existing source-to-draft problems, including the Obelisk pike/bike interaction, are not repaired by this experiment. Neither literal quote matching nor the duplicate-span detector is a semantic fidelity check.

Full local artifacts: `worktrees/narration-v1-dialogue-edit-results/` under the main CampaignGenerator checkout. Start with `passages.md`, then `index.html` and `review.md`. `cases.json` identifies the exact source and baseline files. Per-arm directories contain the submitted prompts, raw response, metadata, and unified diff.

The accepted writing brief and proposed editing contract were preserved in commit `b13bfe2`; the three test prompts and runner were frozen before generation in `046801c`. Production defaults and campaign inputs remain unchanged.
