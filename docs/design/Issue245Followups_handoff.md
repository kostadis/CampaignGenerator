# Issue #245 Follow-ups — Execution Handoff

**Date:** 2026-08-10, status re-verified 2026-08-11. **Audience:** an Opus orchestrator
session executing the open issues that came out of the #245 narration work, with Sonnet
implementers per work order and the GM as the merge gate. Everything here was verified in
the originating session; extend this doc rather than re-deriving.

## Status as of 2026-08-11 — read this before picking up a work order

Five of the six work orders have landed. Verified on `main` and against the live campaign
trees, not inferred from issue state:

| WO | Issue | State | Evidence |
|---|---|---|---|
| WO-1 | CG#247 | **done** | `session_doc/voice.py:32-63` — `_resolve_voice_key`, three-step resolution, ambiguity refused, stderr warning on a non-empty miss |
| WO-2 | campaigns#147 | **done (Phandalin only)** | `narrate.genre` **and** `profiles[0].knobs.narration_genre` both 7,351c / 60 newlines / contains "present tense"; matches `voice/_genre.md` at similarity 1.000. **OOTA is still flattened** — see below |
| WO-3 | CG#249 | **landed, issue still open** | `KnobDrawer.vue:266-273` is a `rows="8"` textarea with the specified help text. Verify a paste round-trip and close #249 |
| WO-4 | CG#248 | **parser done** | `a9a3951`. campaigns#142/#145 (the data gates) closed; **campaigns#141 / #143 / #144 still open** — the parser now handles those layouts, so these likely need verification and closing rather than work |
| WO-5 | CG#251 | **done** | `8d55c0d` in `base.md`, plus `session_doc/voice_lint.py` — the scan became a tested console script rather than living only in the skill |
| WO-6 | CG#250 | **shipped past design** | R1–R6 built; see `ExtractionContract_proposal.md` (the why) and `ExtractionContract_implementation.md` (what shipped) |

**The capstone verification below has not been run.** WO-1 and WO-2 are both merged, so
its precondition is met and it is the highest-value remaining item in this doc: it would
be the first ch46 render with the full intended prompt stack, and item 2 (Vukradin's
sardonic-operator beats) is a live open question either way it resolves.

**What this doc's WO-2 turned out to be a symptom of:** a hand re-sync fixes one campaign
and nothing stops the next paste from re-flattening, because `narrate.genre` is a *copy*
of `voice/_genre.md`. OOTA is now the same bug this doc fixed for Phandalin — 16,303
chars, zero newlines, in both `narrate.genre` and the profile knob — so `narrate.py:37`
hands the model a 16K one-line `GENRE:` label, twice. Tracked as **#276**, with the
durable fix (gate on size, then replace the pasted key with `narrate.genre_file:`) and
the measurements in
[`VoiceCriticAlignment_proposal.md`](VoiceCriticAlignment_proposal.md) §5. Read that
before doing another manual re-sync.

## Already done — do not redo

- **CG#246** (merged): GM-table-speech escape hatch (content-based, self-flag audit
  comment, `assemble.py` strips), HARD BANS tic-family block in `base.md`, multi-line
  genre block in `narrate.py`, anti-restatement length directive, dual-format roster
  parser (legacy + Phandalin) with species + empty-roster stderr warning, `_`-skip in
  voice/examples loaders, `cache_system=True`, golden regenerated at tip.
- **campaigns#140** (merged): 4 Phandalin voice specs scope-noted (constraints 1–8 bind
  in-fiction speech only), "ever the X" removed, `soma.md` Ch08/11 deleted.
- **The Opus-5 vs Fable-5 benchmark** (posted on #245, issuecomment-5232809273): fable
  ≈1.1 vs opus ≈2.4 flags/1000 words on matched ~7,890-word corpora. Renders + 12
  per-scene voice-critique reports + 2 summaries: `scratch_output/bench_245/` (gitignored).
- **CG#252** (merged): `DEFAULT_MODEL = claude-fable-5` (GM decision from the benchmark).
- **campaigns#148** (merged, closed #146): `voice/_genre.md` tense rule past → present.
  The GM wanted present all along; "past tense, always" was a drafting assumption from
  the file's creation (`a6a389dd`), later hardened (`349eb636`), never a GM choice.

## Standing constraints (bind every work order)

1. **Never commit to main.** Feature branch + PR per work order; the GM merges. Both
   repos (`CampaignGenerator`, `campaigns`).
2. **Any live model call uses the `claude-code` SUBSCRIPTION backend, never the API**
   (GM ruling from #245). Expect fable's always-on-thinking wall-clock tax.
3. **LLM renders, humans decide.** Scope/ordering/attribution are precision decisions —
   see the GM-decision gates below; do not resolve them by picking a "reasonable default."
   An unanswered question is not a decision: re-ask and wait.
4. All API calls via `campaignlib` (`stream_api`/`call_api`); never import `anthropic`
   in scripts; no retry logic in scripts.
5. **Worktree traps** (if using a worktree): the editable-install `.pth` hardcodes the
   main checkout — `cd <worktree>` before every run, `env -u PYTHONPATH ~/.venvs/main/bin/python -m pytest -q`,
   clear `__pycache__` before trusting results, and assert `session_doc.__file__` resolves
   inside the worktree. `tests/` has no `__init__.py`; never cross-import test fixtures.
6. **Golden prompts:** any change to `config/agents/session_doc/narrate/*.md` or
   `session_doc/narrate.py` prompt text trips `tests/test_session_doc_prompts.py`.
   Regenerate ONCE at the branch tip with `UPDATE_PROMPT_GOLDEN=1`, eyeball the diff,
   and state the changed/total entry counts in the PR.
7. **campaigns repo working tree carries unrelated uncommitted modifications**
   (including `Phandalin/config/session_doc.yaml`). Never `git add -A`; name every path;
   see the WO-2 gate before touching `session_doc.yaml` at all.
8. Full suite baseline: 3 known environment failures (`test_gate2_rpg_retrieval`,
   `test_cli_parallel_fully_cached`, mempalace fresh-palace fallback) — pre-existing on
   main, not yours.

## Work orders (in execution order)

### WO-1 — CG#247: deliver the voice specs (do this first; everything downstream benefits)

**Bug:** `session_doc/voice.py` — `load_voice_files` keys `brewbarry_new_pipeline.md` as
`brewbarry_new_pipeline` (only `_voice` is stripped); `get_voice_note` looks up
`brewbarry`. All four Phandalin narrators resolve to `None`; the VOICE SPEC block has
been absent from every render since 2026-05-17. Both entry paths affected (CLI
`sd_narrate.py:211/304`; UI `server/routers/scene_editor.py:892`).

**Change spec:**
- Lookup resolves, in order: exact full-name key → first-name key → unique key whose
  name starts with `firstname` + separator (`_` or `-`). If the prefix match is
  ambiguous (two candidate keys), resolve to none and warn — never guess.
- stderr warning when the voice dir yielded a non-empty dict but a narrator resolves to
  no voice file; include the narrator and the available keys (mirror the #246
  empty-roster warning's tone).
- `_`-prefix skip and `v1/` non-recursion stay as-is (loading `v1/` would resurrect the
  superseded specs — do not "fix" that).

**Acceptance:** regression tests using the real filename shapes — `brewbarry_new_pipeline.md`,
legacy `brewbarry_voice.md`, bare `brewbarry.md`, an ambiguity case, a `_genre.md` skip
case; live one-liner against `~/src/campaigns/Phandalin/voice` shows all four narrators
FOUND; warning fires on a synthetic miss. Prompt text is unchanged → golden untouched.

### WO-2 — campaigns#147: re-sync Phandalin's flattened genre config

`Phandalin/config/session_doc.yaml` holds `narrate.genre` (and
`profiles[].knobs.narration_genre`) as the OLD past-tense genre doc with all newlines
collapsed to one 7,063-char line. Until re-synced, UI renders get past tense and a run-on
`GENRE:` label regardless of #148 and #246.

**Change spec:** replace both values with the current `voice/_genre.md` content, real
newlines, via YAML edit (or `PUT /api/editor/config`). Verify: value linecount ≈ the
source file's, contains "present tense", YAML round-trips.

**⚠ GATE (do not skip):** `session_doc.yaml` already carries unrelated uncommitted local
modifications in the GM's tree. Diff the file, show the GM what is pre-existing vs what
the re-sync changes, and get explicit approval before committing — committing the path
naively would sweep in their unpushed state.

**Done for Phandalin (campaigns#147 closed); do not re-run it as written.** Both values
are re-synced and carry real newlines. But the *shape* of this work order is the problem:
it repairs one copy of a duplicated document by hand, and WO-3 only narrows the window in
which the UI re-flattens it — it does not close it, because the YAML value is still a
paste. **out-of-the-abyss is now in exactly the pre-repair state this WO describes**
(16,303 chars, zero newlines, both `narrate.genre` and `profiles[0].knobs.narration_genre`).
Do not hand-fix it: **#276** carries the one-line code fix (gate the delimited block on
size, not on `"\n" in g`) and the real one (`narrate.genre_file:` resolved at load time,
migrate the pastes, delete the key), with the measurements in
[`VoiceCriticAlignment_proposal.md`](VoiceCriticAlignment_proposal.md) §5.

### WO-3 — CG#249: genre knob input → textarea

`frontend/src/components/scene-editor/KnobDrawer.vue:266-273`. Change the genre field to
a `<textarea>` (sensible rows, monospace optional), update the help text ("a directive or
a full multi-line genre document"), keep the knob's persistence path unchanged.
**Acceptance:** pasting a 61-line document preserves newlines through save → reload →
`.knobs.json`; `npm run build` clean; no other knob widened (scope is genre only).
This makes WO-2's repair durable — without it the next UI paste re-flattens.

### WO-4 — CG#248 + campaigns#141–145: roster coverage for the other five campaigns

Parser work (CG#248, extend `session_doc/roster.py`, keep the #246 guards — first bold
line after a character heading only, no cross-section bleed):

| Campaign | Layout (verbatim shape) | Notes |
|---|---|---|
| Hillsfar | `### Name` + `**High Elf Ranger 11** — player: kostadis1` | species+class fused in one bold; em-dash player suffix |
| out-of-the-abyss | `### Zalthir — Monk 8 (Warrior of Shadow) · Bronze Dragonborn · Player: Gabe` | all in the heading, `·`-separated; tolerate extra `· Faith: …` |
| stormgiants | `**Class/Level:** Cleric 13 (Light Domain) \| **Species:** Wood Elf \| **Player:** Wade Brown` | tolerate extra `\| **Alignment:** …` (Unla Key); verify Thistle's entry matches before coding |
| obelisk (PC) / toee | same labeled pipe form | see data gates below |

Fixture tests use verbatim lines from each campaign's real `docs/party.md` (the
`tests/test_roster.py` Phandalin fixture is the pattern — including its local-fixture-copy
rule). Output format stays `- Name (Player): Species Class N (Subclass)`; emit what the
source has, never infer a missing field.

**⚠ GATES — campaign-side data fixes that are GM decisions, not parser work:**
- **campaigns#142 (obelisk):** the three sidekick lines (`**Tiefling mage sidekick, Level 2**`)
  are not machine-readable. Propose labeled replacements; the GM decides the `Player:`
  value for sidekicks and resolves the "(level-up to 3 pending)" annotations.
- **campaigns#145 (toee):** missing levels (Zephyr/Zinnia/Sequoia), species duplicated
  into `Class/Level`, slash-list player names (`Kostadis/Kostadis Roussos/kostadis1`).
  Propose the cleaned block; the GM picks canonical player names and supplies levels.
- If any of these `party.md` files is pipeline-generated, the fix belongs in the
  generator run, not a hand edit — check provenance (`provenance search`) before editing.

### WO-5 — CG#251: close the tic-family rotation hole

The #246 ban stopped the listed wordings; the benchmark caught the *move* surviving as
"the way X do when…" rotations (3 confirmed instances, all invisible to every scan).

**Change spec:**
- `config/agents/session_doc/narrate/base.md` HARD BANS: add the rotated shells
  ("the way X do(es)/say(s) … when …", "in the way X say it when…", "the way they say
  things at that age") and one sentence restating the test: any phrasing that generalizes
  an observed behavior to a class of people is the banned move, whatever the wording.
- `~/.claude/skills/voice-critic/SKILL.md` (user-local file, edit in place): extend
  scan C with the `\b(in )?the way (he|she|they|men|women|people|\w+)\s+(do|does|say|says|said|get|gets)\b.{0,40}\bwhen\b`
  family; add `filed (it|that) away` to scan B (three occurrences across both benchmark
  arms). Keep the "scans are a floor" caveat.
- Golden regen per standing constraint 6.

**Acceptance:** the three benchmark instances (quoted in CG#251) match the new regex;
golden diff reviewed; no other prompt text touched.

**Done (#251 closed), and it went further than the WO asked.** The scan did not stay in
the skill: it is now `session_doc/voice_lint.py` (`TAXONOMY_RE`, plus the `filed`
convergence checks), a tested console script that exits 1 for gating. Two consequences the
next session should know — the skill's copy of that regex is now a *duplicate* of the
linter's, and `voice_lint`'s licensed/unlicensed filer sets are OOTA-hardcoded, so the
filing checks are inert on Phandalin. Both are findings F3/F4 in
[`VoiceCriticAlignment_proposal.md`](VoiceCriticAlignment_proposal.md), tracked as
[kostadis/mytools#125](https://github.com/kostadis/mytools/issues/125) — which also carries
the larger problem this WO's "edit the skill in place" instruction created: the skill is a
*deployed copy*, and edits to `~/.claude/skills/` do not reach the tracked source in
`mytools/dotfiles/claude/skills/` (mytools#120).

### WO-6 — CG#250: extraction contract (design first — do NOT implement before GM sign-off)

Three defects in `scene_extractions_smoothed/` output: (a) the same span in two
conflicting copies (scene-02 Toblen line: beats re-attribution with the "Vucherdin"
garble vs raw laundered Verbatim-moments span — each benchmark model trusted a different
one); (b) beats duplicated across adjacent scene files (1,675-gold in 05 and 06; the
road-trip beat across 04/05); (c) editorial brackets (`[the good stuff on]`, `[blurb]`)
reaching the renderer with no policy (fable preserves, opus deletes — neither should be
the one deciding).

**Deliverable for this WO:** a one-page design in `docs/design/` proposing the contract
(single authoritative copy per span with explicit linkage; overlap handling at scene
boundaries; bracket policy), with the three GM decision points called out. Implementation
in the scene_extract/smoothing pipeline only after the GM approves. These are
attribution/scope decisions — the exact class the Pipeline Design Rule reserves for the
human checkpoint.

## Capstone verification (after WO-1 + WO-2 merge)

Re-render ch46 scenes 02 + 03 (`claude-fable-5`, subscription backend, same knobs as the
benchmark — command template at the top of `scratch_output/bench_245/bench_fable/run.log`).
This is the first render ever with the full intended prompt stack (voice specs delivered,
present tense, multi-line genre block). Check, against the `bench_245` baselines:

1. VOICE SPEC block present (WO-1's live one-liner is the precondition; the render is the proof).
2. Scene 03 Vukradin: the sardonic-operator beats ("put the knife", "felt like
   confirmation") should soften toward the spec's sincere register — the benchmark's one
   shared failure, attributed to the missing spec. If it persists WITH the spec delivered,
   that is a new finding worth a #245 comment, not a silent shrug.
3. Present tense throughout; hatch still firing; `/voice-critic` re-score optional but
   cheap and gives a before/after on the same scenes with one variable changed.

## Reference artifacts

- Benchmark data + per-scene critiques: `scratch_output/bench_245/{bench_opus,bench_fable,render_opus_scene02}`
- The #245 comparison comment: https://github.com/kostadis/CampaignGenerator/issues/245#issuecomment-5232809273
- Issues: CG#247 #248 #249 #250 #251; campaigns#141 #142 #143 #144 #145 #147 (#146 closed by #148)
- Extraction ground truth for ch46: `~/src/campaigns/Phandalin/summaries/20260623/scene_extractions_smoothed/`
- **Successor design note:** [`VoiceCriticAlignment_proposal.md`](VoiceCriticAlignment_proposal.md)
  — written 2026-08-11 from a review of `/voice-critic` against the pipeline this doc's work
  orders produced. Cites this doc's benchmark numbers rather than re-deriving them, carries
  the OOTA half of WO-2 as **#276**, and the critic-side follow-ons as
  [kostadis/mytools#125](https://github.com/kostadis/mytools/issues/125). It also records what
  WO-1 changed for the *pipeline* but not for the checker: the critic still uses the pre-#247
  lookup, so it finds no voice spec at all on Phandalin.
