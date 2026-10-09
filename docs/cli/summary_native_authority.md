# Summary Native: reviewed corrections and classified notes

Summaries remain the source of campaign truth. Authority records preserve the
GM's instructions, review decisions, scope, and history in `docs/authority.yaml`.
A ruling changes campaign truth when its reviewed replacement is applied to the
maintained summary. Regenerate affected projections after applying it.

Use **Grounding Docs → Summary-native** for the corresponding controls. The UI
calls the same CLI operations described below. Keep the campaign configuration
selected throughout a workflow so the preview and apply use the same workspace.

## Initialize and inspect

Set `CAMPAIGN_DIR` to the absolute campaign directory. Examples use the campaign's
`config/config.yaml`; substitute its actual configuration path if different.

```bash
summary_native authority init --campaign-dir "$CAMPAIGN_DIR"
summary_native authority validate --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native authority status --json --config "$CAMPAIGN_DIR/config/config.yaml"
```

Initialization creates an empty ledger and refuses to overwrite an existing one.
`status` reports its revision and digest and any pending transaction. Preserve
both the ledger and `docs/authority/`, which contains immutable review artifacts,
events, snapshots, journals, and receipts.

## Review and apply a correction

1. Author a ruling record with an exact source path and anchor, rejected text,
   replacement text, source digests, audience, effective interval, and affected
   projections. Start a new ruling in `draft` status. Use exact registry identities
   for entity/thread subjects and named characters. A `topic` subject needs no
   entity registry entry.
2. Stage the record and inspect the proposed ledger revision. Accept that revision
   using the stage digest and the current ledger digest returned by the workflow.
3. Create a source proposal. Inspect its exact before/after diff and record the
   displayed proposal digest.
4. Apply that digest, then inspect the receipt and history.
5. Rebuild affected inputs and regenerate the affected projections; review their
   drafts before promotion.

```bash
summary_native authority record stage /tmp/ruling.yaml --json --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native authority record apply "$STAGE_ID" --stage-sha256 "$STAGE_SHA" --expected-ledger-sha256 "$LEDGER_SHA" --json --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native authority propose "$RULING_ID" --json --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native authority apply "$RULING_ID" --proposal-sha256 "$PROPOSAL_SHA" --json --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native authority history "$RULING_ID" --json --config "$CAMPAIGN_DIR/config/config.yaml"
```

The uppercase variables stand for values returned by the preceding command;
never reuse a digest from an older preview. Record schemas and annotated examples
are in the [ledger contract](../../specs/035-gm-ruling-authority/contracts/authority-ledger.md).
The source adapter accepts an exact replacement in a maintained summary. A missing
or ambiguous passage, changed source, unsupported target, or overlap with claimed
verbatim text requires a new review. It does not edit recordings or transcripts.

Use `authority list`, `show ID`, and `history ID` to inspect current and historical
state. To retire an eligible record, pass `record retire ID --reason TEXT
--expected-revision N --expected-ledger-sha256 SHA`. Retiring preserves history;
applied source changes use the withdrawal procedure below.

### Revise a record without losing history

For an active note, keep its ID and set `revision` to exactly the current value
plus one. Update its source digest when the classified content changes, then use
`record stage` and `record apply` with the fresh ledger digest. The previous
revision remains in the mutation history.

A draft ruling can be revised the same way. To correct a ruling that has already
been proposed but has not been applied, stage its next revision in `draft` status
and clear its `proposal_id`. Accept the revision, then create and review a new
proposal. Old proposal artifacts remain, but their approval digest is stale.
An applied ruling uses withdrawal; it cannot be reset to draft through record
revision.

## Regenerate after source or policy changes

Follow the existing [build, extract, and synthesis workflow](summary_native_howto.md)
for the affected chapter range. For example:

```bash
summary_native build --since 2 --until 57 --force --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native extract --since 2 --until 57 --force --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native synth world_state --since 2 --until 57 --force --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native synth campaign_state --since 2 --until 57 --force --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native synth party --since 2 --until 57 --force --config "$CAMPAIGN_DIR/config/config.yaml"
```

If the corrected summary already has a classification note, its previous
`content_digest` becomes stale. Review the corrected section, update that active
note to the next revision with the new digest, and stage/apply the revision
before regeneration. This is an explicit refresh of the classification record.

Existing document prerequisites, including audit and planning support, still
apply. Planning with configured notes also needs the reviewed selection digest
and audience described below. `--force` requests regeneration; it cannot bypass
approval, stale digests, source restrictions, audience coverage, or recovery.
Authority manifests explain the record/source/selection generation used by a run.
An input change during generation makes that result stale.

## Select classified planning notes

Stage and accept note records through the same record workflow. Each record names
an anchored source section and its digest, classification, audience, interval,
projections, and selection label. `PREP` and `OVERLAY` also need a planning date.
Then add explicit selectors to `config/planning.yaml`, preserving other settings:

```yaml
notes:
  - id: commission-plan
    path: notes/neverwinter/the_commission.md
    record_ids: [commission-current-plan]
  - id: town-notes
    path: notes/town/*.md
```

Paths resolve from the campaign root; absolute external paths are disclosed in the
preview. Exact paths and globs materialize into a sorted, deduplicated selection.
Inspect concrete files, sections, selection reasons, classifications, audiences,
warnings, and external markers before using its digest.

```bash
summary_native authority notes preview --audience gm --json --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native synth planning --since 2 --until 57 --authority-selection "$SELECTION_SHA" --audience gm --force --config "$CAMPAIGN_DIR/config/config.yaml"
```

A changed note or glob membership requires a fresh preview. Missing, unreadable,
empty, or zero-match configured selections refuse. Omitting `notes` preserves
summary-only planning; setting `notes: []` is an error.

| Classification | Interpretation |
|---|---|
| `CANON`, `TABLE` | Established evidence. An overlapping contradiction needs explicit resolution; neither wins by its label or timestamp. |
| `RULED` | Reviewed source-change instruction and audit history. |
| `PREP` | Intended future material. |
| `OVERLAY` | Current planning direction ahead of conflicting `PREP` within its scope. Equal conflicting overlays need review. |
| `OPEN` | Unresolved material. |

Future plans never become completed history merely by inclusion. Non-overlapping
chapter intervals can describe legitimate evolution.

## Choose an audience

Targets are `gm`, `players`, `characters`, or `character:<exact-character-id>`.
Player knowledge and character knowledge have separate grants. `characters`
includes individual characters; `players` does not grant them access. GM review
can inspect all declared records.

Extract and synthesize for the same target; planning also uses that target's
reviewed selection digest. For example, after classifying the required sources:

```bash
summary_native extract --since 2 --until 57 --audience players --force --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native synth world_state --since 2 --until 57 --audience players --force --config "$CAMPAIGN_DIR/config/config.yaml"
```

Use the existing model/backend options for extraction and synthesis. Non-GM
checked notes and run artifacts use separate audience directories beneath the
range's `state/audiences/`; GM retains its existing state location. Ordinary
planning notes retain their note/anchor provenance and are not assigned chapter
numbers for extraction.

Unclassified legacy material is GM-only. A non-GM request with incomplete required
source coverage refuses; add reviewed classifications before retrying. Filtering
must cover inputs, references, fallbacks, diagnostics, and caches as well as prose.
A GM preview or cached result cannot stand in for a character view.

### Classify complete support documents

Structured inputs such as YAML registries and JSON audit artifacts need a
complete-document grant before a non-GM loader can use them. A support note
record uses the reserved source anchor `__document__` and a `content_digest`
computed from the complete, unchanged file. For example, its source fields are:

```yaml
source:
  path: config/players.yaml
  anchor: __document__
content_digest: "<SHA-256 of the complete file>"
```

Supply the remaining required note fields, including classification, effective
scope, audience grants, projections, reviewer, and selection label, then stage
and accept the record normally. This grant authorizes the entire file: review
its complete contents for the target audience. Partial section grants cannot
silently authorize a complete registry, configuration, dossier, or audit input.

The reserved anchor is only for reading support documents. It cannot be used to
apply a maintained-summary correction, and it requires no added comments or
markup in YAML or JSON. Ordinary planning prose keeps its section anchors.

## Resolve conflicts

```bash
summary_native authority conflicts --status open --json --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native authority conflict resolve "$CONFLICT_ID" --resolution-record /tmp/resolution.yaml --expected-ledger-sha256 "$LEDGER_SHA" --json --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native authority conflict history "$CONFLICT_ID" --json --config "$CAMPAIGN_DIR/config/config.yaml"
```

Inspect both source scopes and affected projections. The resolution file must
identify the matching applied ruling. Record the human resolution explicitly; file recency does not choose a winner. Structured comparable claims
can be checked deterministically. Prose candidates require human judgment. Inspect
history after resolution to see why subsequent runs differ.

To record a contradiction you noticed yourself, name the existing records and
choose whether it is a human-identified conflict or a prose candidate needing
review. Repeat `--record` for each record:

```bash
summary_native authority conflict identify "$CONFLICT_ID" --record "$FIRST_RECORD" --record "$SECOND_RECORD" --basis prose_candidate --reason "Needs GM comparison" --expected-ledger-sha256 "$LEDGER_SHA" --json --config "$CAMPAIGN_DIR/config/config.yaml"
```

A prose candidate receives no automatic truth verdict. After review, dismiss a
false finding explicitly, preserving the reason and prior history:

```bash
summary_native authority conflict dismiss "$CONFLICT_ID" --reason "The passages describe different circumstances" --expected-ledger-sha256 "$LEDGER_SHA" --json --config "$CAMPAIGN_DIR/config/config.yaml"
```

Use a fresh ledger digest after each accepted operation. A disposition applies
to the compared record revisions; revising a claim can produce a new finding.
Compatible records may share the same evidence without becoming a conflict.

## Withdraw safely

```bash
summary_native authority withdraw "$RULING_ID" --reason "Later GM decision" --json --config "$CAMPAIGN_DIR/config/config.yaml"
```

Withdrawal requests a reviewed reversal; it does not immediately restore old
source bytes. Inspect and apply the returned reversal proposal through the same
proposal-digest checkpoint. Unrelated later edits remain. If the corrected passage
has itself changed, author and review a replacement against the current source.
The original ruling, approval, and receipt remain in history.

## Recover an interrupted operation

If status reports a pending transaction, inspect its ID and run:

```bash
summary_native authority recover "$TRANSACTION_ID" --json --config "$CAMPAIGN_DIR/config/config.yaml"
summary_native authority validate --config "$CAMPAIGN_DIR/config/config.yaml"
```

Recovery finishes the approved transaction from its recorded snapshots and can
be repeated safely. Unexpected current bytes cause refusal instead of overwrite.
Preserve those files and the journal for inspection. Do not delete the pending
journal to make generation proceed.

| Exit | Meaning | Next step |
|---:|---|---|
| 0 | Completed | Inspect returned artifacts or continue. |
| 2 | Invalid record, selection, audience, source, or target | Correct the reported input and validate again. |
| 3 | Stale proposal, selection, manifest, or draft | Refresh and review the relevant preview or regenerate. |
| 4 | Recovery required or unexpected transaction bytes | Inspect status and recover the named transaction. |
| 5 | Blocking conflict or incompatible proposal | Review the conflicting scopes and resolve explicitly. |

`--json` returns `ok`, `code`, `message`, `artifacts`, and `data`. Specific error
codes refine these categories while retaining the numeric exit. Follow the exact
next command supplied by a refusal.

## Adopt in an existing campaign

There is no previous general authority ledger to convert. Initialize an empty
ledger deliberately, then stage reviewed records and selectors. Old derived
caches/run records need regeneration before authority-aware use; they are not
silently upgraded. Existing source-only workspaces need no authored migration.
Preserve records after adoption; reverse an applied correction through withdrawal.

These stores retain their existing roles:

- `docs/summary_native/canon.yaml`: not-a-duplicate and link decisions.
- `docs/corrections.yaml`: known-stale provenance context.
- `transcript_corrections.yaml`: transcript repair.

Their entries are not imported as general rulings. See the
[adoption guide](../../specs/035-gm-ruling-authority/migration.md),
[CLI contract](../../specs/035-gm-ruling-authority/contracts/cli.md), and
[transaction contract](../../specs/035-gm-ruling-authority/contracts/transaction.md)
for schema and recovery details.
