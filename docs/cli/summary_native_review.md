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

## Classified noise: `review noise`

NPC verification resolves some number/ordinal and status occurrences on its own,
because they are provably not story facts. Each one is recorded as **classified
noise** with its class, the token, the one sentence it sits in, the scenes that
sentence cites and, where relevant, the word or scene that resolved it. The same
record is the `## Classified noise` section of `<stem>.verify.md`. The checks are
deterministic code and make no model call. Nothing is resolved silently, and an
occurrence that matches no class stays a normal finding. Noise is never recorded
as a GM decision unless the GM, or the GM's standing policy, says so: an unmarked
noise item stays undecided.

Every occurrence is its own review item, with a single diagnostic whose
`legacy_code` is `noise-<class>`. An occurrence belongs to exactly one class, the
first that applies in this precedence order:

| Class (precedence order) | Meaning | Example |
|---|---|---|
| `label` | a chapter or scene label, a range after a chapter word, or a leading list numeral | "In Chapter 036, Blasius warns…"; "chapters 028-064" |
| `idiom` | an ordinal inside a curated idiom (`data/ordinal_idioms.yaml`) | "for the first time", "at first", "third person" |
| `negated-status` | a status word in a sentence that says no status is established | "No further status (alive, dead, escaped) is established" |
| `spelled-number` | a spelled-out number or comma-grouped number whose digit form a cited scene states | "five gold pieces" vs "5 gp"; "a thousand" vs "1,000" |
| `synonym` | a status word supported by a reviewed synonym (`data/status_synonyms.yaml`) | "departed" vs evidence "leaves" |
| `other-citation` | a number absent from one cited scene but present in another scene the same sentence cites | "200" is in 085.07, and the sentence cites 085.07 and 085.08 |

A number in none of the scenes the sentence cites is a finding, not noise, and it
names the token, the sentence and the cited scenes.

```sh
summary_native review noise REVIEW --campaign-dir CAMPAIGN [--json]    # read-only
```

Text mode prints one line per class, for example `label  281 (281 undecided)`.
Classes always appear in precedence order, and an empty class shows `count: 0`.
`--json` adds every occurrence with its `item_id`, NPC, draft line, token,
sentence, cited scenes, `resolved_by` and current decision.

`review noise decide` records one verdict on one class, as one decision per
undecided occurrence. Like `carry` and `policy` it is a dry run by default and
`--write` saves it, through the same validated, journaled `submit_decisions` path.
`--class`, `--verdict {approve,reject}`, `--reviewer` and `--note` are all
required; there is no all-classes form. `approve` records `accept_no_change` and
`reject` records `reject_action`. The saved note is prefixed
`GM class verdict on batch card [noise-<class>] (<n> occurrences): ` and then your
note.

```sh
summary_native review noise decide REVIEW --class label --verdict approve \
  --reviewer GM --note 'Chapter labels are not story facts' --campaign-dir CAMPAIGN --json          # plan
summary_native review noise decide REVIEW --class label --verdict approve \
  --reviewer GM --note 'Chapter labels are not story facts' --campaign-dir CAMPAIGN --json --write  # save
```

An occurrence that already has a current decision, including a Discuss, is
skipped and listed under `already_decided`. It is never overwritten. A rejected
class shows as GM disagreement with the classification, which is the signal to
fix the tables or the rules.

| Refusal | Cause |
|---|---|
| `REVIEW_NOISE_UNKNOWN_CLASS` | `--class` is not one of the six classes; the message lists them |
| `REVIEW_NOISE_NOTHING_TO_DECIDE` | the class has no undecided occurrences |
| `REVIEW_NOISE_NOTE_REQUIRED` | `--note` is blank |
| `REVIEW_NOISE_NOTE_TOO_LONG` | the note, once prefixed, exceeds `max_note_chars` |

**Standing auto-approve.** Because each noise item has exactly one `legacy_code`,
`review policy` already covers a class. Name `noise-<class>` in the policy file
and only that class is approved, each item with a note naming the policy and the
class. A class covered by a policy gets no batch card, and its occurrences stay in
the audit record.

```yaml
# policy.yaml
noise-label: "chapter labels are not story facts"
```

The six `noise-*` codes (`noise-label`, `noise-idiom`, `noise-negated-status`,
`noise-spelled-number`, `noise-synonym`, `noise-other-citation`) are a public
contract, because policy files key on them.

**On the review page.** Unless a policy covers it, the review-artifact kit shows
one card per class listing every occurrence with its token, sentence, cited scenes
and resolving evidence. One verdict on the card expands to one decision per
occurrence, each carrying the provenance note above. A card left unmarked leaves
every occurrence undecided. The app exposes the same two commands as
`GET /{review_id}/noise` (runs `review noise REVIEW --json`) and
`POST /{review_id}/noise/decide` with body
`{noise_class, verdict, reviewer, note, write}` (runs `review noise decide`). The
routes only build argv and shell out.

## Per-item custody: what a decision depends on

A review records the exact bytes of every file it was built from (its source
custody). A decision is refused only when a file **that item rests on** has
changed, not when any file in the review has. An item's dependency set is
computed at check time from the custody record, the item's bindings and the
bytes of the NPC's evidence file; nothing extra is stored.

For an NPC verification item the set is:

- the sources the item binds, plus the evidence of the other items on the same
  draft, plus the draft's `<range>/evidence/<stem>.md` twin when custody holds
  it (a union only ever over-includes);
- the summaries that evidence file names in its `- Source: <path> (line N)`
  lines. The GM ruled that summaries belong to the set: a corrected summary
  makes the claims drawn from it stale, so it refuses. It reads the file only
  while its bytes still equal what custody recorded;
- any custody source of an unrecognised kind.

Any other item rests on what it binds, the sources no item binds, and
unrecognised kinds.

**The fallback widens, never narrows.** If the item has no evidence at all, every
evidence file joins; if the evidence file cannot be read, is not current, or has
any irregular `Source:` line or `## Chapter` section, every summary joins. A
refusal can therefore be broader than necessary, never narrower. On the real
stormgiants review (`npc-review-6ee694eebf5b`, 781 items, 164 drafts) no item
falls back; changing one draft stales only that NPC's items, and changing
`010-session-the-seer.md` stales the 8 NPCs whose evidence names it
(`tests/test_summary_native_custody_baseline.py`, read-only replay).

### The refusal

`review decide` (and `review npc sign`, `carry --write`, `policy --write`,
`noise decide --write`, which submit through it) and `review import` check every
submitted item under the writer lock. One stale item refuses the whole batch
and nothing is written. The exit code is 3. Text mode:

```text
REVIEW_STALE_CUSTODY: 2 source file(s) changed; 3 submitted item(s) depend on them; nothing was saved
  changed  docs/npcs/summary_native/ch001-086/draft/npc_nug.md: nug — npc-…, npc-signoff-…
  missing  docs/summaries/010-session-the-seer.md: blasius — npc-…
Bring them current: summary_native review refresh npc-review-6ee694eebf5b --expected-generation 5
A changed draft also needs a new verification review before its sign-off can be approved.
```

An import says `nothing was imported`. With `--json` the same code arrives with
`data` (`version`, `operation` = `decide` or `import`, `review_id`,
`review_generation`, `changed_files`, `stale_items`, `by_npc`, `remedy`):
`changed_files` lists only files a submitted item depends on, each with its
`state` (`changed`, `missing`, `unreadable`) and the submitted items resting on
it; `stale_items` lists every stale item (an item with no dependency at all
carries `"reason": "no_dependency"`); `by_npc` groups them. The local routes relay
`data` verbatim; the phone reviewer shows a whitelisted `detail` and HTTP 409.

**Remedy.** Run the named `review refresh REVIEW --expected-generation N`, which
the tool never runs for you. A changed **draft** also needs a new
`npc-verify` and a new verification review before its sign-off can be approved:
refresh rebinds custody, it does not re-verify a draft.

### `review status`: `changed_files` and `stale_by_npc`

`review status` keeps `review_id`, `generation`, `item_count` and `counts`
unchanged and adds two keys, both computed from the **current files** at call
time: `changed_files` (`path`, `role`, `state`, `stale_item_count`, only for
custody sources that are not current) and `stale_by_npc` (per NPC: `npc`,
`npc_key`, `stale_item_count`, `stale_item_ids`, `changed_files`). Both are `[]`
when nothing changed.

`counts.stale` is the **live** count: the number of items that depend on a file
that is not current, which is exactly the total of `stale_item_count` across
`stale_by_npc`. It moves the moment you edit a file, before any refresh.

**Migration note (#647).** Before, `counts.stale` meant "items a past
`review refresh` marked stale", so it read 0 right after an edit while
`stale_by_npc` was populated. That figure is still there, renamed
`counts.stale_at_last_refresh` (a new key; same value the old key had). A reader
that wanted the old meaning must read the new key; a reader that only wanted "how
many items are stale" now gets the right number from `counts.stale`. In the
repo, only `review status` output carries this key; the Shared review page's own
`show` counts and the review-artifact kit do not read it.

`counts` is not a partition: an approved item whose files changed is counted in both `approved` and the live `stale`, and `pending` counts only items marked at the last refresh. Publish still refuses such an item.

`counts.pending` still includes an item stale at the last refresh and is not
changed by this.

### Refusals and `--limit`

`review show --limit N` accepts `1` to the configured `max_page_items` (default
50). Outside that range it exits 2 with code `REVIEW_PAGE_INVALID` and
`data: {"parameter": "limit", "requested": N, "minimum": 1, "maximum": M}`. In
`--json` mode a refusal that has no structured detail carries
`data: {"refused": "<message>"}` rather than `null`; `ok` is the verdict.

### Non-ASCII dossier ids (#630)

A dossier selection `id` that is already a plain opaque id (`[A-Za-z0-9][A-Za-z0-9_.-]*`) is
used unchanged, so existing reviews keep their item ids. Any other id (for example
`aerasumé`) is folded to ASCII through `npc_slug.slug_for` and suffixed with `-` and
8 hex digits of the SHA-256 of the original id (`aerasume-3f2a9c1d`), so two ids that
fold alike never collide. The NPC label shown to the GM is the original `npc` name.

### Withdrawals are always allowed

`review retract` never reads source bytes. Withdrawing a decision on a stale item
works, so you can take back an approval whose evidence has changed. A bundle
whose only new events are withdrawals also imports when its items are stale.

### Import

`review import` keeps its record-level check (the bundle's custody digest must
match the local one, which catches a bundle from a copy refreshed independently)
and adds the per-item byte check above for every decision event the import would
append. An imported decision on an item whose files have changed refuses with
`operation: "import"`.

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
