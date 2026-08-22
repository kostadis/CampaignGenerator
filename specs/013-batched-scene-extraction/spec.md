# Feature Specification: Batched Scene Extraction (one transcript, one call)

**Feature Branch**: `perf/scene-extract-token-utilization`

**Created**: 2026-08-22

**Status**: Draft

**Input**: User description: "today the re-extract quotes phase re-reads the vtt for every scene. When using `claude -p` that burns a lot of tokens. To address the `claude -p` pass, what I want is to batch the scenes per call - so that I make 1 call, and get all of the scenes."

---

## Existing behaviour (measured, not assumed)

Stage 2 ("Re-Extract Quotes") sends **the entire session transcript once per scene**. The transcript sits in the system prompt; the per-scene user message names one scene and quotes its gm-assist bullets.

On the **metered API** this is close to free after the first scene: the transcript is marked as a cached prefix, so scenes 2..N read it at cache-hit rates, and `--batch` compounds that with a further discount.

On the **subscription path** none of that applies. Each scene is a separate `claude -p` process with a fresh session, and the cache markers are flattened to plain text on the way in. Nothing is reused. Batch submission is unavailable on this path at all — it requires the metered backend — so the per-scene loop is the only mode the subscription has.

Measured on the Phandalin corpus (`~/Phandalin/Phandalin/summaries/`):

| Quantity | Measured |
|---|---|
| Session transcript | 106–150 KB (≈ 15–20K tokens) |
| Scenes per session | 5–8 |
| Transcript sent per full re-extract, subscription | **5–8×** the transcript (≈ 90–145K tokens) |
| Transcript sent per full re-extract, if sent once | ≈ 18K tokens |
| Total extraction file bytes, one session (8 scenes) | 117 KB |
| Of that, **model-generated** output (see note) | ≈ **23K tokens** |
| Largest single scene output | 23 KB (≈ 5.8K tokens) |
| Current per-scene output ceiling | 8,192 tokens |

**Note on the generated figure**: only the `## Verbatim moments` body is produced
by the model — the front-matter, the `# {name}` heading and the verbatim
gm-assist summary are assembled locally by `format_scene_output` from values
already in hand. Measured over the moments sections alone: 16.8K tokens for the
7-scene session, **23.0K for the 8-scene one** (research D3).

The waste is real and large. The constraint that limits the fix is in the last three rows: collapsing N calls into one converts N separate output ceilings into a single one, and one session's full extraction output is roughly **3.5× the current per-scene ceiling**.

### Resolved decisions

Three decisions were taken by the GM against those measurements:

| Decision | Ruling |
|---|---|
| **Default output ceiling** | Raised from 8,192 to **32,000** — enough for the measured 8-scene session (~29K) with headroom. |
| **Call shape** | **One call when the session's projected output fits the ceiling; split into the fewest groups that fit when it does not.** The ceiling is GM-adjustable, so raising it for a long session collapses the run back to a single call. |
| **Activation** | The editor **pre-selects** batched mode when the subscription backend resolves, and leaves it off on the metered API where caching already delivers the reuse. It stays a visible control the GM can flip either way. |

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Re-extract a session on the subscription without paying for the transcript N times (Priority: P1)

The GM has a reviewed Stage 1 summary with the session's scenes named, and clicks Re-Extract Quotes with the subscription selected. Today the transcript is transmitted once per scene. The GM wants it transmitted once for the whole session — or, for a session too long to answer in one response, once per group rather than once per scene.

**Why this priority**: This is the entire point of the feature. Everything else is a safeguard around it.

**Independent Test**: Run a re-extract of a session with a known scene count on the subscription path, with the pass instrumented to report how many times the transcript was transmitted. For a session whose projected output fits the ceiling: one transmission for the whole run, and one output file per scene on disk.

**Acceptance Scenarios**:

1. **Given** a session with 8 named scenes and a reviewed summary, whose projected output fits the ceiling, **When** the GM runs a full re-extract on the subscription path, **Then** the transcript is transmitted exactly once and 8 per-scene extraction files are written.
2. **Given** the same session, **When** the GM runs the same re-extract, **Then** each written file is identical in structure (front-matter, scene heading, verbatim scene summary, verbatim-moments section) to what the per-scene mode produces — only the extracted content may differ.
3. **Given** a session where 5 of 8 scenes already have extraction files and Force is not set, **When** the GM re-extracts, **Then** only the 3 missing scenes are requested, and the 5 existing files are left untouched.
4. **Given** a session whose projected output exceeds the ceiling, **When** the GM runs a full re-extract, **Then** the scenes are divided into the fewest groups that fit, the transcript is transmitted once per group, and the run states how many groups it used and why.
5. **Given** that same session, **When** the GM raises the ceiling above the projection and re-runs, **Then** the run uses a single group.

---

### User Story 2 - A short or interrupted response does not destroy the run (Priority: P1)

One response now carries every scene. If it ends early — the model runs out of output budget, the process dies, the response is truncated mid-scene — the GM must not lose the scenes that did arrive, and must be told exactly which ones did not.

**Why this priority**: Also P1, because without it the feature is a regression. Today a failure costs one scene and the run resumes; batched, the same failure could cost the whole session. Resumability is not a nice-to-have here, it is the thing that makes batching safe to adopt.

**Independent Test**: Feed the pass a deliberately truncated response covering the first K of N scenes. K files must be written, the N−K missing scenes must be named in the output, and the process must exit in a way that marks the run incomplete.

**Acceptance Scenarios**:

1. **Given** a response that contains complete extractions for the first 5 of 8 scenes and stops mid-way through the 6th, **When** the pass processes it, **Then** the 5 complete scenes are written, the partial 6th is discarded rather than written half-formed, and scenes 6–8 are reported as not extracted.
2. **Given** that same outcome, **When** the GM re-runs without Force, **Then** only scenes 6–8 are requested.
3. **Given** a response in which one scene's section is present but empty, **When** the pass processes it, **Then** that scene is reported as returning no moments rather than being written as an empty file that a later run would skip.
4. **Given** a response whose scene sections cannot be matched back to the requested scenes at all, **When** the pass processes it, **Then** nothing is written and the failure names the mismatch — an unparseable response must not be silently written as one scene's content.

---

### User Story 3 - Verbatim fidelity does not regress (Priority: P1)

Extraction exists to produce exact transcript spans. In per-scene mode the model sees one scene's bullets and has a full output budget for that scene alone. In batched mode it sees every scene boundary at once and must ration one budget across all of them. The GM needs evidence that quotes did not get compressed, paraphrased, or dropped as the response ran long.

**Why this priority**: P1 by the project's own constitution — a paraphrased quote is the most expensive failure the system can produce, and this change alters exactly the conditions under which the model produces quotes. A token saving bought with degraded verbatim spans is not a saving.

**Independent Test**: Extract the same session both ways and run the existing deterministic quote verifier over both outputs. The batched run's exact-match rate must not be materially worse, and per-scene quote counts must not collapse for the scenes that appear late in the response.

**Acceptance Scenarios**:

1. **Given** a session extracted in per-scene mode and the same session extracted in batched mode, **When** both are checked with the deterministic quote verifier, **Then** the batched run's verified-quote rate is no worse than the per-scene run's by more than a stated tolerance.
2. **Given** a batched run over N scenes, **When** the per-scene quote counts are compared against the per-scene run, **Then** the last scenes in the response have not lost a disproportionate share of their moments relative to the first.
3. **Given** any batched run, **When** its output is inspected, **Then** no scene's section contains content attributed to a different scene's boundary.

---

### User Story 4 - The GM can see what the batching bought (Priority: P2)

After a run, the GM wants to know it worked: how many scenes came back in one exchange, and how much transcript re-transmission was avoided compared with the per-scene mode.

**Why this priority**: The feature is a performance claim. An unmeasured performance claim is an assumption. This is also what makes the tuning decisions (grouping thresholds, output ceilings) answerable later with data rather than guesswork.

**Independent Test**: Run a re-extract and confirm the run output states the number of scenes requested, the number returned, and the transcript transmission count for the run.

**Acceptance Scenarios**:

1. **Given** a completed batched run, **When** the GM reads the run output, **Then** it states how many scenes were requested, how many were returned complete, and how many transcript transmissions the run made.

---

### Edge Cases

- **A single scene.** A session with one scene must behave identically to today — batching a set of one is the per-scene call.
- **A single scene that alone exceeds the ceiling.** Grouping cannot make a group smaller than one scene. The run must proceed with that scene alone rather than refusing, and say that the projection exceeds the ceiling so the GM can raise it.
- **A projection that is wrong.** The projection is an estimate made before the response exists. A run whose actual output overruns the ceiling despite a projection that fit is the ordinary short-response case (User Story 2), not a special one.
- **Two scenes with the same name.** Scene names come from human-authored headings and are not guaranteed unique. The response must be attributable back to the requested scenes by position, not by name-matching alone.
- **A scene name that collides with the response's own delimiter syntax.** A scene literally titled with the marker text must not be able to split the response at the wrong point or truncate a neighbour.
- **A scene with no matching transcript moments.** Silence is the correct answer for a scene the transcript does not cover. This must be distinguishable from "the response stopped before reaching this scene" — the first is a finished result, the second is unfinished work.
- **Force over already-reviewed files.** The existing snapshot-and-clear-review behaviour (prior content preserved, review marker cleared, no overwrite when content is identical) must survive batching unchanged.
- **Every scene already extracted, Force off.** No call, no tokens, no files touched — the run reports there is nothing to do. Batching must not turn today's free no-op into a paid one.
- **A partial session, Force off.** With 5 of 8 scenes on disk, only the 3 missing scenes are sent, and the group sizing is computed over those 3 — so a nearly-finished session costs a fraction of a full one, not the same as one.
- **Force on a partially-extracted session.** All 8 scenes are re-requested and re-grouped; the 5 existing files are snapshotted before being overwritten, exactly as the per-scene mode does.
- **Mode switched mid-session.** A session partly extracted per-scene and finished batched (or the reverse) must complete correctly — both modes read the same on-disk evidence of what is already done.
- **The response arrives in scene order that differs from the requested order.** Either it is reconciled deterministically or it is a hard failure — it must not be assigned positionally onto the wrong scenes.
- **Metered-API path.** The per-scene loop there already achieves the reuse this feature is chasing, by caching. Nothing about that path may be made worse.
- **Auto-continued responses.** The subscription path already concatenates continuation turns and warns that a seam may exist. A seam landing inside a scene boundary marker must not corrupt the split.

---

## Requirements *(mandatory)*

### Functional Requirements

**Core batching**

- **FR-001**: The extraction pass MUST be able to request extractions for multiple scenes in a single exchange, transmitting the session transcript once for that exchange.
- **FR-002**: A batched run MUST produce the same on-disk artefacts as the per-scene run: one file per scene, same location, same naming, same internal structure (front-matter, scene heading, verbatim gm-assist summary, verbatim-moments section).
- **FR-003**: The batched request MUST carry every requested scene's name and its gm-assist bullets, so scene scope remains defined by the human-reviewed summary and not inferred by the model from the transcript.
- **FR-004**: The response MUST be split back into per-scene content deterministically, by an explicit boundary marker, with no model call and no similarity matching involved in the split.
- **FR-005**: The split MUST be verified against the requested scene set before anything is written. A response that yields sections which cannot be reconciled with the request MUST write nothing and report the mismatch.
- **FR-006**: A scene whose returned section is empty MUST be reported as returning no moments, and MUST NOT be written as an empty file.
- **FR-006a**: A run MUST use a single call when the requested scene set's projected output fits within the run's output ceiling.
- **FR-006b**: When the projection exceeds the ceiling, the run MUST divide the requested scenes into the fewest contiguous groups whose individual projections each fit, and MUST issue one call per group. A group MUST never be smaller than one scene.
- **FR-006c**: Grouping MUST be deterministic: the same scene set, ceiling and projection method MUST always produce the same grouping.
- **FR-006d**: The run MUST report how many groups it used and, when it used more than one, that the projection exceeded the ceiling — so the GM can choose to raise the ceiling and collapse the run back to one call.

**Selection and control**

- **FR-007**: Batched mode MUST be a visible control that the GM can set either way on every run, surfaced on the CLI and in the editor.
- **FR-007a**: The editor MUST pre-select batched mode when the resolved backend is the subscription, and MUST leave it unselected on the metered API. The pre-selection is a default the GM sees and can override before the run — it MUST NOT be applied invisibly or become unoverridable. *(Constitution X is satisfied by visibility and overridability, not by refusing to have a default: the scene set itself is still chosen explicitly by Force / skip-if-exists, per FR-008.)*
- **FR-008**: The set of scenes a batched run acts on MUST be the same set the per-scene run would act on: all scenes when Force is set, otherwise only scenes with no existing file.
- **FR-008a**: Skip-if-exists MUST be applied **before the request is built**, not after the response arrives. A scene that already has an extraction file, with Force off, MUST NOT appear in the request, MUST NOT be counted in the output projection, and MUST NOT influence group sizing. Sending every scene and discarding the already-extracted ones would spend exactly the tokens this feature exists to save — for a session with 5 of 8 scenes done, it would cost the full projection instead of three-eighths of it.
- **FR-008b**: When every requested scene already exists on disk and Force is off, the run MUST make **no call at all** and say so — the same no-op the per-scene mode performs today.
- **FR-008c**: With Force set, every scene MUST be in the request set, and the projection and grouping MUST be computed over all of them.
- **FR-008d**: Whether a scene counts as already-extracted MUST be decided by the same rule the per-scene mode uses today — the presence of its extraction file — so the two modes can never disagree about what still needs doing. A run started in one mode and finished in the other MUST converge on the same set.
- **FR-009**: The existing per-scene mode MUST remain available and unchanged, including on the metered path where caching already delivers the reuse this feature is chasing.

**Resumability and failure**

- **FR-010**: Every scene whose section arrived complete MUST be written, even when the response ended before covering all requested scenes.
- **FR-011**: A scene whose section is incomplete (the response ended inside it) MUST NOT be written.
- **FR-012**: A run that did not return every requested scene MUST name the missing scenes and MUST exit in a way that marks the run as incomplete.
- **FR-013**: Re-running after a partial batched run, without Force, MUST request only the scenes still missing from disk.
- **FR-014**: The existing Force semantics MUST be preserved exactly: prior content snapshotted before overwrite, review markers cleared, and no overwrite (and no snapshot) when the new content is identical.

**Fidelity**

- **FR-015**: No **alias-map-derived** transform may be applied to the transcript on the batched path. Entity aliases reach the model as roster knowledge, never as a rewrite over the transcript. *(Constitution IV; the alias-as-transform defect this repo has already fixed once.)*
- **FR-015a**: The **player speaker-label** normalisation that already runs before the engine (`normalize_vtt_speakers`, `session_doc/scene_extract.py:427` — mapping each person's Zoom display names to their character/GM label, feature 009) stays in scope and unchanged on the batched path. It is a declared identity mapping authored in `players.yaml`, not a similarity-based rewrite of what was said. FR-015 is about the alias map specifically; it is **not** a claim that the transcript reaches the model byte-identical to the file on disk.
- **FR-016**: The extraction instructions governing verbatim quoting MUST apply per scene in batched mode with the same force they have per call today, including the prohibition on merging utterances, on editorial insertions inside quotes, and on repairing transcript garbles.
- **FR-017**: The output ceiling for a batched run MUST default to 32,000 tokens — sized against the measured **23K** of model-generated output for a full 8-scene session (research D3), leaving ~28% headroom — rather than the 8,192 per-scene default, which cannot accommodate a whole session.
- **FR-017a**: The ceiling MUST remain adjustable per run, on the CLI and in the editor. Raising it above a session's projection MUST collapse that run to a single call (FR-006a); the ceiling is the GM's lever over the saving-versus-response-length trade, not a fixed constant.
- **FR-017b**: Raising the ceiling MUST NOT change the per-scene mode's own default, which stays where it is.

**Observability**

- **FR-018**: A completed run MUST report the number of scenes requested, the number returned complete, the number of groups used, and the number of transcript transmissions made.

**Human checkpoint**

- **FR-019**: Batching MUST NOT collapse the Stage 1 → Stage 2 gate. The scene structure a batched run consumes is still the human-reviewed summary; nothing in this feature may let the model propose or revise scene boundaries.

### Key Entities

- **Scene request set**: the ordered scenes a run will extract — derived from the human-reviewed summary, filtered by what already exists on disk unless Force is set. Carries each scene's name, its gm-assist bullets, and its destination file.
- **Batched exchange**: one transmission carrying the transcript plus one group's scenes, and the response carrying every scene in that group.
- **Group**: a contiguous run of scenes answered by a single exchange. One group for a session that fits the ceiling; the fewest that fit otherwise.
- **Output ceiling**: the per-run cap on response length, defaulting to 32,000 tokens and adjustable per run. It is what decides how many groups a run uses.
- **Scene boundary marker**: the explicit delimiter that makes the response splittable without inference. Must be unambiguous against arbitrary human-authored scene names and against extracted transcript content.
- **Run report**: scenes requested, scenes returned complete, scenes missing, groups used, transcript transmissions.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Re-extracting a session of N scenes on the subscription path transmits the transcript **once per group**, not once per scene. On the measured 8-scene, 18K-token-transcript corpus that is one transmission, removing ≈ 125K transmitted tokens per full re-extract.
- **SC-001a**: A session whose projected output fits the 32K default ceiling uses exactly one call. On the measured corpus (5–8 scenes, ≈ 23K generated at the top of the range — research D3) that is every session sampled.
- **SC-001b**: For any session, transcript transmissions are at most ⌈projected ÷ ceiling⌉ and always strictly fewer than the scene count for sessions of two or more scenes.
- **SC-002**: Wall-clock time for a full re-extract is **measured and recorded** for both modes on the same session. There is **no time threshold** — see the goal ruling in Assumptions. Time parity is an acceptable outcome; a regression is not.
- **SC-003**: For a session extracted both ways, the deterministic quote verifier reports a verified-quote rate for the batched run no more than 5 percentage points below the per-scene run.
- **SC-004**: For a session extracted both ways, no scene loses more than 20% of its extracted moments in the batched run, and the loss is not concentrated in the scenes appearing last in the response.
- **SC-005**: A run given a response covering only the first K of N scenes writes exactly K files, names the N−K missing scenes, and a subsequent run without Force requests exactly those N−K.
- **SC-005a**: For a session with K of N scenes already on disk and Force off, the request contains exactly N−K scenes and the projection is computed over exactly those N−K. Measured against the 8-scene corpus: with 5 done, the run's projected output is roughly three-eighths of a full run's, not equal to it.
- **SC-005b**: For a session with all N scenes on disk and Force off, the run makes zero calls and transmits the transcript zero times.
- **SC-005c**: For the same session with Force on, the request contains all N scenes and every existing file is snapshotted before being overwritten.
- **SC-005d**: A session extracted half in per-scene mode and half in batched mode ends with the same N files as a session extracted wholly in either mode.
- **SC-006**: 100% of batched runs produce files structurally indistinguishable from per-scene runs — same paths, same front-matter, same section headings.
- **SC-007**: No batched run writes content for a scene under a different scene's file.
- **SC-008**: The per-scene mode's behaviour on the metered path is unchanged — same requests, same caching, same files, same 8,192 default ceiling.
- **SC-009**: Raising the ceiling above a session's projection reduces that session's run to a single call, verifiably, without any other change to the invocation.

---

## Assumptions

- **Tokens are the goal; time is not (GM ruling).** The original framing led with elapsed time. The GM has since ruled: *"how much time I save is less important than how many tokens. In fact, if it takes as much time I am okay."* So the committed promise is SC-001 — the transcript transmitted once per group instead of once per scene, ≈ 125K tokens removed from an 8-scene re-extract — and wall-clock is an observation, not a target.

  This is worth stating because the structure argues the time saving would have been modest anyway: batching removes redundant **prefill** and N−1 subprocess startups, but **total decode is unchanged** — the same ~23K output tokens are generated either way — and decode dominates on this backend (`campaignlib/api/backends.py` records 3m57s for 10,100 output tokens). An earlier draft of SC-002 promised ≥50% wall-clock reduction; that number was never sourced and the arithmetic puts the real figure nearer 20–36%. It has been withdrawn rather than defended. **Do not reintroduce a time target without measuring the prefill/decode split first.**

- **The transcript, not the instructions, is the cost.** The transcript dominates the per-call payload; the extraction instructions and NPC roster are small by comparison. Batching is worth doing because it removes the transcript's repetition, and the small shared preamble riding along with it is not what this feature is optimising.
- **Partial results are kept, not discarded.** When a response ends early, scenes that arrived complete are written and the rest are reported missing. This is the resumable behaviour the per-scene mode already has (skip-if-exists), and it makes the follow-up run cheap. The alternative — discard everything on a short response — would make a batched run strictly riskier than the loop it replaces.
- **A complete scene is one whose section is fully delimited.** Completeness is determined structurally, from the boundary markers, not from judging whether the content looks finished.
- **Scene identity is positional and name-checked, not fuzzy-matched.** Response sections are reconciled to the request by order and confirmed by name; a mismatch is a hard failure. Similarity matching is not used to decide which scene a section belongs to — that is an identity assertion, and this repo forbids those.
- **The existing deterministic quote verifier is the fidelity gate.** SC-003 and SC-004 are measured with the zero-token verifier already in the tree, not by asking a model whether the output looks good.
- **`--batch` (the metered Message Batches submission) is a different thing and stays as it is.** It submits N per-scene requests as one job for a discount; this feature reduces N to 1 for a path where that submission mode is unavailable. The two are not alternatives to each other and this spec does not change the former.
- **The subscription path's auto-continuation stays in play.** The existing behaviour of concatenating continuation turns is what makes a large single response possible at all; this feature depends on it rather than replacing it. Grouping reduces how often it is needed; it does not remove the need for it.
- **The projection is an estimate, and being wrong about it is survivable.** Group sizing is decided before any response exists, so it necessarily estimates how much output a scene will produce. An underestimate lands in the short-response path (User Story 2) — scenes that arrived are kept, the rest are re-requested — which is the same failure the per-scene mode already handles. The projection method does not need to be exact; it needs to be deterministic (FR-006c).
- **32,000 is a starting default, not a calibrated constant.** It was chosen against one measured session (~29K across 8 scenes) with headroom. The GM adjusts it per run, and the run reports enough (groups used, scenes returned) to re-tune it from evidence rather than guesswork.

---

## Out of Scope

- Reducing the transcript itself (windowing to a scene's time range, pruning non-dialogue cues). A smaller transcript would cut the payload further and is a legitimate separate lever, but it changes what the model can see and therefore what it can quote — a fidelity decision, not a plumbing one.
- Reusing a single `claude -p` session across scenes as an alternative to batching (N turns in one conversation rather than one turn carrying N scenes). It would also send the transcript once. It is not what was asked for here, and it moves the failure mode from "one long response" to "a long-lived subprocess".
- Any change to Stage 1, to the summary's scene structure, or to who decides scene boundaries.
- Any change to the metered API's per-scene caching or batch submission behaviour, including its 8,192 per-scene output default.
- Calibrating the projection method or the 32K ceiling against a wider corpus. The default and the lever ship together; tuning them is a follow-up informed by what the run report shows.

---

## Dependencies

- The human-reviewed Stage 1 summary with a `## Scenes` section — unchanged, and still the sole source of scene structure.
- The deterministic quote verifier, for SC-003 / SC-004.
- The subscription backend's existing continuation-concatenation behaviour, for responses that exceed a single turn.
