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

## Create, inspect, and rerun

Selections are explicit JSON files that bound the review and later work.

```sh
summary_native review create --campaign-dir CAMPAIGN --kind npc_verification \
  --selection selections/npcs.json --json
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

Expiry and revocation survive restart. The browser cannot apply corrections,
merge identities, recover journals, migrate authority data, or publish.

## Export, import, and retraction

`review export` creates a digest-bound bundle for an explicit selection.
`review import` validates the whole bundle before mutation and refuses stale or
foreign history. Reimporting an unchanged current bundle is a no-op. `review
retract` appends a withdrawal; it does not undo an applied artifact.

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

## Recovery

For a reported pending transaction, inspect its identifier and run:

```sh
summary_native review recover TRANSACTION --campaign-dir CAMPAIGN --json
```

Recovery accepts only approved before/after bytes. Unexpected bytes, symlink
paths, stale proposals, authority mismatches, or incomplete inspected inputs
refuse with no further writes. Do not delete or hand-edit journals to bypass a
refusal.
