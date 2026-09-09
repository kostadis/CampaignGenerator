# Phase 0 — Research: porting the gap-marking contract

Eight decisions. Everything here was checked against the tree, not inferred from the issue.

---

## D1 — Reconcile with a placeholder and variant fragments, not a second copy of the brief

**Decision.** `writing_brief.md` and `prose_mode.md` keep their single copy. The sentence that
contradicts the contract is replaced, in place, by a placeholder whose value is chosen by the
mode.

**Rationale.** The obvious alternative — `writing_brief_gap.md` beside `writing_brief.md` — makes
gap-off byte-identical for free, because the original file is untouched. It also duplicates
fifteen lines of dense prose that every future edit would have to make twice. This repo has
paid that bill: `#435` found `scene_anchored.md` and `bundle_scene.md` each restating three
rules the brief owns, already drifted (`"retain their attribution"` vs `"preserving
attribution"`), and neither matching the brief. One string is the fix that landed there and it
is the fix here.

**Alternatives considered.** (a) Whole-file variants — rejected above. (b) Append the contract
and leave the contradiction, per a literal reading of `prompt.diff` — rejected by FR-004; the
experiment prompt never carried the contradicting sentence, so appending reproduces the diff
without reproducing the tested configuration. (c) Delete the absorbing sentence outright in both
modes — changes non-gap behaviour, which nothing asked for and no evidence supports.

---

## D2 — The placeholder sits exactly where the sentence sits, so gap-off is byte-identical

**Decision.** `{gm_attribution}` replaces the existing sentence in situ, mid-paragraph, and the
*absorb* variant is that sentence character-for-character.

**Rationale.** This is what makes FR-005 a byte-identical requirement rather than a
"semantically equivalent" one. `_fill` emits each value verbatim and does not re-scan the joined
result, so an exact-text variant reassembles the original paragraph exactly. A weaker placement
— hoisting the rule to its own paragraph, say — would change the assembled prompt in gap-off
mode, and there is no evidence about what that costs.

**Consequence for the gap variant.** It is longer than the sentence it replaces and lands
mid-paragraph. That is acceptable in a prose brief and is the price of D1 + D2 together. It is
*not* the same position the sentence occupied in the experiment prompt, which appended it to a
different paragraph — the prompts have no common structure, so no placement can be preserved.
That is precisely why FR-013 requires a re-run rather than a transfer.

---

## D3 — Two placeholders, four variants — because the two sentences are not the same sentence

**Decision.**

| Slot | Absorb variant (today's text) | Gap variant |
|---|---|---|
| `writing_brief.md` `{gm_attribution}` | *GM descriptions become experienced facts; NPC speech voiced by the GM remains NPC speech.* | the contract |
| `prose_mode.md` `{gm_attribution_prose}` | *GM descriptions become experienced facts; speech the GM supplies for an identified NPC or PC stays with that character.* | *Speech the GM supplies for an identified NPC or PC stays with that character.* |

**Rationale.** `#454` describes these as "the same sentence again". They share a first clause and
differ in the second, which was verified by reading both files. One shared fragment would make
them identical and break FR-005 in prose mode. Two slots keep both texts intact.

Only the **first** clause conflicts with the contract. The prose-mode gap variant therefore keeps
its second clause and drops the first — the rule that NPC speech stays with its character is
what the tested model got right unprompted, and dropping it would remove a rule the contract
does not replace.

**Alternatives considered.** One fragment for both slots — breaks FR-005. A single placeholder
in `writing_brief.md` only, leaving `prose_mode.md` untouched — leaves the contradiction live
whenever prose mode is on, which US2 scenario 2 forbids.

### The half of this decision that was implemented wrong, and what it cost

The rule above — *only the first clause conflicts; keep the second* — was applied to
`prose_mode.md` and **not** to `writing_brief.md`, whose gap variant replaced the whole sentence
and so deleted "NPC speech voiced by the GM remains NPC speech". The contract never restates it.

The first re-confirmation run (2026-09-08, `experiments/20260908-454-reconfirm/`,
`per-scene-run1-missing-npc-clause/`) is what found it, and it is the reason the run exists:

- **soma** turned two `**GM** — *as the sun priest*` turns, which carry verbatim NPC dialogue,
  into gap markers. The accepted render had written them as `"But why do you insist on the
  pain?"`.
- **brewbarry** did the opposite — it absorbed the opening GM recap into the narrator's voice
  ("The door of the Spire closes behind us…"), the contract's central prohibition.
- **valphine** and **vukradin** were unaffected. The contrast is the diagnosis: valphine's
  labels are `**[GM, as the banker]**`, so the NPC's identity is in the label itself, and
  vukradin has 40 bare `**[GM]**` labels and no qualified ones at all. Only soma's form puts
  the NPC's identity in an italic context line, which is exactly the case that needs the rule
  stated rather than inferred.

Restoring the clause — inside the GM-turn taxonomy, so it reads adjudication → dropped, NPC
speech → dialogue, description → gapped — fixed **both** symptoms in run 2: the sun priest
speaks again, and brewbarry opens with markers. One missing rule, two opposite failures.

A diagnosis offered in between, and withdrawn: that `writing_brief.md` ¶2 ("give those things
space in the narration as the POV character encounters them") licensed brewbarry's absorption
and was a *third* text needing reconciliation. It is not. The single clause restoration fixed
brewbarry with ¶2 untouched. Recorded because reaching for a prompt-design explanation from one
arm, when the cause was a rule this document had already got right on paper, is the error worth
remembering.

`tests/test_gap_marking_prompt.py::test_gap_mode_keeps_the_rule_that_gm_voiced_npc_speech_is_dialogue`
is the guard.

---

## D4 — Prove FR-005 against a frozen pre-feature golden, not against a regenerated one

**Decision.** Copy today's `tests/golden/prompts/narrate_system_matrix.json` into
`specs/028-gap-marking-contract/golden_pre_feature.json` before touching a template. A test
asserts that every gap-off combination equals its pre-feature entry.

**Rationale.** The golden already exists and already asserts byte-identity across 256
`build_narrate_system` combinations plus nine standalone constants — the exact guarantee FR-005
wants, sitting in the repo. But the golden's own workflow is *regenerate when a prompt edit is
intended* (`UPDATE_PROMPT_GOLDEN=1`), and this feature does intend one: the matrix gains a
`gap_marking` dimension and doubles to 512. Regenerating it makes the file agree with whatever
was built, which proves nothing about the half that was supposed not to move.

Freezing the pre-feature copy separates the two claims: the new golden guards future drift, and
the frozen copy proves *this* change did not move the old half. Same shape as `#453`'s
`baseline.json`.

**Alternatives considered.** Trusting the regenerated golden's diff under review — a 512-entry
JSON diff is not reviewable by eye, and the whole point is that the gap-off half must be
provably untouched.

---

## D5 — The gap marker is not apparatus, and FR-011's binding is a prompt test

**Decision.** `[GM NARRATION — TO BE WRITTEN: …]` is **not** added to `APPARATUS_MARKERS`. The
producer binding is a test asserting the marker's request appears in every gap-on prompt,
modelled on `tests/test_apparatus_marker_pairing.py` but asserting presence rather than registry
membership.

**Rationale.** `session_doc/apparatus.py`'s registry drives `strip_audit_comments`, which
*removes* matching HTML comments from the assembled document. A gap marker must survive — it is
content, and `#455` exists to answer it. Registering it would delete the feature's output at
assembly. The registry is also comment-shaped (`<!-- … -->`); the marker is a bracketed line.

What transfers is the *lesson*, which is why FR-011 exists: `26ec5b0` deleted the prompt that
emitted `table-speech reclassified:` and left the stripper, its seven tests and three
out-of-repo skills standing, with nothing failing, because nothing tied a marker to a producer.
The same deletion must not be possible here.

---

## D6 — Do **not** mask gap markers from the unknown-name scan

**Decision.** `find_unknown_names` continues to see marker text.

**Rationale.** `#396` masks audit comments before the scan because a comment quotes raw table
speech *verbatim* — an unmasked scan reports the very words the pass just removed from the
fiction. A gap marker is the opposite: it is new prose the model wrote about the source. A
proper noun that appears only inside a marker and nowhere in the session's extractions is
exactly the invention the scan exists to catch, and the scan's `known_texts` already includes
`session_source`, so names genuinely drawn from the source are known and stay quiet.

Masking here would build a blind spot into the one check that would notice the model inventing a
name while summarising what it declined to write.

---

## D7 — The bundle path takes the same fragment through a second placeholder

**Decision.** `bundle_base.md` gains `{gm_attribution}` handling by the same mechanism: its
`{writing_brief}` value is filled before interpolation, exactly as `base.md`'s is. No separate
contract text.

**Rationale.** Both templates already interpolate `{writing_brief}`, so filling the brief once
per render and passing the filled string serves both paths with one code change and one text.
Per the Q2 ruling gap marking reaches both; per `#435` there must not be two statements of the
rule.

**The untested part is behavioural, and is not closed by this decision.** The contract's evidence
is four scenes rendered as four calls. Whether marker discipline holds when one response carries
every scene is unknown, which is what SC-009 and FR-013 make a criterion.

---

## D8 — `sd_narrate` writes the render record; the server merges its outcome into it

**Decision.** `sd_narrate` writes `*.knobs.json` with the facts it knows at render time. The
server stops calling `_write_knobs_sidecar` with a config snapshot and instead merges its
outcome fields (`status`, `exchange_count`, `written_count`, `missing_count`, `rejected_count`)
into the file the CLI wrote.

**Rationale.** Q3, and Principle VI: a record only the UI produces is the engine's state living
in the face. The genre-file digest is the precedent — a render's identity, recorded beside the
render.

**The risk, named.** `_narrate_knobs_snapshot(cfg)` builds its dict from the **server's resolved
config**, and two of the sidecar's fields are not knobs at all but *run outcome* computed after
the subprocess exits. So this is not a move; it is a split. The CLI owns render identity
(`model`, `backend`, `prose_mode`, `gap_marking`, `narration_genre_file` + digest,
`gap_contract` + digest, token budget); the server owns outcome. `_read_knobs_sidecar` at
`scene_editor.py:2794` feeds the Review screen's `applied_knobs` and must keep reading one file
with a compatible shape.

This is the highest-risk part of the feature and the part most separable from it. If the split
proves invasive, the fallback is Q3's other branch for this release — but that is a ruling to go
back and ask for, not one to take silently.

**Alternatives considered.** Having both write, CLI first and server second — two writers of one
file, which is the Split-Brain the constitution names. Having the CLI write a second file
alongside — two records of one render, disagreeing eventually.

---

## Open risk, carried into tasks

`build_narrate_system` has nine positional-or-keyword parameters and a tenth is being added.
`_build_matrix` builds 2⁸ combinations of eight of them; adding `gap_marking` makes 512 and
doubles the golden. That is mechanical, but the matrix is also what
`test_apparatus_marker_pairing.py` walks to prove producers exist — so its cost is paid twice,
and both tests get slower. Acceptable: the alternative is a spot check, which is the shape of
the failure `#396` recorded.
