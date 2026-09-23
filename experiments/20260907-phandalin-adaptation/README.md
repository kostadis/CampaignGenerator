# Test: write an adaptation from the existing reviewed record

Date: 2026-09-07. Exploratory, one generated chapter. Not campaign canon.

Start with the [new chapter](response.md), the offline
[side-by-side comparison](comparison.html), or the [evaluation](review.md).

## Question

Can narration become readable, characterful fan fiction when the existing
reviewed smoothed extractions already preserve the record? The test does not
rebuild those extractions or rerun their upstream checks.

This follows the [pipeline audit](../../docs/design/NarrationPipelineAudit.md).
The user's clarification is important: better session summaries reduce the
narrative's burden as an exhaustive record. Events still need to be accurate;
dialogue must remain recognizable; interior thoughts may be invented.
Provenance can connect multiple authoritative artifacts without requiring one
document to carry every responsibility.

## Design and actual run

- Session: Phandalin, 2026-09-02, all five scenes.
- Source repository: `kostadis/campaigns`, commit
  `bbf4e3c064b4e13b47ed523606a62936638a0cc6`.
- Generator checkout: `d9c5de8`; its existing Codex backend was used unchanged.
- Model: `gpt-6-astra`, reasoning effort `medium`, explicitly selected and
  confirmed by the adapter. One text-only generation, about 3 minutes 40 seconds.
- Kept: all five smoothed extractions unchanged, the existing POV assignments,
  and the two declared narrator examples.
- Changed: the writing contract; voice references reduced to their actual
  character-description sections; a concise synthesized campaign style brief
  replacing the old quote-lock and other conflicting editorial instructions.
- The historical final chapter was held out from the generation input. It is
  saved as [baseline.md](baseline.md) for comparison only.
- No generated prose was edited, regenerated, scrubbed, or promoted. No campaign
  files or production code were changed.

Exact inputs are [system_prompt.md](system_prompt.md) and
[user_prompt.md](user_prompt.md). The original reference files are retained in
`inputs/`, including references that were adapted rather than sent verbatim.
[case.json](case.json) records source identity and input hashes;
[run.json](run.json) records the actual backend selection and output hash.
These are file-level provenance, not automatic claim-by-claim certification.

## Evaluation limits

This is a feasibility test, not a controlled same-model A/B or a repeated trial.
Several prompt/reference choices changed together. The historical chapter was
already edited, and its original model identity is not attested here. The
generator was also asked for a whole chapter in one call. We cannot isolate
which change caused an improvement or attribute it to a model upgrade.

The review compares all five new scenes with their frozen source extractions,
checks consequential facts and selected dialogue, and considers reading quality.
It does not certify every sentence against the full VTT or all campaign lore.
The user remains the judge of whether these are the voices they want to read.

## Local commands and a presentation-only failure

From the CampaignGenerator worktree, the completed preparation and generation
commands were:

```sh
/home/kostadis/.venv/bin/python -B experiments/20260907-phandalin-adaptation/run.py prepare
/home/kostadis/.venv/bin/python -B experiments/20260907-phandalin-adaptation/run.py render
```

They deliberately refuse to overwrite an existing prepared case or model attempt.
Keep this directory immutable as evidence; use a fresh directory for another trial.

The original `reader` action wrote the metrics, then failed because its heading
regex greedily captured multiple lines. That was an experiment-helper bug, not
a model or production failure. The frozen runner was left untouched. The
separate [build_comparison.py](build_comparison.py) corrected only the HTML
presentation step, verifying all original input and output hashes first:

```sh
/home/kostadis/.venv/bin/python -B experiments/20260907-phandalin-adaptation/build_comparison.py
```

The resulting reader has five scene pairs and all five source extractions. It
also refuses to overwrite its output. No second model call was needed.
