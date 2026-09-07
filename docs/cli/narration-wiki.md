# Narration Wiki CLI

For a button-by-button browser walkthrough, terminology, Codex companion
prompts, and troubleshooting, see the
[Narration Wiki browser how-to](narration_wiki_howto.md).

`narration_wiki` turns one explicitly selected session into deterministic
evidence, human-reviewed durable patterns, and one-at-a-time guidance
proposals. Mechanical measurements are evidence only: Gate 1 and Gate 2 are
always explicit GM actions.

## Scope and output

Every command requires the same three options:

```bash
narration_wiki COMMAND \
  --campaign-dir /path/to/campaign \
  --session-dir /path/to/campaign/sessions/session-42 \
  --iteration-id iter-001 \
  --json
```

The campaign and session must already exist, the session must be a proper
descendant of the campaign, and the iteration ID must match
`[a-z0-9][a-z0-9._-]{0,63}`. JSON results contain only relative artifact paths.
`status --json` emits exactly one object; other commands may emit progress
before their final object.

## Lifecycle and commands

The disk-derived lifecycle is:

```text
new → collected → measured_before → gate1_review → ready_for_proposal
    → proposal_staged → comparison_applied → awaiting_gate2
    → completed_accepted | completed_rejected
```

Commands:

- `status`: read-only projection of lifecycle, counts, unresolved conflicts,
  active proposal, companion dependency, and recovery.
- `collect`: create a new immutable trace manifest for the selected session.
- `measure --phase before`: persist or, before any Gate 1 ruling, safely
  replace the deterministic d4-v1 baseline.
- `index-check`: read-only campaign/portable page, link, tier, slug, promotion,
  and capability audit.
- `conflict-rule --conflict-id ID --resolution TEXT --rationale TEXT`: persist
  one baseline-bound GM adjudication; it never accepts a pattern.
- `pattern-rule --pattern-slug SLUG --decision accept --tier campaign|portable`:
  accept exactly one Gate 1 pattern. Portable named content additionally needs
  `--named-portable-override --rationale TEXT`.
- `pattern-rule --pattern-slug SLUG --decision reject`: reject exactly one
  pattern; `--tier` is forbidden.
- `proposal-stage --proposal-id ID --draft RELATIVE_PATH`: validate and stage
  one authorized target without changing it. Repeat
  `--evidence-binding-json JSON` for canonical new evidence, or supply one
  `--override-rationale TEXT`; those forms are mutually exclusive.
- `proposal-apply --proposal-id ID`: compare-and-swap exact staged after bytes
  onto the authorized target for measurement.
- `measure --phase after --proposal-id ID`: measure the same corpus against the
  applied comparison bytes.
- `proposal-rule --proposal-id ID --decision accept|reject`: Gate 2 retains the
  comparison or restores the exact before snapshot and appends one impact entry.

## Artifacts

Iteration artifacts live at
`<session>/narration_wiki/<iteration-id>/`: `iteration.json`,
`trace-manifest.json`, `measurement-before.json`, `gate1.json`, conflict
references, drafts, portable promotion handoffs, proposal bundles, and
transaction journals.

Confirmed campaign knowledge lives at `<campaign>/wiki/`: `index.md`, pattern
pages, conflict rulings, `logs.md`, and the append-only `skill-impact.md`.
The companion deployment at `~/.claude/narration-wiki/` is always read-only to
CampaignGenerator.

## Exit categories

| Code | Meaning |
|---:|---|
| 0 | Success |
| 2 | Invalid or empty command syntax |
| 3 | Scope, containment, symlink, or companion dependency refusal |
| 4 | Lifecycle, duplicate, stale hash, unresolved conflict, or idempotency conflict |
| 5 | Invalid draft, schema, manifest, measurement, index, or evidence |
| 6 | Mutation or recovery failure |
| 70 | Unexpected internal failure |

Known refusals have no traceback and name the failed precondition without
exposing absolute host paths.

## Recovery

Run `status` after cancellation or process failure. A nonterminal transaction
is reported in `recovery` with its ID, operation, state, and next safe action.
Expected before/after hashes make recovery idempotent. If live bytes match
neither expected state, status is `needs_attention`; inspect the named journal
and do not start another mutation until the unknown bytes are adjudicated.

## Example

```bash
narration_wiki collect --campaign-dir "$CAMPAIGN" --session-dir "$SESSION" --iteration-id iter-001 --json
narration_wiki measure --phase before --campaign-dir "$CAMPAIGN" --session-dir "$SESSION" --iteration-id iter-001 --json
narration_wiki index-check --campaign-dir "$CAMPAIGN" --session-dir "$SESSION" --iteration-id iter-001 --json
```

The same commands are available at `/workflow/wiki`; the UI reloads `status`
from disk after every success, refusal, failure, or cancellation.
