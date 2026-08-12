# The genre rulebook as a file, as built

> **Issue:** #276 (both fixes). **Shipped:** PR #281 (fix 1), PR #284 (fix 2), 2026-08-12.
> **Also closes:** #220, #249.
> **Operator's manual:** [`docs/cli/genre_rulebook_howto.md`](../cli/genre_rulebook_howto.md) —
> read that first if you want to *use* this. This document is the *why*.
> **Verification record:** `~/src/campaigns/Phandalin/summaries/20260729/capstone_20260729.pr284`.

## The one-paragraph version

A campaign's genre rulebook — tense, POV, register, stock phrases, banned tics, per-narrator
bookkeeping caps — lived in **three** places at once: the hand-authored `voice/_genre.md`, a
pasted copy of it in `narrate.genre`, and a copy of that copy in
`profiles[].knobs.narration_genre`. Nothing kept them in agreement, and the sync that did
exist ran one way only. The paste is what Pass 5 read, and out-of-the-abyss' paste had lost
every newline on the way into YAML, so the campaign with the largest rulebook received it as
a single-line `GENRE:` label — twice, since the prompt repeats it as a tail reminder. Fix 1
made the delimited block depend on size rather than on the presence of a newline. Fix 2
deleted the copies: `paths.genre_file` holds a path, the file is the rulebook, and
`sd_narrate --narration-genre-file` reads it at render time. A migration relocates existing
campaigns and **refuses** wherever choosing between two disagreeing copies would be a content
decision rather than a merge.

## Two problems, and why fix 1 was shipped alone

They are independent, and only one of them needed a decision.

**Delivery** — how the genre text reaches the prompt. Broken by a newline test. Fixable in one
line with no design debt, whichever way the second question went. Shipped first, alone (#281).

**Ownership** — where the rulebook lives. Three copies, no divergence check. Fixing this
required a ruling on which copy is canonical, because deleting the wrong one destroys campaign
content. Shipped second (#284) after the ruling.

Shipping delivery first also removed the urgency from ownership: once a flattened paste is
delivered correctly, flattening stops degrading output, and the remaining problem is drift
rather than damage. That is a better position to decide from.

## Fix 1 — gate on size, not on newlines

`session_doc/narrate.py` chose the genre's delivery form like this:

```python
if "\n" in g:   # delimited GENRE & REGISTER block
else:           # GENRE: {g}
```

The test is a proxy for "is this a document or a label", and the proxy fails for a document
that lost its line structure. Measured on the live trees the day this was found:

| Campaign | `narrate.genre` | newlines | delivered as |
|---|---|---|---|
| Phandalin | 7,351 chars | 60 | delimited block |
| out-of-the-abyss | 16,303 chars | **0** | **`GENRE: <16K one-liner>`** |

The gate is now `"\n" in g or len(g) > GENRE_INLINE_MAX_CHARS`, with the cap at 200. The
comment on the constant records the asymmetry that sets it: erring low is cheap, because the
delimited form is never *wrong* for a short directive — only two lines more verbose — while
erring high is the bug. Nobody should later "tune" it upward.

## Fix 2 — one copy, and it is the file

### Where the path lives, and why not under `narrate`

`paths.genre_file`, not `narrate.genre_file`. It is a path, and `paths` is where path fields
get the whole contract for free: relativized on write (`_relativized_paths`), resolved
absolute on read (`resolved_editor_config`), campaign-scoped rather than session-scoped
(`_CAMPAIGN_PATH_FIELDS`, alongside `voice_dir` and `party`). Putting it under `narrate` would
have meant a second, parallel derivation of the same behaviour — the shape this issue exists
to remove.

The cost is that a profile now owns exactly one path. `_PROFILE_KNOB_TO_GROUPED` maps
`narration_genre_file` → `("paths", "genre_file")`, and the frontend's
`hydrateKnobsFromEditorConfig` had to learn to re-hydrate it, or activating a profile that
switches rulebooks would leave the drawer displaying the previous file. That exception is
documented at both sites rather than left for someone to rediscover.

### The stale key is announced, not dropped

`NarrateKnobs` no longer declares `genre`, and `extra="forbid"` would reject it — which would
take the whole editor down on boot for any campaign not yet migrated. So the key is stripped
by a `model_validator`, following the established `RETIRED_NARRATE_FIELDS` pattern, but under
a separate `RELOCATED_NARRATE_FIELDS` tuple with its own message.

The distinction matters. A retired key is obsolete; this one is a **document with a new
home**. out-of-the-abyss' was 16,303 characters. The notice therefore names the size, the
destination, the migration command, and — the part that earns its length — what the loss costs
until the migration runs:

```
config: ignoring relocated session_doc.yaml narrate field(s) genre (16303 chars) — the genre
rulebook is now a file, addressed by paths.genre_file (#276).
  -> this value is NOT reaching Pass 5. Relocate it with:
     python -m server.migrate_narrate_genre --campaign-dir <DIR>
```

### The resolved view carries a summary, never the text

`ResolvedGenre` is injected into the resolved editor config beside `model` and `work_dir`:
path, exists, line count, char count, a 600-character preview, a 12-character content digest,
and an error string. It deliberately has **no** `text` field. Nothing downstream may read the
rulebook through the config view; Pass 5 reads the file. A `text` field would have recreated
the copy this fix deleted, one layer up.

### The UI points; it does not edit

The drawer shows the path, a status line in one of three states, and a read-only preview. It
offers no way to change the content.

This is the direct lesson of #249. That issue made the genre field a `<textarea>` because a
single-line `<input>` flattened a pasted document. The textarea was the right fix for the
shape the system had; fix 2 changes the shape so the flattening path does not exist at all. A
browser form is not where an 88-line hand-authored document should be edited, and the three
UI states matter more than an editor would:

| State | Meaning |
|---|---|
| unset | No rulebook configured. Pass 5 gets no genre directive. |
| missing | A path is configured and the file is not there. **Pass 5 gets no genre directive.** |
| resolved | Path, line and character counts, preview. |

The middle state is the dangerous one and is styled as an error, because there is no longer a
YAML fallback behind it.

### Runs record identity, not a copy

The per-scene `.knobs.json` used to store `narration_genre` — the entire document. For
out-of-the-abyss that wrote 16K of prose into every per-scene sidecar. It now stores
`narration_genre_file`, `narration_genre_sha` and `narration_genre_lines`.

The digest is not decoration. A path alone cannot answer "did these two scenes use the same
rulebook?" once the file has been edited between renders, and that is precisely the question a
run record exists to answer. When the file did not resolve, no digest is written at all —
claiming nothing is better than claiming a hash of nothing.

### A missing file is loud

`_load_genre_file` warns and returns `None` for a missing or empty file, naming what is lost:

```
Warning: --narration-genre-file <path> does not exist. Pass 5 will run with NO genre
directive — no register rules, no banned-tic list, no bookkeeping caps.
```

Before fix 2 a bad path was survivable, because the YAML copy was still there. Now it is not,
so the warning has to carry the consequence rather than just the fact.

## The migration, and where it refuses

`python -m server.migrate_narrate_genre --campaign-dir DIR`

It reads `session_doc.yaml` **raw**, because the typed model now strips `narrate.genre` — the
very data the CLI exists to rescue. Same technique as `migrate_ensemble_config`.

Three deliberate behaviours:

**Pure flattening is not a conflict.** The comparison is whitespace-normalised. A paste that
lost its newlines is the same rulebook, badly stored; demanding a GM ruling there would be
noise, and it would fire on exactly the campaigns #249 damaged.

**A genuine disagreement refuses.** Which copy is the real rulebook is a content decision.
`--prefer-file` and `--prefer-yaml` exist so the operator states the answer after looking at
it. Nothing is written on the refusal path.

**A divergent profile refuses separately.** A profile carrying genre text that differs from the
canonical rulebook wanted a *different* rulebook, and now needs its own file — which the CLI
cannot invent. `--drop-profile-genre` discards it explicitly and says so in the output.

### Refusals report words, not lines

The first implementation printed a unified line diff. Run against real data it was useless: a
flattened paste is one line, so every line differs and the diff degenerates into "the whole
document".

The refusal now reports differing **word runs** with context. The change paid for itself
immediately — out-of-the-abyss' entire 0.9989 divergence turned out to be the file's H1 title:

```
What differs (words, not lines — the paste has no line structure):
  after “”:
    only in the file:  “# Out of the Abyss Narration Genre”
```

That is the difference between a ruling that takes a second and one that takes ten minutes of
reading. It is also the general point: **a diff must be shaped like the data, not like the
file format.**

## What the build found

Verification was a real render, not inspection. The #245 capstone was run on Phandalin session
20260729 — a session whose existing narration predated both #247's voice-file resolver and
this work, so the before/after isolates exactly what changed. Full record:
`capstone_20260729.pr284` in that session directory.

**The tense rule had never reached the model.** Phandalin's genre states "First-person present
tense, always", twice. Re-rendering scene 04 with the rulebook delivered as a block:

| | Past-tense verbs | Present-tense verbs |
|---|---|---|
| Old render | 31 | 4 |
| Capstone re-render | 7 | 30 |

Extending the measurement to the whole campaign: **3 of 62 rendered scenes are in the tense the
rulebook requires.** All 10 sessions are past-dominant. That is the footprint of a 7,063-character
single-line label, and it is tracked as campaigns#163.

**Why ten sessions of this went unnoticed.** out-of-the-abyss and toee both specify
first-person *past*, and their renders are past. out-of-the-abyss' paste is flattened too, and
its output still looks correct — because past tense is what the model does anyway.

> A rule that agrees with the model's default proves nothing about whether the rulebook is
> being read.

Phandalin is the only campaign of the three whose rule contradicts the default, so it is the
only one where a silent delivery failure was legible. This is the most reusable thing the build
produced: when validating that instructions reach a model, test on an instruction the model
would not have followed by accident.

**A second-order find.** Measuring em-dash use on the new render surfaced that the genre file
*permits* the em-dash for interrupted thought without forbidding it as a general connective —
8 of 17 uses were connective. `/voice-critic`'s scan A, meanwhile, flags every narration
em-dash, so the checker and the rulebook disagree in both directions. campaigns#158 (fixed for
Phandalin), campaigns#161, kostadis/mytools#125.

## Decisions, and the options that lost

| Decision | Chosen | Rejected, and why |
|---|---|---|
| Where the rulebook lives | **A** — `paths.genre_file`, delete the pastes | **B** keep the paste + a divergence check: leaves three copies and adds a checker to maintain. **C** bidirectional profile sync (#220's own proposal): fixes the profile copy but leaves the paste stale against the file. |
| Field location | `paths` | `narrate` — would need a parallel path-resolution derivation |
| Config view | summary only | include the text — recreates the deleted copy one layer up |
| UI | path + read-only preview | editable textarea writing through to the file: makes the editor a writer of hand-authored campaign files, and a paste can still strip newlines |
| Run record | path + digest + line count | the full text (what it did before): 16K per sidecar, and still cannot detect a mid-session edit |
| Missing file | warn, no genre | fall back to the stale YAML value — a dual-location probe, which this repo's convention forbids |
| Migration on disagreement | refuse | pick the longer/newer copy: silently destroys campaign content |
| Flattened vs file | not a conflict | refuse: would fire on every campaign #249 damaged |
| Rule statement in the genre file | one place | also add it to the banned-tics section — a rule stated twice in one document is the divergence being removed |

## What this does not do

- **It does not migrate campaigns.** The code ships; each campaign is a separate, deliberate
  run. Until then that campaign's stale `narrate.genre` is announced and ignored, which means
  **no genre directive at all** for its renders. This is the first thing to check when a render
  suddenly reads generic.
- **It does not repair existing output.** 59 Phandalin scenes remain in the wrong tense
  (campaigns#163), and whether to re-render is a content decision.
- **It does not give a campaign a rulebook.** Three campaigns have no `voice/_genre.md`
  (campaigns#162).
- **It does not fix the checker.** `/voice-critic` still carries a hand-copied fork of the
  rules, including an em-dash scan that contradicts the genre (kostadis/mytools#125).
- **It does not validate rulebook content.** A file that says nothing useful resolves happily;
  only its existence, size and digest are reported.

## Where to read next

- [`docs/cli/genre_rulebook_howto.md`](../cli/genre_rulebook_howto.md) — how to use it, and
  what every refusal means.
- [`NarrationNextSteps_handoff.md`](NarrationNextSteps_handoff.md) §3 — the ruling in its
  ordering context, with the pre-ruling framing preserved.
- [`VoiceCriticAlignment_proposal.md`](VoiceCriticAlignment_proposal.md) §5 — the survey that
  found the flattening, and the five-copies analysis this is one fifth of.
- [`Issue245Followups_handoff.md`](Issue245Followups_handoff.md) — WO-2, the hand re-sync that
  was the symptom; and the capstone whose render is this build's proof.
