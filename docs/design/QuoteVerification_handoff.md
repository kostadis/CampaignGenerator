# Handoff: quote verification (007) — what shipped, what's next

**Date**: 2026-08-04 | **Spec**: `specs/007-two-phase-extraction/`
**Next feature**: `docs/design/QuoteTriage_seed.md` + `QuoteTriage_research.md`

Pick-up note. Everything below is on `main`; nothing is in flight.

---

## 1. What exists now

`sd_verify_quotes` — a **deterministic, zero-token** quote verifier. It parses
`> "…"` blockquotes out of a session summary or scene extractions and asks
whether each is a contiguous span of the VTT. No model, no network, no
`--backend`. Five verdicts: `verified` / `near` / `unverified` / `unscored` /
`exempt`.

`sd_agent --stage {summary,scenes}` — runs a stage's generation, then that
stage's checks, then **stops at the human gate**. There is deliberately no
`--stage all`.

Both are installed as console scripts in `~/.venvs/main/bin` and smoke-tested.
The Session Doc Editor has a Verify button and a pipeline dot; knobs live in
`<config>/session_doc.yaml` under `verify:`.

**Nothing is auto-corrected**, ever. The only write is an idempotent
`<!-- cg:unverified -->` marker; `--report-only` suppresses even that.

**How to use it**: `docs/cli/quote_verification_howto.md` — operator's manual,
including a table of every error message and what it actually indicates.

## 2. The three findings that matter more than the feature

**a. DeepSeek was not the problem.** Post-`6e00f54`, Claude and DeepSeek are
indistinguishable at Stage 2 — 93% vs 95% exact verbatim, 12 vs 12 flagged. The
71%-verbatim corpus that motivated all of this was from the **pre-fix era**, not
from a model. `research.md` D8c has the control run.

**b. Spec 007's founding number was measuring a bug.** D1's *"only 64% of quotes
are exact verbatim even from Claude"* was computed on pre-`6e00f54` data. With
current code it is 93%. D1 and D8b carry banner warnings rather than being
rewritten, so the reasoning stays auditable — but **do not quote "186 findings
per session, ~90% benign" again.** The real figures are ~25 non-verbatim and 12
flagged, about half actionable.

**c. The failure mode is stitching, not fabrication.** In both post-fix corpora,
**9 of 12** flagged quotes are two real utterances welded into one — every word
genuine, only the join invented. DeepSeek invented *nothing*. A stitched quote
reads perfectly plausible, which is why a reviewing LLM would pass it and string
matching catches it free.

**And the threshold is not the lever.** Sweeping 0.85 across its whole plausible
range moves 2 quotes out of 390. Leave it alone.

## 3. What to do next

The original ask — *"use the DGX to determine if the quotes were real"* — is only
half-served. 007 answered a different question deterministically, which was
right, but three questions remain that string matching provably cannot answer:

1. **Which inline `"…"` spans are dialogue?** Stage 1 checks blockquotes only,
   so ~97% of a DeepSeek summary's quoted material is never looked at. This is
   where the original "fake quotes" complaint most likely lives.
2. **Did a `near` edit change the meaning?** `"My kind"` for `"Mankind"` scored
   0.92; a harmless stutter removal scored 0.94. No threshold separates them.
3. **Did the attributed speaker say it?** Currently unchecked entirely.

**Start here**: `docs/design/QuoteTriage_seed.md` §1 has the paste-able
`/speckit-specify` description; §3 has five clarify questions left deliberately
open. `QuoteTriage_research.md` carries R1–R13 so the spec run does not re-derive
measurements that cost several DGX and subscription runs.

**Step 0 you will forget**: spec-kit's skills are gitignored, so `/speckit-*`
will not resolve in a new worktree until you copy them in *and start a new
session there*:

```bash
cp -r ~/src/CampaignGenerator/.claude/skills <new-worktree>/.claude/skills
```

Copy only `skills` — not `.claude/` wholesale, or you drag the worktrees along.

## 4. Open follow-ups (filed on 007, none started)

- **T052** — close the Stage 1 coverage hole. The cheap fix is a *prompt
  contract* (require `> "…"` for dialogue in `config/agents/enhance_summary.md`),
  not a looser parser. Cannot help artifacts already on disk.
- **T054** — `dgxlib/models.yaml` has **no entry** for the served DeepSeek model,
  so it runs on `default` (`max_tokens 16384`, thinking off, 120 s idle). Fix
  before any feature that issues many small local requests.
- **T055** — deterministic **stitched-vs-invented** discriminator. Prototype and
  measurements in `specs/007-two-phase-extraction/calibration/segment_decomposition.py`.
  The two classes need opposite repairs ("split this" / "delete this") and a
  score cannot tell them apart. Probably worth more than anything else on this
  list.

## 5. Corpus state — two sessions are worth re-extracting

Measured verbatim rates across the live trees (`sd_verify_quotes` over every
`scene_extractions*` dir). **Most pre-fix extractions are fine** — this is not a
bulk job:

| session | quotes | verbatim | |
|---|---|---|---|
| Phandalin **20260623** | 522 | **71%** | re-extract (proven: 93% today from identical inputs) |
| OOTA **20260720** | 450 | **71%** | re-extract |
| Phandalin 20250528-ch03 | 623 | 83% | borderline, worth a look |
| everything else large | 255–659 | 90–99% | fine |

**Do not** re-extract on a low score from a `_smoothed` directory — `/voice-smooth`
strips disfluencies deliberately, so 39–68% there is the intended output. And
the 2026-03/04 Phandalin dirs use an older format the Stage 2 parser barely
reads; their percentages are noise on samples of 0–18 quotes.

## 6. Operational notes

- **`~/src/dgx/current-setup.md` drifts.** It claimed Qwen3-Next-80B on spark1
  with a *"verified live, no drift"* note; spark1 was actually serving
  `deepseek-ai/DeepSeek-V4-Flash-0731`, and **spark2's chat slot was down**.
  Probe `curl http://192.168.1.147:8001/v1/models` before trusting it.
  `config/wiring.yaml`'s `dgx_model` is stale the same way (the endpoint is
  right); it is rendered/do-not-edit, so override per run with `--model`.
- **The subscription backend works** and is the cheap way to A/B against Claude:
  `--backend claude-code --model claude-sonnet-4-6`. Thinking is suppressed and
  `--effort high` pinned automatically.
- **Two merged worktrees remain** under `.claude/worktrees/`
  (`dgx-two-phase-extraction`, `scene-index-join`), ~93 MB. Harmless now that the
  guardrail scanners ignore them, but their branches are merged and they can go.
- Full suite from the main checkout: **1 failed / 2639 passed**. The failure,
  `test_mempalace_client::TestLiveRoundTrip`, is pre-existing and unrelated.

## 7. Method note, because it cost several hours

Three explanations were argued for a 71%-vs-95% gap between two corpora that
differed in **date as well as model**, and all three were wrong — including a
"rejection" of the alias hypothesis that re-normalised using *today's*
`build_alias_normalizer`, which carries a guard added in `6e00f54` itself and so
could never reproduce the old behaviour.

One control run — the same extraction with current code — settled it in minutes.

**When two measurements differ in more than one variable, run the missing arm
before theorising.** Related: `docs/design/EnsembleGroundingInvestigation.md`
records "three samples is not a calibration" for the same reason.
