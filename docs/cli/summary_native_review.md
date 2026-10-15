# Summary-native review operations

Use `summary_native review` to adjudicate generated claims without giving the
browser permission to change campaign truth. The browser service can read a
review and save a decision. Migration, refresh, reruns, corrections, identity
changes, recovery, and publication remain local operator commands.

Run commands from the campaign root or pass `--campaign-dir`. Use `--json` for
scripts and preserve returned digests exactly.

## Initialize or migrate

Review storage requires authority schema version 2. Preview before applying:

```sh
summary_native review migrate --campaign-dir CAMPAIGN --dry-run --json
summary_native review migrate --campaign-dir CAMPAIGN --plan-sha256 SHA --json
summary_native review init --campaign-dir CAMPAIGN --json
summary_native authority validate --campaign-dir CAMPAIGN --json
```

Apply accepts only the reviewed preview digest. It refuses a stale or invalid
authority tip and uses the shared recovery journal. Review operations on an
unmigrated campaign name the required migration and never perform it silently.

**Which campaigns need this.** Any campaign whose `docs/authority.yaml` is
version 1, which is every campaign that used `summary_native authority` before
review existed. Until it is migrated, authority and review commands, `review
init` and `npc-publish` refuse with the command above. A campaign with no
`docs/authority/` is unaffected: registry commands and a migration dry run do
not create that directory.

Range builds made before review have no subject-level identity dependencies.
Identity merge planning refuses them and names the adoption. Preview it, then
apply the returned digest:

```sh
summary_native review dependencies migrate --campaign-dir CAMPAIGN --dry-run --json
summary_native review dependencies migrate --campaign-dir CAMPAIGN --plan-sha256 SHA --json
```

`summary_native build --force` on the range does the same by rebuilding it.
Without either, everything else keeps working: freshness checks read an old
manifest through its whole-registry digest, so any registry change marks the
range stale.

Verify with `summary_native authority validate --campaign-dir CAMPAIGN --json`
(the ledger reports version 2) and `review list` (empty after a fresh init).

## Create, inspect, and rerun

Selections are explicit JSON files that bound the review and later work.

```sh
summary_native review create --campaign-dir CAMPAIGN --kind npc_verification \
  --selection selections/npcs.json --json
summary_native review create --campaign-dir CAMPAIGN --kind grounding_documents \
  --selection selections/documents.json --json
summary_native review document create REVIEW --campaign-dir CAMPAIGN \
  --selection selections/documents.json --json   # add documents to an existing review
summary_native review list --campaign-dir CAMPAIGN --json
summary_native review status REVIEW --campaign-dir CAMPAIGN --json
summary_native review show REVIEW --campaign-dir CAMPAIGN --json
summary_native review history REVIEW --campaign-dir CAMPAIGN --json
```

Approve records the GM's semantic ruling. Reject and Discuss remain unresolved.
Mechanical failures remain failures until repaired and rechecked; semantic
approval cannot turn them into passes. `review refresh` preserves only
approvals whose complete semantic and custody dependencies still match.
`review finding add` records an attributable GM finding.

Use `review rerun preview` with a literal selection, inspect the membership,
then run the returned selection digest with `review rerun run`. Only those
deterministic checks execute. No model is called.

## Private browser review

Bind only to an intentionally selected private LAN or Tailscale interface and
configure the exact origin. Do not use a wildcard or public relay.

```sh
summary_native review service start REVIEW --campaign-dir CAMPAIGN \
  --host PRIVATE_ADDRESS --port 8766 \
  --origin http://PRIVATE_ADDRESS:8766 --json
summary_native review access issue REVIEW --campaign-dir CAMPAIGN \
  --expires-in 3600 --json
```

The returned URL contains a capability secret. Keep it out of logs,
screenshots, shell history, and issue text. Revoke it when review is finished:

```sh
summary_native review access revoke REVIEW --campaign-dir CAMPAIGN \
  --grant GRANT_ID --json
summary_native review service stop REVIEW --campaign-dir CAMPAIGN --json
```

`--port` defaults to `port` in `config/review.yaml` (8766), and `--expires-in`
to `grant_expiry_seconds` (one day). `review serve` takes the same arguments and
runs the service in the foreground; the app's **Start reviewer** button runs
`service start`, its background form.

In the browser, Save records the chosen verdict on the item on screen. If that
item is one of the ticked items, the verdict goes to every ticked item; ticking
items and then opening a different one never decides the ticked ones.

Expiry and revocation survive restart. The browser cannot apply corrections,
merge identities, recover journals, migrate authority data, or publish.

## Export, import, and retraction

`review export` creates a digest-bound bundle for an explicit selection.
`review import` validates the whole bundle before mutation and refuses stale or
foreign history. A withdrawal in the bundle must carry opaque ids, and every
imported authority decision record must match a decision event that is already
local or arrives in the same bundle. Reimporting an unchanged current bundle is
a no-op.

`review retract` appends a withdrawal; it does not undo an applied artifact.
`--reviewer` names who is withdrawing. The withdrawal and its audit event record
that person; the original decider stays on the withdrawal as
`withdrawn_decision_reviewer`.

```sh
summary_native review retract REVIEW --event EVENT --expected-decision-revision 1 \
  --reason 'Evidence needs renewed review' --reviewer GM --campaign-dir CAMPAIGN --json
```

## Delegated decisions: carry and policy

Two commands record decisions the GM has delegated instead of making item by
item. Because they decide on the GM's behalf they never run implicitly: each is
a dry run by default that writes nothing, `--write` is required to save, and
saving goes through the same validated, journaled path as `review decide`
(batched at `max_batch_decisions`). Every note they write names the command that
produced it, so the history shows which approvals were made by rule.

`review carry` moves approvals from an earlier review to a new one. An item is
carried only when the same item id holds a current, non-withdrawn **approve**
decision in the source review and nothing judged has changed: the same action,
claim text, diagnostic messages and source path. An NPC draft sign-off carries
only when the draft sha256 is identical and the draft still passes the
`review npc sign` guard (complete verification, mechanical pass, bytes on disk
unchanged). Proposal-bound approvals are never carried. Everything else is
listed under `needs_review` with a reason. The recorded reviewer defaults to
`<original reviewer> (carried)`; `--reviewer` overrides it.

```sh
summary_native review carry NEW_REVIEW --from OLD_REVIEW --campaign-dir CAMPAIGN --json          # plan
summary_native review carry NEW_REVIEW --from OLD_REVIEW --campaign-dir CAMPAIGN --json --write  # save
```

`review policy` approves (`accept_no_change`) items whose diagnostics carry
exactly **one** distinct `legacy_code` and that code is in a policy file — a
YAML map of `legacy_code: note`. Items with mixed codes are never touched;
items whose action cannot be waived (mechanical or GM-confirmed blockers, draft
sign-offs) are listed as `ineligible`. `--reviewer` is required. Each note names
the policy file and its sha256 prefix plus the code and the policy note.

```yaml
# policy.yaml
typography-normalised: Quote matches the evidence except for curly/straight marks.
number-inconsistency: Every number on the line was checked by hand against the evidence.
```

```sh
summary_native review policy REVIEW --policy policy.yaml --reviewer 'GM (delegated policy)' \
  --campaign-dir CAMPAIGN --json [--write]
```

Re-running either command after a write is safe: already-decided items are
skipped, and batch request ids derive from batch content, so a retried batch is
an idempotent replay.

## Corrections and exact sign-off

Source corrections reuse the reviewed-authority proposal and apply gates. An
approved proposal may change only an allowed maintained summary path and must
retain the exact ruling, span, custody, decision, and authority lineage. Draft
corrections remain preview-only.

Grounding documents require separate exact-byte sign-off. Promotion rechecks
the draft, summaries, registry and planning inputs, outline and pointer rules,
and current non-withdrawn sign-off while holding the writer lock. A changed
byte requires a new sign-off. NPC publication uses the same separation: repair
and recheck hard failures, then sign the exact dossier draft.

## Identity decisions

Only a global alias decision may produce a registry merge proposal. Scoped or
custom aliases remain Discuss/blocked. A prepared proposal lists both canonical
alternatives, every inspected path, create/replace/delete targets, collisions,
guards, and prose that still needs generation and later sign-off.

Apply the exact approved digest through the shared journal. It never calls a
model while holding the writer lock. Accurate summaries remain byte-for-byte
unchanged; edit a summary only when its facts are wrong. Distinct decisions
suppress only the reviewed scope and evidence and reopen on relevant evidence.

After apply, choose a nonempty subset from the receipt's `remaining_review_work`
and prepare its exact producer plan. Add `--execute` only from the trusted local
CLI; model work runs outside the writer lock and generated prose stays pending
review and exact sign-off.

```sh
summary_native review identity regenerate REVIEW --receipt RECEIPT \
  --selection selected-regeneration.json --campaign-dir CAMPAIGN --json
summary_native review identity regenerate REVIEW --receipt RECEIPT \
  --selection selected-regeneration.json --execute \
  --campaign-dir CAMPAIGN --json
```

Legacy distinct or rejected-alias guards require a separate reviewed exact
registry proposal. Inspect the blocked resolution, prepare it with a reviewer
and reason, apply its exact digest, then prepare a new identity preview.

```sh
summary_native review identity resolution REVIEW --proposal BLOCKED_PROPOSAL \
  --campaign-dir CAMPAIGN --json
summary_native review identity guard-prepare REVIEW --proposal BLOCKED_PROPOSAL \
  --reviewer GM --note 'Why this guard is retired' --campaign-dir CAMPAIGN --json
summary_native review identity guard-apply REVIEW --resolution RESOLUTION \
  --resolution-sha256 SHA256 --campaign-dir CAMPAIGN --json
```

## The app's Shared review page

The Shared review page (`/grounding/review`, and `/npcs/review` for dossiers)
is the trusted local face of these commands. It invokes each one through the
CLI and shows what the CLI said: a refusal arrives with its own code and
message (for example the transaction id a recovery needs), with HTTP 409 for
stale state, 423 for a pending transaction, 404 for an unknown item and 422
for an incompatible disposition. Only a command that dies without answering
reads as "Review command failed safely". **Record a decision** reads the item
named under Item ID and saves one decision bound to its current revision, the
same as `review decide`. A blank port, grant lifetime or page size uses
`config/review.yaml`.

## Recovery

For a reported pending transaction, inspect its identifier and run:

```sh
summary_native review recover TRANSACTION --campaign-dir CAMPAIGN --json
```

Recovery accepts only approved before/after bytes. Unexpected bytes, symlink
paths, stale proposals, authority mismatches, or incomplete inspected inputs
refuse with no further writes. Do not delete or hand-edit journals to bypass a
refusal.
