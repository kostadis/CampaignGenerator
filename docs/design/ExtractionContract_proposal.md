# Extraction contract for `scene_extractions_*` — design proposal

**Issue:** #250. **Status:** proposal. **Do not implement before the GM rules on D1–D3 below** — all three are scope/attribution calls, the class the Pipeline Design Rule reserves for a human checkpoint.

Evidence: `~/src/campaigns/Phandalin/summaries/20260623/` (ch46, six scenes, 1,244 VTT cues). Ground truth is `GMT20260624-035836_Recording.transcript.cleaned.vtt`; the disputed cues are byte-identical in the raw sibling, so the raw-vs-`.cleaned` choice is not implicated in either defect.

## The finding that reframes the issue

#250 reports three defects in `scene_extractions_smoothed/`. Two things turned up that change what the contract has to be.

**First: the arbiter already exists and already catches both disputed spans.** `sd_verify_quotes` (spec 007) is implemented, deterministic, and calls no model. Run over this corpus it flags both — including auto-diagnosing the stitch:

```
### 05_arrival_in_neverwinter.md:188
- Quote: "So it says that it will cost us 1,675 gold, and… I'm hoping that we can barter this staff and bird calls as part of the—"
- Likely stitched: contains `...` — two separate utterances joined into one quote.
  Usually fixed by splitting it, not by rewording.
- Score: 0.73
- Nearest transcript line (Gary Young): "I'm hoping that we can barter this, staff and bird calls as part of the,"
```

So the contract does not need a new arbiter. It needs to *wire the existing one in* and decide what its verdicts mean.

**Second: the defects have different origins, so a contract enforced at one stage would fix half of them.** Running the verifier over both layers separates the stages cleanly:

| layer | verified | near | unverified |
|---|---|---|---|
| `scene_extractions_new/` (extraction) | 365 (70%) | 119 (23%) | **34 (6%)** |
| `scene_extractions_smoothed/` (smoothing) | 242 (50%) | 153 (32%) | **79 (16%)** |

Smoothing more than doubles the unverified count. Some of that is by design — the voice-smooth pass exists to fix garble and disfluency for readability — but `sd_narrate` renders from `smoothed/`, i.e. **the renderer consumes the less faithful of the two layers.**

## Defect provenance

### A — one span, two conflicting copies (extraction *and* smoothing)

| stage | text | score |
|---|---|---|
| VTT cue 1013 | `Kostadis Roussos: Vucherdin, I think that if you were willing to play a song, it would be for free.` | ground truth |
| `new/02:12` (`## Scene summary`, human) | `*"Vucherdin, …"*` | exact |
| `new/02:28` (`## Verbatim moments`, model) | `> "Vukradin, …"` | **0.97** — name laundered |
| `smoothed/02:28` | `> "How much you got? Toblen says: well — Vukradin, …"` | **0.80** — splice added |

Two independent errors introduced at two different stages: extraction launders `Vucherdin` → `Vukradin`; smoothing prepends `"How much you got? Toblen says: well — "`, folding a second utterance and a piece of meta-narration into a span marked verbatim.

Attribution is **correct** at both stages (`**[GM]** — *as Toblen, offering it free for a song*`, matching the VTT speaker). #250 lists re-attribution as part of this defect; it is not. The defect is spelling plus splice.

### B — one span, two scenes (extraction)

| stage | text | score |
|---|---|---|
| VTT cue 4513 | `Gary Young: So it says that it will cost us 1,675 gold, and…` | ground truth |
| VTT cue 4521 | `Gary Young: I'm hoping that we can barter this, staff and bird calls as part of the,` | ground truth |
| `new/06:84` | `> "So it says that it will cost us 1,675 gold, and…"` | exact |
| `new/05:187` | both cues joined | **0.75** |

Cues 4513 and 4521 are eight cues apart. The longer copy is a fabricated continuity, and it sits in the wrong scene — the armorer negotiation is scene 06. This one originates in extraction; smoothing merely carried it forward.

**Correction to #250:** the "road-trip beat duplicated across 04/05" is *not* duplication. `04` carries the departure decision, `05` the journey; the bathrobe thread legitimately spans both. Only 05/06 is a true duplicate span. A naive overlap-dedup would destroy real thread continuity.

### C — brackets are four classes, not one

467 bracketed spans. Counting them dissolves most of the problem:

| class | count | examples | disposition |
|---|---|---|---|
| Speaker labels | 417 | `[GM]` 162, `[Vukradin]` 108, `[Brewbarry]` 75, `[Soma]` 35, `[Valphine]` 32, `[Lathander]` 3, `[GM / Vukradin]` 2 | structural — preserve |
| Sub-scene markers | 40 | `[scene tag — The Golden Eyes]` | structural — preserve |
| Transcription markers | 7 | `[unclear]` 2, `[inaudible]` 2, `[stop]`, `[so]`, `[out]` | factual about the VTT — preserve; deleting one fabricates certainty |
| **Editorial insertions inside a verbatim quote** | **3** | `[the good stuff on]` (`smoothed/04:107`), `[blurb]` (`04:181`), `[those are Brin and Giles]` (`new/04:69`) | **contested — D3** |

Only the last class is the reported problem, and it is a verbatim-integrity violation rather than a formatting one: `> "Don't underestimate the power of [the good stuff on] the good people."` is marked verbatim while carrying inserted text. Fable preserved these; Opus deleted them. Neither should have been the component deciding.

## Proposed contract

**C1 — Authority comes from VTT verification, never from position, section name, or length.** Every intuitive tiebreak picks the wrong copy here:

| candidate rule | wrong on |
|---|---|
| "the section named `Verbatim moments` wins" | A — the human summary is the faithful copy |
| "the longer / more complete copy wins" | A and B — the corrupted copy is longer in both |
| "the more readable copy wins" | A and B |
| "the later pipeline stage wins" | A — smoothing degrades 0.97 → 0.80 |

The only arbiter that gets both right is the transcript. Standing caveat: a similarity band says *an edit happened*, never that the edit was *safe* — 0.92 can be meaning-changing and 0.94 harmless. So `near` escalates; it must never silently resolve a conflict.

**C2 — One authoritative copy per span, keyed on VTT cue index, with other appearances as references.** Re-transcription is what let A and B drift. Cue 4513 is a stable identity for the 1,675 span wherever it is discussed.

**C3 — Scene ownership by cue range, not narrative fit.** A span belongs to the scene whose cue range contains its cue. This is mechanical and auditable, and it is the only rule that distinguishes B (same cue, two scenes — real duplicate) from the 04/05 bathrobe thread (different cues, adjacent scenes — legitimate continuity). No similarity measure can make that distinction.

**C4 — The contract binds `scene_extractions_new/` as the verbatim record, and `smoothed/` declares its edits.** Given smoothing triples the unverified rate, the two layers cannot carry the same promise. Either `smoothed/` stops claiming verbatim for spans it edited, or the renderer reads verbatim spans from `new/` and prose from `smoothed/`.

## GM decision points

**D1 — When the human `## Scene summary` and the model's `## Verbatim moments` disagree and the verifier cannot settle it (`near` on both, or the span is absent from the VTT), what happens?**
(a) Human summary wins — it was right in the one confirmed case, but it is GM-assist prose, not a transcription, so it will not always be. (b) Refuse and flag: the span renders as neither until the GM resolves it — safest for verbatim integrity, costs an interruption per conflict. (c) Verbatim moments wins — recorded for completeness; the evidence is against it.

**D2 — Is laundering a transcription garble corruption?** The VTT says `Vucherdin`; the registry knows that is Vukradin. Either preserve the spoken form always and carry identity as metadata (the established rule — an alias is identity, never a text substitution, and passing the equivalence set as a transform destroys which form was spoken), or permit canonical spelling inside quotes when the registry is confident. This ruling alone decides whether `new/02:28`'s 0.97 is a defect or acceptable, independent of the splice.

**D3 — Class-4 brackets: strip, preserve, or refuse?** Three instances here. Strip = the quote reads clean and silently loses the editor's repair. Preserve = an editorial hand sits inside a verbatim span. Refuse = flagged, does not render until rewritten. Whatever is chosen must also say what happens to a *new* class-4 bracket, so the renderer never improvises again.

## Out of scope for this proposal

- Any change to `scene_extract.py` or the smoothing pass — implementation follows sign-off.
- The `## Scene summary` / `## Verbatim moments` split itself (spec 007 D4). This contract governs conflicts *between* them, not the boundary.
- Re-running extraction for ch46. This corpus is evidence, not a migration target.
- Threshold calibration. 0.85 is spec 007's starting point and is explicitly not calibrated for a local model; the numbers above are all at that default.

## Reproducing the measurements

```bash
cd ~/src/campaigns/Phandalin/summaries/20260623
python3 -m session_doc.sd_verify_quotes \
  --vtt GMT20260624-035836_Recording.transcript.cleaned.vtt \
  --scene-extractions scene_extractions_new --report-only --out /tmp/new.md
python3 -m session_doc.sd_verify_quotes \
  --vtt GMT20260624-035836_Recording.transcript.cleaned.vtt \
  --scene-extractions scene_extractions_smoothed --report-only --out /tmp/smoothed.md
```
