# Research: NPC Review Noise Resolution (041)

Every decision below was taken from reading the code in this worktree at `e6c13a9`. Each one names the file it rests on.

## R1 — Where the two checks live today

- **Number/ordinal**: `pipelines/summary_native/review/verification.py::_deterministic_semantic_advisories`. It runs inside `adapt_selected_verifications`, so it only exists at **review-item build time**, not in `npc-verify`'s own `verify.md`. `_cited_claims` pairs each draft *line* with each single cited occurrence, and `_markers` (regex `_MARKER_RE`) tokenises numbers and ordinals. Codes: `number-inconsistency`, `ordinal-inconsistency`, `same-citation-inconsistency`.
- **Status**: `pipelines/summary_native/npc_verify.py::check_status_words`. It scans the Last-State section and the first MAP section for `STATUS_WORDS` and compares each literal word against the NPC's **whole evidence text**. Code: `status-claim-unsupported` (advisory).

**Decision**: put all classification logic in one new pure module, `pipelines/summary_native/noise.py`. Both call sites delegate to it, so the number and status checks share sentence segmentation, citation scoping and the noise-record shape.
**Rationale**: one seam per concern (Constitution V and XII in spirit). Two copies of sentence splitting would drift.
**Alternatives rejected**: patching each call site in place. The number check would then gain sentence scoping while the status check stayed line-scoped, which is the drift FR-002 and FR-010 forbid.

## R2 — Unit of comparison: sentence, with line fallback

**Decision**: split each draft line into sentences with a deterministic splitter. A boundary is `[.!?]` followed by whitespace and an uppercase letter or an opening quote. It never splits inside `[...]` citation brackets, and never after a short closed list of abbreviations (`St.`, `Mr.`, `Mrs.`, `Dr.`, `vs.`, `e.g.`, `i.e.`, `ch.`). A sentence's citations are `npc_check.citation_parts(sentence)`. If it has none, it inherits `citation_parts(line)`, never another line's (spec Edge Cases).
**Rationale**: in summary_native drafts, citations usually close a sentence. Bullets often carry one trailing citation for the whole bullet.
**Alternatives rejected**: an NLP sentence tokenizer. It is a new dependency and not deterministic across versions.

## R3 — Token model

**Decision**: tokens normalise to `(kind, value)`, where `kind` ∈ {`cardinal`, `ordinal`}:
- digits with grouping commas, `\d{1,3}(?:,\d{3})+` or `\d+`, are one cardinal token;
- `\d+(st|nd|rd|th)` and the ordinal words `first`–`twelfth` (plus `twentieth`, `hundredth`) are ordinals;
- spelled cardinals are converted by a small deterministic parser covering units, teens, tens, `hundred`/`thousand`/`million`, hyphenated tens (`twenty-five`) and the article forms (`a hundred`, `a thousand`).

A spelled phrase the parser cannot fully convert is checked **as written**. It is never silently passed (spec Edge Cases). Two tokens match when kind and value are equal. A draft cardinal never matches an evidence ordinal, and vice versa.
**Rationale**: FR-004 and FR-005. Value comparison makes "five" = "5" and "a thousand" = "1,000" symmetric.

## R4 — Labels

**Decision**: a numeric token is a **label** when:
- it follows `chapter(s)`, `ch.?`, `scene(s)` or `session(s)`, including a range form `N–M` or `N-M` after such a word; or
- it is a scene id of the citation form `\d{3}\.\d{2}`; or
- it is a leading list numeral (`^\s*\d+[.)]\s`).

Only the token attached to the label word is a label ("36 hit points in Chapter 36" labels the second "36" only).
**Rationale**: FR-003. This covers the 281 label findings in #617 by the categories listed there.

## R5 — Classes, precedence and the "examined" accounting

**Decision**: an occurrence is examined by a check, then lands in exactly one bucket:

1. `supported`: present in **every** scene the sentence cites (number check), or the literal status word is in the evidence. Nothing is recorded beyond a count.
2. Classified noise, by first match in this fixed precedence: `label` > `idiom` > `negated-status` > `spelled-number` > `synonym` > `other-citation`.
   - `spelled-number`: the match succeeded only through value normalisation (a spelled form on either side).
   - `other-citation`: present in at least one, but not every, scene the sentence cites. The old per-citation rule flagged exactly this.
3. GM-facing finding: everything else.

**Rationale**: SC-005 (amended) needs a closed partition. The precedence makes FR-014 testable. `supported` is not noise: the old rule never flagged it either, so recording it would inflate the audit.

## R6 — Reviewed tables

**Decision**: two YAML files in the existing package data directory, `pipelines/summary_native/data/`:
- `ordinal_idioms.yaml`: exact lowercase phrases ("first time", "at first", "third person", "first of all", "at first light", "second-hand", "second nature", "third party").
- `status_synonyms.yaml`: status word → list of evidence forms, e.g. `departed: [depart, departs, departing, leave, leaves, left, leaving]`, `died: [die, dies, dead, death, killed, slain]`, and so on for every entry in `STATUS_WORDS`.

Loaded with `Path(__file__).parent / "data" / ...`, the same pattern as `npc_forms.WORDLIST_PATH`. A loader validates the shape and raises on malformed data. There is no silent default.
**Rationale**: FR-006 and FR-007 require reviewable data, separate from logic, changed by PR.

## R7 — Negated status

**Decision**: a sentence is a not-established non-claim when it matches one of a closed set of patterns, case-insensitive:
- `\bno (further )?status\b … \bestablished\b`
- `\bstatus\b … \b(is|remains) (not|un)(\s)?(established|known|stated|confirmed)\b`
- `\b(not|un)known whether\b`
- `\bunclear whether\b`

Every status word inside such a sentence is `negated-status`. A bare `not` elsewhere does not negate.
**Rationale**: FR-008 plus the spec Edge Case "he did not flee; he died".

## R8 — Representing noise in the review store

**Decision**: each classified-noise occurrence becomes **its own ReviewItem**, one per (sentence, token, class). Its single diagnostic carries `legacy_code = "noise-<class>"` (`noise-label`, `noise-idiom`, `noise-negated-status`, `noise-spelled-number`, `noise-synonym`, `noise-other-citation`), `severity = ADVISORY`, `assignment_basis = MECHANICAL`, and a new `FindingCategory.CLASSIFIED_NOISE`. Diagnostic `details` carry `noise_class`, `token`, `sentence`, `cited_scenes`, `resolved_by` (the evidence word or scene that resolved it) and `check` (`number` | `status`).
**Rationale**:
- FR-017 requires a decision record per occurrence, so one item per occurrence.
- `review policy` (`delegated.plan_policy`) already approves items whose **only** legacy_code is in the policy file. One code per class therefore makes FR-015 work with zero change to policy code, in exactly the way `typography-normalised` works.

**Schema impact**: adding an enum member and new code strings is additive. Existing reviews never contain them, and readers of old reviews are unaffected. No migration is needed (Constitution XIII does not trigger). This is called out in `plan.md`.
**Alternatives rejected**:
- One aggregate item per class: it cannot give per-occurrence decision records.
- Noise as an audit file outside the store: option A, which the GM rejected in Q1.

## R9 — The class batch card (Q1 = B)

**Decision**: the engine is a new CLI verb, mirroring the delegated `carry`/`policy` pattern in `review/cli.py`:
- `summary_native review noise REVIEW [--json]` lists classes with counts, decided/undecided, and every occurrence.
- `summary_native review noise decide REVIEW --class C --verdict approve|reject --reviewer R --note N [--write]` is a dry run by default. `--write` submits one decision per undecided occurrence of that class through `delegated.submit_decisions` → `save_decisions`. `approve` maps to `accept_no_change` and `reject` to `reject_action`. The note is prefixed `GM class verdict on batch card [noise-<class>]:`.
- It refuses an unknown class, a class with zero undecided occurrences, and a missing `--class`. Principle X: there is no "all classes" form.
- A class covered by a standing policy is approved through `review policy` and never needs this verb (FR-017a). `review noise` reports which classes are fully decided.

**Rationale**: the decision path is the existing validated one. Nothing new writes decisions.

## R10 — Faces (Constitution XI)

The GM's actual review page is built by the shared review-artifact kit in **mytools** (`dotfiles/claude/skills/_shared/review-artifact/npc_review_items.py` → `build_review.py` → `read_decisions.py`), per #616. The in-repo faces are `server/routers/review_routes.py` and the review web viewer (`pipelines/summary_native/review/web/`).

**Decision**:
- (a) In CG: add `noise` and `noise decide` routes to `server/routers/review_routes.py`, each shelling out to the CLI (Principle VI).
- (b) In mytools: `npc_review_items.py` emits one card per noise class (card id `noise-class:<class>`, listing the member item ids). `read_decisions.py` expands a class verdict into the per-item decisions the kit already produces. Its page explains that one verdict covers every listed occurrence.

**GM ruling (2026-11-12)**: (b) is in scope. The kit stays in mytools and is edited in place there, on its own branch and PR. It is not moved into CG, and no CG-native NPC page is built. #616 stays open. Fixing the CG↔mytools boundary (which repo owns code that reads CG's review store) is deferred to #643.

## R11 — Interaction with existing behaviour

- `same-citation-inconsistency` keeps its rule, but uses the R3 tokenizer and skips R4 labels, so "5,000" and chapter labels stop producing false conflicts there too.
- `verify.md` (`render_verify_md`) gains a "Classified noise" section with per-class counts and occurrences for the status check, which runs inside `npc-verify`. The number check's noise appears in the review store, because that is where the check runs (R1).
- Item fingerprints include code and detail, so re-verified drafts get new item ids. Carrying approvals across that change is #625's problem, not this feature's.

## R12 — Baseline location and the labelled oracle

The stormgiants ch 1–86 build lives in a **separate checkout**, `~/storm-giant/stormgiants`, not the campaigns monorepo's `~/src/campaigns/stormgiants` (which has no NPC build). It contains:
- `docs/npcs/summary_native/ch001-086/` (the build) and `publish_log.json`;
- `docs/reviews/npc-review-6ee694eebf5b` and `npc-review-8e7e7ca1760a` (the baseline reviews), plus five later reviews;
- under `npc-review-6ee694eebf5b/requests/`: the GM's bulk noise rulings from that session, `gm-number-noise-*-{0,100,200,300}.json` and `gm-status-synonym-*.json`.

**Decision**: those request files are a **GM-labelled oracle**. Every token the GM ruled as noise, and by elimination every remaining true positive, is there.
- Phase 2 includes a read-only harness test, skipped when the checkout is absent. It replays the baseline review's drafts and evidence through the new classifier and compares against the oracle.
- SC-001: no more than 100 GM-facing number/ordinal findings.
- SC-004: every non-noise token is still a finding.
- SC-002: status findings on GM-ruled synonyms = 0.
- The harness only reads the stormgiants checkout. It never writes to it.

The unit fixtures still reproduce every #617 and #618 example, so the suite stays meaningful on machines without the checkout.

## R13 — Worktree import shadowing

Running from the worktree with `PYTHONPATH=<worktree>`, `import pipelines` resolves to the worktree (checked: `pipelines.__file__` → `wt621/pipelines/__init__.py`). Every test command in quickstart and tasks sets `PYTHONPATH` explicitly, so the editable install of the main checkout cannot shadow the branch.
