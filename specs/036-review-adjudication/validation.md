# Implementation Validation — Issue #547

## Current status

Implementation and automated validation are complete. Task completion is tracked in tasks.md. All 66 tasks are complete, including T026/T053/T066 following the recorded iOS/Tailscale walkthrough and final grant/service cleanup. User-reported phone observations and independently verified audit evidence are distinguished below. The sections below are chronological checkpoints: later rechecks explicitly close earlier findings. The constitution table reflects the current gate status; test counts from separate runs are never additive.

## Environment and entry gate

- Worktree: `/tmp/campaigngenerator-547`; branch `codex/547-review-adjudication`; base `9feedcf35ce8f7dc8083b75b595231dae483a2a2`.
- Implement prerequisite script found spec/plan/tasks and supporting design artifacts.
- Read-only checklist gate: requirements.md 16 total / 16 checked / 0 unchecked. No checklist markers changed by implementation.
- No before_implement or after_implement hooks configured.
- Git ignore verification: Python/Node/environment/build/log/editor patterns already present. Frontend npm package is private. No Dockerfile, ESLint/Prettier configuration, Terraform or Helm setup detected; no irrelevant ignore files added.
- Use `PYTHONPATH=/tmp/campaigngenerator-547` when testing worktree code; existing installed editable console entry points may otherwise resolve the original checkout.
- Sandbox-local FastAPI tests stalled. The root's initial baseline process was stopped (only its PID1690806); the same baseline was restarted with escalated local test permissions. This is an environment retry, not a passing result.

## Baseline

Command: `PYTHONPATH=/tmp/campaigngenerator-547 python -m pytest -q tests/test_summary_native_authority*.py tests/test_summary_native_npc_verify.py tests/test_registry*.py tests/test_resolve_name.py tests/test_retrieve_render_isolation.py`.

Log: `/tmp/campaigngenerator-547-baseline-escalated.log`. Result: **599 passed in 34.53 seconds**. Collected before production changes; this is the pre-change baseline, not implementation verification.

## Required acceptance evidence

- SC-001/002: durable 25-item NPC phone review and actual-phone/desktop/CLI continuity; viewport emulation alone is insufficient.
- SC-003/004: seven taxonomy categories; exact selected checking; semantic versus custody freshness and unrelated approval survival.
- SC-005: 38-pair identity adjudication, global-only safe application and scoped/collision refusal.
- SC-006: shared decisions across NPC, identity and four grounding drafts with explicit document sign-off.
- SC-007: recovery/replay, no unexpected overwrite, unauthorized/stale mutation refusal.
- Written security implementation review, adversarial actual-service tests, installed-wheel resource smoke and existing affected regressions.

## Foundation snapshot verification

Root ran `PYTHONPATH=/tmp/campaigngenerator-547 python -m pytest -q tests/test_summary_native_review_models.py tests/test_summary_native_review_transactions.py tests/test_summary_native_review_migration.py`: **28 passed in 0.58s** at this intermediate snapshot. Store/CLI integration and additional audit-reference/tip-hardening checks were still in progress; this does not mark the foundation complete.

## Foundation regression checkpoint

Root independently ran `PYTHONPATH=/tmp/campaigngenerator-547 python -m pytest -q tests/test_summary_native_review_models.py tests/test_summary_native_review_transactions.py tests/test_summary_native_review_migration.py tests/test_summary_native_review_foundation.py tests/test_summary_native_authority*.py`: **144 passed in 23.63s**. Log: `/tmp/campaigngenerator-547-foundation-regression.log`. This includes strict campaign-identity decoding and read-time custody binding changes. Additional authority-reference hardening is under review and will be rechecked after its final edits.

An earlier focused snapshot of the foundation plus basic authority module passed **40 tests in 1.91s**. These are separate runs, not additive coverage totals.

## Constitution implementation gates

This table tracks implementation evidence independently of the design's PASS assessments. Pending rows are not release approval.

| Principle | Evidence required | Implementation disposition |
|---|---|---|
| I. Disk is Truth | Durable decision/history/restart tests; exact publication approval | PASS: real restart and immutable store; exact four-document and NPC publication gates |
| II. Human Checkpoint | Explicit review/apply/sign-off refusal tests | PASS focused: correction, document and NPC exact gates; 38-pair identity refusal and save/apply separation |
| III. Retrieval/Render Separation | Existing isolation regression plus no new model invocation | PASS: broad 3,141-pass run plus focused verification of its sole compatibility failure; retrieval isolation included |
| IV. Verbatim | Source correction exactness and hard verifier blockers | PASS: genuine #546 exact-input integration and nonwaivable NPC verifier/publication tests |
| V. One Seam per Boundary | Bounded CLI invocation from both HTTP surfaces | PASS: bounded runner and real HTTP/CLI; regeneration uses the existing SSE seam; final route tests pass |
| VI. CLI Owns Workflow | CLI decision/mutation contracts and thin route evidence | PASS: public decisions, publication, identity apply/replay and executable receipt-bound regeneration |
| VII. Deliberate Synthesis | Instrumented selected checks and affected-only regeneration | PASS: selected checks/refresh/rerun; real selected compose producer, complete-range link selection and pre-run cleanup CAS |
| VIII. Discoverable State | Status/history/recovery/blocked-state UI and CLI evidence | PASS: stale/read counts, exact prepared alternatives, receipt projection, pending recovery and visible controls |
| IX. Shared Human Workflow | Phone, desktop and CLI share decisions; Discuss unresolved | PASS: real Chromium/CLI and iOS/Tailscale saved-decision continuity; final grant/service cleanup verified |
| X. Explicit Selection | Empty/all-scope refusal, bound previews and literal batches | PASS: explicit selections, 38-pair matrix, empty/broadened regeneration refusals and canonical output mapping |
| XI. Bidirectional Parity | Complete command/flag-to-control audit | PASS: route/UI audit and explicit regeneration SSE execution test |
| XII. Shared Option Semantics | Shared config/defaults and no approval-bypass flag | PASS: shared config, publication/force refusal and parser-valid regeneration arguments |
| XIII. Explicit Migration | v1 refusal, preserved snapshots, digest-bound migration/recovery | PASS: public authority/dependency migration, retry, preserved data and final recovery suites |

## Quickstart execution findings

The first root CLI run against a fresh copy of `tests/fixtures/summary_native_review/campaign/` refused at `review migrate --dry-run` with `AUTH_STALE: authority ledger has no valid mutation-history tip`. The disposable v1 fixture needs valid #546 history; weakening migration verification is not an acceptable fix. Reported to the implementation owner. No later quickstart steps were counted as passed.

After the fixture received a matching v1 initialization event/tip, root repeated the public CLI workflow on `/tmp/cg547-root-acceptance-2fx0rbvq`: migration dry-run, digest-bound migration apply, review init, repeated init with unchanged campaign ID, repeated migration dry-run reporting no-op, and authority validate all passed. The resulting authority ledger is version 2/revision 2. Later story acceptance has not yet run.

Packaging setup: isolated build tooling installed at `/tmp/cg547-wheel-build-env/bin/python`; this is only environment preparation, not a passing wheel smoke.

## US1 decision checkpoint

Root ran `PYTHONPATH=/tmp/campaigngenerator-547 python -m pytest -q tests/test_summary_native_review_decisions.py tests/test_summary_native_review_foundation.py tests/test_summary_native_review_verification_adapter.py`: **15 passed in 1.65s**. This covers an intermediate decision-store/adapter implementation, not completed server or UI acceptance.

A separate root temporary-campaign probe created an entity-subject item, saved its approval, loaded the updated ledger and called `validate_record_identity`: passed after the subject mapping fix.

Root also reran migration/transaction/foundation tests after further hardening: **24 passed in 0.97s**. These checkpoint totals are separate runs and must not be added together.

## Resolved integration finding: stale import

Root reproduced on a temporary campaign: approve item at decision revision 1; export; reject at revision 2; import old export with unchanged review generation 1. Import incorrectly accepted and changed counts from rejected=1/approved=0 to rejected=0/approved=1. This blocks T017 completion until a regression proves stale import refuses with zero mutation and accepted imports preserve exact revision/provenance bindings.

## Independent running-service checkpoint

Root exercised the real service on loopback using public CLI dispatch and HTTP against disposable campaign `/tmp/cg547-root-acceptance-2fx0rbvq`, review `npc-review-0c557187cc67`:

- Created the selected 25-item NPC queue through `review create`.
- Started managed service on an ephemeral loopback port and issued a 1-hour capability without printing or retaining its raw token.
- Read the protected shell and 25-item queue, then saved one Approve/no-change, one Reject and one Discuss with notes in one explicit batch: HTTP 200.
- Retried the identical request: HTTP 200 with identical result.
- CLI status agreed: approved=1, rejected=1, discussed=1, pending=22.
- Revoked the grant: subsequent protected read and save both returned 404.
- First stop reported an error while the test process still owned the child process (possible zombie-state lifecycle bug). After the test parent exited, a separate CLI status reported running=false and stop safely returned stopped=false. No running acceptance service remains. This lifecycle observation was sent to the coding owner; it is not recorded as a passing stop test.

This proves HTTP/CLI continuity on loopback. It does not substitute for browser rendering, actual-phone continuity, all adversarial tests or later stories.

## Shared subprocess regression

After review transport added bounded stdin support, root ran `PYTHONPATH=/tmp/campaigngenerator-547 python -m pytest -q tests/test_subprocess_runner.py tests/test_subprocess_abort.py`: **19 passed in 7.72s**. Log: `/tmp/campaigngenerator-547-subprocess-root.log`. This checks the shared runner and existing disconnect/abort behavior; review lifecycle/browser disconnect acceptance remains separate.

## US2 intermediate checks and refresh finding history

Root ran decision/rerun/refresh suites: **16 passed in 3.48s**. These are intermediate contracts, not full US2 acceptance.

A separate root probe exposed an uncovered regression: approve under `ordinal-check` rule version 1; refresh under version 2 correctly marks the item stale; refresh again at generation 2 with current version 2 incorrectly preserves the item and restores approved=1/stale=0. This blocks T033 completion. Refresh must compare to each immutable item's reviewed semantic/rule dependencies, not only the preceding manifest. Relevant surrounding identity/citation context also needs proof beyond finding an unchanged excerpt once in the file. Sent to the coding owner.

Stale-import finding recheck: root repeated the original temporary-campaign reproduction after the fix. Importing the current export returned `imported_events=0`; importing it after a newer rejection refused, with every campaign file byte unchanged. The reproduced overwrite finding is closed. Broader cross-campaign/provenance tests remain part of final interchange acceptance.

## Local adapter and refresh checkpoints

Root independently ran `tests/test_summary_native_review_routes.py`: **9 passed in 2.04s**. Log: `/tmp/campaigngenerator-547-routes-root.log`. One existing main-app OpenAPI warning names the unrelated `scene_editor.api_polish` operation. Route tests do not substitute for visible component controls or result rendering.

Root reran `tests/test_summary_native_review_refresh.py`: **6 passed in 1.38s**, including the new repeated-refresh and heading-change regressions. The specific approval-resurrection finding is closed; full paragraph/citation context preservation remains under review because heading-plus-excerpt alone misses changed surrounding attribution.

## 2026-10-10 intermediate integration review

Root ran `PYTHONPATH=/tmp/campaigngenerator-547 python -m pytest -q tests/test_summary_native_review_refresh.py tests/test_summary_native_review_identity.py tests/test_summary_native_review_dependencies.py tests/test_summary_native_review_migration.py`: **34 passed in 8.52s**. This includes paragraph-context refresh coverage. Dependency helpers do not yet prove integration with all real corpus writers and consumers; T043 remains open.

An independent grounding-document probe exposed a publication gap: sign world-state draft, prepare promotion, append draft bytes, then apply the original proposal. Apply succeeded and created a receipt/destination. This must refuse with zero writes. Document application also needs exact dependency and current-signoff validation under the writer lock. Reported to Sol; this is an open finding, not a passing US4 gate.

Root repeated the broad legacy regression checkpoint with local test sockets enabled:

```sh
PYTHONPATH=/tmp/campaigngenerator-547 python -m pytest -q tests/test_summary_native_authority*.py tests/test_registry*.py tests/test_resolve_name.py tests/test_summary_native_npc_verify.py tests/test_retrieve_render_isolation.py
```

**599 passed in 30.97s**. Log: `/tmp/campaigngenerator-547-registry-review-regression.log`. This run predates the complete T041 shared registry-loader lock integration; it is not the final T064 result. The apparent pause was normal test execution, not a root-suite deadlock.

## Installed wheel checkpoint

`/tmp/cg547-wheel-build-env/bin/python -m build --wheel --no-isolation --outdir /tmp/cg547-wheel-artifacts` built `campaigngenerator-0.1.0-py3-none-any.whl`. Root installed it into `/tmp/cg547-wheel-smoke-env` and ran from `/tmp` with `PYTHONPATH` unset: module provenance was the wheel's site-packages; packaged viewer HTML/JS/CSS were present; installed `summary_native review --help` passed. Runtime dependencies were reused through a `.pth` pointing at `/home/kostadis/.venv/lib/python3.14/site-packages`; this is packaging/entry-point evidence, not clean dependency-resolution proof. Final wheel smoke and missing-asset refusal remain T062/T064 work.

## Read projection finding (open)

Root independently reproduced rule-change refresh followed by divergent reads: `review_status` returned approved=0/stale=1, while `_show_review` (the dedicated service read path) returned approved=1/stale=0/settled=1 and item freshness=current. The viewer must use the same coherent freshness/decision projection as status and must not allow stale old evidence to masquerade as current approval. Reported to Sol.

## Live Chromium review checkpoint

Root exercised fresh 25-item disposable campaigns through public CLI migration/init/create and a managed loopback service. At 375×812, the real packaged viewer saved two explicitly selected Discuss decisions with a note; CLI agreed, progress remained 0/25 settled, no page JavaScript errors or horizontal overflow. In a second run, another tab at 320×740 attempted an older revision, displayed the competing-decision conflict, reloaded, then successfully saved a new approval. Root waited for `Saved 1 decision` (not the preexisting `Saved` marker) and confirmed CLI approved=1/discussed=1/unresolved pending=24. Both viewports fit. Each grant was revoked and each service stopped successfully. Probes: `/tmp/cg547-live-browser-probe.py`, `/tmp/cg547-tabs-browser-probe.py`. These are emulated viewports, not physical-phone acceptance.

Stale-read projection recheck now agrees: after rule-change refresh, both status and show report approved=0/stale=1, show settled=0, item freshness=stale. The reproduced read mismatch is closed.

Changed-draft-after-preview recheck now refuses `REVIEW_DOCUMENT_STALE`, with every campaign file hash unchanged and no destination created. That narrow finding is closed. A separate source freshness gap remains: change the underlying `summaries/001-fixture.md` after preview while leaving the corpus manifest untouched; promotion still succeeds. Exact live source and captured reference-bundle dependencies must be checked, not just manifest bytes.

After T041 shared registry-lock integration, root repeated the same broad authority/registry/name-resolution/NPC-verifier/isolation command: **599 passed in 31.86s**, log `/tmp/campaigngenerator-547-lock-regression.log`. Independent fork and thread probes confirmed writers wait while the parent/thread holds the campaign lock and acquire after release. This is evidence for the lock implementation; complete consumer/identity crash recovery remains T051/T052.

Root also ran document and correction suites together: **18 passed in 2.33s**. Code review found correction tests do not prove #546 adapter reuse: the new source correction path fabricated a ruling ID and directly journaled a bound file. T034/T037 require real summary-only #546 ruling/proposal integration, not only passing synthetic correction fixtures; reported to Sol.

Adversarial service checkpoint: root independently ran security-regression, HTTP, local-route and shared-subprocess suites together: **28 passed in 24.21s**. See `security-review.md` for exact scope and remaining gates.

T041 cached-consumer finding: warming `entity_registry.resolve._load_registry`, then preparing a pending journal, produces `AUTH_RECOVERY` on direct registry load but permits the cached resolver read. This is an open boundary gap despite the passing broad tests. Reported to Sol with a disposable-campaign reproduction.

Root's warmed-cache pending-journal recheck now refuses `AUTH_RECOVERY` for both direct and cached registry reads. The specific bypass is closed. Root also ran rerun, verification taxonomy and adapter suites: **12 passed in 1.29s** after durable member recording/scoped-check integration. Full real selected-CLI acceptance remains distinct.

Installed-wheel final feature checkpoint (T062): root independently ran `PYTHONPATH=/tmp/campaigngenerator-547 python -m pytest -q tests/test_summary_native_review_installation.py tests/test_installable_wheel.py`: **11 passed in 12.93s**. Log: `/tmp/campaigngenerator-547-wheel-root.log`. Includes installed asset provenance, real installed CLI authority/review initialization away from checkout, and safe generic failure when each required asset is absent. Packaging must still be included in the final T064 run after all code changes.

Scoped verifier checkpoint: root ran `tests/test_summary_native_review_scoped_verification.py tests/test_summary_native_npc_verify.py`: **32 passed in 1.89s**, covering the real scoped checks and existing verifier behavior.

Cross-feature rerun/rebind finding (open): on the refresh fixture, root replaced the initial approval with Reject, appended an unrelated paragraph, and refreshed. Refresh correctly preserved `item-1` with no stale items; unresolved preview succeeded, but execute refused `rerun live dependency bytes changed or are stale`. Rerun bound the immutable item's old full-file custody hash rather than the current audited rebind. Reported to Sol for a cross-feature regression and correction.

## Public document CLI checkpoint and bundle finding

Root ran public `review document create`, signed all four exact document hashes, prepared an explicit four-document selection, promoted it and repeated promote. All four returned receipts and replay returned identical receipts on `/tmp/cg547-doc-cli-94gzpsk2/campaign`.

Inspection then exposed a required integration failure: public `summary_native check-pointers .../state/reviewed/world_state.md --config .../config/config.yaml` exited **2** because six `reviewed/reference/*.md` files and `reviewed/timeline.md` were missing. The exact promoted document declares those paths relative to itself, but promotion copied only the main drafts. This remains a T058 blocker until the exact referenced bundle is staged and destination pointers pass existing checks. The successful CLI responses prove invocation/replay, not completed valid publication.

The stable combined document/correction/migration/rerun/authority-transaction suite passed **55 tests in 4.43s** independently. A simulated crash immediately after native #546 restaging now resumes successfully in a root probe; complete durable recovery/related input freshness remain part of correction integration.

## 2026-10-10 integration rechecks

Root independently ran document, correction, refresh, dependency and migration suites together: **50 passed in 4.95s**. This includes the real configured corpus writer/adoption test and exact non-target correction-input refusal. It is an intermediate run, not the final regression gate.

Refresh/interchange regression: adding an unrelated paragraph, preserving the item through generation-2 refresh, exporting the current item and importing that exact export now returns `imported_events=0`. The prior `KeyError: item_id` from treating a review-level rebind event as an item decision is closed.

The public four-document CLI scenario was repeated with realistic outline-compliant drafts in `/tmp/cg547-doc-cli-root-be5vnbyl/campaign`: create, four exact sign-offs, explicit four-document prepare, promote, and identical receipt replay all succeeded. Public `check-pointers` exited **0** for each reviewed `world_state.md`, `campaign_state.md`, `party.md`, and `planning.md`. The earlier broken destination bundle finding is closed. Physical-phone/long-document UI acceptance is separate.

New dependency finding (open): build/adopt the clean corpus with Manshoon absent from the registry, then add `Manshoon` as an alias of the unrelated Alice Vale entity. Actual grouping now resolves `npc/Manshoon` to Alice Vale, but `check_fresh` incorrectly returns current because the dependency closure considers changed canonical names without aliases that capture existing headings. Reproduction: `/tmp/cg547-alias-freshness-root-u7n534hy`. Reported to Sol for an integration regression and correction before final acceptance.

Identity closure finding (open): root added an existing published dossier at the production `npc_publish` destination `docs/npcs/bob_stone.md` to the identity recovery campaign. Preparing an Alice-survivor proposal returned no blocking reasons, but the published file was absent from `inspected_paths`. The initial inventory scans synthetic ownership subdirectories and hyphenated names; the actual publisher uses `schema.NPCS_DIR` and `npc_slug.slug_for`. Campaign: `/tmp/cg547-real-published-root-x6ihaf2b/campaign`. T044/T048 complete-closure acceptance remains open until real published/range NPC artifacts and references are inventoried through existing path conventions.

Alias-capture freshness recheck: the original adopted campaign now refuses freshness with `entity registry changed since build — run summary_native build --force` after the alias captures the existing heading. That reproduced finding is closed.

Live restart continuity: on `/tmp/cg547-restart-browser-yj368m8f/campaign`, Chromium at 320 pixels loaded an item, selected Discuss and typed a note; root restarted the loopback service without reloading the page. Save fetched a fresh CSRF nonce and returned HTTP 200/`Saved 1 decision`, with the exact note preserved. CLI agreed (discussed=1, unresolved=25); zero page errors. Grant revoked and service stopped. Script: `/tmp/cg547-restart-browser-probe.py`. Earlier probe attempts exposed a separate real UI race: CSS `display:grid` overrides `hidden`, making decision controls usable before asynchronous item load, after which loading clears early input. Reported to Sol; this remains a UI finding until fixed.

Long-document read acceptance: `/tmp/cg547-longdoc-browser-probe.py` served a 197,406-byte outline-compliant Unicode world-state draft through the actual loopback service. Chromium at 320×740 loaded four bounded sections through the final marker, retained the exact full-document SHA-256 display, and reported zero JavaScript errors and no horizontal overflow. Campaign `/tmp/cg547-longdoc-browser-7yqmleb8/campaign`; grant revoked and service stopped. This verifies document read/transport rendering, not the separate exact sign-off action or physical-phone gate.

Audited-rebind/rerun recheck: root repeated Reject → unrelated paragraph → generation-2 refresh with preserved item → unresolved preview → execute selected citation checker. The member now completes successfully; the prior stale old-custody refusal is closed. This is a cross-feature callback-seam probe, distinct from the final public real-verifier scenario in T038.

After four-document promotion and replay, public `authority validate --campaign-dir /tmp/cg547-doc-cli-root-be5vnbyl/campaign --json` returned `OK`, ledger revision 7. This validates the resulting publication authority references in addition to destination pointers.

Real browser sign-off→CLI integration: the long-document probe was extended on `/tmp/cg547-longdoc-browser-qwx3nv1g/campaign`. After reading all four sections, Chromium saved one Approve decision with the exact note. Public CLI reported approved=1/pending=3, history recorded `document_signoff`, and `review document prepare` produced one document-promotion proposal. There was no publication. Grant revoked and service stopped. The harness initially used a list index on the CLI history envelope after prepare; independent public history and proposal inspection confirmed the result, and the harness envelope access was corrected. This confirms separate document sign-off through the actual HTTP/CLI seam.

## Public identity acceptance checkpoint

Root ran `/tmp/cg547-identity-public-probe.py` through the public CLI engine on a fresh complete fixture, with explicit authority and dependency adoption, 38 selected pairs, both canonical previews for each pair, and one exact approved merge. Campaign `/tmp/cg547-identity-public-root-ibixp52j`, review `duplicate-review-ec3d82807937`; per-pair outcomes are in `preview-results.json` there.

Pair 01 applied successfully. The receipt covers registry replacement, canonical corpus dossier replacement, loser dossier deletion, manifest update, and both regenerated validation reports. Replay returned the identical receipt, summary SHA-256 values remained unchanged, and public authority validation returned `OK`.

The scenario is **not yet a complete T053 pass**: all eight path-collision/authored-conflict cases (07, 08, 15, 16, 23, 24, 31, 32) returned applicable despite expected refusal. The other 30 classifications agreed. Reported to Sol to reconcile actual production path handling and fixture materialization. An unchanged preview retry also refused `REVIEW_PROPOSAL_CONFLICT` (global scope omitted `value`, while the normalized model includes null); reported for repair. Post-apply `review show` lacks an application/receipt projection, so the saved approval is visible but its committed application is not yet discoverable from the shared viewer DTO.

### Identity refusal matrix and browser recheck

The fresh 38-pair scenario now matches every expected classification: **5 applicable safe pairs, 33 blocked scoped/nonpersistent/type/guard/collision/authored-conflict pairs**. Campaign `/tmp/cg547-identity-public-root-a8ewe1sh`, review `duplicate-review-95604c68ac8d`, log `/tmp/cg547-identity-public-root-latest.log`. The eight prior collision/conflict mismatches are closed. Pair 01 again changed the exact six receipt paths, retained source-summary hashes and replayed identically. Shared item reads now expose `application.state=applied`, receipt ID/digest, changed paths and remaining reviewed work; the missing application projection is closed.

Actual browser prepared-alternative flow: `/tmp/cg547-identity-browser-probe.py` opened the real 38-pair service at 375×812, selected Candidate 1A's exact proposal digest, and saved one approval. The saved event carried disposition `merge` and matched a prepared ID/digest; registry bytes were unchanged after save. Public local CLI application then succeeded with a receipt. Zero browser errors/overflow; capability revoked and service stopped. Campaign `/tmp/cg547-identity-browser-zokgdibl/campaign`. An initial harness launch used relative `PYTHONPATH=.` and therefore failed service startup after its cwd changed; the successful run used the required absolute worktree path. This is browser emulation, not physical-phone evidence. Public distinct suppression/reopening and affected-only regeneration remain independent acceptance work.

Unchanged preview retry recheck: the original failing campaign now returns `REVIEW_IDENTITY_PREPARED` twice with identical full proposal results. The scope-null normalization finding is closed.

Two-range preservation finding (open): root added a real built/adopted `ch011-011` containing only Zelda to the Alice/Bob recovery campaign. An Alice-survivor merge preview has no blockers but schedules a replacement of `derived/summary-native/ch011-011/manifest.json`, solely to advance its whole-registry snapshot. Campaign `/tmp/cg547-unrelated-range-root-o6h8g4dc/campaign`. This defeats the promised preservation of unrelated artifacts after subject-level adoption; reported for a real two-range regression and selective write-set correction.

### Independent public distinct decision / evidence reopening

Root ran `/tmp/cg547-distinct-root.py` against a fresh complete fixture at
`/tmp/cg547-distinct-root-99vardeb` using public migration, initialization,
review creation and decision CLI parsers. Pair 01 was a real duplicate candidate
before review; a distinct decision suppressed it in the real parsed-summary
`duplicates.find_possible_duplicates` consumer. Inserting new material evidence
under Candidate 1A reopened the same pair. Registry bytes remained identical.
Review: `duplicate-review-573f1778da56`. This closes the public producer-to-consumer
distinct evidence-binding check; physical-phone acceptance remains unperformed.

### Final focused NPC, transport, preservation checkpoints

- Root ran `PYTHONPATH=/tmp/campaigngenerator-547 /home/kostadis/.venv/bin/python -m pytest -q tests/test_summary_native_npc_publish.py tests/test_cli_npc_publish.py tests/test_summary_native_review_scoped_verification.py`: **44 passed in 3.02s**. Includes production public exact NPC signoff, stale evidence/draft refusal, and mechanical failure refusal under force.
- Sol ran the independent US2 batch `python -m pytest -q tests/test_summary_native_review_verification.py tests/test_summary_native_review_verification_adapter.py tests/test_summary_native_review_scoped_verification.py tests/test_summary_native_review_refresh.py tests/test_summary_native_review_rerun.py tests/test_summary_native_review_corrections.py tests/test_summary_native_npc_publish.py tests/test_cli_npc_publish.py`: **75 passed in 6.16s**. Covers all seven finding categories, diagnostic preservation, exact scoped checks, approval survival/staleness, genuine #546 corrections and publication gates. This is separate evidence, not an additional total.
- Root ran `PYTHONPATH=/tmp/campaigngenerator-547 /home/kostadis/.venv/bin/python -m pytest -q tests/test_summary_native_review_http.py tests/test_summary_native_review_security_regressions.py tests/test_summary_native_review_routes.py tests/test_subprocess_runner.py tests/test_subprocess_abort.py`: **47 passed in 31.96s**, one existing duplicate OpenAPI operation warning from `scene_editor.py`. Real loopback servers and FastAPI tests required socket-capable execution. Log: `/tmp/campaigngenerator-547-security-final-root.log`. An initial command used a nonexistent test filename and collected nothing; the corrected command above is the evidence.
- Root reran unrelated-range preservation with a fresh identity campaign and the real adopted Zelda corpus: `/tmp/cg547-unrelated-final-root-ewu1gsgf/campaign`. Preview excludes the unrelated range and application preserves all **six** range files byte-for-byte. The previous manifest over-write finding is closed. Existing immutable previews retain their original payload; this check intentionally prepared a fresh preview.
- Root created two approved NPC findings, one for Bob Stone and one for Zelda, then applied the Alice/Bob merge at `/tmp/cg547-stale-approval-root-si0hz5ki/campaign`. Before apply neither approval was stale; after apply only the affected Bob finding was stale. The staleness event is in the same identity journal. Unrelated approval remains current. Probe: `/tmp/cg547-stale-approval-root.py`.

T049/T050 remain open while executable affected-only regeneration and reviewed conflict resolution are completed; merely storing a schedule does not satisfy them.

### Installed wheel final regression

Root ran `PYTHONPATH=/tmp/campaigngenerator-547 /home/kostadis/.venv/bin/python -m pytest -q tests/test_summary_native_review_installation.py tests/test_installable_wheel.py`: **11 passed in 16.73s**. Log: `/tmp/campaigngenerator-547-wheel-final-root.log`. Unlike the early manual `.pth` smoke, these tests built and installed the wheel with its declared dependencies and ran from a directory outside the checkout. Late regeneration changes will receive focused installed-entry-point validation when complete.

### Viewer loading and snapshot closure

The viewer now keeps the detail panel hidden until its item and first document section are loaded, then initializes the note and reveals the panel. Combined with the explicit `[hidden]` CSS rule, this closes the late initial-load overwrite of an unsent note identified during the live browser probes. The final Playwright run remains the regression check.

Freshness now compares the caller's preloaded manifest with the live manifest while holding the shared authority lock and refuses a changed generation before composing current registry/dependency state. Sol's dependency suite includes this explicit preloaded-generation regression (8 passed); direct pending-journal refusal was independently replayed earlier.

The Spec Kit extension configuration has hooks only for `after_specify` and `after_plan`; no `before_implement` or `after_implement` hook requires dispatch.

### Broad combined regression and remaining compatibility issue

Root ran:

```sh
PYTHONPATH=/tmp/campaigngenerator-547 /home/kostadis/.venv/bin/python -m pytest -q tests/test_summary_native*.py tests/test_registry*.py tests/test_resolve_name.py tests/test_retrieve_render_isolation.py tests/test_provenance*.py tests/test_ensemble*.py tests/test_cli_npc*.py --ignore=tests/test_summary_native_review_installation.py
```

Result: **1 failed, 3141 passed, 3 skipped, 1 warning in 251.41s**. Log:
`/tmp/campaigngenerator-547-full-final-root.log`. Failure:
`tests/test_summary_native_followups.py::test_external_summary_path_survives_synth`:
legacy build with an explicit external `--summaries-dir` now returns 2. Reported
to Sol to preserve read-only external-source compatibility while retaining the
review mutation containment boundary. The warning is the existing scene-editor
duplicate OpenAPI operation ID. No aggregate success is claimed for this run.

## Success criteria reconciliation (current checkpoint)

| Criterion | Evidence | Status |
|---|---|---|
| SC-001: 25 findings and durable phone/desktop decisions | Real Chromium/CLI explicit batch, all verdict semantics, tab conflict, restart with unsent note, durable retry/revocation | PASS: actual iOS/Tailscale verdicts, saved-note restart confirmation and CLI history |
| SC-002: 320/375 layouts and real-phone reachability | Live viewport checks, no overflow, raw HTML inert, 197,406-byte document read in four sections | PASS: iOS/Tailscale touch and sectioned long-document reading confirmed; independent 320/375 px checks |
| SC-003: seven categories and no false semantic certification | Independent US2 75-test batch; scoped numeric evidence, typography/verbatim distinction, nonwaivable hard failures | PASS |
| SC-004: exact rerun membership and selective freshness | Selected verifier and rerun tests; independent refreshed-custody rerun; independent affected Bob/unrelated Zelda approval probe | PASS |
| SC-005: 38 identity pairs, exact merge and distinct reopening | Public 38-pair matrix: five safe, 33 blocked; browser exact proposal approval then local apply; distinct evidence reopening; six unrelated files preserved | PASS: automated 38-pair scenario and exact prepared phone approval/apply/replay |
| SC-006: shared decisions for three content types | Actual NPC and identity browser saves, long-document full-digest signoff, four-doc publication/pointer checks and exact NPC publication; common export/import tests | PASS: automated plus all four phone document sign-offs verified |
| SC-007: replay/recovery and unauthorized/stale refusal | Real security 47-test batch, create/replace/delete recovery, unexpected-byte preflight, exact correction/document/identity replay | PASS: final integrated and late mutation checks, including cleanup concurrent-edit refusal |

Actual iOS/Tailscale reachability, touch feedback, saved-state restart continuity,
identity adjudication and four-document sign-off are now recorded below. The
phone reconnect result is user-reported, without independent correlation of a
new retry event. Same-request idempotency has separate automated coverage.
Sectioned long-document phone reading is user-confirmed and final
acceptance-service cleanup is independently verified below. No live campaign migration or model generation was performed.

### Compatibility regression closed

Root reran `PYTHONPATH=/tmp/campaigngenerator-547 /home/kostadis/.venv/bin/python -m pytest -q tests/test_summary_native_followups.py tests/test_summary_native_corpus.py tests/test_summary_native_freshness_notes.py tests/test_summary_native_review_dependencies.py`: **57 passed in 1.76s**. This includes the sole failure from the broad run. Log: `/tmp/campaigngenerator-547-compatibility-final-root.log`. External summaries remain usable as read-only inputs; they are excluded from the identity mutation inventory. The initial attempted command named a nonexistent freshness module and collected nothing; the command above is the completed check.

Root also ran the then-current identity/recovery/dependency set: **39 passed in 23.16s**, log `/tmp/campaigngenerator-547-identity-final-root.log`; late execution tests added afterward require the final targeted run.

Independent metadata apply at `/tmp/cg547-opaque-fixed-root-eznd3agt/campaign` preserved custom top-level `operator_metadata` and survivor entity `operator_tag`. Opaque metadata on an eliminated identity must block when its ownership cannot be preserved unambiguously.

### Final integrated feature, frontend and identity checks

- Root ran `PYTHONPATH=/tmp/campaigngenerator-547 /home/kostadis/.venv/bin/python -m pytest -q tests/test_summary_native_review_*.py tests/test_summary_native_npc_publish.py tests/test_cli_npc_publish.py tests/test_subprocess_runner.py tests/test_subprocess_abort.py --ignore=tests/test_summary_native_review_installation.py`: **236 passed, one existing OpenAPI warning in 68.70s**. Log: `/tmp/campaigngenerator-547-final-feature-root.log`. The subsequent cleanup-race fix requires a focused rerun.
- `npm --prefix /tmp/campaigngenerator-547/frontend run build`: **PASS**, including TypeScript compilation. Log: `/tmp/campaigngenerator-547-build-final-root.log`.
- `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 PLAYWRIGHT_BROWSERS_PATH=/tmp/campaigngenerator-546-playwright npm --prefix /tmp/campaigngenerator-547/frontend run test:e2e -- summary-native-review.spec.ts`: **10 passed in 8.3s**. Log: `/tmp/campaigngenerator-547-playwright-final-root.log`. This includes both narrow widths, notes/batches, conflicting tabs, safe rendering, sectioned documents and exact identity alternative approval. This browser suite does not substitute for the independently recorded real-server checks or an actual phone.
- Root reran the public 38-pair CLI scenario at `/tmp/cg547-identity-public-root-9nvrxa2t`, review `duplicate-review-9a8e7feccf62`: **five applicable, 33 refused/blocked, all expected applicability outcomes match**. Five type-mismatch fixture rows refuse earlier at the producer's missing-category-evidence gate; the direct identity suite separately proves the type-mismatch gate. Pair 01 apply changes seven receipt-listed paths: registry, exact review stale-event, survivor dossier, loser deletion, corpus manifest and both validation reports. Replay returns the identical receipt and every summary remains byte-identical. Full paths/hashes are in the immutable receipt and `/tmp/cg547-identity-public-root-final.log`.

### Final cleanup concurrency finding (open)

At `/tmp/cg547-cleanup-race-root-qj_aajg9/campaign`, root's producer seam wrote a
canonical regenerated draft and simulated a concurrent human edit of the loser
draft. Cleanup captured the *new* loser bytes as its deletion precondition,
deleted that edit and returned complete. No live campaign was used. Cleanup must
bind the original bytes in the pre-run schedule and refuse changed bytes after
generation and on replay. Reported to Sol for the final T049/T051 closure.

## Final automated completion checkpoint

Root's late identity/recovery/journal/routes command:

```sh
PYTHONPATH=/tmp/campaigngenerator-547 /home/kostadis/.venv/bin/python -m pytest -q tests/test_summary_native_review_identity.py tests/test_summary_native_review_identity_recovery.py tests/test_summary_native_review_transactions.py tests/test_summary_native_authority_transactions.py tests/test_summary_native_review_routes.py
```

**70 passed, one existing OpenAPI warning in 23.48s**. Log:
`/tmp/campaigngenerator-547-late-final-root.log`. The cleanup race is closed by
root's original independent probe at `/tmp/cg547-cleanup-fixed-root-naxu7iph/campaign`:
`REVIEW_STALE_IDENTITY` refuses the changed cleanup target and preserves the exact
concurrent human edit. Cleanup preconditions are now bound before the producer,
with all-target preflight and replay markers. No model runs under the writer lock.

Root rebuilt and installed the final source state and reran
`tests/test_summary_native_review_installation.py tests/test_installable_wheel.py`:
**11 passed in 13.72s**. Log: `/tmp/campaigngenerator-547-wheel-latest-root.log`.
`git diff --check` passes. The final security review has no unresolved code finding.
No after-implement extension hook is configured.

The broad run's sole failure is resolved by the recorded 57-test compatibility
recheck. Counts from the broad, feature, focused, wheel and browser runs are
separate overlapping suites and must not be added together.

All implementable tasks are complete. **T026, T053 and T066 remain unchecked only
for their actual-phone acceptance requirements.** Automated mobile viewport
evidence, public 38-pair flow, selected reruns, publication and recovery are
recorded above. This is not a claim that actual-phone release acceptance passed.

## Actual-phone acceptance started

At the user's request, a fresh disposable campaign was initialized at
`/tmp/cg547-phone-acceptance-imhqdj6c/campaign`. NPC review
`npc-review-0f860652f37f` contains 25 findings plus 25 separate draft signoff items
(50 total, initially pending). The actual feature service is managed on the
host's exact Tailscale IPv4 interface, port 8765. Its capability page returned
HTTP 200 from the host. The private grant lasts four hours; its secret is not
recorded here. A duplicate queue and four-document review are prepared for the
later phone steps. Device/browser, phone reachability and saved decisions are
pending user evidence. T026/T053/T066 remain open.

### Phone feedback: decision selection is not visually apparent

The user reported during the actual-phone walkthrough that tapping a button did
not visibly change its color/state, making the selected action unclear. CLI
inspection after this report shows no saved decisions (all 50 items pending).
The viewer previously updated only a status message below the note field; it
had no pressed styling on verdict buttons. A visible and accessible selected
state, adjacent unsaved feedback, and restored saved selection are being fixed.
Phone acceptance remains open pending the user's recheck.

Phone selection feedback fix: verdict and identity selection now have a strong
pressed color/border and accessible `aria-pressed` state, with an adjacent
unsaved-selection message. Opening a different item resets selection; an
existing saved verdict is restored when reopened. Root checked the actual
running Tailscale page at 375 px using a browser without saving any decisions:
color change, exclusive selection, reset between items, and no horizontal
overflow all pass. Screenshot inspected at
`/tmp/cg547-phone-selection-feedback.png`. The existing phone URL/service remains
active; the user must refresh to load the updated assets and repeat the touch
check. Actual-phone acceptance is still pending.

Focused Playwright regression for this phone finding passed: `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 PLAYWRIGHT_BROWSERS_PATH=/tmp/campaigngenerator-546-playwright npm run test:e2e -- summary-native-review.spec.ts --grep "verdict selection switches"` from `frontend/`: **1 passed in 3.1s**, covering switch/reset and saved-verdict restoration. No phone decisions were changed by verification.

### Phone feedback: queue lacks saved-decision visibility

The user saved decisions, returned to the queue, and could not identify updated
items. Independent CLI inspection confirms three durable phone decisions:
Fixture claim 1 approved, claim 3 rejected, and claim 4 discussed (with a note).
The queue currently shows claim text but no normal saved verdict labels. This
is a presentation failure, not lost decisions. Persistent textual row badges
are being added; phone acceptance remains open pending the user's recheck.

Queue feedback fix verified: rows now show Pending, Approved, Rejected or Discuss
as text badges; stale items show `Stale — review again`. Root verified the actual
phone campaign at 375 px without submitting decisions: the user's claim 1/3/4
statuses display correctly and survive reload, an unsaved choice on claim 2 does
not change its saved badge, and no horizontal overflow occurs. Screenshot:
`/tmp/cg547-phone-queue-feedback.png`. Focused Playwright regression
`--grep "queue badges show only persisted verdicts"` passed **1 test in 3.1s**.
The service and grant are unchanged; phone recheck is pending.

### Phone feedback: advance directly after finishing an item

The user requested an action to proceed to the next item without returning to
the queue and finding their previous scroll position. A Save and next action is
being added. It must advance only after an acknowledged save, keep the current
item/note on failure, follow the visible queue order and handle the end of the
queue explicitly. The original phone campaign and its decisions remain intact.

Root confirmed the Save and next control is visible on the actual running
Tailscale page at 375 px with no horizontal overflow. This check submitted no
decisions. The change also needs to distinguish a successfully saved decision
from failure to load the next item, and bring the next heading into view so the
phone does not remain scrolled to the previous item's action buttons.

Save and next regression complete: **4 Playwright tests passed in 4.1s** with
`--grep "save and next"`. Successful saves advance in visible queue order and
focus/scroll the next heading into view; failed saves preserve the current item
and retry intent; the final item reports the end without wrapping; next-item
load failure after a successful POST reports Saved and offers Retry next item
without another decision write. Batch members are excluded from the next-item
choice. JavaScript syntax and `git diff --check` pass. User phone decisions,
service and capability grant were preserved. Phone recheck remains pending.

### Phone walkthrough: navigation accepted; restart check underway

The user confirmed “This is good” after the Save and next update. Root then
restarted the disposable NPC review service on the same Tailscale endpoint,
retaining the same grant. Before/after CLI status and complete history are
identical: 3 approved, 1 rejected, 1 discussed, 47 unresolved/pending, no stale
items. The existing capability link returns HTTP 200 after restart. Phone-side
refresh confirmation and device/browser identification are still pending; this
host check does not itself complete the real-phone continuity gate.

### Phone walkthrough: saved state survives restart

The user reported iOS with Chrome/Safari (the exact browser used was not
distinguished). After the service restart described above, the user confirmed
on the phone that refreshing retained the 3 Approved, 1 Rejected and 1 Discuss
badges and the saved note. This confirms phone-side saved-state continuity for
this restart; it does not establish separate runs in both browsers. Offline
save/retry and the remaining identity/document phone walkthroughs remain open.

### Phone walkthrough: connection recovery reported successful

The user confirmed that the instructed Tailscale-disconnect/save/reconnect/retry
flow retained the note and saved successfully. A subsequent CLI snapshot still
shows 3 approved, 1 rejected and 1 discussed; its most recent events are the
previous two approvals of the same item with different request IDs and no note.
Thus the phone report is recorded, but a new offline-retry event has not been
independently correlated in the audit history. Do not infer same-request retry
idempotency from that report alone; automated coverage remains the evidence for
that property. The prepared 38-pair identity review is now served separately on
the same private Tailscale address, port 8766; its capability is kept only in the
private acceptance state file. The NPC service remains available.

### Phone identity walkthrough: first saved decision verified

The user confirmed the first identity interaction saved. CLI history for
`pair-01` shows decision revision 1, verdict `discuss`, disposition `defer`,
and note `Phone `, with no approved proposal ID/digest. This proves the phone
identity decision was persisted, but does not yet satisfy the exact prepared
merge approval gate. No identity apply was attempted; the next phone step is
to select the Candidate 1A prepared alternative and save an Approve decision.

### Phone identity approval: stale binding safely refused

CLI verified pair-01 revision 2 as approve/merge, note `Phone `, bound to
proposal `identity-pair-01-g1-a06b5f4f429de6fd50379627-1`, digest
`fcc12a2f9cd07ea56e7a8556bd9d0c34c66eb8788118ccd490a165a9babdc3c9`,
canonical Candidate 1A. The registry still matched the proposal
registry_sha256 before local apply. Apply refused with
`REVIEW_STALE_IDENTITY: approval binding changed`: the earlier Discuss
decision advanced the decision revision after initial preparation. A fresh
global alternative set was prepared at expected decision revision 2; a new
phone approval is required before applying it. No successful merge or replay
is claimed for this attempt.

### Phone identity walkthrough: exact approval applied and replayed

The user saved the refreshed Candidate 1A alternative from the phone. CLI
verified decision revision 3, approve/merge, with the exact proposal
`identity-pair-01-g1-60160d6eb0c7de523ed7af1c-1`, digest
`bd928a7d235bde8bd86a3c4d3ddd04247071b914e0e49dcccdc1edab09c32723`. The registry hash still matched the
prepared proposal before trusted local apply. Apply succeeded on the disposable
campaign; repeating the same apply returned an identical receipt and left all
campaign file hashes identical. All source summary hashes were unchanged.
Receipt changed paths:

- `docs/entity_registry.yaml`
- `docs/reviews/duplicate-review-c8e329178c33/events/rebind-identity-pair-01-g1-60160d6eb0c7de523ed7af1c-1-851aee644ca0.json`
- `docs/summary_native/ch001-001/dossiers/npc_candidate_1a.md`
- `docs/summary_native/ch001-001/dossiers/npc_candidate_1b.md`
- `docs/summary_native/ch001-001/manifest.json`
- `docs/summary_native/ch001-001/validation_report.json`
- `docs/summary_native/ch001-001/validation_report.md`

Authority transaction, snapshot, ledger and receipt audit files were also
created/updated as expected. Full before/after changed-path evidence and the
receipt are in `/tmp/cg547-phone-identity-apply.json`. Phone display of the
applied state and the scoped-blocked pair remain to be confirmed.

### Phone identity walkthrough: applied and blocked displays confirmed

The user confirmed that refreshed pair-01 shows Applied, and pair-02 shows
Blocked merge choices that cannot be selected. Together with the verified
phone approval, local exact-digest apply/replay and the independently recorded
38-pair scenario, this completes T053.

### Phone grounding documents: all four sign-offs verified

The user confirmed completing reading/layout and approval of all four drafts.
CLI status is approved=4/pending=0. History contains exact `document_signoff`
approvals for world_state, campaign_state, party and planning. Campaign_state
and planning each have a second approval with a distinct request ID; these are
separate decisions, not evidence of a duplicated same-request retry.
T026 is complete based on the earlier three-verdict phone workflow, CLI
continuity, restart confirmation, touch feedback and layout checks. The short
four-document phone read does not certify sectioned long-document reading.
A separate existing 197,406-byte disposable document fixture is served on
private Tailscale port 8768 for that remaining check.

### Final phone acceptance and cleanup — 2026-10-10

The user confirmed completing the long-document section-loading/readability
check and saving approval. CLI verified the world_state `document_signoff`
on exact digest
`161e862f3ad88a61a234a11ae467740f007d57bbfeb880a1e9cba4d7d9a0bc95`;
the long-document review actually has all four documents approved. World_state
has two approvals with distinct request IDs, revisions 1 and 2. The phone
reading/section navigation result is user-reported; durable sign-off is
independently verified. This completes the remaining T066 phone reading gate.

All four acceptance grants (NPC, identity, four documents and long document)
were revoked. Each old capability returned generic HTTP 404 for GET and POST
/decisions both before and after a service stop/start. All four services were
then stopped. Cleanup evidence: `/tmp/cg547-phone-cleanup.json`. The original
capability URLs are no longer usable; no capability secret is recorded here.

T026, T053 and T066 are now complete. The thirteen constitution gates and
SC-001 through SC-007 are satisfied by the automated/public-CLI evidence plus
the physical iOS/Tailscale walkthrough above. Browser identity remains the
user description Chrome/Safari, not a claim that both browsers were tested.
Offline recovery was user-confirmed; its specific new event was not correlated
in history, so same-request retry correctness relies on the independent
automated coverage. No live campaign data was changed.
