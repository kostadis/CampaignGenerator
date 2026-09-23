# Scene composition: a one-pair narration experiment

Date: 2026-09-07. Phandalin, September 2, scene 5: the House of a Thousand Faces.

Start with the [anonymous A/B reader](comparison.html), or open
[Version A](version-A.md) and [Version B](version-B.md) separately. Both are raw,
unedited model responses. Read them before the [evaluation](review.md) or the
[assignment key](assignment.json) if you want to make your own initial judgment.

## Question and treatment

The preceding [whole-chapter experiment](../20260907-phandalin-adaptation/README.md)
allowed freer adaptation, but still produced fragmented prose. The user asked
how to get the narrator to compose scenes rather than connect selected transcript
lines, then authorized this proposed two-version test.

The control retains that experiment's general composition paragraph. The other
version replaces only that paragraph with a scene-specific assignment: choose
where to enact or summarize, preserve whole interactions, and develop Soma's
experience of discovering the Harpers while Brewbarry is inside the tavern.
The [exact diff](prompt.diff) records the entire difference.

The factual restrictions, dialogue permissions, invented-interiority permissions,
genre, character references, prose examples, model, effort, and output format are
identical between arms. Both receive one shared [user message](user_prompt.md).

Both prompts were adapted equally from chapter scope to scene scope. They receive
the unchanged smoothed scene 5 extraction and its existing POV-plan entry, the
same clean descriptions of all four characters, and both existing narrator-example
files. They do not receive either prior chapter draft, a quality review, or the
other arm's output. No upstream source was rewritten.

## Provenance and execution

- Public campaign repository: `https://github.com/kostadis/campaigns`.
- Pinned campaign commit: `bbf4e3c064b4e13b47ed523606a62936638a0cc6`.
- Source material copied from the verified, frozen parent experiment, not the
  live campaign working tree. The original parent manifest is in `inputs/`.
- Generator checkout: `d9c5de87a0ec4831c1cdc999b26491851b1f7c01`.
- Requested model and effort: `gpt-6-astra`, `medium`, through the existing
  `codex-cli` subscription adapter. Each arm's `run.json` attests the actual
  selection and hashes the request and response.
- Two independent single-turn, text-only calls, launched concurrently. The
  adapter disables tools, project instructions, and external plugins. There is
  no model fallback and no automatic retry.
- Random A/B assignment was saved before generation. Neither model sees that
  assignment or information about the comparison.
- [case.json](case.json) hashes the frozen inputs, runner, reader, prompt diff,
  and predeclared [evaluation criteria](evaluation_criteria.md).
- No production code or campaign files were changed. Nothing is promoted to canon.

## Interpretation limits

One stochastic sample per arm cannot establish reliability or statistical
significance. There is no exposed shared seed. The scene-specific block combines
planning instructions with editorial choices; this test cannot separate their
effects. A positive result would support this particular writing assignment, not
prove that a generic automated planner can create equally useful assignments for
other scenes.

The assistant knows the hypothesis and prepares the treatment, but reads the
anonymous drafts before opening their assignment and records its initial
assessment separately. That is presentation blinding, not a double-blind study.
The user's preference is independent and more important for the target voices.

Factual review uses the supplied reviewed extraction, not a new full VTT audit.
Literary invention is allowed; omissions and errors are judged by their effects
on events, knowledge, character, and meaningful interactions. Paragraph counts
are diagnostic, not success criteria. A longer or less fragmented draft does not
automatically win.

The test design follows the task-specific comparison and human-judgment approach
described in [OpenAI's evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices).
[Official Astra guidance](https://developers.openai.com/api/docs/guides/latest-model#prompting-best-practices)
also informed checking for conflicting instructions while preserving the model
and effort selected for this test. It does not establish which creative brief
will produce the better story.

## Commands

Run from `/home/kostadis/CG-find-bug`:

```sh
/home/kostadis/.venv/bin/python -B experiments/20260907-phandalin-scene-composition/run.py prepare
/home/kostadis/.venv/bin/python -B experiments/20260907-phandalin-scene-composition/run.py render control
/home/kostadis/.venv/bin/python -B experiments/20260907-phandalin-scene-composition/run.py render composition
/home/kostadis/.venv/bin/python -B experiments/20260907-phandalin-scene-composition/build_reader.py
```

These commands refuse to overwrite an existing prepared case, model attempt, or
reader. Preserve this directory; create a separate case for further experiments.
