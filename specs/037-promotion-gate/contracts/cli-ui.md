# CLI and Application Contracts

Implemented commands. Execute all domain behavior through the installed `summary_native` or `migrate_grounding_bundle` console scripts. Paths below are campaign-relative unless --config or --campaign-dir specifies the campaign itself. New commands return the existing `{ok, code, message, artifacts, data}` envelope with --json.

## Shared scope

- Config uses existing `find_default_config()` semantics. `--config PATH` is resolved after parsing; no fallback to the toolkit checkout.
- Range operations require explicit `--since N --until N`; `--out-root PATH` has the existing summary-native default. No absent selection means all, latest, or current.
- The selected output root must be contained in the campaign. Managed live paths are fixed by layout, never an arbitrary destination argument.
- New promotion/claims settings live once in `GroundingConfig` under a strict optional `summary_native.promotion` block. Existing config without the block gets documented centrally defined defaults; UI uses unset sentinels. No rewriting of existing config merely by reading it.
- Backend/model/token/chunk options exist only on candidate extraction and reuse the existing add_backend_args/config precedence. `--force` only regenerates explicitly selected cached candidate outputs; it never bypasses freshness, review, migration or conflicts.

## Whole-bundle promotion

```text
summary_native promote --config PATH --since N --until N [--out-root PATH]
  --review REVIEW --check-report REPORT --dry-run [--json]
summary_native promote --config PATH --since N --until N [--out-root PATH]
  --review REVIEW --check-report REPORT --preview-sha256 SHA --request-id ID [--json]
summary_native promotion status --config PATH [--operation ID] [--json]
summary_native promotion receipt --config PATH --operation ID [--json]
summary_native promotion recover --config PATH --operation ID [--json]
```

Dry-run and commit modes are mutually exclusive. `--dry-run` never writes. It returns manifest/diffs, gate results, expected live identity and canonical preview digest even when blocked (with nonzero exit and refusal reasons). An explicitly requested report ID must refer to the same selected bundle and current evidence; stale/foreign IDs refuse. Before the claims stage is implemented the foundation exposes `claims: not_available` and is not represented as completion of #548; final feature release requires the integrated gate.

Commit needs an eligible recomputed preview digest and request ID. Reusing a request ID with changed intent refuses; retry of a completed identical operation returns its original receipt without moving current, including when a later publication has happened. The command prints success only after durable reconciliation. `commit_unknown` is a recovery outcome with an operation ID, never an implied rollback.

Status and receipt are read-only. Status may report drift, pending migration, blocked inputs or unknown activation with exit 0 and `data.state`; inspection is not a failed publication. Recover aborts a preactivation attempt or reconciles activation; it cannot silently publish a prepared orphan. A new publication requires a fresh explicit commit.

Legacy `summary_native review document prepare/promote` returns `PROMOTION_WHOLE_BUNDLE_REQUIRED` with replacement instructions. Their application endpoints return the same refusal. Old proposals/receipts remain inspectable but cannot acquire live-publication authority. Existing create/sign/review/export/import capabilities remain; old sign-off rule versions need fresh v2 items for this gate.

## Claim selection, extraction, checking and review

```text
summary_native claims select --config PATH --since N --until N [--out-root PATH]
  [--sources FILE] [--json]
summary_native claims selection chunks --config PATH --input FILE [--source ID ...] [--json]
summary_native claims selection save --config PATH --input FILE [--reviewer NAME] [--json]
summary_native claims extract --config PATH --selection FILE
  [--backend NAME] [--model NAME] [--max-tokens N] [--chunk-chars N]
  [--force] [--json]
summary_native claims import --config PATH --selection FILE --candidates FILE [--json]
summary_native claims review --config PATH --selection FILE
  [--candidates RUN] --review REVIEW [--json]
summary_native claims check --config PATH --selection FILE --review REVIEW [--json]
summary_native claims show --config PATH --report REPORT [--json]
summary_native claims prepare-disposition --config PATH --review REVIEW --item ITEM
  --expected-decision-revision N --disposition dismiss|accept_uncertainty
  --rationale TEXT [--json]
```

`select` is read-only and emits a proposed manifest. Existing range/corpus selection is displayed explicitly, with candidate source suggestions; --sources supplies the user's exact source/horizon selections. `selection chunks` materializes explicit whole-source chunk choices without expanding scope. To use the selection, the GM confirms its exact chunks/sources; `selection save --reviewer` may add that explicit confirmation to an otherwise unconfirmed canonical input. Extract/import refuse a manifest missing `confirmed_by`, `confirmed_at`, or its exact confirmed digest. These fields record selection, not source truth or a cryptographic authentication claim.

`extract` spends tokens only on listed chunks and never silently expands sources. It writes immutable run revisions beneath `state/promotion/claims/`; truncated/malformed output gets an explicit failure with preserved diagnostics. Changing backend/model/selection/rules invalidates cache reuse. `import` validates hand-prepared candidates against the same selection/excerpts and creates an attributable candidate run; imported candidates still require review.

`review` creates or updates typed mapping items and the four v2 document-signoff items in the shared review, marking affected prior approvals stale as needed. When no candidates are selected it still exposes deterministic structured-source coverage and explicit semantic limits. `check` computes mechanical findings from accepted mappings and active structured authority, merges selected semantic candidate findings, and writes immutable JSON/Markdown reports. It registers new required finding items with stable revisions and stales affected sign-off eligibility. Repeating identical inputs reuses report content; no unnecessary new reviews.

Review workflow order is select → optional extract/import → review mappings → check → resolve findings → check current resolutions → sign off four documents → preview → promote. Final gate evaluation includes sign-offs but does not alter the report content to which those sign-offs bind.

`prepare-disposition` creates an exact evidence/rationale-bound action revision offered in shared review. It does not record approval. On the phone, Approve accepts the displayed prepared dismissal/uncertainty action; Reject means correction needed and Discuss remains unresolved. Existing `review correction prepare/apply` handles source repairs. No freeform note is interpreted as authority or a disposition.

`show` displays immutable report data and current freshness separately. Export uses the existing shared-review export for decisions and the named report files for findings. No second import/export authority format is introduced.

## Explicit migration

```text
migrate_grounding_bundle --campaign-dir DIR --dry-run [--json]
migrate_grounding_bundle --campaign-dir DIR --plan-sha256 SHA [--json]
migrate_grounding_bundle --campaign-dir DIR --status [--json]
migrate_grounding_bundle --campaign-dir DIR --verify [--json]
migrate_grounding_bundle --campaign-dir DIR --recover --operation ID [--json]
```

Exactly one mode. Recovery identifies operations with `--operation ID` throughout the family; the separate one-shot migrator uses boolean mode flags, following the repository migrator grammar. Dry-run includes the complete before/after/config/alias inventory and whether the baseline is validated legacy or pristine absent. Unknown ownership, partial incompatible live bundle or unsafe paths refuse with instructions. Apply binds the preview digest; --force is not offered because overwriting an unreviewed inventory would be unsafe. Ordinary promotion cannot run migration. See [migration.md](../migration.md).

## Exit semantics for these new commands

| Exit | Meaning |
|---|---|
| 0 | Completed operation, or successful inspection (state may still be blocked/unknown) |
| 2 | Invalid selection/path/schema, unsupported layout/platform, migration or legacy-command refusal |
| 3 | Stale preview, report, review or dependency; refresh/review required |
| 4 | Pending recovery or unknown commit outcome; operation ID supplied |
| 5 | Blocking finding, incomplete declared check/extraction, authority conflict or missing sign-off |
| 70 | Execution/model transport failure; selected incomplete work retained |

Preserve existing unrelated command exit meanings. Model failure never becomes a clean deterministic report. Stable codes include `PROMOTION_MIGRATION_REQUIRED`, `PROMOTION_WHOLE_BUNDLE_REQUIRED`, `PROMOTION_STALE_PREVIEW`, `PROMOTION_BLOCKED`, `PROMOTION_COMMIT_UNKNOWN`, `PROMOTION_PATH_CONFLICT`, `CLAIMS_INCOMPLETE` and `CLAIMS_STALE`.

## Local application parity

Typed routes under `/api/grounding/summary-native` invoke the commands above using fixed argv and bounded JSON execution. Long extraction/checking uses existing SSE subprocess execution; browser disconnect follows the existing job behavior and never invents success. Do not hold a domain lock during model streaming. Domain results/errors retain CLI codes.

| User control | Route / underlying command |
|---|---|
| Select campaign range and see source proposal | POST `/claims/select` → claims select |
| Confirm/save explicit source/chunk selection | POST `/claims/selection` → persist exact validated selection via CLI selection input mode |
| Extract candidates / import prepared candidates | POST `/claims/extract`, `/claims/import` |
| Create/open shared review | POST `/claims/review` + existing ReviewLauncher service/access controls |
| Prepare dismissal/uncertainty action | POST `/claims/disposition` → claims prepare-disposition |
| Run checks / read report | POST `/claims/check`, GET `/claims/reports/{id}` |
| Preview complete bundle | POST `/preview` → promote --dry-run |
| Confirm displayed exact preview | POST `/commit` → promote with digest/request ID |
| Status / receipt / recover | GET `/status`, GET `/receipts/{id}`, POST `/recover` |
| Migration preview/apply/status/verify/recover | Matching `/migration/*` controls invoking the separate migrator |

`claims select --sources FILE` may emit its selection to stdout; `claims selection chunks` creates the exact chunk scope and the explicit selection-save operation accepts a file or stdin (`claims selection save --input FILE|- [--reviewer NAME]`) using the same strict contract. Unlike read-only `select`/`chunks`, save writes canonical bytes only to `<range>/state/promotion/selections/<selection-sha256>.json` and returns that campaign-relative path plus digest. It derives the range from the validated selection and refuses arbitrary output paths, foreign campaign IDs, or a conflicting existing digest. Repeating the same scope and reviewer preserves the original confirmation timestamp/digest and returns the same path. No browser-only selection state or route-only policy.

Promotion panel shows range, all six member classes, complete added/removed paths, live human-edit differences, report basis/coverage, four sign-offs, blocking reasons, activation state and receipt. Button feedback persists across reload; a pending request is distinct from saved or published. Empty selection disables invocation and engine still refuses it. After a stale response, refresh preview rather than auto-submit a new digest.

The private capability review server remains read/review-save only. It receives no promotion, migration, arbitrary source-selection or model-extraction power. Existing CSRF/origin/path/size/audience limits remain; new action validation applies to every transport. Phone review must preserve long-document section loading, selected button feedback, queue badges and Save and next.
