# Quickstart and Acceptance Guide

This guide describes the implemented validation workflow. Run it against a disposable campaign copy and record actual results in implementation validation evidence. Browser emulation does not substitute for the real-phone scenario.

## Prerequisites and fixture contract

- Installed feature build with Python >=3.10; frontend dependencies installed using its lockfile.
- An explicit private interface reachable from the test phone, or a separately configured private Tailscale Serve origin; do not configure public sharing for this test.
- `tests/fixtures/summary_native_review/campaign/` must ship a self-contained disposable campaign: authority v1 baseline, v1 entity registry with merge/distinct/scope/type/collision cases, reviewed summaries, linked evidence, 25 NPC findings spanning all seven categories, 38 duplicate pairs and four grounding drafts. A fixture README maps each case to its expected result.
- `selections/npcs.json`, `duplicates.json`, `documents.json` materialize explicit inputs. Decision/selection templates include the exact expected fields and instruct the tester to use IDs/digests returned by their own run. No golden credential or acceptance of stale digests.

## Setup and migration

```sh
cd /tmp/campaigngenerator-547
export PYTHONPATH=/tmp/campaigngenerator-547
REVIEW_TEST_CAMPAIGN=$(mktemp -d /tmp/cg-review-547.XXXXXX)
cp -a tests/fixtures/summary_native_review/campaign/. "$REVIEW_TEST_CAMPAIGN/"
summary_native review migrate --campaign-dir "$REVIEW_TEST_CAMPAIGN" --dry-run --json
```

Review the reported target set, then execute with its returned proposal SHA:

```sh
summary_native review migrate --campaign-dir "$REVIEW_TEST_CAMPAIGN" --plan-sha256 <migration-sha> --json
summary_native review init --campaign-dir "$REVIEW_TEST_CAMPAIGN" --json
summary_native authority validate --campaign-dir "$REVIEW_TEST_CAMPAIGN" --json
summary_native review create --campaign-dir "$REVIEW_TEST_CAMPAIGN" --kind npc_verification --selection "$REVIEW_TEST_CAMPAIGN/selections/npcs.json" --json
```

Expected: version 2 authority ledger, unchanged registry v1, preserved old source/history bytes, returned review ID and all selected findings with their original diagnostics. Repeat initialization/migration to prove safe no-op. Running new review operations against the unmigrated fixture must name the migration command.

## Phone and desktop continuity

Use returned review ID as `REVIEW_ID`. Choose an address assigned to the host and an origin reachable from the phone; example below requires replacing address/port with the explicitly selected private endpoint.

```sh
summary_native review service start "$REVIEW_ID" --campaign-dir "$REVIEW_TEST_CAMPAIGN" --host <private-interface-address> --port 8766 --origin http://<private-interface-address>:8766 --json
summary_native review access issue "$REVIEW_ID" --campaign-dir "$REVIEW_TEST_CAMPAIGN" --expires-in 3600 --json
```

Open the returned capability link on an actual phone. Read the exact claim/evidence, record Approve with no-change disposition, Reject, Discuss and a note. Use the same page on desktop. Inspect through CLI:

```sh
summary_native review status "$REVIEW_ID" --campaign-dir "$REVIEW_TEST_CAMPAIGN" --json
summary_native review history "$REVIEW_ID" --campaign-dir "$REVIEW_TEST_CAMPAIGN" --json
summary_native review service stop "$REVIEW_ID" --campaign-dir "$REVIEW_TEST_CAMPAIGN" --json
```

Restart with the same explicit endpoint and reload the saved link before grant expiry. Expected: saved decisions survive; unsent notes never appear saved; same counts and reviewer/notes across phone, desktop and CLI. Repeat with network loss during a save and retry the same request ID. Verify a conflicting stale tab gets a conflict, not silent last-write-wins. Check 320/375-pixel layouts, touch controls, long Markdown and evidence. Record phone/browser, transport, screenshots and results without the capability secret.

Revoke the grant using `review access revoke REVIEW --grant <returned-grant-id>`; the old link must return a generic refusal for both reads and writes. Server stop/start must not resurrect it.

## Selected rerun and semantic checks

Use a literal selection of current rejected/discussed/mechanical-failure IDs and revisions saved to a selection file. Run `summary_native review rerun preview REVIEW --selection FILE --mode unresolved --campaign-dir "$REVIEW_TEST_CAMPAIGN" --json`, inspect its members and execute `summary_native review rerun run REVIEW --selection-sha256 SHA --campaign-dir "$REVIEW_TEST_CAMPAIGN" --json`. Test empty selection refusal and current-approved-item refusal.

Expected: exactly selected check IDs execute; source loading does not count as rerunning all checks. A selected timeout remains unresolved; completed members are retained. Regenerate an unrelated dossier, use `review refresh ... --expected-generation N`, and verify unchanged per-item approvals survive with an audited rebind. Change relevant evidence or a checking-rule revision; affected approvals must become stale.

Inspect the “second” source/“third” generated claim: citation resolution can pass, semantic support cannot become certified. Import a GM finding using `review finding add ... --finding FILE --expected-generation N`. Review typography-only findings separately, including a claimed-verbatim fixture that remains mechanically blocking. Repair a generated draft error without modifying its correct source summary.

## Identity application

```sh
summary_native review create --campaign-dir "$REVIEW_TEST_CAMPAIGN" --kind duplicate_identity --selection "$REVIEW_TEST_CAMPAIGN/selections/duplicates.json" --json
```

First preview and apply dependency adoption with `summary_native review dependencies migrate --dry-run ...` and its returned `--plan-sha256`; a reported rebuild remains a refusal until the named corpus is rebuilt. In the returned review, choose canonical identity, global alias disposition and exact pair selection. `summary_native review identity prepare REVIEW --item ITEM --expected-decision-revision 0 --scope-kind global ...` shows both immutable alternatives, registry, inspected summaries, dependent dossiers/links/citations/manifests, destination filenames, collisions and rebuild scope. Save approval through `review decide` with disposition `merge` and the exact proposal ID/digest. Inspect it with `review identity detail`, then `review identity apply REVIEW --proposal ID --proposal-sha256 SHA ...` commits it.

For receipt-listed generated work, write `{"paths":["EXACT_RECEIPT_PATH"]}` to a selection file and run `summary_native review identity regenerate REVIEW --receipt RECEIPT --selection FILE ...`; inspect the exact parser-valid jobs, then repeat with `--execute` locally. Generated prose remains pending review and sign-off. For a legacy guard, inspect `review identity resolution`, use `review identity guard-prepare REVIEW --proposal BLOCKED --reviewer GM --note REASON ...`, apply the returned exact digest with `review identity guard-apply`, and prepare a fresh merge preview.

Expected: accurate summaries retain their wording; dependent deterministic identity artifacts agree; generated prose needing rebuild/sign-off is clearly pending; unrelated artifacts/approvals remain unchanged. Reapply the same digest to get the original receipt without more changes. Scoped aliases, nonpersistent entities, type mismatch, anti-merge guard and ambiguous filenames each block with zero mutation. A distinct decision suppresses only the reviewed scope/evidence; new evidence reopens it while legacy registry guards remain intact.

Use failpoint fixtures to interrupt before/after each create/replace/delete and receipt/tip step. `review recover TRANSACTION` must resume exact approved bytes. Modify one pending target to unexpected bytes and confirm recovery makes no further mutation. Concurrent expert registry writes must respect the same pending journal.

## Grounding documents and publication

Create the document review with `summary_native review document create DOCUMENT_REVIEW --selection "$REVIEW_TEST_CAMPAIGN/selections/documents.json" ...`. Review all four drafts through the same page. Resolve every finding but leave one document unsigned: promotion must refuse. Sign each exact digest with `review document sign`. Write `{"documents":["world_state","campaign_state","party","planning"]}` to a local selection file and pass it to `review document prepare --documents FILE`. Write the returned proposal IDs and digests as `{"proposals":[{"proposal_id":"...","proposal_digest":"..."}]}` and pass it to `review document promote --proposals FILE`. Mutate one draft byte after sign-off; promotion must refuse as stale. Also verify a removed bundle dependency fails pointer validation and run `summary_native check-pointers` on all four promoted files.

## Test commands after implementation

```sh
PYTHONPATH=/tmp/campaigngenerator-547 python -m pytest -q tests/test_summary_native_review_*.py
PYTHONPATH=/tmp/campaigngenerator-547 python -m pytest -q tests/test_summary_native_authority*.py tests/test_summary_native_npc_verify.py tests/test_registry*.py tests/test_resolve_name.py tests/test_retrieve_render_isolation.py
npm --prefix /tmp/campaigngenerator-547/frontend run build
npm --prefix /tmp/campaigngenerator-547/frontend run test:e2e -- summary-native-review.spec.ts
```

Also run affected provenance/ensemble/registry-projection suites identified by the consumer inventory, existing summary-native integration tests, and the installed-wheel resource check. Use the installed console entry point with an isolated environment to avoid accidentally invoking an older editable checkout.

## Acceptance record

Map recorded evidence to SC-001 through SC-007: real phone continuity; layout; seven categories; exact rerun membership; 38-pair adjudication/refusal; three content types/four documents; idempotent recovery and unauthorized/stale mutation refusal. Include the security implementation review and adversarial real-server suite from [http-security.md](contracts/http-security.md). These are release gates; this planning document does not claim they have passed.
