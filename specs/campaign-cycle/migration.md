# Session workflow migration

The new authoritative file is `<session>/session_workflow.yaml` (schema 1).
Existing production configuration, lineage, narration-wiki state, original VTT,
and HTML review pages keep their existing owners and locations. There is no
automatic migration on read and no dual-location state fallback.

Existing sessions have no historical human approvals in the new record.
Neither an existing output nor a `.reviewed` marker constitutes a signature.
Use the normal workflow to submit and review actual drafts after import.

Inventory without writing:

```bash
python -m session_doc.workflow.migrate --campaign-dir /campaign --session-dir summaries/001 --config config/config.yaml --dry-run
```

After reviewing the report, select the exact files to preserve:

```bash
python -m session_doc.workflow.migrate --campaign-dir /campaign --session-dir summaries/001 --config config/config.yaml --artifact session-summary.md --artifact old-review.html
```

The migrator copies exact bytes into `.session-workflow/objects/<sha256>` and
records historical evidence in YAML, without changing selected source files.
Schema-v0 inventory records with only `schema_version`, `session_id`, and
`artifacts` may be replaced with `--force`; their exact original YAML is also
preserved. Unknown fields are reported by dry-run and refuse mutation. Unknown
versions and existing schema-v1 state refuse replacement. No unsupported shape
is guessed. The operator must resolve unsupported legacy data separately.

Verify with `session_workflow status --campaign-dir /campaign --session-dir
summaries/001 --json`, inspect migration evidence and compare source hashes.
The initial record contains no approvals or inferred runs. To undo a new import,
retain its evidence and remove only the new workflow YAML deliberately; source
artifacts were never moved or edited. Keep review pages as historical evidence.
JSON decisions import only through `session_workflow import`, which validates
the session, run, draft binding and individual finding hashes. HTML is never
executed or scraped for implied approval.

The editor's interchange panel exposes `migrate` with `dry_run`, `artifacts`,
and `force` using the same migrator and report. Fresh sessions use `init`.


### Optional native calibration records

Existing workflow schema-1 state requires no migration and is not rewritten on
read. Calibration is an optional schema-1 contract at `run.task.calibration`,
created only by the explicit `session_workflow calibration-register` operation
(documented in docs/cli/session_workflow.md). Existing completed runs and approvals
are retained. Pending voice-smooth runs now require calibration approval before
submission; a refusal names the registration/decision/approval commands.

Earlier `review/calibration.yaml` and Markdown files are provisional artifacts,
not authoritative review state. They are never auto-discovered or upgraded. To
bring one into the editor, preserve its original bytes, copy its sample into the
run's review directory, construct the documented report from the selected source
and resolved authorities, then explicitly register it at the current revision.
Do not import historical null decisions or infer approval from file existence.
Verify with calibration-export and resume: the same run remains pending_agent,
all new cards are undecided, and draft approval remains absent. Registration leaves
the earlier files intact. Unsupported report schema versions are rejected by the
strict contract rather than silently converted. An explicit report replacement
archives its previous decisions and invalidates calibration approval.
