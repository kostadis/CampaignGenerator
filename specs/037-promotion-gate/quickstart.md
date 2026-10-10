# Quickstart and Validation Guide

This guide validates the implemented commands. Use disposable campaign copies only; do not point validation at the original Phandalin campaign.

## Prerequisites

- Install the wheel or editable package into an isolated test environment with Python >=3.10.
- An initialized authority ledger v2 and shared review store from #546/#547.
- A complete four-document range with timeline, nested references, run/path records and required dependencies. The implementation fixture factory must produce both a pristine campaign and a validated prior live bundle.
- Frontend dependencies and the project's configured Playwright browser for UI checks.

## 1. Disposable workspace and explicit migration

The fixture factory `tests/fixtures/summary_native/promotion/create_campaign.py` creates a synthetic campaign containing range 001–003, reviewed-source metadata and an existing structurally valid live bundle. It performs no model calls or network requests.

```bash
python tests/fixtures/summary_native/promotion/create_campaign.py --campaign-dir /tmp/cg548-validation
migrate_grounding_bundle --campaign-dir /tmp/cg548-validation --dry-run --json
migrate_grounding_bundle --campaign-dir /tmp/cg548-validation --plan-sha256 <returned-sha> --json
migrate_grounding_bundle --campaign-dir /tmp/cg548-validation --verify --json
```

Expected: exact alias/config/member preview; all original bytes retained; one adopted generation; unrelated documents unchanged. Hash the entire fixture before and after dry-run and confirm no created/deleted/changed files, including locks/reports. A partial or unsafe prior bundle refuses.

## 2. Selected claim workflow

```bash
summary_native claims select --config /tmp/cg548-validation/config/grounding.yaml --since 1 --until 3 --json
summary_native claims selection chunks --config /tmp/cg548-validation/config/grounding.yaml --input <proposed-selection.json> --source <source-id> --json
summary_native claims selection save --config /tmp/cg548-validation/config/grounding.yaml --input <confirmed-selection.json> --reviewer "Acceptance GM" --json
summary_native claims import --config /tmp/cg548-validation/config/grounding.yaml --selection <saved-selection.json> --candidates <fixture-candidates.json> --json
summary_native claims review --config /tmp/cg548-validation/config/grounding.yaml --selection <saved-selection.json> --candidates <run-id> --review promotion-check --json
```

Inspect exact proposed mappings in the existing shared review UI or CLI. Approve correct interpretations using their current digests/revisions; reject/discuss others. These choices are synthetic fixture decisions, never retroactive rulings on original campaign facts. The same flow with explicit `claims extract --selection ... --backend ... --model ...` validates optional extraction once requested; deterministic acceptance can use imported candidates without spending tokens.

The existing CLI has parity for each review action. Inspect current item/review digests and revisions first:

```bash
summary_native review show promotion-check --config /tmp/cg548-validation/config/grounding.yaml --json
summary_native review decide promotion-check --config /tmp/cg548-validation/config/grounding.yaml --decisions <decisions.json> --json
```

The decision file uses the existing strict request shape (replace values with those returned by show; do not reuse sample revisions blindly):

```json
{"version":1,"request_id":"acceptance-mapping-001","review_generation":1,"reviewer":"Acceptance GM","decisions":[{"item_id":"<mapping-item>","item_revision":1,"review_digest":"<returned-sha256>","expected_decision_revision":0,"verdict":"approve","disposition":"accept_no_change","note":"Confirmed the displayed interpretation of this exact source span."}]}
```

For a semantic finding, prepare the exact proposed dismissal or accepted-uncertainty action, then show it and approve its new current item/digest through the same `review decide` request. Reject/Discuss use the existing `reject_action`/`defer` dispositions. Do not apply a dismissal to a mechanically blocking item.

```bash
summary_native claims prepare-disposition --config /tmp/cg548-validation/config/grounding.yaml --review promotion-check --item <finding-item> --expected-decision-revision <current-N> --disposition dismiss --rationale "<evidence-backed reason>" --json
```

Run checks, resolve findings, and run again with current decisions:

```bash
summary_native claims check --config /tmp/cg548-validation/config/grounding.yaml --selection <saved-selection.json> --review promotion-check --json
summary_native claims show --config /tmp/cg548-validation/config/grounding.yaml --report <report-id> --json
```

Expected: paired source locations and six-category reports; no model invocation from check. Confirmed false claims block until source correction/regeneration. A current evidence-backed dismissal or explicitly accepted uncertainty remains in the report. Pending/Discuss, missing required evidence and failed selected extraction block. Each of four v2 document items then requires an exact sign-off through the existing review controls, or repeat this CLI command for each returned world_state, campaign_state, party and planning item:

```bash
summary_native review document sign promotion-check --config /tmp/cg548-validation/config/grounding.yaml --item <document-item> --document-sha256 <returned-document-sha256> --expected-decision-revision <current-N> --reviewer "Acceptance GM" --json
```

The sign command must validate the v2 context as well as bytes and refuse unresolved required findings. `review show` supplies current IDs/revisions; never synthesize approval IDs from a filename.

## 3. Preview and publish

```bash
summary_native promote --config /tmp/cg548-validation/config/grounding.yaml --since 1 --until 3 --review promotion-check --check-report <report-id> --dry-run --json
summary_native promote --config /tmp/cg548-validation/config/grounding.yaml --since 1 --until 3 --review promotion-check --check-report <report-id> --preview-sha256 <returned-sha> --request-id acceptance-001 --json
summary_native promotion status --config /tmp/cg548-validation/config/grounding.yaml --json
summary_native promotion receipt --config /tmp/cg548-validation/config/grounding.yaml --operation <operation-id> --json
```

Expected: all four documents, actual `canon_events_timeline.md`, full nested references, retained records, complete copied-byte checks and one activated generation with a completed receipt. The receipt exposes original review events and completion/recovery timing honestly. Git status may show campaign artifacts, but no commit or push occurs.

Repeat the identical request: no additional content changes. Publish a later generation, then repeat the earlier completed request: return its historical receipt without changing current. Edit a live prose file after preview: commit refuses stale preview; source sign-off is preserved when its own evidence is unchanged.

## 4. Fault and concurrency gates

Implementation test modules should include:

```bash
python -m pytest tests/test_summary_native_promotion.py tests/test_summary_native_promotion_recovery.py tests/test_grounding_bundle_readers.py tests/test_migrate_grounding_bundle.py
python -m pytest tests/test_summary_native_claims.py tests/test_summary_native_claims_review.py tests/test_summary_native_claims_phandalin.py
python -m pytest tests/test_summary_native_review_documents.py tests/test_summary_native_review_routes.py tests/test_summary_native_no_llm.py tests/test_state_docs_no_live_writes.py
```

Required assertions:

- Failures before activation leave the exact prior live bundle and unrelated files intact. Fail receipt preparation and every write/sync/check boundary. Crash after pointer swap returns/reconciles committed or explicit unknown, never a fictitious rollback.
- A continuous supported reader during publication sees only complete old/new generations. Two contenders cannot both commit against the same expected prior state.
- Hash changes in source/ref/timeline/rules/review reject; destination drift only invalidates preview. New findings cannot inherit sign-off accidentally.
- Traversal, arbitrary symlinks, corrupt current/activation history, alias detachment, mixed ranges, incomplete output and old per-document publication all refuse.
- Each reconstructed Phandalin shape has bad and positive controls, source provenance and a reconstruction label. Assert no “latest wins” for Petra, no model verdict for suspicion/hostility, no leaking GM-only evidence into party outputs.
- Dry-run leaves zero file changes. Pure promotion/check modules remain AST-guarded against model imports/calls; only explicit extractor may reach campaignlib's seam.

Broaden regression coverage to shared reader/config/migration seams and required wheel Python versions. Do not run unrelated model-producing campaigns as a substitute for these tests.

## 5. Application and phone acceptance

```bash
npm --prefix frontend run build
npm --prefix frontend run test:e2e -- summary-native-promotion.spec.ts
```

From the application's SummaryNative Promotion panel, choose the same disposable range and repeat source selection, import/extraction invocation, checks, review launch, preview, publication, receipt and migration/recovery inspection. Compare CLI/HTTP result codes and input digests. The UI must expose every meaningful option and cannot hardcode an override.

Using the existing private LAN/Tailscale review service, open the disposable review from an actual phone. Confirm both claims/evidence, a long sectioned document, selected action feedback, persisted queue badges, Save and next, and reconnect/reload continuity. Phone saves only review decisions; publish from the trusted application or CLI. Stop/revoke test services after acceptance. No new capability URL is created by this guide.

## Completion evidence

Record exact commands/results and acceptance limitations in validation.md during implementation. Distinguish reconstructed rule coverage from unavailable historical replay, automated browser checks from actual-phone reports, process-kill recovery from physical-power-loss guarantees, and passing deterministic checks from human semantic sign-off.
