# A Persistent Wiki Layer Between Narration Critiques and the Rulebook

> **Status:** proposal. Written 2026-08-31 from a read of the narration pipeline as it
> stands after #276/#277, against [WikiSkill (arXiv:2608.27454v1)](https://arxiv.org/abs/2608.27454).
> **Scope:** the accumulation loop that turns per-session `/voice-critic` findings into
> durable rulebook edits. Not the rules themselves, and not the Pass 5 prompt.
> **Tracked by:** CampaignGenerator #358. The skill-side half lives in
> `mytools/dotfiles/claude/skills/` and wants a companion `kostadis/mytools` issue,
> mirroring the #276 / mytools#125 split.
> **Predecessor:** [`VoiceCriticAlignment_proposal.md`](VoiceCriticAlignment_proposal.md) —
> its §1 ("one rulebook, five copies") is the precondition this note builds on, and its
> D4 budget ledger is reused verbatim as a `measure` output.
> **Constrains and is constrained by:** #340, whose finding that surface-form bans do not
> stop the behaviour is both the argument for this change and the limit on its naive form (§4).
>
> **Division of labour with the predecessor:** that note is about *which copy of the rules
> is authoritative and who reads it*. This one is about *how a new rule gets into the
> authoritative copy in the first place*. It assumes the single-rulebook state that #276
> fix 2 established and does not re-litigate it.
> Paper stored locally at `~/src/wikiskill/wikiskill-arxiv-2608.27454v1.md`.

## 1. The problem: findings do not survive their session

`/voice-critic` writes real reports — **110 across the campaign trees**. Exactly one
consumer reads them, `fable-narration/SKILL.md:30`, and only within the same
`<session-dir>`. No pipeline code reads them at all:

```
$ grep -rn voice_critique session_doc/ server/
$                                     # zero hits
```

The accumulator that *should* close the loop already exists and already works:
`<campaign>/voice/_genre.md`, which reaches the narrator twice per scene — the opening
genre block and the tail reminder (`narrate.py:182-274`). OOTA's is a genuine post-mortem
document: `### Banned tics / anti-patterns` with verbatim offending examples, per-narrator
bookkeeping caps, and doc-level budgets ("more than two of four sections containing
'filed' is the convergence bug").

It works. It just does not get fed. `git log --follow voice/_genre.md` shows **two commits
ever** — corrections land in occasional large manual batches, when the GM re-reads a stack
of critiques and rewrites the rulebook by hand.

### 1.1 Measured state

| Observation | How verified |
|---|---|
| 110 `voice_critique*` files; 1 same-session consumer | `find` across trees; `grep -rn voice_critique ~/.claude/skills` |
| No pipeline code reads them | `grep -rn voice_critique session_doc/ server/` → 0 |
| OOTA rulebook edited in 2 batches, never incrementally | `git log --follow voice/_genre.md` |
| `docs/session_review_template.md` has **zero instances**; no `docs/session_reviews/` exists | `find` across all campaign trees |
| Phandalin rulebook: 61 lines, no banned-tics section, **no `voice_lint` block** | `grep -c '```yaml voice_lint'` → 0 |
| OOTA rulebook: 105 lines, has the block, mtime 2026-08-27 | same |
| toee: `genre_file: null` — no rulebook reaches the model at all | `config/session_doc.yaml`; cf. #295 |

The live trees are the single-campaign checkouts — `~/Phandalin/Phandalin/`,
`~/out-of-the-abyss/out-of-the-abyss/`, `~/toee/toee/`, all on `main`, all committed
2026-08-29/30. `~/campaigns/` is six weeks stale (OOTA rulebook there is the 88-line
pre-`voice_lint` version, mtime 2026-06-03) and must not be written to.

### 1.2 The dead precedent

`docs/session_review_template.md` — Wins / Misses / Surprises / Canon Integrity Check /
Process Updates / Next Session Top 3, with a "Running Archive" footer — is exactly this
idea, designed for exactly this job. It has **zero instances**. There is no
`docs/session_reviews/` directory in any campaign.

A blank form does not get filled in. Whatever replaces it has to be *driven* — a skill
invoked as part of the post-session routine, not a schema the GM maintains.

### 1.3 Three forks of the caps table

`fable-narration/SKILL.md:50-62` carries a copy of OOTA's per-narrator caps —
Thorin / Grygum / Daz / Zalthir. The skill takes a `[session-dir]` with **no campaign
switch**, so running it on Phandalin (Vukradin / Soma / Valphine / Brewbarry) delivers
caps for four characters who do not exist in that campaign.

Its em-dash prohibition exists *only* in the fork. `Phandalin/voice/_genre.md:39` states
the permission — "Italics for one-word thoughts; em-dash for interrupted speech or
thought" — and never the ban. `voice-critic/SKILL.md` asserts Phandalin's rulebook bans
the connective use; it does not.

`campaign-chapter-review/references/review_checklist.md` holds a third copy.

`voice-critic/SKILL.md:15` forbids precisely this: *"read the rules from where the model
read them… Never retype a rule into this file. A second copy diverges at the next tic."*
Two skills sit on opposite sides of one rule.

## 2. Why now: the precondition landed

The predecessor note's §1 tabulated five divergent copies of the rulebook and concluded
*"the check is a hand-copied subset of the instruction, so it drifts in both directions."*
Both blockers have since been fixed:

- **#276 fix 2.** `narrate.genre`'s pasted duplicate is gone. Phandalin and OOTA
  `config/session_doc.yaml` now carry `paths.genre_file: voice/_genre.md`, resolved by
  `_load_genre_file()` (`sd_narrate.py:82`). Editing the file changes the next render.
- **F4.** `voice_lint`'s OOTA-hardcoded `UNLICENSED_FILERS` moved out of module constants
  into the fenced ` ```yaml voice_lint ` block inside the rulebook, with exit code 1 so it
  can gate a pipeline, and every skip carrying its own reason rather than reporting clean.

There is now exactly one rulebook per campaign, the renderer reads it, and a deterministic
checker reads it. **The only thing still missing is the loop that puts new rules into it.**

## 3. What the paper prescribes, and what already exists

| WikiSkill layer | Here | Build? |
|---|---|---|
| **Raw** — immutable execution traces | `narration/voice_critique_*.md`, `scrub_manifest_*.md`, `*.sources.yaml`, `.knobs.json`, the narration itself | **have it** — already immutable, already per-session |
| **Skill** — what the executor reads | `voice/_genre.md` + its `voice_lint` block, `voice/<char>_voice.md`, `examples/<char>.md` | **have it** — this is what gets evolved |
| **Wiki** — persistent knowledge | *nothing* | **the entire gap** |
| Inference Agent | `session_doc/sd_narrate.py` | **unchanged** (§3.2) |
| Wiki Maintainer | — | new (skill) |
| Skill Proposer | — | new (skill) |
| Gating + `skill-impact.md` | — | new (script, deterministic) |

### 3.1 The asymmetry that makes it work

Skill edits roll back on rejection; **the wiki never rolls back** (paper §3.2.4). A
rejected proposal leaves its evidence *and its rejection* behind, so the next iteration
does not re-propose it.

This is the mechanism. Without it the loop is amnesiac and rediscovers the same rejected
idea forever — which is a fair description of what re-reading a stack of critiques by hand
already feels like.

### 3.2 Hard constraint: the renderer must not read the wiki

The paper's ablation (§5.1) found that giving the *inference agent* wiki access **degraded**
final quality, 63.7% → 60.9%, with the largest drop on the hardest benchmark. Their reading:
the executor solves from the wiki instead of from the skill, so the traces stop being
informative about whether the skill works.

Translated: **`sd_narrate.py` must never load the wiki.** The wiki feeds the proposer only;
the renderer sees only the evolved rulebook and voice files. This rules out the most
tempting integration and is why no narration-path code changes here.

### 3.3 Calibration

Table 4 and §D.2 give the expected shape: 3–5 proposals per iteration, 1–1.8 accepted —
most proposals *should* be rejected. Wiki pattern pages run 18–48 lines; the skills they
feed stay 45–142 lines. The wiki grows; the rulebook stays short. Cost is 1 maintainer call
plus 10–20 ReAct turns per iteration, independent of corpus size.

## 4. The constraint #340 imposes

**#340 is the strongest argument for this change and the sharpest warning about its naive
form.** Its finding: the banned surface forms are effectively dead — 0 instances of
`the shape of X`, 0 em-dash connectives in Set A — while the behaviour they were written
to stop survived in *both* model families in different clothing. Set B was produced by a
model that never read the Claude-specific tic list and converged on the same structural
defect independently. Its conclusion: *"the fix being structural rather than a longer ban
list."*

A wiki that accumulates surface forms would be a longer ban list with better filing.

The value exists only if pattern pages encode the **move** and its root cause. That is not
a hopeful gloss — it is what the paper's own Wiki Maintainer contract requires (§E.2):
*"Identify ACTION PATTERNS and strategies, not just error messages"*, and every page must
carry *"Root cause analysis (WHY it happens, not just WHAT happens)"*. A page whose body is
a quoted string and nothing else fails the contract and should be rejected at GATE 1.

#340's three directions land as:

1. **"Detect, don't prohibit"** → the `measure` verb (§6). Cross-narrator n-gram reuse —
   any 3+ gram appearing in ≥2 narrators' prose in one session — becomes a first-class
   metric, catching all of #340's Set A evidence. Model-independent, cheap, deterministic.
2. **Narrator-exclusive context** → out of scope. It is a Pass 5 prompt change and §3.2
   keeps the renderer untouched.
3. **Score it in the A/B** → `measure` emits per-category rates, so composition differences
   are visible where an undifferentiated flag count called the ch48 comparison a tie
   (16.4 vs 15.1 flags per 1k prose words, sharply different composition).

## 5. The normalized-key problem

Every durable-state file in this ecosystem works because it has a key a later run can
subtract against:

| File | Key |
|---|---|
| `notes/.scrub_state.json` | exact match text |
| `docs/ensemble/.alias_decisions.json` | canonical name |
| `docs/.entity_triage_state.json` | `norm` |
| `docs/entity_registry.yaml` | canonical name |
| `notes/vtt_transcription_corrections.md` | surface form |

Voice findings have none — they are prose sentences with prose rationales. That is
plausibly why nobody built the store, and it is the one genuinely new problem here.

The paper's answer is its `index.md` entry format, which it calls the most important part
of the wiki (§E.2, "Index Description Quality (CRITICAL)"):

```
- [pattern-name](patterns/pattern-name.md): PROBLEM + ROOT CAUSE + FIX in one or two sentences.
```

A stable **slug** plus a one-line discriminative description — a key a *reader* subtracts
against, not a string matcher. Adopt it rather than inventing one.

The second bridge is already built: `voice_lint` reads its caps from the fenced block in
the rulebook and exits 1 on a hard ERROR. A pattern that *can* be mechanized promotes into
that block and becomes machine-checkable. One that cannot — register policy, anachronism
rulings, the class `scrub/SKILL.md` says the scanner can never hold — stays prose but keeps
its slug so the ledger can reference it.

## 6. Design

### 6.1 Layout

```
~/.claude/narration-wiki/              # global craft tier — portable prose lessons
  index.md
  patterns/em-dash-density.md
  patterns/portable-tic-shape-of-x.md
  patterns/cross-narrator-vocabulary-convergence.md    # seeded from #340

<campaign>/wiki/                       # per-campaign tier
  index.md
  skill-impact.md                      # DETERMINISTIC — harness writes this
  logs.md                              # chronological, maintainer appends
  patterns/<character-or-canon>.md
```

The campaign tier lives inside the campaign repo so it versions with the rulebook it feeds.
Two tiers because the paper's transfer result (§4.2.2) says general procedural knowledge
transfers while model-specific workarounds do not. Cross-campaign, OOTA's craft lessons are
the transferable half — so Phandalin starts from transfer, not from an empty wiki.

### 6.2 `narration_wiki.py` — the deterministic harness

New module in `session_doc/`, console script `narration_wiki`. It owns everything that must
not be a model decision.

| Verb | Does |
|---|---|
| `collect <session-dir>` | globs the raw layer, tolerating all three naming generations (`voice_critique_*.md` flat *and* `voice_critiques/` dir; `scene_extractions{,_new,_smoothed}/`; `gm-assist{,ant,-doc}.md`); emits a trace manifest |
| `measure <files> --genre-file F` | wraps `voice_lint` + the predecessor's D4 doc-level budgets + cross-narrator n-gram reuse (§4); emits `observed / budget / verdict` JSON |
| `ledger-append` | writes one `skill-impact.md` row — iteration, target file, unified diff, before/after `measure`, GM ruling. **Never called by a model** |
| `patch-apply` / `patch-revert` | applies or reverts one atomic edit; revert restores the rulebook and never touches the wiki |
| `index-check` | lints `index.md` for the PROBLEM+ROOT-CAUSE+FIX shape and duplicate slugs |

`measure` **imports** `session_doc/voice_lint.py`. It does not reimplement the regexes —
F3 in the predecessor note is that exact mistake, and this proposal must not repeat it.

**Traversal hazard.** `collect` globs, and `~/campaigns/` contains two symlinks that escape
the workspace — `mnt -> /mnt/` (7.5T, the whole host filesystem) and `wsl -> /mnt/wsl`.
They are git-ignored (`campaigns/.gitignore`), so the guard protects git and nothing else:
any pass that recurses with dereference enabled (`find -L`, a trailing-slash `du` glob,
symlink-following `grep -r`) will walk the host. `collect` must root itself at
`<campaign>/`, never at the workspace root, and pass `-P` / bound its depth.

If it needs a skip list, `.mempalaceignore` is the convention already in use — one per
campaign plus a shared `summaries/.mempalaceignore`, excluding `docs/chapters/`,
`docs/background/`, and the pipeline intermediate dirs.

### 6.3 The loop

One iteration per session, run after `/voice-critic`:

```
0. collect     harness globs the raw layer                    DETERMINISTIC
1. measure     before-state                                   DETERMINISTIC
2. Maintainer  traces + current wiki -> proposed patterns             LLM
   ├─ creates/updates pages, updates index, appends logs
   └─ GATE 1: GM confirms each pattern before it enters the wiki
3. Proposer    wiki index + skill-impact + traces on demand           LLM
   └─ ONE atomic edit to ONE file (rulebook / voice file / lint block)
      ReAct with read_file, ~10-20 turns
4. measure     after-state, same corpus                       DETERMINISTIC
5. GATE 2: GM sees diff + before/after ledger -> accept | reject
6. ledger-append + patch-apply-or-revert                      DETERMINISTIC
```

**The wiki persists through a rejection; the rulebook rolls back.**

What each model call removes from the human: **nothing.** The maintainer drafts pages the
GM confirms. The proposer drafts one edit the GM accepts or rejects. The ledger the next
iteration reasons over is written by the harness from the GM's ruling, not by a model
reporting on itself.

`measure` is **evidence, not the gate.** A budget breach argues for a proposal; it never
accepts one. Prose quality has no scalar and this design does not pretend otherwise — the
GM is `R()`.

### 6.4 Step 1 — kill the forks, seed the wiki

Prerequisite, and it makes iteration 1 start from transfer rather than zero.

- `fable-narration/SKILL.md:50-62` → split. Em-dash density, portable tics, register
  separation to the **global** wiki; the Thorin/Grygum/Daz/Zalthir table to the **OOTA**
  wiki and its existing `voice_lint` block. §4 of that skill becomes a pointer that
  resolves the rulebook from the session's campaign, ending the wrong-campaign bug.
- `campaign-chapter-review/references/review_checklist.md` narrator summaries → same.
- `voice-critic`'s Phandalin em-dash claim → either promote the ban into
  `Phandalin/voice/_genre.md` as a real rule or drop the claim. **GM ruling required**;
  this is a rules question, not a cleanup.
- Author Phandalin's missing ` ```yaml voice_lint ` block from the seeded patterns,
  lighting up checks that are inert there today.

## 7. Verification

1. **Determinism.** `measure` twice on `Phandalin/summaries/20260623/narration/` gives
   byte-identical JSON. `ledger-append` is append-only; a second call with the same
   iteration is refused.
2. **Naming tolerance.** `collect` succeeds on all three generations: OOTA `20260622`
   (flat critiques, `scene_extractions_new/`), OOTA `20260629` (`scene_extractions/`,
   `gm-assist-doc.md`), toee `20260329` (`voice_critiques/` dir, flat `scene1.md`).
3. **Phandalin lint block.** `voice_lint` on a 20260623 scene reports campaign-specific
   checks as *run*, not `[skipped] … has no yaml voice_lint block`. OOTA's existing block
   still passes unchanged.
4. **Rollback asymmetry.** Reject a proposal: `git diff voice/_genre.md` is empty,
   `wiki/patterns/` retains the new page, `skill-impact.md` carries the Rejected row with
   its diff — and the next proposer run cites that row rather than re-proposing.
   *This is the mechanism; if only one test runs, run this one.*
5. **Forks dead.** `grep -n "Thorin\|Grygum\|Zalthir" ~/.claude/skills/fable-narration/SKILL.md`
   returns nothing; running it against a Phandalin session surfaces Phandalin narrators.
6. **Renderer isolation.** `grep -rn wiki session_doc/` finds only `narration_wiki.py`;
   a render with the wiki directory removed is byte-identical.
7. **End to end.** One iteration on Phandalin `20260623` (7 critiques on disk). Expect
   3–5 proposals, ~1 accepted. A first pass that accepts everything means the gate is not
   working.

## 8. Non-goals

- Auto-applying critique fixes. The report stays a review artifact — predecessor §6,
  unchanged.
- Any automatic quality score. `measure` is evidence for a ruling, never a substitute.
- Changing what the rules say. This is accumulation and single-sourcing, not content.
- Touching the Pass 5 prompt, including #340's narrator-exclusive-context direction.
- Merging the maintainer and proposer roles. They are extract and structure respectively,
  and the repo's doctrine puts a checkpoint between them.
- Backfilling the 110 historical critiques. Seed from OOTA's rulebook — already the
  distilled form — then run forward one session at a time.

## 9. Risks

- **The maintainer will over-generate patterns.** The paper caps pages at 10–30 lines and
  forbids duplicates; GATE 1 is where that is enforced. Confirming more than ~3 patterns a
  session means the prompt is too permissive.
- **Two tiers means a routing decision every iteration.** Wrong-tier placement is how
  "Valphine never uses contractions" ends up firing on OOTA. Heuristic at GATE 1: if it
  names a character, it is campaign-tier.
- **`session_review_template.md` is the precedent for this failing** (§1.2). Right idea,
  zero adoption, because nothing drove it. If the loop is not invoked as part of the
  post-session routine, this becomes the second dead loop — and that is a process risk, not
  a design one, so no amount of design fixes it.

## 10. Open questions

1. Does the global craft tier live in `~/.claude/narration-wiki/` (portable across
   machines only via dotfiles) or inside `mytools/` where the skills already are? The
   latter versions it and is consistent with mytools#125's split, at the cost of a
   longer path from every campaign.
2. Should `measure`'s cross-narrator n-gram threshold (3+ grams, ≥2 narrators) be a
   rulebook knob rather than a constant? Making it configurable is the F4 lesson; making it
   a constant is honest until a second campaign disagrees with the default.
3. Does GATE 1 need to be per-pattern, or is a batch confirmation of the maintainer's whole
   proposal enough? Per-pattern is safer and matches `/scrub`'s hard rule; batch is what
   will actually get used at 11pm after a session.
