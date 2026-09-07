# Three renderers, one set of messages — mechanical findings

Recorded 2026-09-07. Replays the three generation calls archived in
[campaigns#237](https://github.com/kostadis/campaigns/pull/237) on two further
renderers, with every system and user message byte-identical to the originals.

**These are the mechanical findings only.** No literary judgement is recorded
here, deliberately: campaigns#237 kept the assistant's reading separate from the
GM's, and the GM's blind read of `scene_blind_all.html` and
`chapter_blind_all.html` has not happened yet. Nothing below is a claim about
which draft is better.

| | astra | fable | spark |
|---|---|---|---|
| backend | `codex-cli` | `claude-code` | `dgx` |
| model | `gpt-6-astra` | `claude-fable-5-1` | `DeepSeek-V4-Flash-0731` |
| effort | medium | medium (explicit) | **no dial exists** |
| thinking | not recorded | always on | off |
| `max_tokens=32000` | accepted, ignored | enforced | enforced |

## 1. The effort dial does not survive the third backend

The experiment was framed as "same prompts at medium". Two of three renderers can
honour that. The Spark cannot, and the reasons are worth more than the arm:

- 0731's `reasoning_effort` scheme is **low / high / max**. There is no medium.
- The deployed image's tokenizer wrapper predates the scheme: omitted passes
  through as `None`, an explicit `"low"` is mis-mapped to `"high"`.
- `campaignlib`'s DGX path sends no `reasoning_effort` at all.
- `dgxlib` pins the model to `thinking_default: false`, so the wire request
  carried `chat_template_kwargs: {enable_thinking: false}`.

A cross-backend "hold effort constant" comparison is not generally available.
Whatever the prose shows, that constraint is real and precedes it.

## 2. `max_tokens` means three different things

The same `32000` was **ignored** by the Codex adapter, **enforced** as
`CLAUDE_CODE_MAX_OUTPUT_TOKENS` by the claude-code path, and **enforced** by
vLLM. Any cross-backend comparison inherits that as an uncontrolled variable;
this one does, and says so rather than matching it after the fact.

## 3. Typography: Astra is the outlier, and the pipeline assumes Astra

| renderer | typographic `’` | ASCII `'` |
|---|---|---|
| astra (chapter) | 164 | 0 |
| fable (chapter) | 0 | 233 |
| spark (chapter) | 0 | 361 |
| historical (shipped) | 102 | 186 |

Two of three renderers normalise apostrophes to ASCII from identical input. The
smoothed extractions and the POV plan are written with `’`, so **a downstream
verbatim-quote check or lint keyed on that character would fail against
two-thirds of the renderers you might plausibly use.**

This surfaced as a false failure: the fable chapter run recorded `failed` because
its structural check compared headings verbatim and fable spells `Rsolk's` where
the plan spells `Rsolk’s`. The chapter was complete and correctly ordered. That
run record is left as-is — it honestly reports what its own check found — and
`build_reader.py` re-derives the comparison and admits the draft on proof that
the sole difference is typography. The Spark runner folds typography before
comparing and records verbatim headings alongside.

## 4. The Spark did not follow the scene output contract — twice

The scene system prompt says:

> Output only the finished scene under the supplied section heading. Do not
> include a chapter title, an audit, a coverage checklist, commentary on your
> writing, or new sections.

and the user message supplies `## Soma — Harpers Behind the Wall`.

| renderer | control arm emitted | composition arm emitted |
|---|---|---|
| astra | `## Soma — Harpers Behind the Wall` | `## Soma — Harpers Behind the Wall` |
| fable | `## Soma — Harpers Behind the Wall` | `## Soma — Harpers Behind the Wall` |
| spark | `# The Dead Drop at the House of a Thousand Faces` | `# Harpers Behind the Wall` |

**The control arm's title is copied verbatim out of the source extraction**,
which carries its own `# The Dead Drop at the House of a Thousand Faces` on line
7. The instruction exists *because* the source has a title; the local model lost
the instruction to the competing structure sitting in its own input. The
composition arm failed differently — it kept the right scene name but dropped the
`Soma — ` POV prefix and demoted H2 to H1.

The chapter arm, given five explicit fixed headings, complied on all five. So
this is not "the model ignores headings" — it is weaker instruction-following
where an instruction competes with a pattern in the context, which is the
failure mode a single-heading prompt maximally exposes.

Both scene drafts are admitted to the blind read for prose comparison, with a
`contract_violation` recorded in `adjudication.json`, and with **every** scene
draft's opening heading line stripped uniformly for display — otherwise the
violation itself would identify the draft on sight.

## 5. Shape metrics

From `metrics_all.json`. Structural counts, not quality:

| draft | words | paras | median para | quote-led | quote-led ≤5 words |
|---|---|---|---|---|---|
| historical (shipped) | 9,568 | 675 | 10 | 401 | 155 |
| astra chapter | 5,389 | 411 | 9 | 210 | 77 |
| fable chapter | 7,533 | 292 | **17** | 192 | 48 |
| spark chapter | 6,576 | 369 | 15 | 234 | 71 |
| astra control / composition | 1,781 / 1,699 | 115 / 117 | 11 / 10 | 58 / 62 | 18 / 20 |
| fable control / composition | 2,388 / 2,675 | 94 / 101 | **17 / 16** | 59 / 68 | 17 / 17 |
| spark control / composition | 1,204 / 2,780 | 67 / 161 | 12 / 11 | 36 / 123 | 13 / 44 |

The archived finding said of the Astra chapter: *"Fragmentation remained."* Its
median paragraph was 9 words against the shipped chapter's 10 — the adaptation
brief did not change the shape. Fable's median is 17 on the same messages, with
the fewest short quote-led paragraphs of any draft (48 against Astra's 77 and the
shipped chapter's 155).

That is a measurable difference on precisely the axis campaigns#237 recorded as
unresolved. It is **one sample**, it is a count of paragraph lengths and not a
judgement of whether the result reads better, and long paragraphs are not a goal
in themselves. It says the fragmentation the archive attributed to the brief may
be at least partly attributable to the renderer — a hypothesis for a repeated
trial, not a finding.

## Timing (Spark only)

`wall_clock_seconds`, uninstrumented, one sample each: chapter 395.2s (6,576
words ≈ 23 tok/s single-stream, inside the documented 21–31 band), control 94.4s,
composition 183.6s. Recorded because it is the number the hosted arms cannot
give at all, not as a benchmark.

## What none of this settles

One sample per arm, stochastic decoding, no seed, no repetition. A difference
between two drafts is as consistent with run-to-run variance as with the model.
The Spark arm is additionally not effort-matched and cannot be. Nothing here
revalidates the production narration path, and no draft is promoted by being
recorded.
