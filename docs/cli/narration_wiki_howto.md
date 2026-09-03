# Narration Wiki browser how-to

Use the Narration Wiki to turn evidence from one completed session into durable
campaign knowledge and, optionally, a reviewed change to narration guidance.
The browser page is `/workflow/wiki` (for example,
`http://localhost:5001/workflow/wiki`).

This workflow does not automatically decide what good writing is. Measurements,
Codex drafts, and generated diffs are review material. The GM makes both durable
decisions.

## The short version

```text
Select one session
  → Collect its evidence
  → Measure a baseline
  → Ask the Codex maintainer for pattern drafts
  → Gate 1: accept or reject every pattern
  → Ask the Codex proposer for one guidance proposal
  → Stage and review its diff
  → Apply it temporarily
  → Measure the comparison
  → Gate 2: accept permanently or reject and restore
```

Two distinctions prevent most confusion:

- **Gate 1 accepts a lesson into the campaign wiki.** It does not edit the
  narration rulebook.
- **Gate 2 accepts a proposed guidance edit.** Applying the comparison is only
  temporary until Gate 2 accepts it.

## Before starting

You need:

- the CampaignGenerator server running for the intended campaign;
- one existing session directory below that campaign;
- a new stable iteration ID such as `iter-007`;
- a companion dependency showing `Present: true`, `Compatible: true`, and the
  `maintainer, proposer` roles;
- the Codex skills `$gm-narration-wiki-maintainer` and
  `$gm-narration-wiki-proposer`.

An iteration ID may contain lowercase letters, numbers, `.`, `_`, and `-`. Do
not reuse an ID for a fresh collection: collection is intentionally immutable.

## 1. Select exactly one session

At the top of the page, fill in **Explicit selected session**:

- **Campaign ID:** the configured campaign identity, such as `Phandalin`.
- **Session relative path:** the path below the campaign root, such as
  `summaries/20250514-chapter-02-new`.
- **Iteration ID:** a new ID, such as `iter-007`.

Click **Reload status**. The **Disk-derived state** panel should show `new`, or
report that the iteration does not yet exist. The browser does not own the
state; it rereads the files after every action.

## 2. Collect evidence

Click **Collect** once.

This creates:

```text
<session>/narration_wiki/<iteration-id>/
├── iteration.json
└── trace-manifest.json
```

The manifest records the exact evidence files, their hashes, missing optional
roles, and the narration documents that form the measurement corpus. It does
not rewrite the source documents.

Check the streamed output. A normal current-layout corpus should contain the
final rendered narration documents, not `.knobs.json`, plans, critiques, or
scene-extraction copies. If the measurement corpus contains dozens of those
supporting files, stop and see [A 44- or 46-document corpus](#a-44--or-46-document-corpus).

## 3. Measure the baseline

Click **Measure baseline**.

The baseline reads the fixed corpus and runs the configured checks. Typical
categories include:

- banned phrase shapes;
- portable portrait/taxonomy constructions;
- em-dash counts;
- filing and narrator-specific bookkeeping budgets;
- cross-narrator repeated phrases.

`ok`, `breach`, and `skipped` are mechanical findings, not acceptance
decisions. A skipped check means it was not configured or could not run; it
does not mean the prose passed that check.

The result is saved as:

```text
<iteration>/measurement-before.json
```

Do not edit `iteration.json` or the measurement file by hand.

## 4. Generate Gate 1 pattern drafts

The browser does not invoke the companion model itself. In Codex, ask the
maintainer explicitly:

```text
Use $gm-narration-wiki-maintainer for:
campaign root: /path/to/campaign
session: summaries/session-name
iteration: iter-007
```

The maintainer reads the baseline, exact campaign guidance, and collected
evidence. It may write:

```text
<iteration>/drafts/<pattern-slug>.md
<iteration>/conflict-drafts/<conflict-id>.json
```

It cannot accept its own pattern, resolve a conflict, or edit guidance. Reload
status after it finishes.

The **Patterns** row in **Disk-derived state** looks like:

```text
{"accepted":0,"pending":2,"pending_portable_sync":0,"rejected":0}
```

The value of `pending` is the number of Gate 1 decisions still required. The
state may remain `measured_before` until the first ruling; the counts are the
useful signal here.

## 5. Resolve conflicts, if any

If **Unresolved conflicts** is non-empty, use the conflict card before trying
to accept a blocked pattern. Read the conflict draft and its source statements,
then provide:

- the resolution selected by the GM;
- the rationale for that selection.

No source wins merely because it appears first. A conflict ruling resolves the
disagreement but still does not accept the related pattern.

## 6. Gate 1: accept or reject every pattern

Open each Markdown draft under `<iteration>/drafts/` and review its Problem,
Root Cause, Corrective Strategy, and Evidence. The current Gate 1 card requires
you to enter the slug; it does not present a draft picker.

For each draft:

1. Enter its exact filename stem in **Pattern slug**.
2. To accept it for this campaign, leave **Tier** as **Campaign** and click
   **Accept pattern**.
3. To reject it, click **Reject pattern**. A rejected pattern carries no tier.
4. Wait for the command to finish and confirm that `pending` decreased.

Use **Portable** only for campaign-independent craft knowledge that should be
maintained by the companion deployment. Named campaign material requires an
explicit override and rationale. A portable acceptance remains
`pending_portable_sync` until the companion publishes a compatible confirmed
page, so **Campaign** is the normal choice for campaign-specific voice rules.

When every draft has a ruling and at least one accepted pattern is available,
the state becomes `ready_for_proposal`. If all drafts were rejected, there is
no guidance proposal to make.

## 7. Generate one incoming proposal

Choose one accepted pattern for the next atomic change. Give the proposer an
explicit proposal ID:

```text
Use $gm-narration-wiki-proposer for:
campaign root: /path/to/campaign
session: summaries/session-name
iteration: iter-007
pattern: accepted-pattern-slug
proposal ID: descriptive-id-001
```

The proposer verifies Gate 1, resolves this campaign's authorized targets, and
writes only:

```text
<iteration>/proposals/incoming/<proposal-id>.yaml
<iteration>/proposals/incoming/<proposal-id>.candidate
```

The candidate is the complete proposed replacement for one authorized file.
The live guidance file is still unchanged.

## 8. Stage and inspect the generated diff

In the **Proposal / Gate 2** panel, enter:

- **Proposal ID:** the exact ID supplied to the proposer;
- **Draft path relative to iteration:**
  `proposals/incoming/<proposal-id>.yaml`.

Leave override rationale blank for a new proposal, then click **Stage
proposal**.

Staging validates the accepted patterns, target allowlist, live target hash,
and candidate. It creates snapshots and a complete unified diff without
changing the live target. The generated diff appears in the Proposal/Gate 2
panel and is stored at:

```text
<iteration>/proposals/<proposal-id>/change.diff
```

Read the entire diff before continuing. One proposal must change exactly one
authorized target.

## 9. Apply the comparison temporarily

Click **Apply comparison** only after the staged diff is acceptable to test.

This replaces the one live guidance target with the exact staged candidate.
The change is provisional and hash-checked. Do not manually edit that target
while the comparison is active.

## 10. Measure the comparison

Click **Measure comparison**. CampaignGenerator reruns the named checks against
the same frozen narration corpus and writes:

```text
<iteration>/proposals/<proposal-id>/measurement-after.json
```

Compare the baseline and comparison rows, then read the limitation below before
interpreting them.

### Important: prose changes are not regenerated

The current comparison does **not** regenerate narration. It uses the same
existing documents so the corpus identity remains fixed.

This is meaningful when the proposal changes structured checker configuration:
the same prose may receive different, newly configured findings. It does not
measure the writing effect of a prose-only prompt or rulebook instruction. For
such a proposal, numerical before/after results may be identical.

For a prose-only change:

- use Gate 1 evidence and the staged diff for the current Gate 2 decision;
- treat Measure Comparison as a check for mechanical regressions, not proof of
  improved prose;
- validate the writing effect on a later narration render after acceptance.

A true prose A/B would require a future candidate-generation step that reruns
the narrator with the candidate guidance while holding source inputs and model
settings constant. That step is not part of this workflow today.

## 11. Gate 2: keep or restore

After the comparison measurement:

- **Accept proposal** retains the candidate bytes as the campaign's live
  guidance and records an `Accepted` impact.
- **Reject proposal** restores the exact before snapshot and records a
  `Rejected` impact.

This is the point at which a guidance change becomes permanent. Both outcomes
are recorded in `<campaign>/wiki/skill-impact.md` with the diff and measurement
references. After completing one proposal, another accepted pattern can be
handled as a new proposal with a new ID; proposals remain one-at-a-time.

## Where things live

| What | Location |
|---|---|
| Selected iteration and measurements | `<session>/narration_wiki/<iteration-id>/` |
| Pending pattern drafts | `<iteration>/drafts/` |
| Accepted campaign lessons | `<campaign>/wiki/patterns/` |
| Incoming proposal authored by Codex | `<iteration>/proposals/incoming/` |
| Staged diff and snapshots | `<iteration>/proposals/<proposal-id>/` |
| Durable proposal history | `<campaign>/wiki/skill-impact.md` |
| Companion capability and portable patterns | `~/.claude/narration-wiki/` |
| Command and error details | **Streamed output and history** panel |

## Troubleshooting

### `required artifact is missing: iteration<campaign>json`

The selected iteration was never collected, the session path is wrong, or the
iteration ID belongs to another session. Recheck all three selection fields.
For a genuinely new iteration, click **Collect** before measuring.

### `Command exited with code 4`

Code 4 is a lifecycle or stale-state conflict, not a generic crash. Read the
text in **Streamed output and history**, then click **Reload status**. Common
causes are:

- collecting an iteration ID that already exists;
- using the wrong iteration;
- attempting Gate 1 before a baseline exists;
- accepting a pattern with an unresolved conflict;
- staging while another proposal is active;
- corpus or guidance drift after a Gate ruling;
- using stale target bytes or a duplicate proposal ID.

Do not create files merely to silence a missing-artifact error. Return to the
first incomplete lifecycle step.

### A 44- or 46-document corpus

The collector is loading a stale implementation that classifies plans,
settings, critiques, and scene-extraction copies as narration. Cancel the
measurement, update or launch CampaignGenerator from the corrected checkout,
and use a new iteration ID. Do not reuse the bad manifest: collection is
immutable.

### The browser times out or `localhost` cannot be reached

The HTTP server is not running, was blocked by a long process, or is listening
on another port. Restart the CampaignGenerator server, reopen the correct URL,
and click **Reload status**. Disk artifacts survive a browser disconnect.

### An action was canceled

Reload status first. If the **Recovery** row names a transaction, click
**Recover transactions** before doing anything else. If recovery reports
`needs_attention`, inspect the named journal and target rather than retrying
blindly.

### Companion dependency is missing or incompatible

The **Companion dependency** panel should show both roles and contract version
1. Check `~/.claude/narration-wiki/capabilities.yaml`. CampaignGenerator can
still collect and measure locally, but companion-dependent drafting and
portable synchronization are not ready.

### The diff is blank

A diff is generated only after **Stage proposal** succeeds. Gate 1 acceptance
and the Codex proposer's incoming files do not stage themselves. Confirm the
proposal ID and iteration-relative YAML path, stage it, then reload status.

## Worked field example

For a Phandalin session, the browser fields might be:

```text
Campaign ID: Phandalin
Session relative path: summaries/20250514-chapter-02-new
Iteration ID: iter-006
```

For proposal `epigram-cap-001`:

```text
Proposal ID: epigram-cap-001
Draft path relative to iteration:
proposals/incoming/epigram-cap-001.yaml
```

The general CLI command reference is [Narration Wiki CLI](narration-wiki.md).
