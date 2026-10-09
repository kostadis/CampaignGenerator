# Implementation Validation

## Baseline — before runtime changes

Worktree base: `a9aac0676954dd867dfad03c8edeb532107fef94`.

- `python -m pytest -q tests/test_summary_native*.py tests/test_state_docs*.py tests/test_planning_config_service.py`: **1810 passed, 1 skipped**, 63.63 seconds. Executed outside the sandbox because the existing FastAPI test environment requires it.
- `npm --prefix frontend run build`: **passed**.

These results describe the existing implementation only. Feature acceptance and final regression results must be recorded separately after implementation.

## Independent review checks during implementation

These are targeted review checks, not the final regression or acceptance gate.

- Selection hashing: ran the same selector with three record IDs in three fresh
  Python processes (`PYTHONHASHSEED=1`, `2`, and `3`). Initially reproduced three
  distinct digests. After canonicalization, all three digests are identical.
- Withdrawal: in a disposable campaign, created and applied a correction, edited
  an unrelated chapter title, requested withdrawal, and applied the reversal.
  Initially reproduced a false stale-passage refusal. After the fix, the original
  claim is restored and the unrelated title edit remains.
- Regeneration coverage review: rejected the initial helper-only test. The revised
  test invokes production CLI build, extraction, and all four synthesis commands
  with `--force`, inspects corrected draft text and provenance manifests, and
  checks metadata/receipt changes refuse draft reuse before a model call.
- Browser coverage review: the initial correction happy path does not by itself
  complete T025; retirement, withdrawal, recovery, stale status, and stale proposal
  binding require their own assertions.
- Documentation: all local Markdown links in `docs/cli/summary_native_authority.md`,
  `docs/cli/summary_native_howto.md`, and `docs/README.md` resolve. The operator guide
  remains subject to verification against the final CLI/UI.

## US1 and US2 route/UI verification

- `npm --prefix frontend run build`: **passed**.
- `PYTHONPATH=$PWD python -m pytest tests/test_summary_native_authority_routes.py tests/test_planning_note_selector_routes.py -q`: **3 passed in 2.23s**. This includes a real CLI-backed authority-note preview with a materialized glob member, plus planning selector CRUD.
- `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 PLAYWRIGHT_BROWSERS_PATH=/tmp/campaigngenerator-546-playwright npm --prefix frontend run test:e2e -- summary-native-state.spec.ts`: **21 passed in 15.3s**.
  The suite covers the five-action ordinary authority correction, retirement, stale-projection status, withdrawal, pending recovery, proposal/record binding invalidation, selector preview membership/classification/audience/reason/external/warning/digests, repeated GM selector forwarding, and clearing the reviewed selection after membership drift.

### T025 lifecycle correction

- `PYTHONPATH=$PWD python -m pytest tests/test_summary_native_authority_routes.py tests/test_planning_note_selector_routes.py -q`: **4 passed in 3.09s**. The authority-status subprocess test writes an obsolete planning run manifest and verifies the real safe stale shape `{doc,draft,reason}`.
- `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 PLAYWRIGHT_BROWSERS_PATH=/tmp/campaigngenerator-546-playwright npm --prefix frontend run test:e2e -- summary-native-state.spec.ts`: **22 passed in 16.0s**. The lifecycle fixture uses an applied `RULED` record for withdrawal and a separate active record for retirement, and renders the actual structured stale-projection shape.

### Independent `--config` correction smoke

Against a disposable fixture, the installed `summary_native` entry point with
`PYTHONPATH=/tmp/campaigngenerator-546` successfully ran initialization, validation,
status, record stage, record apply, proposal, source apply, and history. Every
operation after initialization used `--config <fixture>/config/config.yaml`;
proposal resolved the summary directory without `--summaries-dir`.

This smoke exposed a separate UI parity defect: the real stage response had
`data.id`/`data.sha256`, while the UI and its mock expected
`data.stage_id`/`data.stage_sha256`. T024/T025 were reopened for a consistent
response contract and a real subprocess stage/apply route regression.

### T024/T025 stage-envelope parity correction

- The UI now takes the staged record id and approval digest directly from the
  stable CLI envelope `data: {id, record, sha256}`. The browser mock uses the
  same shape and the route test stages a real record, passes those exact values
  to apply, then verifies the actual ledger revision and record count.
- `PYTHONPATH=$PWD python -m pytest tests/test_summary_native_authority_routes.py tests/test_planning_note_selector_routes.py -q`: **6 passed in 6.47s**.
- `npm --prefix frontend run build`: **passed**.
- `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 PLAYWRIGHT_BROWSERS_PATH=/tmp/campaigngenerator-546-playwright npm --prefix frontend run test:e2e -- summary-native-state.spec.ts`: **23 passed in 20.7s**. This includes the five-action GM correction, staged record apply, retirement, structured stale status, withdrawal, pending recovery, and proposal-to-record binding assertions.

### T032–T034 preview metadata parity correction

- The real GM preview route test now initializes the authority ledger, stages and
  applies a PREP planning record, persists its selector, and verifies the CLI
  response carries the concrete member metadata: path, scope, digest, and
  `records[{id, classification, audience, effective, status, anchor, section_sha256}]`.
  The UI derives visible classifications, audiences, and record scope only from
  that CLI-owned array; its browser mock has the same envelope.
- `PYTHONPATH=$PWD python -m pytest tests/test_summary_native_authority_routes.py tests/test_planning_note_selector_routes.py -q`: **6 passed in 8.85s**.
- `npm --prefix frontend run build`: **passed**.
- `PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 PLAYWRIGHT_BROWSERS_PATH=/tmp/campaigngenerator-546-playwright npm --prefix frontend run test:e2e -- summary-native-state.spec.ts`: **23 passed in 20.8s**.

### US3 production all-document audience gate

- Added the reserved read-only `__document__` support anchor for complete YAML,
  JSON, and Markdown deterministic inputs. It requires a NoteRecord whole-file
  digest at stage time and is forbidden for rulings and source replacement.
- The production fixture runs CLI extraction then all four synthesis documents
  for `players` and `character:Thorin Giantfriend`, with maintained summaries,
  planning selection, full classified deterministic support, and a GM sentinel.
  It verifies no sentinel reaches restricted prompts or artifacts. Removing one
  party-sheet grant gives the generic reviewed-coverage refusal without naming
  the missing path.
- `PYTHONPATH=$PWD python -m pytest tests/test_summary_native_authority_apply.py tests/test_summary_native_authority_cli.py tests/test_summary_native_authority_leaks.py -q`: **22 passed in 3.81s**.
- `PYTHONPATH=$PWD python -m pytest tests/test_summary_native_authority*.py -q`: **83 passed in 11.94s**.

### Independent source/audience/regeneration gate

Executed from the feature worktree after the complete-document support adapter
landed:

```bash
python -m pytest -q tests/test_summary_native_authority_leaks.py tests/test_summary_native_authority_regeneration.py tests/test_summary_native_authority_sources.py
```

Result: **17 passed in 4.07 seconds**. The audience fixture runs real extraction
and all four synthesis commands for players and a named character, then scans
model prompts and audience artifacts for a GM-only sentinel. It also checks
refusal after a required support grant is removed. The source tests exercise replacement boundaries; the regeneration test
exercises source truth and changed authority metadata/receipt freshness.

### Independent installed-CLI conflict smoke

Using a fresh disposable campaign and the installed `summary_native` entry point
with `PYTHONPATH=/tmp/campaigngenerator-546`, initialized the ledger, staged and
applied two overlapping structured CANON claims, listed the resulting conflict,
recorded a human prose candidate, read its exact history, dismissed the candidate,
and read its history again. All commands succeeded. Conflict listing is a read
operation returning exit 0 with findings; blocking synthesis is verified separately.
The operator guide's identify/dismiss flags match the actual CLI parser.

Implementation hooks were checked in `.specify/extensions.yml`: no
`before_implement` or `after_implement` hooks are registered.

### First broad regression attempt

The expanded Python suite initially returned **1919 passed, 1 skipped, 5 failed**
in 115.77 seconds. Four real subprocess route tests imported the original
checkout because this attempt omitted `PYTHONPATH`; their stderr showed a CLI
without the new authority command. The fifth failure was the existing router
configuration-default guard matching the new subprocess timeout literal. These
failures were sent for correction and this run is **not** the final passing gate.
The quickstart now explains worktree subprocess import setup.

### Final focused acceptance suite

```bash
PYTHONPATH=/tmp/campaigngenerator-546 python -m pytest -q tests/test_summary_native_authority*.py tests/test_summary_native_planning.py tests/test_summary_native_routes.py tests/test_planning_config_service.py
```

**351 passed in 27.35 seconds**. Log:
`/tmp/campaigngenerator-546-final-focused.log`. This includes the actual
source-apply interruption/recovery matrix and corrected worktree subprocess
imports. The subsequent full regression covers final tests added after this
focused run was collected.

## Quickstart acceptance mapping

All scenarios use disposable fixtures and fake model clients; no campaign data was modified.

1. Initialization/validation: init hardening tests cover strict init, second-init refusal, atomic init event/tip, crash recovery, and validation.
2. Notes/selection: selection, planning, route, and config tests cover strict record apply, concrete preview metadata, selector refusal, and membership drift.
3. Earthstone correction: apply tests cover exact diff, stale proposal refusal, immutable artifacts, provenance, and generated-output protection.
4. Regeneration: the regeneration test invokes production build, extract, and all four forced synthesis projections.
5. Audience/cache isolation: leak/cache/audience tests run players and a named character through extraction and all four documents and scan prompts, artifacts, and errors for sentinels.
6. Conflicts: conflict/history/freshness tests cover overlapping claims, disjoint evolution, equal overlays, prose candidates, dispositions, and synthesis exit 5 before a model call.
7. Recovery: the source-apply failpoint matrix interrupts every durable write, verifies forward/idempotent recovery and retained history, and refuses unexpected bytes.
8. Withdrawal: withdrawal tests preserve unrelated edits, refuse changed corrected passages, apply reversal, retain history, and stale drafts.
9. UI parity: the final frontend build passed and the Summary Native Playwright suite passed **24 tests**; real subprocess route suites cover stage/apply and conflict lifecycle paths.


### Final broad regression and guard follow-up

```bash
PYTHONPATH=/tmp/campaigngenerator-546 python -m pytest -q tests/test_summary_native*.py tests/test_state_docs*.py tests/test_planning_config_service.py tests/test_planning_config.py tests/test_planning_note_selector_routes.py tests/test_subprocess_runner.py
```

The frozen production implementation returned **1932 passed, 1 skipped, 1 failed**
in 93.51 seconds. The sole failure was the router-default test's broad text scan
matching the named transport timeout constant. That test-only correction landed
after pytest collection; production code did not change. The guard now excludes
module-level transport constants while continuing to check route defaults.

```bash
PYTHONPATH=/tmp/campaigngenerator-546 python -m pytest -q tests/test_summary_native_config_defaults.py
```

The complete affected module then passed: **64 passed in 1.04 seconds**, including
the previously failing case. Together these runs verify all 1933 runnable tests
in the expanded suite, with one existing skip. No failures remain unresolved.
Logs: `/tmp/campaigngenerator-546-final-python-corrected.log` and
`/tmp/campaigngenerator-546-final-defaults.log`.

Final documentation links resolve, `git diff --check` passes, and the read-only
requirements checklist remains 16/16 checked. No implementation hooks are
registered. All 57 implementation tasks are complete; changes remain uncommitted
in `codex/546-gm-rulings` at `/tmp/campaigngenerator-546`.
