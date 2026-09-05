# Session production and shared review

Open **Session → Production review** (`/workflow/cycle`) to inspect runs,
read preserved evidence, review findings, and approve a draft. Set the session
directory inside the active campaign, then Load or Initialize. Reload and CLI
changes read the same `session_workflow.yaml`. No state depends on browser storage.

The CLI uses the same request JSON as the editor's interchange panel:

```bash
session_workflow init --campaign-dir /campaign --session-dir summaries/001 --config /campaign/config/config.yaml
session_workflow status --campaign-dir /campaign --session-dir summaries/001 --json
session_workflow start --campaign-dir /campaign --session-dir summaries/001 --expected-revision 1 --request start.json
```

Each mutation requires the revision last read from status. Requests have exactly
the keyword fields below; unexpected fields refuse rather than disappear.

| Operation | JSON request fields |
|---|---|
| start | stage, selection (explicit IDs), inputs (paths), generation, dependencies (approved run IDs), required_checks |
| submit | run_id, outputs (session-relative paths), generation |
| check | run_id, check (name, status, sources, findings, producer, at) |
| decide | run_id, decisions (individual finding_id, finding_sha256, decision, actor, rationale, at, optional group) |
| approve | run_id, actor, rationale, draft_binding (from status) |
| apply | run_id, finding_ids (explicitly selected, individually approved changes) |
| select-version | run_id (approved and fresh) |
| export | run_id |
| import | document (validated exported JSON with explicit decisions) |
| evidence | an Evidence object from status or export |
| recover | empty object; complete a journaled interrupted replacement |
| migrate | config, artifacts, dry_run, force (see migration guide) |

`generation` records backend, model, effort (or null), producer, command, and
available usage. It must describe the actual producer. Use a distinct run when
changing settings. A skill receives a resolved pending task, works natively,
and submits findings or output references. It never approves its own draft.
Corrected and smoothed material is derived; never present it as verbatim.

Check `sources` must bind every output in the run. Findings include an ID, scene,
evidence, location, description, proposed action, explicit consequences for all
three decisions, and optional rule provenance and exact replacement. Evidence
objects come from status: path, sha256, snapshot, label. Check status `skipped`
or `failed` remains visible and blocks draft approval. Unmarked findings and
Discuss remain unresolved. Group discussions still produce individual records.

The editor offers explicit selection and bulk decisions, scene filters, evidence
preview, JSON download/import, and separate draft sign-off. Selecting all means
materializing the displayed IDs; clearing selection disables batch actions.
Approving a proposed change does not apply it. Applying makes a new derived
draft with fresh check and approval requirements. Approve a clean draft even
when no findings were reported. Rules may settle recurring questions only in
their recorded scope; they never sign off an unseen output.

If the workspace revision, source bytes, rule authority, or an approved dependency
changes, reload and review the new output. Never reuse stale approvals. An
interrupted application leaves originals and a transaction journal on disk.
Run `recover` to finish only if target hashes still match the journal. External
edits cause a refusal, preserving both edits and archived originals for inspection.

For old sessions, follow [the explicit migration guide](../../specs/campaign-cycle/migration.md).
