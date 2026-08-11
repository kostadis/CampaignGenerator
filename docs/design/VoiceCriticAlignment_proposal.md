# Voice-Critic Alignment with the Fable-Era Narration Pipeline

> **Status:** proposal. Written 2026-08-11 from a read of the `/voice-critic` skill
> against the narration pipeline as it stands after #245/#246/#247/#248/#251/#252.
> **Scope:** what the critic must read and count to be a real check on Pass 5 output,
> plus one code-side bug found while measuring.
> **Landed by:** [PR #277](https://github.com/kostadis/CampaignGenerator/pull/277).
> **Predecessor:** [`Issue245Followups_handoff.md`](Issue245Followups_handoff.md) — the six
> work orders that produced the pipeline reviewed here. This note is the successor: §5 is
> the OOTA half of that doc's WO-2, and F3/F4 are what its WO-5 left behind.
>
> **Division of labour with that doc, which this one overlaps:** it is the execution record
> (benchmark numbers, standing constraints, per-WO acceptance criteria, current status); this
> is the analysis (why the checker drifted from the thing it checks, and what it should read
> instead). The citation direction is fixed: **the benchmark numbers are owned there and
> cited here** — F5 and §6 do not re-derive them, and if the benchmark is re-run the
> correction goes there first. The five-copies survey (§1) and findings F1–F11 are owned
> here. New execution status belongs in that doc's status table, not in this note.
> **Tracked by:** CampaignGenerator #276 (genre flattening, §5) and
> [kostadis/mytools#125](https://github.com/kostadis/mytools/issues/125) (skill
> realignment, §3–§4 — the skill itself lives in `mytools/dotfiles/claude/skills/`).

## 1. The problem: one rulebook, five copies

The narration rules — banned tics, per-narrator bookkeeping registers, register-wrong
vocabulary, doc-level caps — now exist in five places that nothing keeps in agreement:

| # | Copy | Form | Who reads it |
|---|---|---|---|
| 1 | `config/agents/session_doc/narrate/base.md:42-64` | HARD BANS, stated as *moves* | the narrator model |
| 2 | `<campaign>/voice/_genre.md` | prose spec, incl. per-POV caps and doc-level counting rules | humans, `/fable-narration` |
| 3 | `narrate.genre` in `<config>/session_doc.yaml` | **pasted copy of (2)** | the narrator model |
| 4 | `session_doc/voice_lint.py:31-55` | regexes + licensed-filer constants | `voice_lint` CLI, tests |
| 5 | `~/.claude/skills/voice-critic/SKILL.md:65-101` | hand-written scans + word list | the critic |

(1)–(3) reach the model. (4) and (5) are the check. The check is a hand-copied subset
of the instruction, so it drifts in both directions: the critic flags things the prompt
no longer says, and misses rules that live only in (2).

The design principle this violates is the repo's own: *the human decides the rules, the
LLM renders inside them.* A critic that carries its own private copy of the rules is not
verifying the pipeline — it is verifying a fork of the pipeline's intent.

## 2. Current state, measured

Measured 2026-08-11 on the live campaign trees.

**What the narrator receives** (`session_doc/narrate.py:31-114`): the genre block from
`narrate.genre` (delimited when multi-line, else a one-line `GENRE:` label), `base.md`
with HARD BANS, scene scope + anti-restatement length directive, `prose_mode`,
per-character examples, the resolved voice spec, and the genre repeated at the tail.

**What the critic reads** (`SKILL.md:19-30`): voice spec, per-character examples,
`docs/party.md`. Not the genre document. Not `base.md`.

**Voice-spec resolution:**

| Campaign | `voice/` filenames | Critic's patterns (`<key>_voice.md`, `<key>.md`) |
|---|---|---|
| out-of-the-abyss | `daz_voice.md`, `grygum_voice.md`, `thorin_voice.md`, `zalthir_voice.md` | match |
| Phandalin | `brewbarry_new_pipeline.md`, `soma_new_pipeline.md`, `valphine_new_pipeline.md`, `vukradin_new_pipeline.md` | **no match — all four** |

`session_doc/voice.py:32-63` (`_resolve_voice_key`, the #247 fix) resolves the Phandalin
names for the *pipeline*. The critic still carries the pre-#247 rule, so on the
fable-era campaign it reports every spec as missing and degrades to examples-only.

**Genre delivery:**

| Campaign | `narrate.genre` | newlines | `voice/_genre.md` | delivered as |
|---|---|---|---|---|
| Phandalin | 7,351 chars | 60 | 7,352 chars / 61 lines, similarity 1.000 | delimited `GENRE & REGISTER` block |
| out-of-the-abyss | 16,303 chars | **0** | 16,340 chars / 88 lines, similarity 0.999 | **one-line `GENRE:` label, twice** |

## 3. Findings

Severity: **B** breaks today, **G** gap under fable, **C** correctness/consistency.

| ID | Sev | Finding |
|---|---|---|
| F1 | B | Critic's voice-spec lookup is pre-#247 (`SKILL.md:27`, `:57`); all four Phandalin specs read as missing, so spec-conflict flags can never fire and every suggestion is marked `[no spec available — best guess]`. |
| F2 | B | Critic never reads `narrate.genre` or `base.md`, so it cannot check rules that live only there, and its own scan lists rot silently. |
| F3 | C | `voice_lint` exists as a console script (`pyproject.toml:86`) and its `TAXONOMY_RE` (`voice_lint.py:43-48`) is character-for-character the regex `SKILL.md:78` retypes. Two copies of one regex diverge at the next tic. |
| F4 | B | `voice_lint`'s filing rules are OOTA-hardcoded (`UNLICENSED_FILERS = ("thorin","zalthir")`, licensed grygum/daz). On Phandalin every filing check except the >2-sections convergence rule is inert — and the one cross-model reflex on record (`filed … away`) is from **fable Vukradin 03**, a Phandalin scene. |
| F5 | G | Scan-C calibration is 100% opus (`SKILL.md:87-89`). Against the #245 benchmark — fable ≈1.1 flags/1000w vs opus ≈2.4 on matched ~7,890-word corpora, *as recorded in [`Issue245Followups_handoff.md`](Issue245Followups_handoff.md) §"Already done"; not re-measured here* — the scans mostly return zero under fable, leaving `SKILL.md:67`'s "floor, not a ceiling" doing all the work. Fable's recurring profile is already enumerated in the `fable-narration` skill: em-dash overuse, bookkeeping-noun caps, cross-narrator register bleed, portable tics. |
| F6 | G | The fable-era rules are **doc-level budgets** — `_genre.md`'s "more than one 'the shape of X' across the entire doc means the pass failed" and "more than two of four sections containing 'filed' is the convergence bug"; `fable-narration`'s "at most one *filed it* in the whole doc", "1–2 load-bearing narration em-dashes in the whole doc". A per-scene critique cannot evaluate any of them, and the summary (`SKILL.md:119`) counts flags rather than checking budgets. |
| F7 | G | `/fable-narration` emits one assembled `session-summary-fable-doc.md` (`## <Char> — <Scene>`, no frontmatter, no `narration/` dir) and names `/voice-critic` as its verification step, but the report path `SKILL.md:116` needs a scene number and a narration directory that input does not have. |
| F8 | C | #246's table-speech hatch writes `<!-- table-speech reclassified: … -->` into per-scene files; `assemble.py:31-42` strips it at assembly, so **the per-scene files the critic reads are exactly where it survives**. The skill says nothing: it neither excludes the comment from prose flags nor surfaces it. Each one is the model making a scope call about what is in-fiction — a human checkpoint by this repo's doctrine. |
| F9 | C | `SKILL.md:146` ("2–8 total flags") contradicts `:109` ("flag every genuine issue"). At fable's rate a 600–900-word scene often deserves 0–1; a floor of two invites invention. |
| F10 | C | `SKILL.md:13` still describes the prompt as Phase 1/2/3 (examples, hoisted spec, contrast). It is now also HARD BANS, the genre block, scene scoping, and the anti-restatement directive. |
| F11 | — | **Correct as written, do not "fix":** the report filename never collides with `assemble --pattern`'s default `session_doc_scene_*.md` (`assemble.py:110`), and the `.scrubbed.md` preference (`SKILL.md:25`, `:51`) still mirrors `collect_scene_files` (`assemble.py:64-77`). |

## 4. Proposed design

### D1 — Resolution parity with the pipeline (fixes F1)

The critic resolves a narrator to a voice file using the same three steps as
`voice.py:_resolve_voice_key`: exact full-name key, then first-name key, then the
*unique* key continuing with `_` or `-`; skip `_`-prefixed files; **refuse to guess**
when two candidates match, and say so in the report. Same rule for `examples/`.

A resolution table goes at the top of every report — narrator → file used, or the miss
reason. A silently missing spec is what let this survive.

### D2 — The critic reads the effective rulebook (fixes F2)

Inputs gain, in precedence order:

1. `narrate.genre` from `<config>/session_doc.yaml` — the **effective** genre text the
   model actually received. Not `voice/_genre.md`; they are separate copies (§2).
2. `config/agents/session_doc/narrate/base.md` — the HARD BANS list.

The report states which it read and their sizes. When `narrate.genre` is absent, say so
and fall back to `voice/_genre.md` **with a warning that the model may not have seen it**.

### D3 — Delegate the mechanical layer to `voice_lint` (fixes F3)

The skill runs `voice_lint <files>` and folds its ERROR/warn lines into the flag list
verbatim, keeping only the scans `voice_lint` has no equivalent for (em-dash scan A,
register-vocabulary scan B). The retyped regex at `SKILL.md:78` is deleted; the evidence
narrative that justifies the pattern stays, pointing at `voice_lint.py`.

**Companion code change (F4):** `voice_lint`'s licensed/unlicensed filer sets move out of
module constants into the campaign's own rulebook, so the check works for Phandalin and
any future campaign. Cheapest correct source is the genre document the caps are already
written in — parse them from `narrate.genre`, or add an explicit `narrate.bookkeeping:`
block. Until then the skill must state that filing checks are OOTA-only, rather than
reporting a clean run.

### D4 — A budget ledger, not a flag count (fixes F6)

The directory/summary report carries a table of every doc-level cap with
`observed / budget / verdict`: `the shape of` ≤1 doc-wide, portable-portrait ≤1,
taxonomy 0, `I file*` in ≤2 sections, per-narrator bookkeeping caps, narration em-dashes
≤2 doc-wide. A budget breach is a finding in its own right even when no individual
sentence reads badly — that is the whole point of a cap.

### D5 — An explicit assembled-doc mode (fixes F7)

Two input shapes, declared in the report:

- **per-scene** — `session_doc_scene_NN_*.{scrubbed.,}md`, frontmatter narrator, one
  report per scene into the narration dir (today's behaviour).
- **assembled** — one doc split on `## <Char> — <Scene>` (`session-summary-doc.md`,
  `session-summary-fable-doc.md`). One report beside the input,
  `<doc-stem>.voice_critique.md`, sections keyed by heading rather than scene number.
  This is the shape `voice_lint` already assumes and the shape `/fable-narration` emits.

The budget ledger of D4 is mandatory in assembled mode and computed across the whole doc.

### D6 — Table-speech spans are a review queue (fixes F8)

Never flag prose inside `<!-- table-speech reclassified: … -->`, and list every
occurrence in a **Reclassified table speech** section of the report with the quoted
before/after, for the GM to accept or reject. The model decided a span was
out-of-fiction; that is a scope decision and it gets a human.

### D7 — No flag floor (fixes F9)

Delete the "2–8" range. Report every real finding and zero when there are none; a clean
scene is a legitimate result and a valuable one under fable.

### D8 — Refresh the framing (fixes F10, F5)

Rewrite `SKILL.md:13` to describe the current prompt, and name fable's four recurring
failure modes as first-class flag categories, marked as the model-default profile rather
than opus-era anecdote.

## 5. Code-side: the genre document arrives flattened (#276)

`narrate.py:35-48` chooses the genre's delivery form by `if "\n" in g`. OOTA's
`narrate.genre` is 16,303 characters with **zero** newlines — a paste of the 88-line
`voice/_genre.md` whose line structure was lost on the way into YAML. So the campaign
with the largest genre spec gets it as `GENRE: <16K on one line>`, twice (opening plus
the tail reminder at `narrate.py:105-113`), instead of the delimited
`GENRE & REGISTER — BEGIN/END` block #246 added for exactly this case. Silent: no
warning, no test, and the prompt golden covers the multi-line path only.

Two fixes, in order of increasing correctness:

1. **Gate on size, not newlines.** Anything past a short-directive threshold gets the
   delimited block. One line, removes the failure mode.
2. **Stop keeping a copy.** `narrate.genre` being a pasted duplicate of
   `voice/_genre.md` is a two-source-of-truth split: editing the file does not propagate,
   and the two drift silently (OOTA is already at 0.999). Replace it with a
   `narrate.genre_file:` path resolved at load time, migrate the existing pastes, and
   delete the `genre:` key — per this repo's single-user, migrate-and-delete convention.
   The check that (2) is done: editing `voice/_genre.md` changes the next render.

(2) is the real fix; (1) is worth shipping first because it is one line and the flattened
case is live today.

## 6. Non-goals

- Auto-applying critique fixes. The report stays a review artifact.
- Re-running the #245 benchmark. Its numbers are cited from
  [`Issue245Followups_handoff.md`](Issue245Followups_handoff.md), not re-derived here; the
  renders behind them are gitignored (`scratch_output/bench_245/`), so that doc plus the #245
  comment are the durable record.
- Changing `base.md`'s bans or the genre specs' content. This is about which copy is
  authoritative and who reads it, not what the rules say.
- Merging `/voice-critic` and `/fable-narration`. They are generate-then-verify and
  verify-only respectively; D5 is what lets one check the other.

## 7. Verification

- **F1:** run the critic on a Phandalin scene; every narrator resolves to its
  `*_new_pipeline.md` spec and the resolution table shows it. Run on OOTA; `*_voice.md`
  still resolves. Add a two-candidate fixture and confirm it refuses rather than guesses.
- **F2:** the report names `session_doc.yaml`'s `narrate.genre` and `base.md` with sizes.
- **F3:** the skill's output includes `voice_lint`'s lines; `grep -c 'the way' SKILL.md`
  finds no regex copy.
- **F6/D4:** on a doc that breaches a cap without any single bad sentence, the ledger
  reports the breach.
- **F8:** on a per-scene file containing a hatch comment, prose inside it is unflagged
  and it appears in the reclassified section.
- **#276:** OOTA renders with the delimited block; a test asserts a newline-free genre
  over the threshold still gets it.

## 8. Open questions

1. Where do the per-narrator bookkeeping caps live once they leave `voice_lint.py`'s
   constants — parsed from the genre document, or an explicit `narrate.bookkeeping:`
   block? Parsing prose for caps is exactly the kind of extraction this repo does not
   trust; an explicit block is more honest but is a fourth place to keep in sync unless
   the genre doc stops being a copy (§5, fix 2).
2. Does the assembled-doc mode replace per-scene critique once `/fable-narration` is the
   default path, or do both stay? Per-scene is the only mode that can gate a re-render of
   one scene.
