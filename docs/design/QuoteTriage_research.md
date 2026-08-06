# Research payload: LLM quote triage (companion to `QuoteTriage_seed.md`)

**Date**: 2026-08-03 | **Predecessor**: `specs/007-two-phase-extraction/`

Established facts, measured — not assumptions. A spec-kit run should **extend**
this rather than re-derive it. Every number below came from real runs on
Phandalin session `20260623` (1,244 VTT cues) unless stated otherwise.

Raw scored corpora are checked in at
`specs/007-two-phase-extraction/calibration/*.tsv`, with the scripts that
produced them (`calibrate.py`, `threeway.py`, `segment_decomposition.py`).

---

## R1 — What 007 already shipped (do not rebuild it)

`sd_verify_quotes` is a **deterministic, zero-token** verifier: it parses
`> "…"` blockquotes and asks whether each is a contiguous span of the VTT.
No model, no network, no `--backend`. Five verdicts:

| verdict | meaning |
|---|---|
| `verified` | exact, or whitespace-only difference |
| `near` | traceable to a real line, but edited |
| `unverified` | no plausible source line |
| `unscored` | < 4 tokens — matches anything, so no score is meaningful |
| `exempt` | `(paraphrase)`, `(truncated)`, `[inaudible]` |

`sd_agent --stage {summary,scenes}` runs generation then that stage's checks and
**stops at the stage boundary** (the Stage 1→2 human gate). Reports land at
`<session>/narration/quote_report{,_scenes}.md`. Nothing is auto-corrected; the
only write is an idempotent `<!-- cg:unverified -->` marker.

**The new feature must not weaken any of this.** In particular, verification has
to keep working with **no model available at all** — the deterministic pass is
the floor, and the LLM layer is strictly additive on top of it.

## R2 — The current quality baseline (post-`6e00f54`)

| corpus | quotes | verbatim | near | unverified |
|---|---|---|---|---|
| Claude (subscription, `claude-sonnet-4-6`) | 377 | **352 (93%)** | 13 | 12 |
| DeepSeek V4 Flash (spark1) | 390 | **371 (95%)** | 7 | 12 |
| Claude, **pre**-fix (2026-06-26) | 522 | 374 (71%) | 113 | 31 |

**Post-fix Claude and post-fix DeepSeek are indistinguishable.** The 71% figure
belonged to the pre-fix era, not to a model. So the LLM triage layer is being
designed for a corpus where **~25 quotes per session are non-verbatim and ~12
are flagged** — not hundreds. Token budget should be sized accordingly.

## R3 — The failure mode is STITCHING, not fabrication

Decomposing flagged quotes into their longest contiguous transcript spans:

| corpus | unverified | stitched | **invented** | unclear |
|---|---|---|---|---|
| DeepSeek | 12 | 9 | **0** | 3 |
| Claude | 12 | 9 | **1** | 2 |

**DeepSeek invented nothing at Stage 2.** Nine of twelve failures are two real
utterances welded into one quote — every word genuine, the *join* fabricated.

**This is the single most important design input.** A stitched quote is
coherent, in-character, and made entirely of real words, so it is exactly what a
reviewing LLM is *worst* at catching and what string matching catches for free.
Any design that sends a model to "check if the quote is real" will pass these.

The deterministic discriminator is prototyped and works:
`specs/007-two-phase-extraction/calibration/segment_decomposition.py` (filed as
007 T055, not wired in). It should probably land **before or with** this
feature, because it shrinks and labels what the model is asked to look at.

## R4 — The coverage hole: Stage 1 checks ~3% of DeepSeek's quotes

Quoted spans ≥15 chars in a generated `session-summary.md`:

| model | blockquoted (`> "…"`, checked) | inline (`"…"`, NOT checked) | coverage |
|---|---|---|---|
| Claude | 12 | 60 | 16% |
| **DeepSeek** | **5** | **131** | **3%** |

D5 (007) verifies blockquotes only, because an inline `"…"` is not reliably
dialogue — `the "liberators of the Ordning"` is a label, not speech. That
reasoning still holds; the *consequence* was not measured until now.

**This is where the GM's original "enhance_summary produces fake quotes"
complaint most likely lives** — in the 97% nobody checks. Deciding which inline
spans are dialogue is a genuine judgment call, which makes it the strongest
candidate job for a local model.

007 T052 proposes a cheaper alternative: a **prompt contract** requiring `> "…"`
for dialogue in `config/agents/enhance_summary.md`. The two are not exclusive
and the spec should weigh them — a prompt fix costs nothing at check time but
changes generation, and cannot help artifacts already on disk.

## R5 — Similarity cannot separate a meaning-changing edit from a harmless one

Two DeepSeek quotes, both bucketed `near`:

| score | quote | transcript | |
|---|---|---|---|
| **0.92** | "**My kind** has been spreading violence and pain…" | "**Mankind** has been spreading violence and pain…" | **meaning changed** |
| **0.94** | "No, I have my soul is for rent." | "No, I, I have, my soul is for rent." | harmless |

The corrupting edit scores *below* the harmless one. `Mankind`→`My kind` is a
two-character edit; `I, I have,`→`I have` is three. **Edit distance ranks them
the same because they are the same size**, so no threshold separates them.

**This is the second strong candidate job for a model**: given a quote and its
nearest transcript line, did the edit change the meaning? That is semantic
judgment, provably outside what string matching can do.

## R6 — The threshold is not a lever; do not spend design effort on it

Sweeping it across its whole plausible range:

| threshold | 0.60 | 0.70 | 0.75 | 0.80 | **0.85** | 0.90 | 0.95 |
|---|---|---|---|---|---|---|---|
| DeepSeek (19 scored of 390) | 1 | 6 | 10 | 10 | **12** | 13 | 15 |
| Claude post-fix (25 of 377) | 1 | 3 | 5 | 5 | **12** | 15 | 22 |

0.75→0.85 moves 2 quotes of 390. 0.85 stays.

## R7 — The `.vtt` choice moves the finding count 26%

Sessions carry both `*.transcript.vtt` (raw ASR) and `*.transcript.cleaned.vtt`
(`/vtt-spell-pass` output). On 20260623 they differ on **72 cue lines**, every
one a proper noun (`Blueberry`→`Brewbarry`, `Cryovane`→`Cryovain`,
`Pruta`→`Prutha`). Same 522 quotes: raw → 39 unverified, cleaned → 31.

Any LLM layer must be given **the same transcript the deterministic pass used**,
resolved once. `sd_agent.resolve_vtt` already does this and prints its choice.

## R8 — Never pass the alias set to a model as a transform (D13, `6e00f54`)

`scene_extract` used to pipe the VTT through `build_alias_normalizer` before the
model saw it, so "verbatim" quotes were transcriptions of a pre-corrupted
transcript. Fixed: the roster now reaches the model as **knowledge** in the
system prompt (`format_npc_roster`), and the VTT is never rewritten.

**The new feature inherits this rule absolutely.** A triage model may be *told*
that "Blueberry" and "Brewbarry" denote one NPC; it must never be handed a
rewritten transcript, and it must never rewrite one.

Note `docs/entity_registry.yaml` is auto-discovered from the CWD and **replaces**
a `--dossier-dir` scan (569 entities for Phandalin).

## R9 — Never auto-apply (the #151 scar)

`scrub_mechanics.py` was an autonomous LLM apply pass; it stripped spells out of
narration and was replaced by a propose→confirm→apply skill. 007 chose *flag in
place + report* for the same reason.

**The LLM layer triages; the GM decides.** Its output is a queue with evidence,
never an edit. This is Constitution Principle II and the global "LLMs are
renderers, not architects" rule.

## R10 — Speaker attribution is currently unchecked

Every report says so explicitly: it answers *were these words said*, not *did
this person say them*. `SourceTranscript` already keeps `speakers[]` alongside
`spoken[]`, and each finding carries `nearest_speaker` — so the data needed to
pose the question exists; only the judgment is missing. Third candidate job.

## R11 — DeepSeek's measured behaviour (relevant to prompting it)

- It **retains disfluencies** more than Claude: 28% of its quotes carry a
  `you know` / `, like,` / stutter, against Claude's 21% — and the VTT's own
  cues are 21%. It copies rather than tidies.
- It **prefers inline quoting** to blockquotes (R4).
- Its one genuine garble in 390 quotes doubled a name
  (`Alphonse 'Big Al' Kalazorn, she turns to Alphonse 'Big Al' Kalazorn`) —
  with no normalizer in the path, so models *can* produce doubling on their own.

## R12 — DGX operational facts (verified live 2026-08-03)

- **spark1 `192.168.1.147:8001` serves `deepseek-ai/DeepSeek-V4-Flash-0731`**,
  256K ctx. `~/src/dgx/current-setup.md` still said Qwen3-Next-80B — **probe
  `/v1/models` before trusting that file.**
- **spark2 `192.168.1.121:8001` was not answering** (box pings; Ollama on 11434
  is up). Do not assume two boxes.
- `config/wiring.yaml` supplies `dgx_endpoint` (correct) and `dgx_model` (stale).
  It is rendered/do-not-edit — override per run with `--model`.
- **`dgxlib/models.yaml` has no entry for the served DeepSeek model**, so it
  resolves to `default`: `max_tokens 16384`, thinking off, 120 s idle timeout.
  Filed as 007 T054. A triage feature that sends many small requests should fix
  this first, or it inherits settings nobody chose.
- `--backend dgx` used to silently return an **Anthropic** client when no
  endpoint resolved (fixed in this branch: it now resolves from wiring and
  raises rather than falling back). Any new CLI must route through
  `client_from_args`, never construct a client itself
  (`tests/test_backend_seam_guardrails.py` enforces this).
- The subscription backend works and is the cheap way to A/B against Claude:
  `--backend claude-code --model claude-sonnet-4-6` (thinking is suppressed and
  `--effort high` pinned automatically).

## R13 — Methodological scar from the 007 calibration

Three explanations were argued for a 71%-vs-95% gap between two corpora that
differed in **date as well as model**, and all three were wrong — including one
"rejection" that re-normalised with *today's* `build_alias_normalizer`, which
carries a guard added in `6e00f54` itself and so could never reproduce the old
behaviour. One control run settled it in minutes.

**When two measurements differ in more than one variable, run the missing arm
before theorising.** If this feature compares triage-on vs triage-off, hold the
model, the transcript, the prompt and the corpus fixed.
