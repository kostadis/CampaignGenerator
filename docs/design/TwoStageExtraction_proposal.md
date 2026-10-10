# Two-Stage Extraction — find spans, then state claims (proposal, 2026-09-25)

> **Status: DEPRECATED, not adopted (2026-10-10).** This proposal targets the **ensemble** pipeline
> (five-lens atomic-fact extraction over narrated chapter prose). Out of the Abyss moved to
> **summary-native** grounding (specs 031–034), which reads the GM's structured summaries and never
> merges facts by prose similarity, so the merge defect measured here no longer sits on the live path.
> It is kept for its measurements and for the `langextract` negative result. Its lesson carried
> forward: merge by position or identity, never by how similar the prose looks. The prototypes it
> references were never committed (`experiments/20260925-two-stage-extraction/` stayed outside the repo).

## Why this doc exists

`EnsembleGroundingInvestigation.md` named the recurring pattern:

> **The pipeline computes a signal, serialises it, and then ignores it — forcing a
> later stage to guess what it was already told.**

Its instance **#200** was *quote position*: `locate_quote` finds the offset,
`ensemble_merge` stamps `quote_offset`, and the value is consumed only for
ordering. The **merge decision never reads it.** Grouping is
`(type, normalized subject)` and dedup inside a group is `SequenceMatcher` over
the `fact` prose.

This doc reports what that costs, measured on a fresh corpus, and proposes a
change of shape rather than a patch: **split extraction into a finder stage that
produces spans and a claim stage that cites them**, so the span becomes the merge
key by construction and no prose comparator ever runs.

It also records the evaluation of `google/langextract` as a candidate finder,
which was **rejected** — the negative result is the more useful half.

Everything below was measured against a corpus re-extracted 2026-09-24/25 from
the current OOTA bible. Artifacts and repro commands are in the last section.

---

## What the prose comparator costs

Measured by replaying the shipped `merge_facts` over the pass files and checking
each output row's constituents against their source spans. 56 chapters,
13,731 raw pass facts, 12,650 merged rows.

| | count |
|---|---|
| quotes locatable in the current chapter | 12,883 / 13,731 (93.8%) |
| **MISSED** — separate rows whose spans overlap | **2,384 pairs** |
| — of those, pairs with **byte-identical** `source_quote` | **821** |
| **UNSAFE** — merged rows whose members sit on **disjoint** spans | **43 rows** |
| — of those, calendar-date rows | 8 |
| largest intra-row span gap | 15,513 chars |

**MISSED** costs the reviewer duplicate rows. 821 pairs carry the *same quote*,
same `type`, same `subject`, and stayed separate because the `fact` sentences
were phrased differently — the comparator never looks at the quote.

**UNSAFE** costs a fact. Two moments fuse and one of them is gone:

```
[chapter_07_murder_most_foul]
  kept: "The events take place on the 10th day of the 2nd Tenday of Taraskh 1493 DR."
  member quotes: "## 9th day of the 2nd Tenday of Taraskh 1493"
                 "## 10th day of the 2nd Tenday of Taraskh 1493"
                 "## 1st day of the 3rd Tenday of Taraskh 1493"
```

Three of the chapter's own date headings collapsed into one row asserting the
10th. The same collapse occurred on the same chapter in the **2026-09-06** run
under `Qwen/Qwen3-Next-80B-A3B-Instruct-FP8`, and again on **2026-09-24** under
`qwen3.8-flash-next`. Chapter 05 collapsed 7th/8th both times; chapter 03
collapsed 4th/5th. **Two models, two runs, three weeks apart, same chapters.**
It is not model noise.

### Which merge method this describes

`subject`, at similarity 0.85 — reached by **implicit fallback**, because no
embed endpoint resolved. The warning fired on 60 of 60 chapters and named the
problem correctly. `config/ensemble.yaml` in the OOTA campaign has no
`embed_endpoint` key, so this is the path that actually runs there today.

Under `embed` at 0.94 these dates survive — but only just, and the team already
knew: the PR #204 calibration sweep recorded

> worst distinct pair — **two different in-world dates** — 0.9375

against a 0.94 threshold, with the duplicate band (0.9051–0.9528) **overlapping**
the distinct band. So dates are the known-hardest case under both methods, and
`embed`'s protection is a **0.0025 margin on overlapping distributions**. That is
a tuning result, not a safety property, and it is unavailable whenever the embed
endpoint is absent.

The mechanism is simple and unfixable by threshold: *"The events take place on
the Nth day of the 2nd Tenday of Taraskh 1493"* is ~97% similar to itself for
every value of N. The digit is the only load-bearing character and both
comparators are blind to it. Position is not.

---

## The proposal

Split the pipeline where it is already implicitly split.

```
stage 1  FIND      the five lenses run as today; their located quotes are
                   unioned into maximal intervals  ->  a numbered SPAN SET
                                (deterministic, zero model calls)

stage 2  CLAIM     each agent prompt runs once over the span set, with the
                   FULL chapter in context; a claim cites `span: <id>`
                   instead of emitting a free-text `source_quote`

stage 3  MERGE     group by span id. Claims on the same span are candidate
                   duplicates; claims on different spans are different facts,
                   always. No prose comparator runs.
```

Two rules are load-bearing.

**The full chapter stays in the claim prompt. Spans are hints, not boundaries.**
A claim pass that saw only its span would inherit an unreviewed scope decision
from stage 1 — LLM structures LLM output, the pattern the global pipeline rule
forbids and the same error class as the four-date collapse. Measured cost of
getting this wrong: 4.7% (ch07) and 5.1% (ch08) of existing facts sit *outside*
any single span and would become unreachable, concentrated in `date` headings and
`interiority` reactions.

**A claim cites a span id, not a quote string.** This is what moves #200 from a
retrofit to the architecture. `quote_offset` stops being a stamped-then-ignored
signal and becomes the key the merge is built on.

---

## The experiment (chapter_07, n=1)

Stage 1 produced **89 maximal intervals covering 96.0%** of the chapter
(median 90 chars, max 252). Stage 2 ran all four agent prompts concurrently
across both Sparks: **119s wall clock**, 286 claims, **every claim carrying a
valid span id**, zero `span: -1`.

| result | value |
|---|---|
| claims | 286 (vs 290 from the current pipeline on this chapter) |
| spans drawing ≥1 claim | 86 / 89 |
| type spread | date 9, location 19, npc 147, event 63, object 35, monster 9, faction 4 |
| spans carrying >1 claim | 84 / 86 — merge candidates, adjudicated by identity |

**The date collapse became impossible.** The three date headings landed on spans
1, 55 and 86; all nine claims about them named their own date correctly. Claims
that *did* share a span were genuine duplicates of one fact — which is what
should merge.

**Claim variety survived.** `interiority` produced 48 claims, 47 typed `npc`,
distinct from the other passes — the lens perspective that a single generalist
pass does not produce.

**New finding:** `generalist` and `sweep` converged almost exactly once they saw
the same span set (49/49 npc, 3/3 date, 8/9 location, 2/2 faction). `sweep` earns
its keep as a *finder*; as a *claim-maker* over a shared span set it looks
redundant. Untested as a removal.

---

## langextract as a finder — evaluated and rejected

`google/langextract` (1.7.0) was evaluated as a stage-1 finder. Its headline
feature, `char_interval` source grounding, is what `locate_quote` already does —
deterministically, rather than via a post-hoc aligner. Measured on a names task
over the whole bible it looked strong: 6,431 extractions, 100% grounded, 1
example-leak in 6,431.

On facts, with the same model, endpoint and prompt as the ensemble, it **was not
stable across chapter size**:

| chapter | chars | langextract coverage | ensemble 5-lens union |
|---|---|---|---|
| ch08 | 4,505 | 90.7% | 89.9% |
| ch07 | 8,814 | 94.4% | 87.5% |
| ch05 | 14,016 | **6.2%** | 75.6% |

The mechanism, measured on ch05 at three buffer sizes:

| `max_char_buffer` | chunks | rows | median extraction len | ≥60 chars | npc% |
|---|---|---|---|---|---|
| 1500 | 10 | 233 | 47 | 39% | 73% |
| 4000 | 4 | 354 | 37 | 30% | 30% |
| 15000 | 1 | 136 | **24** | **1%** | 85% |

As the chunk grows the library extracts **shorter**, degenerating from supporting
passages into bare names. Three compounding causes:

1. **Fixed output budget, unbounded demand.** One chunk is one call producing one
   JSON array, and `max_output_tokens` does not scale with `max_char_buffer`.
2. **Few-shot dilution.** With no hard schema, "what an extraction looks like"
   lives entirely in the `ExampleData` block. At 1,500 chars that block is ~12%
   of the input; at 14,000 it is ~1.3%, and the model falls back on "list the
   named entities." This is also why typing collapsed — ch07 at 15K returned
   **97 of 97 rows typed `npc`**.
3. **Alignment rewards the degenerate output, so the failure is silent.**
   `char_interval` is a string search. A 24-char name aligns trivially; a 90-char
   passage is likelier to be paraphrased and fail. Grounding therefore *rises*
   as coverage collapses — ch07 at 15K reported 100% grounded while typing
   everything `npc`. No exception, no warning.

Best case at its stable setting (1500) on ch05 is still **62.9% coverage against
the ensemble's 75.6%**, and the optimal buffer *inverts* with chapter size — 15000
won ch07/ch08 and destroyed ch05. The OOTA mean chapter is 17.2K, larger than the
one where 15000 failed. There is no single setting for this corpus.

**This is independent confirmation of the size-chunking thesis already in
`EnsembleGroundingInvestigation.md`** — that `annotate_pov` is *"a repair for
damage size-chunking inflicts."* The ensemble is robust here because it made
chunk size a **lens axis** rather than a tuning parameter. Measured on ch05,
`small` (6K) uniquely contributed 14.4% of coverage and `large` (15K) 5.7%: same
text, different scale, different material.

**One failure was the evaluation's fault, not the library's.** At buffer 4000,
224 of 354 rows carried a schema key (`type`/`entity`/`fact`/`source_quote`) as
their extraction class. That is a two-schema collision introduced by feeding
`config/agents/extract_facts.md` — which specifies its own JSON shape — inside
langextract's `extraction_class`/`extraction_text` wrapper. A native user would
not hit it.

**Two integration frictions, recorded so nobody re-derives them.** The OpenAI
provider builds its request from a hardcoded allowlist (`providers/openai.py`)
with no `extra_body` passthrough, so `chat_template_kwargs: {"enable_thinking":
false}` cannot be sent and every call returns `content: None` with the whole
budget in `reasoning` — the trap `campaignlib/api/backends.py` already handles
via the dgxlib registry. And `providers/patterns.py` routes anything matching
`r'^qwen'` to Ollama, `r'^deepseek'` likewise; `language_model_type=` is
deprecated and does not override it, so `factory.ModelConfig(provider=...)` is
required.

---

## What this does not fix

- **Nothing about the five lenses as finders.** Each contributes real unique
  coverage and *the ranking reorders per chapter*: `large` 8.0% on ch08 and 0.3%
  on ch07; `small` 0.2% on ch08 and 14.4% on ch05. No lens is safely droppable,
  and an earlier claim in this investigation that they were redundant was an
  artifact of including langextract in the comparison set.
- **Cost.** This adds a stage. Stage 2 was 119s for four concurrent prompts on
  one chapter, but stage 1 still runs all five lenses. **No end-to-end cost
  comparison against the current pipeline has been made.** It may be more
  expensive.
- **It is not a correctness guarantee.** Claims are still LLM output and still
  need the GM checkpoint. What changes is that the *merge* stops being a model-
  adjacent judgement and becomes identity.
- **Type errors remain.** Both harnesses mistype: langextract calls a mushroom an
  `npc`, the ensemble files a spore radius under `location`.

---

## Open questions

1. **n=1.** The claim pass ran on chapter_07 only — the chapter already known to
   have the date defect. ch05 (14K, where langextract broke) is the first thing
   to test.
2. **Span granularity.** 89 intervals at 96% coverage was usable on an 8.8K
   chapter. Unknown at 17K+, and unknown how it interacts with `scene_index` /
   `chunk_by_scenes` (PR #205), which already carries a coarser positional key
   that stage 3 might use instead of, or alongside, span ids.
3. **Does `sweep` survive as a claim pass?** It converged with `generalist` over
   a shared span set. Worth one A/B before removing.
4. **Relationship to #202's narrative pass.** `narrate_chapter.py` already
   produces a per-chapter prose narrative with `approved: false`. A span set is
   arguably a better input to it than the chapter, since it marks what earlier
   extraction actually located. Unexplored.

## Housekeeping found along the way

- `config/ensemble.yaml` (OOTA) pins `model: 'Qwen/Qwen3-Next-80B-A3B-Instruct-FP8 '`
  — a model no longer served on either Spark since 2026-09-10, **with a trailing
  space inside the quotes**. `chapters_selected` is still pinned to a single
  chapter from a previous run.
- The 2026-09-24 rerun completed **60 of 62** chapters.
  `chapter_40_crystals_ghosts_and_crazed_earth` and `chapter_50_fungus_among_us`
  have no `merged.json`; `docs/ensemble/merged_rerun.json` is incomplete. The
  driver is resumable and skips finished chapters.
- The pre-2026-09-13 ensemble corpus is **stale against the current bible**:
  quote locatability 62.1%, versus 93.8% after re-extraction. Quotes carrying
  `quote_verified: true` from the 09-06 run exist in neither the current chapters
  nor the current bible. `docs/chapters/chapter_05_*.md` also still opens with
  `# Chapter 06` — the filename/heading drift `renumber_chapters.py` addresses.

---

## Reference — artifacts and repro

Prototypes live outside the repo (session scratchpad, not promoted):
`positional_merge.py` (measures MISSED/UNSAFE against the shipped algorithm),
`claim_pass.py` (stage 1 + stage 2), `lx_facts.py` and `compare.py` (the
langextract evaluation), plus `posmerge_rerun.json` with all 2,427 findings.

Corpus re-extraction, as run:

```bash
python pipelines/ensemble/ensemble_batch.py \
  --chapters 'docs/chapters/chapter_*.md' \
  --per-chapter-dir docs/ensemble/per_chapter_rerun \
  --out docs/ensemble/merged_rerun.json \
  --model qwen3.8-flash-next \
  --endpoints http://192.168.1.147:8001/v1 http://192.168.1.121:8001/v1 \
  --chunk-parallel 8 --chapter-parallel 3 --campaign-dir .
```

`--chunk-parallel 8` matches the Sparks' live `max_num_seqs 8`; the built-in
default of 4 was tuned for a retired configuration. Both boxes serve the same
id, so throughput — not single-stream latency — is the axis that matters.

Measurements worth not re-deriving:

- Span set, ch07: 426 raw spans → 267 distinct → **89 maximal intervals, 96.0%**.
- Facts outside any single span (would be lost to a span-scoped claim pass):
  **4.7%** ch07, **5.1%** ch08; concentrated in `date` and `interiority`.
- langextract on the full bible, names task, buffer 1200: 6,431 extractions,
  **100% grounded**, 1 example leak. Its stable regime is small chunks.
- Bible extraction surfaced three name candidates absent from the canon chain —
  `Ronc` (registry has `Runc`), `quagoth` (canon `Quaggoth`), and a `Zarith`
  occurrence that resolves in the registry to `Andarin Zarith`, a different
  entity, while sitting one sentence from `Sarith`. **Unruled — GM decision.**
