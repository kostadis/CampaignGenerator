# Spec-kit seed: LLM quote triage on the DGX

**Date**: 2026-08-03 | **Companion**: `QuoteTriage_research.md`
**Predecessor**: `specs/007-two-phase-extraction/` (the deterministic verifier)

The research payload beside this file exists so a spec-kit run does not re-derive
facts already measured. Run the phases below in order; the only manual step is
copying the research file into the feature directory once it exists.

## Why this feature exists (read before writing the spec)

The original ask was: *"`enhance_summary` produces fake quotes — build an agentic
flow that uses the DGX to determine if the quotes were real."*

007 answered a **different question deterministically**: is this quote a span of
the VTT? That is exact string matching, an LLM is strictly worse at it, and the
answer is free. That was the right call and it is shipped.

But it left the original ask only half-served, in two ways worth naming:

1. **The local-inference exploration never happened.** Verification touches no
   model, so the Spark appears only in generation.
2. **Three questions remain that string matching provably cannot answer**, and
   all three are judgment calls — which is exactly what a model is for.

Measuring also **overturned the premise**: at Stage 2 DeepSeek invented *nothing*
(R3). Nine of its twelve failures are *stitches* — two real utterances welded
into one, every word genuine, only the join fabricated. A reviewing LLM asked
"is this quote real?" would pass all nine. So this feature must not be "have the
model check the quotes"; it must target the specific residue the free check
cannot reach.

## 0. Prerequisites

Speckit's skills are gitignored, so a fresh worktree has `.specify/` but no
`.claude/`:

```bash
cp -r /home/kroussos/src/CampaignGenerator/.claude/skills .claude/skills
```

Do **not** copy `.claude/` wholesale — the main checkout's `.claude/worktrees/`
is large. Skills load at session start, so `/speckit-*` will not resolve until a
**new session** is started in that directory.

Land 007 first (`feat/dgx-two-phase-extraction`). This feature builds directly on
`session_doc/verify_quotes.py` and `sd_agent`.

## 1. `/speckit-specify`

Paste this as the feature description:

> Add an optional local-model triage pass that runs **after** the existing
> deterministic quote check and looks only at what that check cannot decide.
>
> The deterministic verifier answers "were these words on the tape". Three
> questions remain that it provably cannot answer, and each is a judgment call:
>
> 1. **Which inline `"…"` spans in a session summary are actually dialogue?**
>    Today only `> "…"` blockquotes are checked, so for a summary that quotes
>    inline, ~97% of its quoted material is never looked at. The model reads each
>    inline span in context and says whether it is speech (and therefore should
>    be verified) or a label, title, or turn of phrase.
> 2. **Did an edit change the meaning?** Quotes that differ from the transcript
>    only slightly are bucketed as "near" and presented as probably harmless, but
>    a two-character edit can invert the sense. Given the quote and the real
>    line, the model says whether the change is cosmetic or substantive.
> 3. **Did the attributed speaker actually say it?** The current check answers
>    only whether the words were said, never by whom, although the transcript's
>    speaker labels are already parsed and carried on every finding.
>
> The pass runs on the local DGX box by default, is entirely optional, and the
> deterministic check must continue to work unchanged with no model available at
> all. It never edits an artifact and never decides anything: it produces a
> triage queue with its reasoning and the evidence beside it, for the GM to act
> on in Claude. Its input is only the small residue the free check hands it — a
> few dozen quotes per session, not the whole corpus — so a session costs a
> handful of small requests rather than one large one.
>
> Findings from the model must be visibly distinguishable in the report from
> findings the deterministic pass produced, so that a confident-sounding model
> judgement is never mistaken for a mechanical fact.

Suggested `--short-name`: `quote-triage`.

## 2. Copy the research payload in

Once `specs/NNN-quote-triage/` exists:

```bash
cp docs/design/QuoteTriage_research.md specs/NNN-quote-triage/research.md
```

Then have `/speckit-plan` **extend** R1–R13 rather than start a fresh research
pass. The measurements in there cost several DGX and subscription runs.

## 3. `/speckit-clarify` — the open questions

These are genuinely undecided and shape scope. Do not let the spec silently pick
one.

1. **Does 007 T055 (stitched-vs-invented, deterministic) land first, inside this
   feature, or not at all?** It is prototyped and working
   (`calibration/segment_decomposition.py`). It shrinks and *labels* what the
   model is asked to look at, so it is arguably a prerequisite — 9 of 12
   findings are stitches, and a model does not need to opine on those.
2. **Inline-span triage vs the prompt contract (007 T052).** Requiring `> "…"`
   for dialogue in `config/agents/enhance_summary.md` fixes coverage at zero
   check-time cost, but changes generation and cannot help artifacts already on
   disk. Triage handles both, at a cost. Both? Which first?
3. **Is the local model trusted enough to *narrow* the queue, or only to
   annotate it?** If the model says an inline span is not dialogue, does that
   span leave the report — or stay with a note? Narrowing is more useful and
   strictly more dangerous; a false negative is silent.
4. **Where does it surface** — an extra section in `quote_report.md`, a separate
   `quote_triage.md`, or both? Note the existing report is already the artifact
   the GM reads, and 007 deliberately ordered `unverified` before `near` so the
   volume never buries the findings.
5. **What happens when the box is down?** spark2 was unreachable during 007's
   calibration (R12). Degrade to deterministic-only with a stated note, or fail
   the run? (007's precedent: a check that could not run is *not* a check that
   passed, and says so.)

## 4. Remaining phases

`/speckit-plan` → `/speckit-tasks` → implement. Constitution checks that will
bite:

- **II (Human Checkpoint)** — the model triages, never decides, and never feeds
  another model's unreviewed output. See R9 (#151).
- **IV (Verbatim is Sacred)** — it must never rewrite a quote or a transcript.
  See R8 (D13): the alias set is knowledge, never a transform.
- **V (one seam per boundary)** — go through `client_from_args`; never build a
  client directly. `tests/test_backend_seam_guardrails.py` enforces it.
- **VI (CLI is the Engine)** — CLI first; the router shells out.
- **VIII (State is Discoverable)** — if triage was skipped, unavailable, or
  degraded, the report says so. Silence reads as a pass.

## 5. Did the seed work?

The spec is good if it: targets the three residual questions rather than
"re-check the quotes"; keeps the deterministic pass working with no model;
labels model findings distinctly from mechanical ones; and sizes the token
budget from R2 (~25 non-verbatim quotes per session) rather than from the corpus.

The spec has gone wrong if it proposes sending whole scene extractions to a model
for review, or treats a model verdict as authoritative over a string match.

## 6. Companion follow-ups already filed on 007

Not in this feature's scope unless the spec deliberately adopts them:

- **T052** — the `enhance_summary` prompt contract (see clarify Q2).
- **T054** — `dgxlib/models.yaml` has no entry for the served DeepSeek model, so
  it runs on `default` settings nobody chose. Worth fixing *before* a feature
  that issues many small local requests.
- **T055** — the deterministic stitched-vs-invented discriminator (clarify Q1).
