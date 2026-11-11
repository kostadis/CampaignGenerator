# Source-custody rebase — how to actually use it

> Task-oriented runbook for the GM. A reviewed chapter summary was corrected *after* a grounding
> generation was published from it; this is how you adopt the corrected bytes without a full rebuild.
> It extends [`delta_howto.md`](delta_howto.md) (the incremental-update family) and reuses its gates.
> The design is in `specs/040-source-custody-rebase/`.

## When you need it

Every published grounding generation pins the SHA-256 of each chapter summary it cites. If you edit a
cited summary afterwards (a typo fix, a changed prisoner count, a removed contradiction), the pin no
longer matches. The next `claims select` on any plan built on that generation refuses:

```
CLAIMS_SOURCE_STALE: cited corpus source is stale or missing: claim source,
docs/summaries/.../016-....md: expected sha256 AAA..., actual sha256 BBB...;
run: summary_native delta rebase inspect
```

That message names only the *first* stale source. `rebase inspect` lists all of them.

What a rebase does, in one line: **you decide what each correction means for the lines that cite it,
and the corrected bytes become the new pinned source in a new generation whose parent is the old one.**
No model decides anything about scope, and a changed chapter is never adopted by swapping a hash.

Run everything from the campaign root, or pass `--campaign-dir DIR`. Every leaf takes `--json`.

## The flow

```
inspect ─► prepare ─► show ─► repairs / holds ─► decide ─► grounding check ─► preview
 (read)    (--for-plan)        (GM, or model                   │             claims select/check
                               drafts you approve)             ▼             signoffs ─► apply
                                                         (rebase plan id)         │
                                          rebind the pending delta plan ◄─────────┘
```

Exit codes are the delta family's: 0 ok, 1 refusal, 2 usage, 3 stale, 4 partial, 5 recovery required.

### 1. Inspect (read-only, no model)

```bash
summary_native delta rebase inspect
summary_native delta rebase inspect --plan PENDING_PLAN_ID     # also: is that plan's baseline the active one?
```

For every pinned source whose bytes differ from the active generation's custody (following the
lineage chain) it prints the chapter, path, pinned and actual digests, which plan pinned it, and
whether each old-byte provider could supply the pre-correction bytes. It writes nothing.
`--json` adds `call_counts: {model: 0}`.

### 2. Old bytes: where the pre-correction text comes from

Impact needs the *old* text to diff against. `prepare` tries three providers in a fixed order and
accepts a candidate only if its SHA-256 equals the pin:

1. **snapshot** — a copy kept in the custody store (`docs/summaries/delta/custody/objects/<sha256>`,
   write-once, verified on every read; an earlier rebase may have kept it).
2. **git** — the campaign repository's own history (read-only `rev-list`/`cat-file`/`log`: no
   checkout, no ref change). This is what normally works if you committed before correcting.
3. **explicit file** — `--old-bytes CHAPTER=PATH`, repeatable. A wrong file is a refusal, never a
   silent fall-through to the next provider.

If the bytes were never committed anywhere, you cannot rebase that chapter. Restore the old file from
a backup or an editor undo buffer and pass it with `--old-bytes`.

### 3. Prepare

```bash
summary_native delta rebase prepare \
  --source docs/summaries/016-....md --source docs/summaries/017-....md \
  --old-bytes 17=/tmp/017-before.md \
  --for-plan PENDING_PLAN_ID
```

- `--source` is repeatable and **never defaulted**; there is no "all stale chapters". No source is exit 2.
  A source that matches its pin is `REBASE_NOTHING_TO_REBASE` (exit 2).
- `--for-plan` names the pending delta plan (for example the chapter-43 update you were in the middle
  of). Its candidate lines join the impact set, so a correction that also touches a pending candidate is
  found now, not after publication.
- It snapshots the old and the current bytes into the custody store (the corrected summaries
  themselves are never modified), builds the impact set, and creates a plan of `kind: rebase`. The
  output prints the **rebase plan id**; every later command uses it as `--plan`. Re-running with
  identical input says `already prepared (no change)`.

### 4. Read `rebase show`

```bash
summary_native delta rebase show --plan REBASE_PLAN_ID
```

Writes and prints `rebase/<id>/review.md`:

| Section | Meaning |
|---|---|
| `STALE` (only if present) | Something bound at prepare time moved. Re-run `prepare`. |
| `Chapter NNN` | The unified diff of the old and the corrected bytes. Entries are marked changed, removed or unchanged by their `[ch NNN / ENTRY]` heading. |
| `Affected lines` | Every baseline document line citing a *changed or removed* entry (or citing the chapter with no entry, which is treated as the whole chapter). Each has a stable line id. Lines citing an unchanged entry are not listed. |
| `Affected annotations` | Retained claims annotations whose span intersects a changed region. |
| `Unknown-impact members` | `canon_events_timeline.md` and `reference/**`. They carry no per-source map, so the tool will not guess: each needs your ruling. |
| `Follow-up consumers` | Published NPC dossiers that cite the chapter. Read-only; see Limits. |
| `Decisions so far` | Repairs, holds and decisions recorded to date. |

### 5. Repairs and holds

For each affected line you either write a repair or hold it. A line cannot go through unruled.

```bash
# one line, by hand (a draft; --text, --reason and --reviewer are all required)
summary_native delta rebase repair --plan RID --line LINE_ID \
  --text "…corrected line…" --reason "ch 16 now says 12 prisoners" --reviewer GM_NAME
# then approve (or reject / discuss / hold) it with the existing decision verb
summary_native delta grounding decide PROPOSAL_ID --plan RID --decision approve --reviewer GM_NAME

# optional: model drafts for the affected lines only; nothing is approved
summary_native delta rebase propose --plan RID --backend claude-code --model MODEL
```

`propose` is the only model step in the family. It sees the affected lines, the diff and the
annotations for them, and returns **drafts**; the host validates each, and you approve each one.

**Holds.** A *hold* keeps the line byte-identical and appends one marker line under it
(`⚠ held: superseded by correction to ch NNN — see rebase <id>`). Use it when the line is still
true enough to ship but you have not rewritten it. A scene repeated across many lines would be one
decision per line, so:

```bash
summary_native delta rebase repair --plan RID --hold-entry 16/016.03 \
  --reason "wording only, count unchanged" --reviewer GM_NAME
```

`--hold-entry CH/ENTRY` records one explicit hold decision for every affected baseline line citing
exactly that entry, prints every line id, and writes `rebase/<id>/holds-rN.json`. A line that already
has a proposal is left alone and reported. It does not combine with `--line`/`--text`. An entry no
affected line cites is `REBASE_UNKNOWN_ENTRY` (exit 2) and lists the entries that are cited.

### 6. Decide

```bash
summary_native delta rebase decide --plan RID --reviewer GM_NAME \
  --source-decision 16=adopt-with-repairs --source-decision 17=adopt-with-repairs \
  --source-decision 38=adopt-with-repairs --source-decision 42=adopt-unaffected \
  --member-decision canon_events_timeline.md=attested-unaffected \
  --member-decision reference/npcs.md=repaired \
  --reason "timeline cites no changed scene"
```

`--reviewer` is required and never defaulted. Every selected chapter needs a source decision and
every unknown-impact member needs a member decision (member names are as `show` prints them).

| Source decision | Allowed when |
|---|---|
| `adopt-unaffected` | The chapter has **zero** affected lines and zero affected annotations. Otherwise `REBASE_SEMANTIC_CHANGE`. |
| `adopt-with-repairs` | Every affected baseline line of the chapter has an approved repair or a hold. |
| `reject` | Always; needs `--reason`. Not adopting it leaves its pin stale and blocking. |

| Member decision | Meaning |
|---|---|
| `repaired` | You fixed the member's content. |
| `held` | You are shipping it as is, knowingly. |
| `attested-unaffected` | You assert the correction does not reach it; `--reason` required. |

**Why hash-only adoption of a semantic change is refused.** Swapping the pin to the corrected bytes
would make every line that cites the old wording look verified against text it no longer matches.
`adopt-unaffected` is therefore code-gated on the impact, not on your say-so. A whitespace-only fix in
an uncited region qualifies; a changed count in a cited entry does not.

Decisions bind to the snapshots, impact, baseline and edits they were made against. Change any of
them and the decisions are stale (`REBASE_UNRULED_IMPACT`); re-run `decide`. An identical repeat prints
`unchanged (identical to the latest)`.

### 7. Publish: the existing gates, on the rebase plan id

Nothing new to learn here. Use the [`delta_howto.md`](delta_howto.md) step 6–7 verbs with
`--plan REBASE_PLAN_ID`:

```bash
summary_native delta grounding check   --plan RID        # also enforces REBASE_UNRULED_IMPACT
summary_native delta grounding preview --plan RID --review REVIEW_ID --claims-report REF
summary_native claims select ...                           # the real claims gate, not bypassed
summary_native claims check  ...
summary_native delta review handoff    --plan RID        # exact document signoffs
summary_native delta grounding apply   --plan RID --preview-sha SHA
```

The candidate is the active baseline's four documents with **only** approved repairs and holds applied.
The staged range lists only the rebased chapters at their new digests, with the rest of the span as
declared gaps. Apply activates a new generation whose lineage parent is the old one; the old
generation's files are untouched.

### 8. Rebind the pending delta plan

The pending plan (chapter 43) was bound to the old generation, so it is now stale. Move it:

```bash
summary_native delta rebind --plan PENDING_PLAN_ID --baseline NEW_GENERATION_ID
```

(`rebind` is a top-level leaf, not `plan rebind`.) `--baseline` is required: it must be the active
generation and a direct lineage child of the plan's current baseline (`REBIND_NOT_CHILD`).

| | Result |
|---|---|
| Approved grounding edits | **Re-applied** onto the new baseline when their exact `before` bytes are still there exactly once and do not overlap a held or repaired line. Anything else is marked stale and must be re-decided, never carried on a guess. |
| Candidates, check report, review sign-offs, publication preview | **Invalidated** (recorded, nothing deleted). The digest they bound moved. Re-run `grounding check`, `preview`, claims, signoffs, `apply`. |
| Published NPC receipts | **Untouched.** An NPC binding is carried only when the NPC projection of old and new revision is byte-equal; otherwise it is treated as stale. NPC publication is not repeated. |
| The run state | Re-pointed at the new revision. |

It writes plan revision r+1 and `plans/rebind-<plan>-rN.json`; an identical repeat is `already rebound`.
The output counts re-applied, stale and invalidated items and the NPC bindings carried. Any pending
candidate that still carries the old wording is found by the next `grounding check`.

## Recovery and retry

- `grounding apply` is replay-safe: an identical re-apply writes nothing. If the process died
  mid-promotion, `delta run status --plan RID` reports `recovery_required`, and `delta run resume`
  reconciles by operation identity (see [`delta_howto.md`](delta_howto.md#recovery-status-resume-receipt)).
  The generation ends in one whole state, never half.
- A freshness failure (`REBASE_STALE`, exit 3) means an input changed after it was bound. Nothing was
  written. Re-run the step it names; in the worst case re-run `prepare`.
- `prepare`, `decide` and `rebind` are idempotent on identical input.

## Refusal codes

| Code (exit) | Cause | Remedy |
|---|---|---|
| `CLAIMS_SOURCE_STALE` | A cited source no longer matches its pin (first one only). | `delta rebase inspect`. |
| `REBASE_OLD_BYTES_UNAVAILABLE` (1) | No provider found bytes hashing to the pin; the message lists those tried. | Commit/restore the old file, then `--old-bytes CH=PATH`. |
| `REBASE_OLD_BYTES_MISMATCH` (1) | The `--old-bytes` file hashes differently; shows expected and actual. | Supply the right file. |
| `REBASE_NOTHING_TO_REBASE` (2) | The source matches its pin, or is not pinned by the active generation. | Drop it from `--source`. |
| `REBASE_UNKNOWN_LINE` (1) | `--line` is not an affected baseline line of this rebase (or belongs to a pending plan's candidate). | Take line ids from `rebase show`. |
| `REBASE_UNKNOWN_ENTRY` (2) | `--hold-entry` names an entry no affected line cites. | Use one of the entries it lists. |
| `REBASE_SEMANTIC_CHANGE` (1) | `adopt-unaffected` requested with affected lines or annotations; they are listed. | `adopt-with-repairs` (repair or hold each) or `reject`. |
| `REBASE_UNRULED_IMPACT` (1) | An affected line has no approved repair or hold, an unknown member is unruled, decisions are missing/stale/incomplete, or every chapter is rejected. | Rule what it lists; re-run `decide`. |
| `REBASE_STALE` (3) | Current bytes, baseline, impact, edits, decisions or preview changed since bound. Names the input. | Re-run the step; or `prepare` again. |
| `REBIND_NOT_CHILD` (1) | `--baseline` is not active, or its parent is not the plan's baseline. | Use the active generation produced by this rebase. |

Usage errors (exit 2) include: no `--source`, a malformed `KEY=VALUE`, a duplicate key, missing
`--reviewer` / `--reason` / `--text` / `--baseline`.

## The page

`/grounding/rebase` is the same flow: inspect table (nothing preselected; Prepare disabled until you
tick sources), per-source diff and impact, repair editor, decision radios with no default and a
required reviewer, then step 4 links to the incremental update page with the rebase plan id already
filled in (`/grounding/delta?plan=ID`), and a Rebind button with a link for the pending plan. The page
holds no state that is not a file. Routes: `GET /api/summary-native/delta/rebase/inspect`,
`POST .../rebase`, `GET .../rebase/{id}`, `POST .../rebase/{id}/propose`, `.../repairs`,
`.../decisions`, `POST .../plans/{id}/rebind`.

## Limits

- **Published NPC dossiers are listed, not changed.** `docs/npcs/*.md` that cite a rebased chapter
  appear under Follow-up consumers. Update them afterwards with the NPC path in `delta_howto.md`.
- **Unselected stale sources keep blocking.** A rebase adopts only what you select. Any other stale
  pin still raises `CLAIMS_SOURCE_STALE` until you rebase it too (or leave it blocking on purpose).
- Timeline and reference members are never auto-judged; they are always your ruling.
- Model use is limited to `rebase propose` drafts. Impact, gating, apply and rebind are deterministic.

## Worked example: ToEE, after chapter 43

Campaign `/home/kostadis/toee/toee`, pending plan `plan-0a0f7aa90623202d` (chapter 43). Chapters 16,
17, 38 and 42 were corrected after the generation was published, so `claims select` on the pending
plan stopped with `CLAIMS_SOURCE_STALE` naming only chapter 16.

```bash
cd /home/kostadis/toee/toee
summary_native delta rebase inspect --plan plan-0a0f7aa90623202d
#   -> chapters 16, 17, 38, 42 stale; old bytes: snapshot=no git=yes explicit=no

summary_native delta rebase prepare \
  --source docs/summaries/016-*.md --source docs/summaries/017-*.md \
  --source docs/summaries/038-*.md --source docs/summaries/042-*.md \
  --for-plan plan-0a0f7aa90623202d
#   -> rebase … prepared: plan REBASE_PLAN; N affected lines, M unknown-impact members

summary_native delta rebase show --plan REBASE_PLAN
#   read each diff; note any line that also appears in a ch 43 candidate

summary_native delta rebase repair --plan REBASE_PLAN --line LINE_ID --text "…" --reason "…" --reviewer GM
summary_native delta grounding decide PROPOSAL_ID --plan REBASE_PLAN --decision approve --reviewer GM
summary_native delta rebase repair --plan REBASE_PLAN --hold-entry 38/038.02 --reason "wording only" --reviewer GM
summary_native delta rebase decide --plan REBASE_PLAN --reviewer GM \
  --source-decision 16=adopt-with-repairs --source-decision 17=adopt-with-repairs \
  --source-decision 38=adopt-with-repairs --source-decision 42=adopt-unaffected \
  --member-decision canon_events_timeline.md=attested-unaffected --reason "timeline cites none of the changed scenes"

summary_native delta grounding check   --plan REBASE_PLAN
summary_native delta grounding preview --plan REBASE_PLAN --review REVIEW_ID --claims-report REF
# claims select/check, delta review handoff, then:
summary_native delta grounding apply   --plan REBASE_PLAN --preview-sha SHA

summary_native delta rebind --plan plan-0a0f7aa90623202d --baseline NEW_GENERATION_ID
summary_native delta grounding check --plan plan-0a0f7aa90623202d   # flags any ch 43 line still carrying old wording
```

Finish chapter 43 as usual on the pending plan: repair what the check flags, preview, sign off, apply.
The chapter 43 NPC receipts that were already published are untouched, and NPC publication is not
repeated.
