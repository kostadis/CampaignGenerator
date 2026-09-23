# Third renderer — the DGX Spark

**Evidence only. Not campaign canon, not a chapter revision, not a proposal to
change the production pipeline.**

The third pass over the messages archived in
[campaigns#237](https://github.com/kostadis/campaigns/pull/237). Same three calls,
same byte-identical system and user messages, verified against the source
experiments' own manifests before anything runs.

| | archived | fable arm | this arm |
|---|---|---|---|
| backend | `codex-cli` | `claude-code` | `dgx` |
| model | `gpt-6-astra` | `claude-fable-5-1` | `deepseek-ai/DeepSeek-V4-Flash-0731` |
| effort | `medium` | `medium` (explicit) | **none — see below** |
| thinking | not recorded | always on (Fable family) | **off** (`enable_thinking: false`) |
| `max_tokens=32000` | accepted, ignored | enforced | enforced |

Endpoint: `http://192.168.1.147:8001/v1` — **plain HTTP**. `https://` fails with
`TLS connect error: wrong version number`; vLLM is not serving TLS there.
`prepare` queries `/v1/models` live and refuses if the expected model is not the
one being served, so a swap on the box fails the experiment rather than
quietly renaming it.

## The effort dial does not exist here

The other two arms hold "medium" fixed. This one cannot, and saying otherwise
would be the more interesting result thrown away:

- The 0731 checkpoint introduced a `reasoning_effort` scheme of **low / high /
  max**. There is no medium in it.
- The deployed image's tokenizer wrapper predates that scheme. An omitted value
  passes through as `None`; an explicit `"low"` would be mis-mapped to `"high"`.
- `campaignlib`'s DGX path sends no `reasoning_effort` at all.
- `dgxlib/models.yaml` pins this model to `thinking_default: false`, so the
  resolved request carries `chat_template_kwargs: {enable_thinking: false}`.

So these calls run with no effort control and no reasoning trace. Read this arm
as **"the same prompts on the local box"**, never as "the same prompts at
medium". The recorded `resolved_extra_body` in `case.json` and each `run.json` is
what actually went over the wire.

## Reading the results

```sh
python3 -B build_reader.py
```

Builds the blind readers across **all three renderers** — nine drafts from one
set of frozen messages:

- `scene_blind_all.html` — six single-scene drafts (3 renderers × 2 prompt arms),
  randomly labelled.
- `chapter_blind_all.html` — three generated chapters, randomly labelled, beside
  the edited chapter that shipped.
- `metrics_all.json`, `adjudication.json`, `combined_assignment.json` (the key).

Read the HTML before opening the assignment.

### One draft is admitted by adjudication, not by its own run record

The fable chapter run recorded `failed`. Its structural check compared headings
verbatim, and fable spells `Rsolk's` where the plan spells `Rsolk’s` — a complete,
correctly ordered five-section chapter rejected over two characters. Across the
whole chapter fable used 233 ASCII apostrophes and zero typographic ones; Astra
used 164 typographic and zero ASCII. That is a per-model convention worth
knowing about (a downstream quote-verification or lint pass would trip on it),
not a generation failure.

`build_reader.py` re-derives this from the preserved response and admits the
draft only on proof that the sole difference is typography. It does not edit that
run's record, which stays as the honest report of what its own check found.

This experiment's own heading check folds typography before comparing and records
the verbatim headings alongside, so the difference stays visible without being
fatal.

## What this cannot settle

One sample per arm, stochastic decoding, no seed, no repetition. A difference
between two drafts is as consistent with run-to-run variance as with the model.

Beyond that, this is **not a like-for-like quality comparison** and is not offered
as one: a local 284B/13B-active MoE at fp8 with thinking disabled, against two
hosted frontier models, one of which thinks unconditionally. The uncontrolled
differences are named in `case.json` rather than buried.

Timing is one uninstrumented wall-clock number per arm (`wall_clock_seconds`),
recorded because it is the thing you cannot get from the hosted arms at all — not
because it is a benchmark. The box is one cross-box TP=2 endpoint (spark1 head,
spark2 headless worker) run in throughput mode; single-stream decode was
spot-checked at ~21–31 tok/s and cold prefill at ~1,000–1,200 tok/s, so a
chapter-length generation is a minutes-scale call by construction.

## Provenance

- Source campaign commit `bbf4e3c064b4e13b47ed523606a62936638a0cc6`, inherited
  from the archived case, not re-resolved.
- Generator checkout `d9c5de87a0ec4831c1cdc999b26491851b1f7c01` — the commit the
  archived runs used.
- Served model and context length read live from `/v1/models` at prepare time and
  recorded in `case.json`.

Nothing outside this directory is written. The sibling experiments are read only,
and the campaign workspace is not touched at all.
