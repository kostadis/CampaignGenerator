# Extraction contract for `scene_extractions_*`

**Issue:** #250. **Status: fully ruled 2026-08-10; R1–R3 built, R4–R5 queued.** The GM ruled on D1–D3, then on the three questions implementation raised. R2 was applied by hand (campaigns#151); R1 and R3 are computed by `sd_verify_quotes` as **refusals**, a second axis alongside the three verdicts; R4 and R5 are ruled and not yet built. Every question is kept in full, with the options that lost, because the options not taken are the record of why the taken one is right.

Implementing the rules against the evidence corpus moved every cost estimate in this document and answered one of its open questions with data. Those revisions are marked **Correction** and are in place below; the superseded figures are named so a reader who remembers them knows they were replaced rather than misread.

Evidence: `~/src/campaigns/Phandalin/summaries/20260623/` (ch46, six scenes, 1,244 VTT cues). Ground truth is `GMT20260624-035836_Recording.transcript.cleaned.vtt`; the disputed cues are byte-identical in the raw sibling, so raw-vs-`.cleaned` did not *cause* either defect — but R2 makes `.cleaned` the repair layer, so the two files stop being interchangeable from here on.

## Rulings

| | ruling | measured cost on ch46 |
|---|---|---|
| **R1** (D1) | **Refuse and flag.** A conflict the VTT cannot settle renders as neither copy until the GM resolves it. **A span verbatim in both copies is never a conflict** — two true statements must never be escalated. | **4** interruptions/session (`new/`), **6** (`smoothed/`) |
| **R2** (D2) | **A transcription garble is a defect in the ground truth and gets fixed** — as a **per-cue** correction in the `.cleaned.vtt`, authored by the GM. Never a global string replace, never a model judgement, never a registry canonicalisation. **Applied:** campaigns#151. | 3 cues fixed; **at least 16 more found** — see below |
| **R3** (D3) | **Refuse and flag.** An editorial insertion inside a span marked verbatim does not render until rewritten. Applies to any *new* class-4 bracket, so the renderer never improvises again. | **12** flagged spans/session, both layers |
| **R4** (Q2) | **`corrections.yaml` is the record; `.cleaned.vtt` is generated from raw + corrections.** A correction is cue-indexed data with a `verified` flag, not a hand-edit with a NOTE block. *Not implemented.* | 16 corrections owed on ch46 alone |
| **R5** (C4) | **`smoothed/` stops claiming verbatim** — its section is renamed and nothing there asserts exactness. The contract binds `new/`. *Not implemented.* | R1+R3 in `smoothed/`: 18 → **0** |
| **R6** | **R1 keeps escalating a pair that is identical once brackets are stripped.** Already the shipped behaviour. | 1 refusal/layer retained |

R1's exclusion is load-bearing: without it the rule fires on any two similar-but-distinct real utterances, and the GM is woken up to adjudicate between two facts. With it, D1 can only ever fire where at most one copy is in the tape.

**Correction — R1's cost was quoted as 2/2 and is 4/6.** The 2 came from a scratch pairing regex run over the whole `## Scene summary` section at once, where a single unbalanced quote character pairs across a line break and swallows the spans after it. Scanning line by line finds **17** paired spans in `new/` and 15 in `smoothed/`, not 8 and 7. Both figures are still small enough that the ruling stands at the higher price; the point is that the lower one was a parser artifact, not a property of the corpus.

## What the rules found

The interruption counts are the cheap part of this result. What R1 and R3 actually surfaced is that **defect A is not one incident**. Every one of the four R1 refusals in `new/`, and every one of the twelve R3 brackets, is the same thing the Vucherdin span was: Zoom mishears a word, and the extraction silently repairs it inside a span marked verbatim.

| where | the tape says | the extraction says |
|---|---|---|
| cue 224 | `the strength of **the pandemic**` | `the strength of Lathander` |
| cue 245 | `like a Brewbarry **bathroom**` | `like a Brewbarry bathrobe` |
| cue 1173 | `Brother **Aldrich**` | `Brother Aldric` |
| cue 1211 | `much respect for **the thunder**` | `much respect for [Lathander]` |

That is four more R2 cases in one session, none of which #250 noticed, found by a rule ruled for a different purpose. Add the twelve R3 brackets — every one of which is a repair of a garbled cue (`[stop]` for cue 324's *"our next system"*, `[so]` for cue 831's *"Shalim Lenny"*, `[out]` for cue 857's *"phasing in an"*, `[blurb]` for cue 781's *"a little but"*) — and this session alone carries **16 garbles the tape should own and the extraction is carrying instead.**

This does not change any ruling. It changes the *weight* of R2: correcting the tape is not an occasional courtesy for a mangled name, it is the routine remedy, and R1/R3 are how the cases get found. It also means the resolution advice on most refusals is "fix cue N", not "rewrite the quote".

On `smoothed/` the six R1 refusals include all three defects #250 originally reported — the Vucherdin/`How much you got?` splice at `02:28` (0.80 against its sibling), the three-utterance fold at `06:45` (0.61), and a `Jenna goes:` meta-narration prefix at `03:119` that the issue did not mention.

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

Smoothing more than doubles the unverified count. Some of that is by design — the voice-smooth layer exists to fix garble and disfluency for readability — but `sd_narrate` renders from `smoothed/`, i.e. **the renderer consumes the less faithful of the two layers.** R5 resolves this by making the layer say so.

**There is no smoothing *pass* in this repo.** Nothing here produces `scene_extractions_smoothed/`; the only code that knows the directory exists is `sd_narrate.py:185-193`, which warns when the sibling is present and `--scene-extractions` points at the other one. The layer is hand-made outside the pipeline and reaches narration only when the GM points at it. This matters to R5: there is no prompt to re-word, so "stops claiming verbatim" is a heading convention plus a parser that honours it, not a generation change.

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
| Transcription markers | 7 | `[unclear]` 2, `[inaudible]` 2, ~~`[stop]`, `[so]`, `[out]`~~ | factual about the VTT — preserve; deleting one fabricates certainty |
| **Editorial insertions inside a verbatim quote** | ~~10~~ **12** | see below | **R3 — refuse and flag** |

Only the last class is the reported problem, and it is a verbatim-integrity violation rather than a formatting one: `> "Don't underestimate the power of [the good stuff on] the good people."` is marked verbatim while carrying inserted text. Fable preserved these; Opus deleted them. Neither should have been the component deciding.

**Correction — this count was 3, then 10, and is 12.** The first pass classified brackets by *token identity* across the whole file, so `[Lathander]` landed in "speaker labels" (it is one, three times — but a fourth sits inside a verbatim blockquote) and every marker with a comment attached (`[inaudible — probable "…"]`) matched no known token and fell through uncounted. Reclassifying by *position* — every bracket inside a `> "…"` span — gave ten. Implementing the check moved it to **twelve**, identical in `new/` and `smoothed/`:

```
[Same place the]  [those are Brin and Giles]  [the good stuff on]  [blurb]
[continue?]       [kept]                      [Lathander]
[stop]            [so]                        [out]
[inaudible — probable "I'll fill you in the whole way"]
[inaudible — probable "It's a mermaid, Steph(ane)"]
```

Two further errors, in opposite directions, cancel out to +2:

- **`[stop]`, `[so]` and `[out]` are class 4, not class 3.** They were filed as transcription markers because the whole-file token count had them next to `[unclear]` and `[inaudible]`. In position they supply words: cue 324 says *"that's our next **system**"* and the quote reads `"that's our next [stop]."`. A word the tape does not contain is an insertion whatever it looks like, which is the argument for classifying by position rather than by vocabulary.
- **`[inaudible — Vukradin cut off]` never reaches R3.** It is the entire quote, so it is `EXEMPT` — the extractor reporting absence, with no verbatim span for a bracket to sit inside. Its two siblings *are* R3 cases because they sit inside real quotes.

The remaining hybrids are a transcription marker (class 3, preserve) carrying a conjectured reconstruction (class 4). R3 was ruled against the figure of 3; the true cost is 12 spans a session.

**Correction — `[Lathander]` is a *replacing* bracket, and open question 1 has a measured answer.** The claim above was that it is the one clarifying bracket, since "the tape says Lathander ten times and Morninglord zero." That counted occurrences across the whole file rather than at the cue in question. At cue 1211 the tape says *"much respect for **the thunder**, yes"* — the bracket is replacing a garble, not clarifying a word the speaker used.

Checking every class-4 bracket against its own nearest transcript line rather than against the file: **0 of 12 are clarifying, 12 of 12 replace.** So the proposed exemption would have fired zero times on the corpus that motivated it, and the example that motivated it was the wrong way round. Still unruled — but it is now a question with no measured upside, and the implementation ships without the carve-out.

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

| layer | same span in both sections | consistent (identical, or verbatim in both) | VTT settles it | conflicts R1 must refuse |
|---|---|---|---|---|
| `scene_extractions_new/` | 17 | 5 | 8 | **4** |
| `scene_extractions_smoothed/` | 15 | 4 | 5 | **6** |

The both-verbatim exclusion is what the `consistent` column counts, and it is doing real work: nine spans across the two layers, every one of which would otherwise have been an interruption asking the GM to choose between two things that were both said. `03_…proclamation.md` is the clearest — it pairs a summary span with a moments span at 0.76 similarity and both are verbatim in the tape, joined only by surface similarity. One further overlap lowers the real cost again: `[Lathander]` at `new/06:154` is simultaneously an R1 conflict and an R3 bracket, so the two interruption sets intersect rather than add.

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

- ~~Any change to `scene_extract.py` or the smoothing pass~~ — unblocked by R1–R3, and still not done. R1/R3 detect and report; `scene_extract.py` was not touched and its prompt still does not know the contract exists. (There is no smoothing pass to change — see above.)
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

Every number in this document now comes out of that command. R1 and R3 are computed by the same CLI, reported under `## Refused`, and covered by `tests/test_verify_quotes.py` — the scratch scripts that produced the superseded 2/2 and 10 figures are gone and should not be resurrected.

## What implementation did and did not do

**Did:** compute both rules, report them under a `## Refused` heading that names the rule, the two copies, the similarity between them and how to resolve it; mark the offending lines with an additive, idempotent `<!-- cg:refused:RN -->`; exit non-zero on a refusal even when nothing is unverified.

**Did not:** stop anything from rendering. `sd_narrate` still reads whatever is in `smoothed/`. "Refuse" is currently *detect, mark and report*. Under R5 that is now the settled end state rather than a gap: `smoothed/` stops asserting exactness, so there is nothing for a renderer-side block to enforce there — see below.

Refusals are a second axis, not a fourth verdict. A verdict answers *is this in the tape*; a refusal answers *may the pipeline choose this*, and the answer is routinely "no" for a span that is perfectly verbatim — `> "…the strength of [Lathander]"` matches once the bracket is stripped and is still an editorial hand inside a verbatim span. Collapsing the two axes would have forced exactly the wrong choice at that span.

## The remaining questions, ruled 2026-08-10

All four are now closed. R4 and R5 are ruled but **not built** — they are the work queue, not open design.

**1. Clarifying vs replacing brackets — moot.** Measured: 0 of 12 brackets in the corpus are clarifying, and the example that motivated the question turned out to be replacing (at cue 1211 the tape says *"the thunder"*, not "Lathander"). The exemption would have fired zero times. Never formally ruled; ships without the carve-out because there is nothing behind it.

**2. Where R2 corrections live → R4: `corrections.yaml` is the record, `.cleaned.vtt` is generated.**

A correction becomes cue-indexed data — which transcript, which cues, what the tape says, what it should say, `verified: true|false`, and the evidence — and an apply step rebuilds `.cleaned.vtt` from the untouched raw sibling plus the corrections. The raw file stays the archive; the cleaned file stops being a hand-edited artifact and becomes reproducible output.

The alternative that lost was continuing what campaigns#151 did: edit the cue in place, explain it in a header NOTE block. That works and costs nothing, but the record is prose. Nothing can enumerate what was corrected without diffing against raw, and a guess and a certainty look identical in the file — which is exactly the distinction `verified: false` exists to carry. At three corrections a year that is tolerable. At sixteen a session it is how the tape stops being ground truth.

The option where the tape is never rewritten at all and `sd_verify_quotes` applies corrections at match time also lost, for a specific reason: every other VTT consumer — `enhance_summary`, `scene_extract`, `vtt_voice_compare` — would keep reading the uncorrected tape, so the verifier and the generators would disagree about what was said. Generating the cleaned file keeps all of them consistent for free.

Not built. What it needs: a cue dimension on the correction model (`provenance/corrections.py` keys on `applies_to: {paths, subjects}` today, both document-shaped); the apply CLI; and campaigns#151's three hand-edits back-filled as entries, or the very first tape the rule governs is not reproducible from its own record.

**3. C4 → R5: `smoothed/` stops claiming verbatim.**

Its `## Verbatim moments` heading is renamed, and nothing in that layer asserts that a span is exact. Narration keeps rendering from it, because tidied quotes are what that layer is *for*.

Three consequences, and the middle one is the point:

- **The contract binds `new/`.** R3 objects to an editorial hand inside a span *marked verbatim*; R1 asks which of two copies is faithful. Neither question means anything in a section that declares it edits. R1+R3 in `smoothed/` go 18 → 0; `new/`'s 16 are unchanged.
- **Traceability grading stays on.** Dropping the *verbatim* claim is not dropping verification. `unverified` means *untraceable to any line*, which is a fabrication or a splice, and both are still defects in a layer that only claims to be tidied. The three defects #250 opened over stay visible. What legitimately stops counting as a defect is `near` — a tidied quote is supposed to be near.
- **A first draft of this ruling said the 79 unverified findings would stop being reported.** That was wrong, and building from it would have made smoothing damage invisible — the opposite of what the ruling is for.

The option that lost: quotes reach narration from `new/` and prose from `smoothed/`. It fixes the stated defect (the renderer consumes the less faithful layer) most directly, but it makes `smoothed/`'s quotes dead weight — the layer exists to make quotes readable — and it splits one scene across two files that the Session Doc Editor edits as one.

Not built. What it needs: `_split_scene_body` and `parse_scene_quotes` recognising the second heading, and the contract layer scoping itself off when they see it.

**4. Should R1 skip a pair identical once brackets are stripped → R6: no.**

`01_return_to_phandalin.md:97` is that shape — the summary writes `[Lathander]`, the moments copy writes `Lathander`, identical once the brackets come off. The exclusion would drop `new/` 4→3 and `smoothed/` 6→5.

Rejected because the two copies are not saying the same thing about the tape. At cue 224 the tape says *"the strength of the pandemic"*. The copy that renders repaired that garble **silently**; the copy that does not render **declared** the repair with a bracket. Same words, opposite honesty, and the exclusion would suppress precisely the more informative half. R3 does not catch it either — the bracket is in the summary section, which R3 does not scan. Already the shipped behaviour; recorded so it is not re-litigated.
