# Chapter-Extract Consolidation — Killed Experiment

**Status:** Abandoned (2026-04-15). This records *why*, so the idea isn't re-attempted blind.
**Origin:** `feature/chapter-extract-consolidation` (deleted after this writeup landed).
**Related:** `pipelines/grounding/distill.py`, `pipelines/grounding/campaign_state.py`, `pipelines/grounding/planning.py`, `TheFlow.md`, the global "LLMs render, humans decide" rule.

---

## TL;DR

Three scripts — `pipelines/grounding/distill.py`, `pipelines/grounding/campaign_state.py`, `pipelines/grounding/planning.py` — each independently scan the same `summaries.md` during their extract phase. The experiment replaced those three narrow scans with **one rich structured extract per chapter**, consumed by three synthesizers (`1 × extract → 3 × synthesize` instead of `3 × (extract → synthesize)`).

The hypothesis validated at the extract layer and **failed at the synthesize layer**. All three final documents regressed materially against their hand-tuned baselines. The branch was killed per its own pre-committed kill criteria. **Correctness took precedence over the ~3× token saving.**

Do not re-attempt this as a token optimization without first solving the depth-vs-breadth problem below.

---

## What was tried

A new `chapter_extract.py` ran one pass per chapter against chapter-aligned chunks (`--split-chapters "# Chapter"`), emitting a fixed 8-section schema per chapter (`NPCs / Factions / Party / Quests & Threads / Locations / Events / Arc Score Events / Revealed Information`, plus optional `Tracked Items`). Each of the three synthesizers gained an additive `--chapter-extracts DIR` flag that skipped its own extract pass and read the shared directory instead. No existing flag, prompt, or path was modified — the new route was strictly parallel.

## What worked (the seductive part)

- **The schema is robust across chapter sizes** (2.7K–54K chars). Well-formed output, empty sections correctly omitted on small chapters.
- **Chapter-aligned chunking is clean without a smart chunker.** `# Chapter` gave 36 chunks, avg ~14K — a sweet spot for both API cost and human review. Sub-session headings and character asides sit *inside* chapters, so they don't create spurious boundaries.
- **One file per chapter is genuinely easier to review** than three separate per-script extract dirs for the same span.
- **Spot-check coverage looked comparable** to baseline on a single chapter (chapter 10): roughly equivalent coverage, different format, no critical misses.

This is exactly the trap the global rule warns about: **the rough extraction pass is the ceiling, not the floor.** A first-pass extract that looks impressive is the best the approach can do — not a sign it will hold up downstream.

## Why it was killed (Phase 4, full 36-chapter run)

| Doc | New | Baseline | Verdict |
|---|---|---|---|
| `world_state.md`    | 193 | 268 | Major regression — lost **The Party** and **Items & Artifacts** sections entirely |
| `campaign_state.md` | 207 | 311 | Regression — NPC table dropped 40 → 23 rows; party-resource inventory gone |
| `planning.md`       | 109 | 513 | Major regression — 17 NPC dossiers collapsed to 5; 10 factions → 4; Threat Tracker values *guessed* ("6–8 estimated") instead of read from arc-score docs |

Not truncation — outputs were well under the `max_tokens` cap.

### Root causes

1. **Per-chapter extract breadth comes at a per-entity depth cost.** An 8-section schema makes each chapter's NPC section terser than a dedicated NPC-only extract would be. Synthesis across 36 chapters then reconstructs per-NPC views from fragments — and when told to "be concise," the model cuts the long tail. Breadth at extract time traded away depth that the focused extracts preserved.
2. **Synthesize-from-chapters prompts were too compressing.** They *described* sections rather than *demanding enumeration*. Terser extracts + compressing prompts compounded the loss.
3. **A concrete design error.** `pipelines/grounding/distill.py`'s new prompt marked `## Party` as "incidental context." For `world_state.md` the Party block is the document's anchor — exactly the wrong thing to demote.

## The transferable lesson

**Consolidating N narrow LLM extracts into one broad extract is not free.** The narrowness *is* the depth. A focused "NPCs only" prompt enumerates exhaustively because that's all it's doing; a section inside an 8-part schema gets a fraction of the model's attention. You can't recover that depth in synthesis — the information was never written down at the granularity the synthesizer needs, so it reconstructs from fragments and drops the long tail.

There's also a **failure-coupling** cost the consolidation introduced: today a miss in `planning_extractions/` doesn't touch `campaign_state.md`. After consolidation, one bad shared extract degrades all three docs at once.

This is the same shape as the global pipeline rule: the consolidated extract is still `LLM extracts → human reviews → LLM renders` in structure, so it's *rule-compliant* — but rule-compliance doesn't buy back the depth lost when one prompt is asked to be exhaustive about eight things at once.

## If this is ever revisited

The cheap, untried remediation was **prompt-only fixes** (no new extracts needed — the chapter extracts are cached): demand enumeration rather than description in every synthesize prompt; reinstate `world_state`'s Party + Items anchors; force `planning` to emit one subsection per NPC with no filtering and to read Threat Tracker values directly from the arc-score docs. That would disambiguate *prompt-level compression* from *architectural depth loss*. Only if depth survives enumeration-forced prompts is the architecture worth pursuing — and even then, correctness on all three docs is the gate, not token cost.

The validation chapter extracts were kept at `campaigns/Phandalin/docs/chapter_extracts/` at kill time.

## Kill criteria (as pre-committed, for the record)

> If at any phase the unified extract produces systematically worse synthesis — missed NPCs, dropped arc score triggers, lost party acquisitions — abandon the branch. The existing three-scan pipeline works and the token savings are a cost optimization, not a correctness improvement. **Correctness takes precedence over cost.**

The Phase 4 outputs met these criteria. The branch was abandoned.
