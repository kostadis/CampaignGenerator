# Extraction contract for `scene_extractions_*`

**Issue:** #250. **Status: ratified 2026-08-10** — the GM has ruled on D1–D3; the rulings are R1–R3 below and implementation is unblocked. The three questions are kept in full because the options not taken are the record of why the taken one is right.

Evidence: `~/src/campaigns/Phandalin/summaries/20260623/` (ch46, six scenes, 1,244 VTT cues). Ground truth is `GMT20260624-035836_Recording.transcript.cleaned.vtt`; the disputed cues are byte-identical in the raw sibling, so raw-vs-`.cleaned` did not *cause* either defect — but R2 makes `.cleaned` the repair layer, so the two files stop being interchangeable from here on.

## Rulings

| | ruling | measured cost on ch46 |
|---|---|---|
| **R1** (D1) | **Refuse and flag.** A conflict the VTT cannot settle renders as neither copy until the GM resolves it. **A span verbatim in both copies is never a conflict** — two true statements must never be escalated. | **2** interruptions/session (`new/`), 2 (`smoothed/`) |
| **R2** (D2) | **A transcription garble is a defect in the ground truth and gets fixed** — as a **per-cue** correction in the `.cleaned.vtt`, authored by the GM. Never a global string replace, never a model judgement, never a registry canonicalisation. **Applied:** campaigns#151. | 3 cues this session |
| **R3** (D3) | **Refuse and flag.** An editorial insertion inside a span marked verbatim does not render until rewritten. Applies to any *new* class-4 bracket, so the renderer never improvises again. | **7–10** flagged spans/session |

R1's exclusion is load-bearing: without it the rule fires on any two similar-but-distinct real utterances, and the GM is woken up to adjudicate between two facts. With it, D1 can only ever fire where at most one copy is in the tape.

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
| VTT **cue 253** (file line 1013) | `Kostadis Roussos: Vucherdin, I think that if you were willing to play a song, it would be for free.` | ground truth |
| `new/02:12` (`## Scene summary`, human) | `*"Vucherdin, …"*` | exact |
| `new/02:28` (`## Verbatim moments`, model) | `> "Vukradin, …"` | **0.97** — name laundered |
| `smoothed/02:28` | `> "How much you got? Toblen says: well — Vukradin, …"` | **0.80** — splice added |

Two independent errors introduced at two different stages: extraction launders `Vucherdin` → `Vukradin`; smoothing prepends `"How much you got? Toblen says: well — "`, folding a second utterance and a piece of meta-narration into a span marked verbatim.

Attribution is **correct** at both stages (`**[GM]** — *as Toblen, offering it free for a song*`, matching the VTT speaker). #250 lists re-attribution as part of this defect; it is not. The defect is spelling plus splice.

### B — one span, two scenes (extraction)

| stage | text | score |
|---|---|---|
| VTT **cue 1128** (file line 4513) | `Gary Young: So it says that it will cost us 1,675 gold, and…` | ground truth |
| VTT **cue 1129** | `David Mendenhall: We don't, we don't have that.` | ground truth — *the interruption the stitch deletes* |
| VTT **cue 1130** (file line 4521) | `Gary Young: I'm hoping that we can barter this, staff and bird calls as part of the,` | ground truth |
| `new/06:84` | `> "So it says that it will cost us 1,675 gold, and…"` | exact |
| `new/05:187` | both cues joined | **0.75** |

The two Gary Young cues are not adjacent: **cue 1129 sits between them, and it is a different speaker interrupting** — David Mendenhall's *"We don't, we don't have that."* The longer copy is therefore not merely a fabricated continuity, it is one that **deletes another player's turn** to manufacture it. And it sits in the wrong scene: the armorer negotiation is scene 06. This one originates in extraction; smoothing merely carried it forward.

**Correction to earlier drafts of this doc:** the numbers above were file line numbers presented as cue indices (`cue 1013` is file line 1013, which is cue 253; `4513`/`4521` are lines, which are cues 1128/1130), and the claim that the two barter cues were "eight cues apart" was eight *lines* apart — two cues, one interruption. The identifiers are now given as `cue N (file line M)` throughout.

**Correction to #250:** the "road-trip beat duplicated across 04/05" is *not* duplication. `04` carries the departure decision, `05` the journey; the bathrobe thread legitimately spans both. Only 05/06 is a true duplicate span. A naive overlap-dedup would destroy real thread continuity.

### C — brackets are four classes, not one

467 bracketed spans. Counting them dissolves most of the problem:

| class | count | examples | disposition |
|---|---|---|---|
| Speaker labels | 417 | `[GM]` 162, `[Vukradin]` 108, `[Brewbarry]` 75, `[Soma]` 35, `[Valphine]` 32, `[Lathander]` 3, `[GM / Vukradin]` 2 | structural — preserve |
| Sub-scene markers | 40 | `[scene tag — The Golden Eyes]` | structural — preserve |
| Transcription markers | 7 | `[unclear]` 2, `[inaudible]` 2, `[stop]`, `[so]`, `[out]` | factual about the VTT — preserve; deleting one fabricates certainty |
| **Editorial insertions inside a verbatim quote** | **10** | see below | **R3 — refuse and flag** |

Only the last class is the reported problem, and it is a verbatim-integrity violation rather than a formatting one: `> "Don't underestimate the power of [the good stuff on] the good people."` is marked verbatim while carrying inserted text. Fable preserved these; Opus deleted them. Neither should have been the component deciding.

**Correction — this count was 3 and is 10.** The first pass classified brackets by *token identity* across the whole file, so `[Lathander]` landed in "speaker labels" (it is one, three times — but a fourth sits inside a verbatim blockquote) and every marker with a comment attached (`[inaudible — probable "…"]`) matched no known token and fell through uncounted. Reclassifying by *position* — every bracket inside a `> "…"` span — gives ten per layer, identical in `new/` and `smoothed/`:

```
[Same place the]  [those are Brin and Giles]  [the good stuff on]  [blurb]
[continue?]       [kept]                      [Lathander]
[inaudible — probable "I'll fill you in the whole way"]
[inaudible — probable "It's a mermaid, Steph(ane)"]
[inaudible — Vukradin cut off]
```

The last three are hybrids: a transcription marker (class 3, preserve) carrying a conjectured reconstruction (class 4). R3 was ruled against the old figure of 3; the true cost is 7–10 spans a session and the ruling was re-confirmed at that price.

`[Lathander]` is also the one *clarifying* rather than *replacing* bracket here — the tape says "Lathander" ten times and "Morninglord" zero, so it inserts nothing the speaker did not say. Whether a bracket whose content is present in the tape should be exempt from R3 is mechanically checkable (`Quote.match_variants` already tests both readings) and is **not** ruled on; it is the first open question for implementation.

## Proposed contract

**C1 — Authority comes from VTT verification, never from position, section name, or length.** Every intuitive tiebreak picks the wrong copy here:

| candidate rule | wrong on |
|---|---|
| "the section named `Verbatim moments` wins" | A — the human summary is the faithful copy |
| "the longer / more complete copy wins" | A and B — the corrupted copy is longer in both |
| "the more readable copy wins" | A and B |
| "the later pipeline stage wins" | A — smoothing degrades 0.97 → 0.80 |

The only arbiter that gets both right is the transcript. Standing caveat: a similarity band says *an edit happened*, never that the edit was *safe* — 0.92 can be meaning-changing and 0.94 harmless. So `near` escalates; it must never silently resolve a conflict.

**C2 — One authoritative copy per span, keyed on VTT cue index, with other appearances as references.** Re-transcription is what let A and B drift. Cue 1128 is a stable identity for the 1,675 span wherever it is discussed.

**The key must be the cue index, never the file line.** Applying R2 to this very transcript demonstrated it: correcting three cues added ten NOTE lines to the header and shifted every file line number in the document, while every cue index stayed exactly where it was. A contract keyed on line numbers would have been invalidated by the first correction the contract itself authorised.

**C3 — Scene ownership by cue range, not narrative fit.** A span belongs to the scene whose cue range contains its cue. This is mechanical and auditable, and it is the only rule that distinguishes B (same cue, two scenes — real duplicate) from the 04/05 bathrobe thread (different cues, adjacent scenes — legitimate continuity). No similarity measure can make that distinction.

**C4 — The contract binds `scene_extractions_new/` as the verbatim record, and `smoothed/` declares its edits.** Given smoothing triples the unverified rate, the two layers cannot carry the same promise. Either `smoothed/` stops claiming verbatim for spans it edited, or the renderer reads verbatim spans from `new/` and prose from `smoothed/`.

## GM decision points — all three ruled

**D1 — When the human `## Scene summary` and the model's `## Verbatim moments` disagree and the verifier cannot settle it (`near` on both, or the span is absent from the VTT), what happens?**
(a) Human summary wins — it was right in the one confirmed case, but it is GM-assist prose, not a transcription, so it will not always be. **(b) RULED — refuse and flag:** the span renders as neither until the GM resolves it. (c) Verbatim moments wins — recorded for completeness; the evidence is against it.

The cost of (b) is **not** the 34/79 per-quote unverified figures above — most unverified quotes have no second copy to conflict with. Pairing every quoted span in the summary half against `## Verbatim moments` and classifying both copies:

| layer | same span in both sections | VTT settles it | conflicts R1 must refuse |
|---|---|---|---|
| `scene_extractions_new/` | 8 | 3 | **2** |
| `scene_extractions_smoothed/` | 7 | 3 | **2** |

The both-verbatim exclusion accounts for one of these directly: `03_…proclamation.md` pairs `summary:11` with `moments:49` at 0.76 similarity and **both copies are verbatim in the tape** — two different things genuinely said, joined only by surface similarity. Under R1 that is not a conflict and never reaches the GM. One further overlap lowers the real cost again: `[Lathander]` at `new/06:154` is simultaneously an R1 conflict and an R3 bracket, so the two interruption sets intersect rather than add.

**D2 — Is laundering a transcription garble corruption?** **RULED — it is a mistranscription and gets fixed**, per-cue, in the `.cleaned.vtt`.

Two corrections to how this question was originally framed:

- **The registry does not know.** `Vukradin`'s entry in `Phandalin/docs/entity_registry.yaml` carries exactly one alias, `Bard`. It has never heard of `Vucherdin`. So the option "permit canonical spelling when the registry is confident" would not have fired here — **the model laundered the name on its own initiative**, which is the defect, not a policy gap.
- **This is not the alias rule.** An alias is a *spoken variant* — a person choosing a different name — and the standing rule that an alias is identity and never a text substitution is untouched. An ASR mishearing is a defect in the ground truth itself. Different category, different remedy.

Evidence it is a mishearing: within this one session the tape reads `Vukradin` 11×, `Vucherdin` 3×, `Vukra Din` 1× (cue 422), and **every mangled form comes from a single speaker** (the GM); no player ever produces one. Two of the three Vucherdins (cues 97 and 1018) are plain GM narration, where a mangle has no in-fiction job to do.

The GM ruled all three cues fixed, including 253 — the one in Toblen's voice, where the accident had a case for being kept, since the table has a running bit about NPCs stumbling over this name (cues 464, 466: *"He actually stutters while trying to remember your name."*). The *mechanism* stays per-cue regardless: a global `Vucherdin`→`Vukradin` replace is what would need a model to carve out exceptions, and would flatten a deliberate in-character fumble on the way past. Per-cue, an exception is data the GM authors once.

This also settles `new/02:28`'s 0.97 as **not** a defect once the tape is repaired — but the `smoothed/02:28` splice at 0.80 remains one, independently.

**D3 — Class-4 brackets: strip, preserve, or refuse?** **RULED — refuse and flag.** Strip = the quote reads clean and silently loses the editor's repair. Preserve = an editorial hand sits inside a verbatim span. Refuse = flagged, does not render until rewritten — and it binds any *new* class-4 bracket, so the renderer never improvises again.

## Why the model is not the flagger

The tempting shortcut on both R2 and R3 is "let the model flag it when it thinks the oddity is intentional." We already ran that experiment without meaning to. Both #245 benchmark arms had the Vucherdin span in front of them: **Fable kept the garble with no audit entry; Opus silently reclassified it.** Neither flagged anything, in opposite directions. A component that noticed nothing twice cannot be the one deciding which anomalies deserve the GM's attention — and asking it to would put a scope decision back exactly where this contract exists to take it out.

The discovery path for a *future* accident stays open and stays deterministic: `sd_verify_quotes` surfaces any drifted span as `near`, which is how this one became visible at all. The GM reads the flagged list. What is dropped is the model pre-filtering that list.

## Out of scope

- ~~Any change to `scene_extract.py` or the smoothing pass~~ — unblocked by R1–R3; implementation is the follow-on to this doc.
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

The R1 conflict counts and the R3 bracket recount are not produced by that CLI — they pair the two sections against each other, which nothing ships yet. They are the first thing implementation should turn into a test fixture; until then they are reproduced by the scratch scripts recorded in the #250 PR.

## Open questions for implementation

1. **Clarifying vs replacing brackets** (above): should a class-4 bracket whose content *is* present in the tape be exempt from R3? Mechanically checkable, not ruled.
2. **Where R2 corrections live long-term.** This session's fix edits `.cleaned.vtt` directly. `docs/corrections.yaml` already exists per campaign, is hand-authored, and carries `verified: true|false` — which maps onto "we think this is a typo but have not asked the speaker." But `sd_verify_quotes` does not read it, and its matcher keys on document-path globs, not VTT cue indices. Extending it is the alternative to editing the transcript in place.
3. **C4's two options** — `smoothed/` stops claiming verbatim, or the renderer reads verbatim from `new/` and prose from `smoothed/` — are still both open.
