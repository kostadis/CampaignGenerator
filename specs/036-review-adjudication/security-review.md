# Security Implementation Review — Issue #547

Status: **T065 automated security review PASS; no unresolved code findings. Actual-phone release acceptance and final capability cleanup PASS.**

The dedicated read/save surface and integrated local mutation paths have passing adversarial, recovery and browser evidence below. The iOS/Tailscale walkthrough now confirms NPC continuity, identity approval/apply and four-document sign-off. Sectioned long-document reading was user-confirmed; all four acceptance grants were revoked and returned generic refusal for reads/writes across restart, then their services were stopped. T066 is complete; see validation.md.

## Boundary under review

The dedicated service may read one prepared GM review and save attributable decisions for it. It may not select arbitrary source files, apply corrections/identity merges, publish drafts or administer services. Those actions remain on the trusted local CLI/application surface. Capabilities are bearer credentials; reviewer text is attribution, not authentication.

## Current evidence (supersedes historical checkpoint status below)

| Boundary | Evidence | Current status |
|---|---|---|
| Capability grant | Actual-service expiry, revocation/restart, copied-campaign and writer-lock race tests | PASS |
| Request isolation | Cross-review, traversal, asset allowlist, credential/runtime symlink refusal | PASS |
| Browser writes | Exact Origin/Host/content type/CSRF; actual Fetch Metadata refusal; nonce renewal after restart | PASS |
| Rendering | Real Chromium raw HTML inert, zero external requests; 320/375 layouts and bounded long-document reading/signoff | PASS automated; actual phone OPEN |
| Resource bounds | Fixed and chunked oversized inputs, note/batch limits, bounded subprocess time/output, full-digest document sections | PASS |
| Credential handling | No capability in argv, captured service logs, generic errors or status; injected subprocess errors redacted | PASS |
| Local serving | Explicit loopback lifecycle, occupied-port refusal and private durable handles | PASS; actual LAN/Tailscale phone transport OPEN |
| Durability | Journal preflight/recovery, stale import refusal, compare-and-swap, exact receipt replay | PASS: integrated 236-test feature run plus final 70-test mutation/recovery run |
| Mutation gate | No remote apply/admin routes; genuine #546 correction inputs; exact four-document and NPC publication gates; identity closure/stale approvals | PASS: exact local execution/resolution and concurrent cleanup refusal verified |

Final focused command (root): `PYTHONPATH=/tmp/campaigngenerator-547 /home/kostadis/.venv/bin/python -m pytest -q tests/test_summary_native_review_http.py tests/test_summary_native_review_security_regressions.py tests/test_summary_native_review_routes.py tests/test_subprocess_runner.py tests/test_subprocess_abort.py` — **47 passed in 31.96s**. One pre-existing duplicate OpenAPI operation warning in the scene editor. Log: `/tmp/campaigngenerator-547-security-final-root.log`.

Independent current rechecks close the production NPC path omission, alias capture freshness, pending-journal freshness bypass, unrelated-range mutation, and affected approval staleness findings. The identity preview now includes production dossier paths; the full 38-pair matrix is five safe and 33 blocked. Actual application leaves the unrelated six-file Zelda range unchanged and stales only the affected Bob approval. Preloaded manifest changes are detected under the shared freshness lock. Final regeneration/conflict-resolution execution and cleanup concurrency checks are recorded below.

The following sections retain the chronological review trail. An earlier “open” observation is superseded only by its recorded recheck or the current evidence table above.

## Review observations during foundation work

- Authority review references must validate their immutable event/item/campaign bindings; merely skipping current registry identity validation is insufficient for historical loser records.
- Migration must verify an existing ledger tip before it can become a legitimate new ledger event, including completed/no-op retry paths.
- The shared bounded subprocess seam currently returns raw parsed error payloads. Remote adapters must construct safe responses rather than forwarding arbitrary secret-bearing payloads; grant issuance must disable normal run logging.

These observations were sent to the coding owner. Their disposition and runtime tests must be recorded before the related tasks are marked complete. No live campaign or publicly reachable service has been used for this review.

## Foundation findings disposition

- Campaign identity decoding now rejects duplicate keys and boolean schema versions; coherent snapshot reads validate item/campaign/domain/custody references. Included in the root's 144-test foundation/authority checkpoint.
- Migration validates the existing authority tip before planning/applying, including retry/no-op paths. Migration and existing authority regressions pass at the foundation checkpoint.
- The journal now refuses symlink path components. Root independently attempted a create through a campaign-internal directory symlink on a temporary campaign: it refused `AUTH_RECOVERY` before creating the target. This is one focused path probe, not the complete identity/recovery security suite.
- Authority audit-reference checks now inspect immutable artifacts, subject/domain bindings and recomputed digests. Prepared-proposal binding must remain non-circular; final integration validation is pending.
- Subprocess error payload redaction and grant logging remain open until remote adapters are implemented.

## US1 adapter review in progress

Code review identified and implementation is addressing: bounded CLI reads rather than direct domain reads, nontruncating pagination, streamed request-size enforcement, fixed safe error DTOs, Fetch Metadata checks, campaign-bound grants and credential-path symlink refusal/directory fsync. These require actual-service test evidence before approval.

A separate local interchange integrity finding is open: importing an older exported approval can supersede a newer rejection. Root reproduced the wrong state transition on a temporary campaign. Stale import must refuse without partial writes.

Additional integration review findings sent to the coding owner:

- The packaged viewer initially sent a `version` field rejected by the HTTP request contract; mock browser routes did not enforce that contract. A real-service browser save must pass before T021 acceptance.
- Explicit batch save initially had no handler, and client progress incorrectly treated every verdict/edit as another settled item. Use the server's state and preserve Reject/Discuss as unresolved.
- Managed readiness initially published its handle before socket bind and probed an unverified listener. An occupied port must not yield a false ready result.
- Service stop must remain usable when a campaign transaction needs recovery.

These are implementation findings with fixes in progress; no server release approval is implied.

## Independent HTTP suite checkpoint

Root ran `PYTHONPATH=/tmp/campaigngenerator-547 python -m pytest -q tests/test_summary_native_review_http.py` against actual loopback service processes: **6 passed in 11.75s**. Log: `/tmp/campaigngenerator-547-http-root.log`. Covered capability/other-review/path refusal, restart/revocation, browser-write headers, fixed assets/raw HTML as JSON, oversized body refusal, no remote mutation routes and token absence in captured service output/errors.

Limitations: the expiry fixture currently makes expiry earlier than issue time and therefore also exercises invalid-grant refusal; it must use a well-formed expired grant. Lock-time revocation race, copied foreign grant, chunked body limits, adversarial subprocess errors and occupied-port readiness still require explicit evidence. Browser rendering against a live service is a separate gate.

Stale-import finding recheck: root repeated the original temporary-campaign reproduction after the fix. Importing the current export returned `imported_events=0`; importing it after a newer rejection refused, with every campaign file byte unchanged. The reproduced overwrite finding is closed. Broader cross-campaign/provenance tests remain part of final interchange acceptance.

## Grounding promotion finding (open)

On 2026-10-10 root reproduced changed-draft promotion after preview on a disposable campaign: sign, prepare, change draft, apply still succeeds. The application boundary must revalidate exact source/dependency bindings and current nonwithdrawn signoff while locked before any journal mutation. Merely finding the original historical authority event is insufficient. Final release remains blocked until regression evidence closes this finding.

Grounding changed-draft finding recheck: direct draft change now refuses with zero file writes. A related finding remains open: underlying summary changes after preview are not detected when the corpus manifest itself is unchanged; root reproduced successful promotion. Current ledger/draft checks are not sufficient to certify the full dependency closure.

Live Chromium now proves a two-member explicit batch over the actual HTTP/CLI seam and competing-tab conflict/reload recovery at 375- and 320-pixel widths. No JavaScript errors or horizontal page overflow were observed. Raw-HTML execution, all secret/error boundaries, and actual-phone continuity remain separate gates.

## Independent adversarial checkpoint, 2026-10-10

Root ran `PYTHONPATH=/tmp/campaigngenerator-547 python -m pytest -q tests/test_summary_native_review_security_regressions.py tests/test_summary_native_review_http.py tests/test_summary_native_review_routes.py tests/test_subprocess_runner.py`: **28 passed in 24.21s**. Log: `/tmp/campaigngenerator-547-security-root.log`. The warning is the existing unrelated `scene_editor.api_polish` duplicate OpenAPI operation ID.

New evidence closes the previously identified test gaps for a well-formed expired grant, foreign-campaign copied grant, chunked input without Content-Length, revocation before the decision writer lock, occupied-port false readiness, runtime/credential symlink escapes, private permissions/directory fsync, and secret-bearing subprocess error redaction. The latter error injection uses TestClient with a mocked subprocess failure; grant/transport/lifecycle cases use actual loopback processes. Neither this checkpoint nor mocked-browser tests substitute for final transport revalidation after all viewer/API changes or physical-phone acceptance.

A separate mutation-boundary issue remains open: after warming `entity_registry.resolve._load_registry`, a pending authority journal makes direct `load_registry` refuse `AUTH_RECOVERY` but the cached resolver still returns a registry. Cached consumers must also respect the shared pending-transaction boundary. Root reproduced this independently and sent it to Sol.

Raw-HTML browser checkpoint: root served the adversarial `<img ... onerror=...><script>...</script>` item through the real loopback service and opened it in Chromium at 320 pixels. It remained literal text; `window.PWNED` was unset, claim/evidence contained zero executable image/script nodes, zero external requests were made, zero page errors occurred, and the page did not overflow. The temporary grant was revoked and service stopped.

Cached-resolver finding recheck: both direct registry load and warmed cached resolver now refuse `AUTH_RECOVERY` with a pending journal. The reproduced bypass is closed; full affected-consumer tests remain part of T052.

Source-correction integration remains open: the first implementation directly constructed a source write and fabricated a ruling ID instead of invoking #546's maintained-summary, anchor and genuine ruling/proposal gates. Passing synthetic correction tests does not establish preservation of those boundaries. Sol is replacing that path with the existing reviewed source workflow.

Fetch Metadata checkpoint: an actual service request with a valid capability, current CSRF nonce and exact Origin but `Sec-Fetch-Site: cross-site` refused 400/`REVIEW_ORIGIN_REQUIRED`. Service cleanup succeeded. The viewer also needs nonce renewal for long sessions or server restart; failure must preserve unsent notes/pending request identity while obtaining a fresh nonce. Sent to Sol as session-continuity work.

## Latest mutation-boundary rechecks

The exact correction implementation now reuses genuine #546 rulings/proposals and validates all captured inspected inputs. The correction regression includes changed non-target context refusal; root's combined document/correction/refresh/dependency/migration run passed 50 tests. Underlying summary/reference changes now refuse document promotion. Public promotion of all four realistic outline-compliant documents now includes the exact reference/timeline bundle, and all four destination pointer checks pass; receipt replay is identical.

A further identity application closure finding is open: production `docs/npcs/bob_stone.md` is absent from a prepared merge inventory with no blocking reason. Root reproduced this on a disposable campaign and reported it. A subject-freshness finding is also open: a new alias capturing an existing unregistered heading changes actual grouping while freshness reports current. These findings block complete identity application/freshness acceptance pending fixes and regression evidence.

The alias-capture freshness finding is closed by independent replay of the original reproduction. A live Chromium check also closes restart nonce renewal: an unsent note saved successfully after service restart using a newly fetched CSRF nonce, without page reload. The separate item-loading/hidden-state UI race remains tracked in `validation.md`.

Freshness/pending-journal boundary finding (open): root prepared a pending authority transaction on a valid adopted corpus campaign. `freshness.check_fresh` returned current (`None`) both before and while the transaction was pending. Reproduction: `/tmp/cg547-freshness-lock-root-r9iqmqho`. Codememory identified existing audit/extract/synth/NPC/thread consumers of this seam. Readers must validate a coherent locked snapshot and refuse pending journals without holding a writer lock during model calls. Reported to Sol for the final consumer boundary gate.

Pending freshness recheck: the original disposable pending-journal reproduction now raises `AUTH_PENDING_TRANSACTION` with the exact recovery command. The direct freshness bypass is closed. Final concurrent caller snapshot tests must still establish cross-file coherence when reports/manifests were obtained before entering this function.

## Final registry metadata preservation finding (open)

Root added `operator_metadata: {keep: original}` to a valid disposable registry
at `/tmp/cg547-opaque-registry-root-4ut344w2/campaign`. Both identity alternatives
were applicable with no blockers, but both proposed after-registry payloads
omitted that metadata. No proposal was applied. `dump_registry` serialization
must preserve opaque top-level/entity data through known-field changes or block
an ambiguous merge. The new separate guard-resolution path must preserve the
same data. Reported to Sol; this remains a release blocker until rechecked.

Metadata finding recheck: root's fresh preview/apply at
`/tmp/cg547-opaque-fixed-root-eznd3agt/campaign` preserved both top-level and
survivor-entity opaque fields. The final 236-test feature run includes guard
metadata preservation and typed guard audit separation. The metadata finding is
closed; ambiguous opaque loser data now refuses instead of being discarded.

## Final regeneration cleanup concurrency finding (open)

Root's disposable `/tmp/cg547-cleanup-race-root-qj_aajg9/campaign` proved that a
human edit during a producer run could be deleted: cleanup read post-run bytes
and used those as the delete precondition. This is not an effective compare-and-swap
against the reviewed pre-run state. Bind the old bytes in the immutable schedule;
preflight all cleanup targets after the producer and on replay before any
cleanup mutation. No public or live campaign was used. T065 remains blocked
until this concrete finding is closed.

## Final closure and disposition

Root repeated the original cleanup race at
`/tmp/cg547-cleanup-fixed-root-naxu7iph/campaign`. It now refuses
`REVIEW_STALE_IDENTITY: cleanup target changed during generation` and preserves
the concurrent edit. The final 70-test identity/recovery/journal/routes suite
passes, including the immutable pre-run cleanup bindings and all-target refusal.
The final integrated feature run passes 236 tests, including the actual-service
adversarial cases. The full browser suite passes 10 tests; final rebuilt-wheel
checks pass 11 tests. Exact commands and logs are in `validation.md`.

**No unresolved implementation security findings remain.** The capability server
still exposes only prepared reads and decisions. Guard changes, generation,
identity application and publication require trusted local CLI/application
operations; generation uses the existing streaming subprocess seam. No live
campaign or publicly exposed service was used for acceptance. Actual-phone
reachability/continuity remains an explicit unperformed release gate.
