# Incremental updates after a reviewed session — `summary_native delta`

**Start here when one or a few newly reviewed sessions have arrived and you do not want to rebuild the
whole campaign.** `summary_native delta ...` updates the published NPC dossiers and the four grounding
documents from only the sessions you name, reusing the published history instead of rescanning it.

This page is the operator's manual. The design is `specs/039-incremental-campaign-updates/`; where this
page and a command's `--help` disagree, the code wins.

The names below come from the synthetic test fixture (`tests/fixtures/delta/`): chapters 1 and 2 are the
published baseline, chapter 3 is the new session. **Brannoc Ironvein** is a published NPC who changed in
chapter 3; **Envoy Sella Marr** is published and only mentioned in passing; **Tobin Fenwick** is in the
registry with no dossier (new); **Old Marrow Pike** is not in the registry at all.

## What it is, and what it is not

| Path | Use it when | Where it is documented |
|---|---|---|
| Existing cache or full-range rerender | You want the whole range rebuilt | [summary_native_howto.md](summary_native_howto.md) |
| **Native delta generation and publication** | A new reviewed session on top of a published baseline | this page |
| Explicit local editable-live correction | A small fix to a published line | You edit the live file; this is not the delta feature. `delta baseline adopt` reports it as drift |

A full refresh stays available and is never chosen for you.

Rules that hold for every verb, and are enforced rather than documented:

- **You name the sources.** `--source PATH` is repeatable and has no default; there is no `--all`. An empty
  selection is a usage error (exit 2): `no sources selected; the delta does not default to all chapters.`
- **A model never approves anything.** Proposals, associations and check reports are drafts. Every
  approval is a `decide` (or a review sign-off) with an explicit `--decision approve|reject|discuss`;
  there is no default.
- **A plan is pinned.** If a source file, the grounding generation or a published dossier changes after
  the plan was made, the next command exits 3 instead of proceeding. Re-plan.
- **Publication is per NPC, and preview-bound.** `npc publish` and `grounding apply` act only on a
  preview hash you have just seen; a stale hash exits 3. Both also require a recorded review
  (`delta review handoff`, then your sign-offs): with no review binding they refuse (exit 1).
- **A decision names its reviewer.** `associate decide` and `grounding decide` require `--reviewer NAME`
  (exit 2 without it). There is no default, not even your login name.
- **Secrets never enter a prompt.** Drafting reads an authored file only through its numbered manual
  edits (see [npc_dossiers_howto.md](npc_dossiers_howto.md)). `--audience player` is refused: NPC evidence
  is GM-only.

## Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | Success. | |
| 1 | **Refusal**: a gate said no. The reason is on stderr (and under `--json` as `{"error": ..., "exit_code": 1}`). | Read the message; each one is decoded below. |
| 2 | **Usage**: a required flag is missing, a value is malformed, or the source selection is empty. | Fix the command line. |
| 3 | **Stale or conflict**: something the command is bound to changed since it was bound. | Re-run the earlier step (re-plan, re-preview, re-review). Nothing was written. |
| 4 | **Partial**: some members were published and some held or failed; also `awaiting_review` (members held, none published). | Resolve the held members, then `delta run resume`. Published members are not undone. |
| 5 | **Recovery required**: an interrupted publication has to be reconciled. | `delta run resume --plan ID`; it reconciles from the durable intent. |

`--json` prints exactly one JSON object on stdout. Progress text from a model step goes to stderr under
`--json`.

## Where things live

Everything is a file under the campaign (nothing is held only in a page or a process).

| Path (under the campaign root) | Contents |
|---|---|
| `docs/summaries/delta/plans/<plan>-r<N>.json` | The plan; a change is a new revision, never a rewrite. |
| `docs/summaries/delta/sources/<plan>.sources.json` | What `delta sources` ingested, with read counts. |
| `docs/summaries/delta/census/<plan>.json` | The NPC census. |
| `docs/summaries/delta/census_rulings.yaml` | Your rulings: `excluded`, `deferred`, `indirect_references` (name to reason). |
| `docs/summaries/delta/associations/<plan>.json` | Contextual association proposals and decisions. |
| `docs/summaries/delta/<plan>/npc/` | `members.json`, per-NPC `*.spans.json` and `*.verify.json`, `freshness.json`, `receipts/`. |
| `docs/summaries/delta/<plan>/review/` | `review.md`, and one binding per product (`npc.publication.json`, `grounding.publication.json`). |
| `docs/summaries/delta/<plan>/run.json`, `receipt.json` | Run state and the completion receipt. |
| `docs/summaries/delta/grounding/<plan>/` | `proposals-rN.json`, `decisions-rN.json`, `check-rN.json`, `candidates/<doc>.md`, `lineage.json`, `publish_request.json`, `preview.json`. |
| `docs/npcs/summary_native/delta/attestations/` | Unchanged-NPC attestations. |
| `docs/summaries/delta/transfer/binding-N.json` | A worktree's transfer binding. |

## The steps, in order

Run everything from the campaign root, or pass `--campaign-dir DIR`. Both products share the first two steps.

### 1. Plan the session

```bash
summary_native delta plan \
  --source docs/summaries/003-the-new-fire.md \
  --product npc --product grounding \
  --stop apply
```

- `--source` is the new chapter. The chapter number is read from the leading digits of the file name.
- `--product` is required, repeatable: `npc`, `grounding`, or both.
- `--stop` is how far a later `run resume` goes: `plan | prepare | propose | verify | review | preview |
  apply` (default `plan`, which is why a run does nothing until you raise it).
- `--backend` / `--model` pin the plan's model. Without them the plan uses `grounding.yaml`
  `summary_native.prose`; the delta family has no default of its own.

The plan id is `plan-` plus 16 hex characters derived from the campaign identity, products, stopping
point and sources. The same inputs give the same plan.

Every `--source` must lie **inside the campaign root**. The plan stores campaign-root-relative paths
(`docs/summaries/003-the-new-fire.md`), derives its id from them, and resolves them against the campaign
root whenever it is loaded, so a moved or copied campaign (a worktree) reads its own files, not the
original's. A source outside the root is refused.

| Message | Exit | Meaning and fix |
|---|---|---|
| `no sources selected; the delta does not default to all chapters.` | 2 | Add `--source`. |
| `--product is required: one or more of grounding, npc` | 2 | Add `--product`. |
| `source not found: PATH` | 2 | Wrong path. |
| `source is outside the campaign root: PATH (root R); ...` | 2 | Copy or link the file into the campaign first. |
| `cannot determine a chapter number for PATH; name it with leading digits or give the chapter explicitly.` | 2 | Rename the file `NNN-slug.md`. |
| `no model resolves for backend B; pass --model (or set summary_native.prose in grounding.yaml)` | 2 | Pass `--model`. |
| `cannot read config/grounding.yaml: ...` | 2 | Fix the YAML. |
| `the campaign has no identity yet (...); initialise it with summary_native review init` | 1 | Run `summary_native review init` once. |
| `plan revision already exists and differs: NAME` | 1 | A plan file was edited by hand. Do not edit plans. |

A grounding plan records the active generation as its baseline. If none can be bound the plan is still
saved (`baseline status` reports why).

### 2. Ingest the sources (no model)

```bash
summary_native delta sources --plan PLAN
```

Reports `parsed_new`, `parsed_historical`, `integrity_only` (files hashed but not parsed) and
`model_input`. Nothing in the selection is parsed twice. Blocking validation findings in the selected
sources exit 1 (`N blocking finding(s) in the selected sources`); fix them in the summary and re-plan.
`source changed since the plan was made: PATH (planned X, now Y); re-plan.` is exit 3.

## One reviewed session: the NPC path

### 3. Census (no model)

```bash
summary_native delta census --plan PLAN
```

Classifies each registry NPC in the selected sources by exact name and alias, relative to the **published**
horizon. Player characters (from `players.yaml`) are skipped and listed.

| Disposition | Meaning | Next |
|---|---|---|
| `changed` | Published, with new evidence after its horizon (Brannoc Ironvein). | Draft it. |
| `new` | In the registry, no published dossier (Tobin Fenwick). | Draft it. |
| `mentioned_unchanged` | Published, only a passing mention (Envoy Sella Marr). | [Attest](#a-passing-mention-attestation). Until you attest, the run holds it (`needs attestation`); it is not recorded as carried (FR-013). |
| `absent_from_selected` | Not in the selected sources. | None. |
| `deferred` / `excluded` | You ruled it so in `census_rulings.yaml`. | None. |
| `unresolved` | A name the registry does not know (Old Marrow Pike). | [Associations](#a-new-or-unresolved-name). |

Entries flagged `needs_review` carry the evidence spans that made the call. Edit
`census_rulings.yaml` to rule on a name, then re-run `census`.

| Message | Exit |
|---|---|
| `no entity registry found (docs/entity_registry.yaml); the census resolves names through it` | 2 |
| `docs/summaries/delta/census_rulings.yaml: must be a mapping` | 2 |

### 4. A changed NPC: draft, verify, review, publish

```bash
summary_native delta npc draft   --plan PLAN
summary_native delta npc verify  --plan PLAN
summary_native delta review handoff --plan PLAN      # then review and sign off (below)
summary_native delta npc publish --plan PLAN --member "Brannoc Ironvein" --json     # preview, writes nothing
summary_native delta npc publish --plan PLAN --member "Brannoc Ironvein" --preview-sha SHA
```

- **`npc draft`** is the only model step. For a `changed` NPC the published history is carried forward
  byte for byte and only the new events are appended; the model sees the new evidence, not the whole
  corpus. `--force` redrafts; `--backend`/`--model` override the plan. Output: `drafted N member(s) in
  chNNN-NNN: <subject> (<verdict>)`.
- **`npc verify`** re-runs the native verifier on **sparse evidence**: only the spans the delta read.
  Exit 0 only if every member passes; otherwise exit 1. Sparse evidence is never presented as a full
  corpus: a check that needs the full corpus refuses rather than pass on partial input.
- **`review handoff`** creates one combined review for the plan's changed and new NPC drafts, reusing
  exact-draft sign-offs whose bytes are unchanged, and records a publication-scope binding. It does not
  approve anything. Sign off in the review (`summary_native review ...` or the review page); see
  [summary_native_review.md](summary_native_review.md). `review show --plan PLAN` renders the
  single review document (`review/review.md`) with the delta against the published dossier.
- **`npc publish`** with no `--preview-sha` writes **nothing**, prints `preview SHA for N member(s)`, and
  exits 0 (under `--json` the record carries `preview_sha256` and the per-member digests). Repeat the
  command with `--preview-sha SHA` to publish. There is no "all": name each NPC with
  `--member` (repeatable). Each member is published on its own with a receipt, so one held member does not
  stop or undo another.

| Message | Exit | Fix |
|---|---|---|
| `--plan ID is required` | 2 | Add `--plan`. |
| `no changed or new NPCs to draft in this census` | 2 | Run `census`; nothing needs a draft. |
| `--audience must be one of gm, player` | 2 | |
| `audience 'player' refused: NPC evidence is GM-only until it is classified, ...` | 1 | There is no player audience for NPC evidence. |
| `SUBJECT: census says changed but the publish log has no entry` | 1 | The dossier was never published through the log. |
| `SUBJECT: baseline is repair_required:...; repair it before drafting` | 1 | The published file or log was hand-edited. Restore it or re-publish from the authored file. |
| `SUBJECT: no new evidence after the baseline horizon; attest it instead` | 1 | Use `npc attest`. |
| `chNNN-NNN already holds a full-corpus build; refusing to mix delta drafts into it` | 1 | Use a different range or the full-range path. |
| `SUBJECT: history it would reuse cannot be resolved to evidence (...); repair the baseline` | 1 | |
| `SUBJECT: changed since the plan was made; re-plan` (a path) | 3 | Re-plan. |
| `no freshness record for plan P; run delta npc draft first` | 2 | |
| `no NPC drafts recorded for plan P; run delta npc draft first` | 2 | |
| `SUBJECT: evidence pack is missing; re-run delta npc draft` | 3 | |
| `no members selected; name each NPC with --member (there is no 'all')` | 2 | |
| `not drafted in this plan: A, B` | 2 | Spelling, or the NPC was not a `changed`/`new` member. |
| `the preview is stale: a draft, composition, evidence pack, target or publish-log entry changed since it was made; run the preview again` | 3 | Preview again, then confirm the new hash. |
| `no 'publication' review binding for plan P; run delta review handoff and review before applying` | 1 | |
| `not covered by the review binding: A; run delta review handoff` | 3 | |
| `the review is stale: ...; review again with delta review handoff` | 3 | A draft changed after sign-off. |
| `review decisions block this action: ...` | 1 | A decision is reject, discuss or missing. |

A member the publisher itself will not write is **held**: nothing is written for it, its old dossier
stays, and the line says why (no passing verification, no current exact-draft sign-off, a hand-edited
target, a slug collision). Exit: 0 all published, **4** some published and some held, 1 none published.

### A passing mention (attestation)

An NPC who was only mentioned is not rewritten. Record that you looked, bound to the exact published bytes:

```bash
summary_native delta npc attest "Envoy Sella Marr" \
  --reason "named only as a messenger in ch003; nothing she knows or did changes" \
  --publication SHA256_OF_PUBLISHED_BODY
```

`--reason` and `--publication` are required (the publication is the full lowercase sha256 of the published
body, shown by `baseline`/census evidence). `--plan` is optional and attaches the plan's sources.

| Message | Exit |
|---|---|
| `an attestation needs the GM's reason; --reason is required and cannot be blank` | 2 |
| `--publication must be a full lowercase sha256` | 2 |
| `SUBJECT: not in the publish log; there is no publication to attest` | 1 |
| `SUBJECT: the published dossier is X, not Y; the attestation is bound to the exact bytes you reviewed. Re-review and retry.` | 3 |
| `SUBJECT: baseline is repair_required:...; repair it before attesting` | 1 |

### A new or unresolved name

A `new` NPC (Tobin Fenwick) is drafted like a changed one, with no history to carry. An `unresolved` name
(Old Marrow Pike) has no registry identity. A model may **propose** who it might be, and you decide:

```bash
summary_native delta associate propose --plan PLAN
summary_native delta associate decide ASSOC_ID --plan PLAN --decision approve --reviewer NAME --reason "..."
```

Only an `approve`d association can be drafting evidence. A proposal whose evidence does not match the
cited source text is dropped and counted, not kept. `--reviewer` is required.
If the name is genuinely a new entity, add it to the registry (`registry add`) and re-run `census`; an
association never creates an identity.

| Message | Exit |
|---|---|
| `no entity registry found; associations resolve to registry canonical names` | 2 |
| `decision must be one of [...]; got 'x'` | 2 |
| `--reviewer is required to record an association decision; there is no default reviewer` | 2 |
| `no association A in plan P` | 2 |
| `association A is <state>, not approved; only an approved association can be drafting evidence` | 1 |

## One reviewed session: the grounding path

### 5. Baseline

```bash
summary_native delta baseline status [--plan PLAN]
summary_native delta baseline adopt  [--plan PLAN] --resolve world_state#1=accept --resolve party#2=reject
```

The baseline is the **active promoted generation** plus any local edits to the live files. `status`
lists each document's origin and live digest, `DRIFT` where they differ, and the coverage and gaps the
generation records. Drift is a hand edit to a published line (the editable-live correction). Adoption is
your explicit ruling on each drifted hunk, recorded as a revisioned file; it never rewrites history.

| Message | Exit |
|---|---|
| `bad --resolve X; expected <document>#<n>=accept\|reject` | 2 |
| `hunk H resolved twice` | 2 |
| `disposition must be accept or reject: ...` | 2 |
| `no such drift hunk: H; current hunks: ...` (or `; there is no drift`) | 3 |
| `unresolved drift; resolve each hunk with --resolve <hunk>=accept\|reject: ...` | 1 |
| `adoption revision already exists: NAME` | 3 |
| `the baseline has unreviewed drift; run delta baseline adopt --resolve <hunk>=accept\|reject first: ...` | 1 |
| `no managed grounding generation to bind a baseline to: ...` | 1 (migrate: [grounding_bundle_migration.md](grounding_bundle_migration.md)) |
| `grounding promotion needs recovery: ...` | **5** |
| `cannot bind the grounding baseline: ...` | 1 |
| `the active grounding generation changed since the plan was made (A -> B); re-plan.` | 3 |
| `retained delta lineage changed after publication: PATH`, `the retained delta lineage records name different baselines`, `baseline generation G changed since the delta was published`, `the delta baseline chain loops` | 3 |

### 6. Propose, decide, check

```bash
summary_native delta grounding propose --plan PLAN
summary_native delta grounding decide  PROPOSAL_ID --plan PLAN --decision approve --reviewer NAME
summary_native delta grounding check   --plan PLAN
```

- **`propose`**: one model call over the numbered baseline lines and the selected sources. The model
  returns minimal line edits; the host validates every one against the baseline (target exists, the
  before-digest matches) and drops what does not validate. Output is a `draft` set; **nothing is applied**.
- **`decide`** each proposal `approve | reject | discuss` (no default) with `--reviewer NAME` (required;
  recorded with the decision in `decisions-rN.json`). `--plan` can be omitted if the proposal id is
  unique across plans.
- **`check`**: reconstructs the candidate documents from approved proposals, runs the bounded
  preservation and citation checks (inherited custody and citations must still resolve), and, when
  something changed, one consistency-reviewer model call. It writes `check-rN.json`, the candidate
  files, and the lineage record. A check report is evidence, never an approval. Exit 1 if it blocks.

| Message | Exit |
|---|---|
| `no sources selected; nothing to propose from.` | 2 |
| `source changed since the plan was made: PATH; re-plan.` | 3 |
| `the model's proposal output is not valid JSON (...); nothing was saved` | 1 |
| `the model's proposal output has no 'proposals' list; nothing was saved` | 1 |
| `invalid grounding edit proposals: ...` | 1 |
| `an empty proposal set needs an explicit justification (nothing in the selected sources changes the grounding documents)` | 1 |
| `the model proposed no usable edits and gave no justification for an empty set; rejected: ...` | 1 |
| `unknown target T` | 1 |
| `decision must be one of ...; there is no default` | 2 |
| `--reviewer is required to record a grounding decision; there is no default reviewer` | 2 |
| `no such proposal P in plan X` | 1 |
| `cannot tell which plan owns proposal P; pass --plan ID` | 2 |
| `no grounding proposals for plan P; run delta grounding propose` | 1 |
| `reconstruction blocked: decide each proposal (approve or reject); undecided or 'discuss': ...` | 1 |
| `the consistency reviewer's output is not usable (...); no findings were recorded` | 1 |
| `check BLOCKED: <code> <doc>:<line> <detail>; ...` | 1 |

### 7. Preview and apply

```bash
summary_native delta grounding preview --plan PLAN --review REVIEW_ID --claims-report REF
summary_native delta grounding apply   --plan PLAN --preview-sha SHA
```

`preview` stages the checked candidates and lineage into the existing managed promotion path and shows a
digest-bound preview; it writes `preview.json` and changes no live document. `--review` is the
four-document review whose sign-offs authorise publication and `--claims-report` is the persisted claims
report the promotion gate requires (see [grounding_bundle_promotion.md](grounding_bundle_promotion.md));
both are remembered in `publish_request.json`. The preview digest covers the candidates, the lineage, the
request **and the staged promotion tree** (the staged drafts, the copied `reference/**` and the manifest),
so a staged file edited after the preview is a stale preview. `apply` first needs the review recorded by
`delta review handoff` (sign the four documents, hand off, then apply), then activates the whole
generation through that same path. A new generation, not a patch: the documents are replaced together or
not at all.

| Message | Exit |
|---|---|
| `no candidate documents under DIR` / `no lineage record at PATH` / `no checked candidates to stage; run delta grounding check` / `no lineage record; run delta grounding check` | 2 |
| `publish_request.json lacks <fields>` | 2 |
| `the selected chapters [..] are not contiguous; a promotion range would claim chapters the delta did not select. ...` | 2 |
| `cannot resolve the promotion output root: ...` / `selected source is outside the campaign: PATH` | 2 |
| `RANGE already exists and was not staged by a delta; staging would overwrite its manifest and drafts. ...` | 1 (a full build's range directory is never overwritten; select chapters whose range is new) |
| `baseline custody bytes changed: PATH` | 3 |
| candidates, lineage or check changed after the check (`require_check_binding`) | 3 |
| `promotion preview refused: ...` | 1 |
| `--preview-sha is required; run delta grounding preview first` | 2 |
| `preview is stale: candidates, lineage or plan changed since the preview was confirmed; preview again and confirm the new hash` | 3 |
| `no 'publication' review binding for plan P; run delta review handoff and review before applying` | 1 |
| `the review is stale: ...; review again with delta review handoff` | 3 |
| `review decisions block this action: ...` | 1 |
| `lineage is incomplete: ...` | 1 |
| `promotion refused: ...` | 3 if the promotion said stale, otherwise 1 |
| `no plan P in DIR` / `no plan P revision N in DIR` | 1 |

An `INCOMPLETE` preview lists its problems; do not apply it. Git stays a separate operator action.

## A cited summary was corrected after publication

If `claims select` stops with `CLAIMS_SOURCE_STALE`, a summary the published generation pins has changed. Do not re-plan: use `summary_native delta rebase inspect | prepare | show | repair | decide`, publish the rebase plan through the same grounding gates, then `summary_native delta rebind --plan PENDING --baseline NEW_GENERATION`. See [source_custody_rebase_howto.md](source_custody_rebase_howto.md).

## Baseline adoption (what and when)

Adopt when `baseline status` shows `DRIFT` (someone edited a live grounding file after promotion), and
before `propose`. `accept` keeps your hand edit as part of the baseline; `reject` sends the hunk back to
the published text. The adoption is recorded per generation and revisioned; both `propose` and `check`
refuse while drift is unreviewed.

## Review and handoff

```bash
summary_native delta review show    --plan PLAN
summary_native delta review handoff --plan PLAN
```

Neither verb calls a model or approves anything. `show` writes and prints the one review document
(`review/review.md`); under `--json` it also returns the bindings. `handoff` prepares the review each
product publishes against: NPC (one combined review, unchanged sign-offs reused) and grounding (the
review named in `publish_request.json`). A binding records the exact bytes reviewed; if a draft, the plan
or the rules change afterwards, the next publish exits 3 and tells you to hand off again.

| Message | Exit |
|---|---|
| `SUBJECT: draft or evidence pack is missing; run delta npc draft` | 1 |
| `cannot create the review: ...` | 1 |
| `publish_request.json names no document review; run delta grounding preview --review ID with the four-document review first` | 2 |
| `unknown product 'x'`, `unknown approval scope 'x'; one of ...`, `decision must be one of ...`, `a reviewer is required` | 2 |
| `cannot read review R: ...` | 1 |
| `the review binding is a 'S' approval; a 'publication' approval is required and the scopes are not interchangeable` | 1 |

## Recovery: status, resume, receipt

> **Verify before relying on this section's examples against a live run**: it was written from
> `delta/cli_run.py` and `delta/run.py`; no campaign run was exercised while writing it.

```bash
summary_native delta run status  --plan PLAN
summary_native delta run resume  --plan PLAN
summary_native delta receipt     --plan PLAN
```

- **`run status`** is read-only. It shows the status, each stage (`census`, `draft`, `verify`, `publish`,
  `grounding_apply`), each member's outcome (`published | held | rejected | unchanged | failed`), any
  ambiguous publication, the model calls so far and the **next action**. The status is one of `running`,
  `failed`, `stale`, `awaiting_review`, `partial`, `recovery_required`, `complete`.
- **`run resume`** continues from the last durable stage, up to the plan's `--stop` point. A stage whose
  inputs are unchanged is reused by digest with **no model call**; it reports `(reused)` and the calls
  made this run. A run that is already complete is replayed without rewriting anything. `--force` reruns
  a stage whose artifact changed on disk.
- **`receipt`** writes `receipt.json` from the run state: selected chapters, changed/new/carried/held
  members, publication hashes, checks, decisions with revisions, read and call counts and the recovery
  state. It contains no URL, token or secret. A completed `resume` writes it for you.

| `run resume` exit | Status |
|---|---|
| 0 | `complete` |
| 4 | `partial` or `awaiting_review` |
| 5 | `recovery_required` |
| 3 | `stale` |
| 1 | `failed` or `running` |

If a process died mid-publication, `run status` reports `recovery_required` and names the member (an
intent without a receipt) or `grounding:operation-<request>`. `run resume` finishes the member from its
intent (if the target already holds the intended body the log is brought up to date; otherwise a `failed`
receipt says nothing was published) and recovers a grounding activation **by operation identity**; it
never re-runs a write blindly. If the promotion refuses, the held line names the exact promotion recovery
command to run.

| Message | Exit |
|---|---|
| `plan P has no run yet; run delta run resume first` (`receipt`) | 2 |
| `run R belongs to P-rN, not P-rM; the plan changed` | 3 |
| `drafting did not complete (exit N); re-run resume to continue` | 1 |
| `batch dispatch failed: CODE: MESSAGE` | 1 |
| `batch size must be at least 1` | 2 |
| `unsupported run state schema_version 'x'` / `unsupported receipt schema_version 'x'` | 1 |
| a grounding hold: `blocked: required member(s) not published: ...`, `no grounding preview; run delta grounding preview and confirm it`, `activation OP needs intervention: ...; run CMD`, `the operation was aborted; the request id is spent, use a new one` | 4 (held) |

## Worktrees and artifact transfers

A worktree or copy of a campaign has a different path, so the campaign-identity guard would refuse it.
`transfer` proves a copy came from the canonical campaign without weakening that guard.

```bash
summary_native delta transfer verify --canonical /path/to/canonical --campaign-dir /path/to/worktree
summary_native delta transfer bind   --canonical /path/to/canonical --campaign-dir /path/to/worktree
```

`verify` compares the worktree's `docs/reviews/campaign.json` and every plan in it with the canonical
campaign's, and changes nothing. `bind` verifies and then writes `docs/summaries/delta/transfer/binding-N.json`
in the worktree (never `campaign.json`); after that, delta commands in the worktree accept the canonical
identity. Re-binding an identical transfer returns the existing file. A tampered or stale binding is refused.

| Message | Exit |
|---|---|
| `--canonical DIR is required (the campaign the worktree was copied from)` | 2 |
| `the worktree is the canonical campaign; there is nothing to transfer` | 1 |
| `the canonical campaign has no campaign identity (docs/reviews/campaign.json); initialise it with summary_native review init in the canonical campaign` (also `the worktree has no ...`) | 1 |
| `the LABEL's campaign identity is unreadable (...)` | 1 |
| `DIR is not the canonical campaign: its identity names ROOT` | 1 |
| `unverified transfer: the worktree's campaign identity (...) is not the canonical campaign's (...)` | 1 |
| `unverified transfer: plan(s) ... carry a different campaign identity than the canonical campaign` | 1 |
| `plan record PATH is unreadable; cannot verify the transfer` | 1 |
| `WORKTREE is not bound to a canonical campaign; run summary_native delta transfer bind --canonical DIR` | 1 |
| `the transfer binding record was altered after it was written; re-run delta transfer bind` | 1 |
| `the binding was made for A, not B` | 1 |
| `the campaign identity changed since the transfer was bound; re-verify with delta transfer verify --canonical DIR` | 3 |

## The web page and HTTP routes

The Grounding area has a page, **Incremental update** at `/grounding/delta`, a stepper over the stages
above: pick chapters (each ticked chapter is written into the explicit list; "select all" writes every
resolved chapter into that list, never an implicit set), see the files each stage produced, and record
each judgment (association, proposal, attestation, publication) on the page or in the CLI. The status
banner reads `stale`, `partial` and `recovery_required` from `run status`, so a restart shows the same
state. A decision needs a reviewer name (a field on the page; the last name is remembered in your
browser only as a convenience). NPC publication is two steps on the page, as in the CLI: **Preview NPC
publication** shows the digest and members and writes nothing; **Publish previewed NPCs** then sends
exactly those members with that digest, and changing the member list discards the preview. The routes live under `/api/summary-native/delta` and build exactly the commands on this page:

| Command | Route |
|---|---|
| `plan`, `sources` | `POST /plans`, `POST /plans/{id}/sources` |
| `baseline status` / `adopt` | `GET /plans/{id}/baseline`, `POST /plans/{id}/baseline/adopt` |
| `census`, `associate propose` / `decide` | `POST /plans/{id}/census`, `.../associations/propose`, `POST /associations/{id}/decision` |
| `npc draft`, `verify`, `attest`, `publish` | `POST /plans/{id}/npc/draft`, `.../verify`, `.../npc/{subject}/attest`, `.../publish` |
| `grounding propose`, `decide`, `check`, `preview`, `apply` | `POST /plans/{id}/grounding/propose`, `POST /grounding/proposals/{id}/decision`, `.../check`, `.../preview`, `.../apply` |
| `run status`, `run resume`, `receipt` | `GET /plans/{id}/status`, `POST /plans/{id}/resume`, `GET /plans/{id}/receipt` |
| `review show` / `handoff` | `GET /plans/{id}/review`, `POST /plans/{id}/review/handoff` |
| `transfer verify` / `bind` | `POST /transfer/verify`, `POST /transfer/bind` |
| `npc publish` (preview) | `POST /plans/{id}/npc/publish/preview` (the CLI's preview, `--json`, no `--preview-sha`) |

Long stages stream over SSE (`event: line`, then `event: exit` with the code). Exit 3 maps to HTTP 409,
exit 4 to 207 with per-member outcomes, exit 5 to 409 with the recovery command, and an empty source list
to 400 with the CLI's text. No capability URL or token appears in any response or receipt.

> The routes and the page are described from `specs/039-incremental-campaign-updates/contracts/http.md`;
> check them against the running server before relying on a path.
