# 20260925-two-stage-extraction

Measurement pass behind **[docs/design/TwoStageExtraction_proposal.md](../../docs/design/TwoStageExtraction_proposal.md)**
— read that first.

Continues the #200 thread in
[EnsembleGroundingInvestigation.md](../../docs/design/EnsembleGroundingInvestigation.md):
`quote_offset` is computed, stamped, and never read by the merge decision. These
runners measure what that costs and prototype the shape that fixes it.

**Evidence only.** No campaign canon, no chapter revision, no production change.
Every script is **read-only** against `~/out-of-the-abyss/out-of-the-abyss`;
outputs land next to the runner.

## Scripts

| File | What it does |
|---|---|
| `positional_merge.py` | Replays the shipped `merge_facts` over a `per_chapter` tree and checks each output row's constituents against their source spans. Reports **MISSED** (separate rows, overlapping spans) and **UNSAFE** (merged rows, disjoint spans). Zero model calls. |
| `claim_pass.py` | The two-stage prototype. Stage 1 unions every finder's located quote into maximal intervals (deterministic); stage 2 runs each agent prompt over that span set with the full chapter in context, emitting `span: <id>` instead of `source_quote`. |
| `extract_names.py` | langextract over the whole bible, names task. The run that looked promising — 6,431 extractions, 100% grounded. |
| `lx_facts.py` | langextract on the *facts* task, matched to the ensemble: same model, same endpoint, same `config/agents/extract_facts.md` prompt, same chunk size. The comparison that rejected it. |
| `compare.py` | Coverage comparator. Reports rows / grounded / distinct spans / **source coverage** (% of chapter chars inside ≥1 resolved span) per lens and for langextract, plus the chars each side reached alone. |

`positional_merge.py` and `compare.py` are free to re-run. The two langextract
runners need the venv described below; `claim_pass.py` spends real Spark tokens.

## Paths are hard-coded, as in the predecessors

`positional_merge.py` carries the `/home/kroussos/` → `/home/kostadis/` manifest
remap (the cross-machine split CLAUDE.md describes). `claim_pass.py` has the
original scratchpad path to its langextract input baked in. For another corpus,
copy and edit — do not assume these resolve.

## Campaign source is not copied

The runners read `docs/chapters/*.md` and `docs/ensemble/per_chapter_rerun/` from
the OOTA campaign. Derived outputs are gitignored (see `.gitignore`) for the same
reason as `20260919-phandalin-event-kg/unregistered.json` — campaign content, not
evidence about the method. The numbers are frozen below and in the proposal.

## langextract needs its own environment

Not a CampaignGenerator dependency and not added as one. Python 3.11 (3.14 was
not tried beyond noting wheels are unlikely):

```bash
python3.11 -m venv .venv && ./.venv/bin/pip install "langextract[openai]"   # 1.7.0
```

Two patches are required to reach a Spark at all, both applied inside
`lx_facts.py` / `extract_names.py` and both worth knowing before anyone tries
again:

1. **The provider cannot send `enable_thinking`.** `providers/openai.py` builds
   its request from a hardcoded allowlist with no `extra_body` passthrough, so
   every call returns `content: None` with the whole budget in `reasoning`.
   Measured: 800/800 completion tokens on a trivial extraction. The runners
   monkeypatch `_build_chat_completions_params`. `campaignlib/api/backends.py`
   already handles this correctly via the dgxlib registry — this is a langextract
   gap, not ours.
2. **The router ignores an explicit provider.** `providers/patterns.py` sends
   anything matching `r'^qwen'` to Ollama (and `r'^deepseek'` likewise), which is
   every id these boxes have served. `language_model_type=` is deprecated and
   does not override it; `factory.ModelConfig(provider="OpenAILanguageModel")` is
   required.

## What these established

**The prose comparator costs both directions.** 56 chapters, 13,731 raw pass
facts → 12,650 merged rows, 93.8% of quotes locatable:

- **2,384 MISSED pairs** — separate rows whose spans overlap; **821** of them
  carry byte-identical `source_quote`.
- **43 UNSAFE rows** — merged rows whose members sit on disjoint spans; 8 are
  calendar dates; largest intra-row span gap 15,513 chars.

**The date collapse reproduces across models.** chapter_07 fused 9th / 10th /
1st-of-next-tenday into one row asserting the 10th, on `Qwen3-Next-80B` (09-06)
and again on `qwen3.8-flash-next` (09-24). ch05 fused 7th/8th and ch03 4th/5th
both times. These numbers describe the **`subject`** merge at 0.85, reached by
implicit fallback — the warning fired on 60 of 60 chapters. See the proposal for
why `embed@0.94` only narrows this to a 0.0025 margin.

**The two-stage split makes it structural** (chapter_07, n=1). 89 maximal
intervals at 96.0% coverage; four prompts concurrent in 119s; 286 claims against
the pipeline's 290, every one carrying a valid span id, zero `span: -1`. The
three date headings landed on distinct spans and all nine claims about them named
their own date. `interiority` kept its distinct perspective (48 claims, 47 npc).

**langextract was rejected.** Its reliability is tightly coupled to
`max_char_buffer` and the failures are silent:

| chapter | chars | langextract | ensemble 5-lens |
|---|---|---|---|
| ch08 | 4,505 | 90.7% | 89.9% |
| ch07 | 8,814 | 94.4% | 87.5% |
| ch05 | 14,016 | **6.2%** | 75.6% |

On ch05 at three buffers, median extraction length falls 47 → 37 → **24** chars
and the share long enough to be a supporting passage falls 39% → 30% → **1%** —
it degenerates from passages into bare names, which *align better*, so grounding
rises as coverage collapses. ch07 at 15K reported 100% grounded with 97/97 rows
typed `npc`. Best stable setting (1500) still loses on ch05: 62.9% vs 75.6%. The
optimal buffer inverts with chapter size and the OOTA mean chapter (17.2K) is
larger than the one where 15000 failed.

The buffer-4000 result (224/354 rows carrying a schema key as their extraction
class) is **this evaluation's fault** — two competing schemas in one prompt — not
a library defect. Recorded so it is not miscited.

## Caveats

- The claim pass is **n=1**, on the chapter already known to have the defect.
- **No end-to-end cost comparison** against the current pipeline was made. The
  split adds a stage without removing lenses and may be more expensive.
- The corpus behind these numbers is 60 of 62 chapters;
  `chapter_40_crystals_ghosts_and_crazed_earth` and `chapter_50_fungus_among_us`
  failed and `merged_rerun.json` is incomplete.
