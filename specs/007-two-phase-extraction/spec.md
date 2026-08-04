# Feature Specification: Two-Phase Extraction Agent

**Feature Branch**: `feat/dgx-two-phase-extraction`

**Created**: 2026-08-03

**Status**: Draft

**Input**: User description: "i have been using hermes and openclaw and i have discovered that I can use the deepseek model to extract facts, the consequence of this extraction and summarization is error, but then I can ask openclaw to go back and fix the errors. i would like to make to create such an agent. The goal would be for the extraction phases that we have an orchestrator - kicks off the 'generate summary' then kicks off the 'detect any facts using grounding documents' and then applies the output. The final document, is then reviewed by me using claude. The goal isn't perfection but reducing toil" — refined in conversation to: the observed failure is **invented quotes**, and the wanted second phase is **quote verification**; the target is the **Session Doc Editor** flow, not the ensemble flow.

## Problem

The Session Doc Editor's two extraction stages both instruct the model to
reproduce dialogue verbatim, and neither checks that it did.

- Stage 1 (`enhance_summary`) is told *"Quote dialogue VERBATIM when promoting
  a line to Memorable Moments"*.
- Stage 2 (`scene_extract`) is told *"Quote dialogue VERBATIM. Do not
  paraphrase."*

Running Stage 1 against a local model on the DGX Spark produced a usable
summary containing **fabricated quotes**. Nothing in the pipeline detected
them. An unchecked fabricated quote propagates into scene extractions and then
into narration, where it reaches the table as words a character never said —
the failure the project constitution names as its most expensive (Principle IV,
*Verbatim is Sacred*).

The sibling ensemble pipeline already enforces this contract mechanically; the
session-doc pipeline makes the same demand of the model and enforces nothing.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Catch invented quotes in the generated summary (Priority: P1)

The GM generates a session summary from the transcript using a fast local
model, knowing it will invent some dialogue. Instead of re-reading the whole
summary against the transcript to find the fabrications, they get a report
naming each quote that does not appear in the transcript, with the closest
real line beside it so a reflow is instantly distinguishable from an invention.

**Why this priority**: This is the observed failure. It delivers the entire
value of the feature on its own — a GM can run it by hand after any summary
generation and stop trusting quotes they haven't checked.

**Independent Test**: Generate (or hand-write) a summary containing one exact
quote, one lightly reflowed quote, and one invented quote; run the verifier
against the session transcript; confirm the report classifies all three
correctly and the exact quote is not flagged.

**Acceptance Scenarios**:

1. **Given** a summary quote that appears in the transcript character-for-character,
   **When** verification runs, **Then** the quote is not flagged.
2. **Given** a summary quote identical to a transcript line except for line-break
   reflow or collapsed whitespace, **When** verification runs, **Then** the quote
   is not flagged.
3. **Given** a summary quote that appears nowhere in the transcript, **When**
   verification runs, **Then** it is reported with its location, the closest
   transcript line, and a similarity measure.
4. **Given** a quote the generating model marked `(paraphrase)` or `(truncated)`,
   **When** verification runs, **Then** it is exempt and not reported as a failure.
5. **Given** any verification run, **When** it completes, **Then** no quote text
   anywhere in the checked artifact has been altered or removed.

---

### User Story 2 - Catch invented quotes in scene extractions (Priority: P2)

The GM has moved past the summary to per-scene extractions, which the narration
stage treats as the authoritative record of what was said. They verify those
extractions against the transcript before any narration is generated from them.

**Why this priority**: Same hazard, one stage later, and more dangerous because
narration consumes these files as authoritative. Lower than P1 only because the
observed failure occurred at Stage 1 and Stage 2's output format is more
constrained.

**Independent Test**: Place a scene extraction file containing a fabricated
blockquote in an extractions directory; run verification against the
transcript; confirm the file and the offending quote are named in the report.

**Acceptance Scenarios**:

1. **Given** a directory of scene extraction files, **When** verification runs,
   **Then** every file is checked and the report identifies findings per file.
2. **Given** a scene extraction whose quotes are all genuine, **When**
   verification runs, **Then** the report records it as clean.
3. **Given** narration has not yet run, **When** verification finds fabrications,
   **Then** the GM can correct the extraction before spending tokens on narration.

---

### User Story 3 - One action instead of three (Priority: P3)

Rather than invoking generation, then quote verification, then the grounding
consistency check as three separate steps and remembering the argument each
needs, the GM triggers one action per stage. It generates, then runs the checks
that apply to that stage, and reports what each found. The GM then reviews the
findings in Claude.

**Why this priority**: This is the toil reduction the request is actually
about, but it is orchestration over capabilities that must exist first. Without
US1 there is nothing to orchestrate.

**Independent Test**: Trigger the summary-stage action on a session with a
transcript and a recap; confirm generation, quote verification, and the
consistency check all run in order and each reports its outcome.

**Acceptance Scenarios**:

1. **Given** the summary stage is triggered, **When** it runs, **Then**
   generation, quote verification, and the grounding consistency check execute
   in that order and each reports its result.
2. **Given** quote verification finds fabrications, **When** the run continues,
   **Then** the consistency check still executes — a finding is not an error.
3. **Given** the generation step fails outright, **When** the run continues,
   **Then** it stops rather than checking an artifact that was not produced.
4. **Given** the summary stage completes, **When** the run ends, **Then** it
   stops before scene extraction — the human review point between the two
   stages is preserved.
5. **Given** a local model endpoint is selected, **When** the stage runs, **Then**
   generation uses it and verification runs without contacting any model.

---

### Edge Cases

- **No transcript available.** Verification refuses to run and says so, rather
  than reporting every quote as unverifiable — a missing source is an operator
  error, not a corpus of fabrications.
- **Artifact contains no quotes at all.** Reported as "no quotes found" and
  distinguished from "all quotes verified"; the first is suspicious, the second
  is success.
- **Verification re-run on an already-annotated artifact.** Produces a
  byte-identical file. Markers are never double-applied.
- **A quote spans a speaker change in the transcript.** Cannot match as a
  contiguous span; reported as a failure with the nearest line, for the human
  to judge.
- **A quote is a very short common phrase** (e.g. `"Yes."`). Will match
  somewhere in almost any transcript; the report notes matches below a minimum
  length as weak evidence rather than silently counting them as verified.
- **Transcript and artifact disagree on speaker labels.** Verification checks
  quote *text* only; speaker attribution is out of scope and stated as such.
- **The grounding consistency check finds nothing.** Reported explicitly as a
  clean result, not as an empty file.

## Requirements *(mandatory)*

### Functional Requirements

**Quote verification**

- **FR-001**: The system MUST verify each quote in a checked artifact against
  the session transcript and classify it as verified or unverified.
- **FR-002**: Verification MUST tolerate whitespace and line-break differences,
  so a quote that is verbatim apart from reflow is classified as verified.
- **FR-003**: Verification MUST NOT invoke a language model. Classification is
  determined solely by comparing text against the transcript.
- **FR-004**: For each unverified quote, the system MUST report its location in
  the artifact, the quote text, the closest transcript line, and a similarity
  measure between them.
- **FR-005**: The system MUST exempt quotes explicitly marked `(paraphrase)` or
  `(truncated)` — the markers the generation prompts define for the case where
  no verbatim quote exists.
- **FR-006**: The system MUST NOT alter, replace, or delete any quote text. Its
  only permitted modification to a checked artifact is an additive,
  human-visible marker on an unverified quote.
- **FR-007**: Applying markers MUST be idempotent — re-running verification on
  an already-marked artifact produces an identical file.
- **FR-008**: The system MUST support suppressing in-place marking entirely,
  producing only a report.
- **FR-009**: The system MUST write its findings to a file on disk, so the
  result survives the session and is readable by the CLI, the UI, and a Claude
  conversation alike.
- **FR-010**: The system MUST report a distinct outcome for "no quotes found"
  versus "all quotes verified".
- **FR-011**: The system MUST refuse to run when the transcript is missing or
  unreadable, rather than reporting all quotes as unverified.

**Scope of checking**

- **FR-012**: The system MUST verify quotes in the Stage 1 generated session
  summary.
- **FR-013**: The system MUST verify quotes in Stage 2 per-scene extraction
  files, checking every file in the extractions directory.
- **FR-014**: The system MUST NOT check narration output. Narration legitimately
  reflows dialogue and is produced by a separate tool outside this feature.

**Orchestration**

- **FR-015**: The system MUST provide a single action per stage that runs that
  stage's generation step followed by its applicable checks.
- **FR-016**: The summary-stage action MUST run generation, then quote
  verification, then the grounding-document consistency check.
- **FR-017**: The scene-stage action MUST run generation, then quote
  verification.
- **FR-018**: The orchestrated run MUST stop at the end of its stage. It MUST
  NOT continue into the next stage, preserving the existing human review point
  between stages.
- **FR-019**: A check reporting findings MUST NOT abort the run; remaining
  checks still execute. Only a failure to produce the artifact stops it.
- **FR-020**: The orchestrated run MUST report the outcome of each step
  individually, so the GM can see which step found what.
- **FR-021**: The generation step MUST honour the GM's selected model and
  backend, including a local endpoint.

**Surfaces**

- **FR-022**: Every capability MUST be invocable from the command line, and the
  UI MUST reach it the same way rather than reimplementing it.
- **FR-023**: The Session Doc Editor MUST expose the verification result,
  including whether the report is stale relative to the artifact it describes.

### Key Entities

- **Session transcript**: The recording of what was actually said. The sole
  authority for whether a quote is real. Never modified by this feature.
- **Checked artifact**: A generated document containing quotes — the session
  summary or a per-scene extraction file.
- **Quote**: A span of text in a checked artifact presented as something a
  person said, together with its location in that artifact.
- **Finding**: One unverified quote, with its location, the closest transcript
  line, and the similarity between them.
- **Verification report**: The durable on-disk record of one verification run —
  what was checked, what passed, and every finding.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of quotes that do not appear in the transcript are reported.
  No fabricated quote passes verification.
- **SC-002**: Quotes that differ from the transcript only by whitespace or line
  breaks are not reported. Reflow alone produces no findings.
- **SC-003**: Reviewing a generated summary for fabricated dialogue takes the
  GM under 5 minutes, versus a full re-read against the transcript.
- **SC-004**: Verification of one session's artifacts completes in under 30
  seconds and costs nothing, because no model is called.
- **SC-005**: The number of GM actions required to generate and check one stage
  drops from 3 to 1.
- **SC-006**: Running verification twice on the same artifact leaves the file
  unchanged the second time, in 100% of cases.
- **SC-007**: No quote text is modified by the system in any run.

## Assumptions

- The failure being addressed is **fabricated quotes**. Factual drift against
  campaign canon is a separate failure handled by the existing grounding
  consistency check, which this feature orchestrates but does not change.
- **Nothing is auto-corrected.** The GM chose flag-and-report over automatic
  repair, so applying corrections remains a human action taken in Claude. This
  deliberately excludes the "applies the output" step from the original
  request. The project has prior history here: an autonomous correction pass
  over narration removed legitimate content and was replaced by a
  propose-confirm-apply workflow.
- Narration is out of scope; it is produced by a separate tool.
- Speaker attribution is out of scope. Verification answers "were these words
  said", not "did this person say them".
- The transcript is the authoritative record of spoken dialogue and is treated
  as correct even when it contains transcription errors. A garbled transcript
  line is a transcript problem, addressed by existing transcript-cleanup
  tooling, not by this feature.
- The generation stages already instruct the model to quote verbatim and to
  mark paraphrase and truncation; this feature enforces that existing contract
  rather than introducing a new one.
- The GM may run any stage's generation on a local model endpoint; verification
  is model-independent and unaffected by that choice.
