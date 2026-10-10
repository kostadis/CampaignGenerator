# Implementation notes — issue #549

## Companion delivery order

The companion registry change is isolated at `/tmp/dgx-fun-549` on
`codex/549-dgx-registry`, based on dgx-fun revision
`de3e1e226ad1930308648454d4a3ff8d51efa077`. It adds optional validated
`ModelConfig.max_concurrency` and declares `qwen3.8-flash-next: 8`. Deliver
that branch before CampaignGenerator so an omitted DGX `--parallel` can use the
served capacity; older dgxlib installations continue with fallback 6.

## Validation performed

- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_summary_native_scheduler.py tests/test_summary_native_scheduler_records.py tests/test_summary_native_concurrency.py` — 21 passed in 0.45s.
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_summary_native_extract.py tests/test_summary_native_audit.py tests/test_summary_native_npc_draft.py tests/test_summary_native_npc_verify.py` — 174 passed in 26.03s.
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/test_registry.py` in `/tmp/dgx-fun-549` — 16 passed in 0.29s.
- Root-agent validation outside this sandbox: the route test group passed 160 tests and `npm run build` passed.
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q tests/test_npc_dossiers_routes.py tests/test_summary_native_routes.py tests/test_summary_native_config_defaults.py` — 235 passed in 11.15s.
- `PLAYWRIGHT_CHROME_EXECUTABLE_PATH=/usr/bin/google-chrome npx playwright test e2e/resilient-scheduler-ui.spec.ts` from `frontend/` — 2 passed in 3.9s. The real browser tests use intercepted local API/SSE responses only: they verify resolved concurrency/source, quarantined endpoint and categorized outcome rendering, reload persistence, bare resume, explicit NPC Select all materialization, and empty-selection refusal.
- `npm run build` from `frontend/` — passed after the browser acceptance test was added.
- `pytest -q` from the CampaignGenerator worktree — 8,398 passed, 277 skipped,
  35 failed, and 5 errored in 561.20s. A detached `origin/main` comparison
  reproduced every remaining failure or tied it to the worktree environment:
  missing `config/agents` prompt files, `/tmp` being inside a Git repository,
  a stale installed `summary_native` console script, and existing layering,
  authority-lock, backend-inventory, and NPC-signoff failures. The run found two
  #549 regressions; both were fixed: the NPC router's hard-coded DGX comparison
  now passes its 12 drift guards, and `_npc_verify` no longer combines authored
  reads with journal writes. The authored-write focused rerun has 39 relevant
  checks passing with only the unchanged `authority_cli.py` baseline offender.
- `python -m pytest -q tests/test_registry.py` in `/tmp/dgx-fun-549` — 16 passed
  in 0.33s. (`python -m pytest` is required so the worktree package wins over an
  older installed `dgxlib`.)
- `git diff --check` — clean.

The quickstart scenarios are covered by the focused scheduler, resume,
determinism, taxonomy, route, and real-browser runs above. No live DGX or paid
model call was made.

## Operator and release note

CampaignGenerator now resolves an omitted DGX `--parallel` after backend/model
selection. Resolution order is an explicit positive CLI value, the selected
dgxlib model's positive `max_concurrency`, then the compatibility fallback of
6. Run records and start output retain the effective value and source. Deploy
the `/tmp/dgx-fun-549` companion change first if operators expect
`qwen3.8-flash-next` to resolve to 8; older dgxlib versions safely resolve to 6.

Extract, audit, and NPC draft now dispatch explicit stable items through the
shared scheduler. CLI and UI surfaces expose resume and disk-backed status, and
NPC verification remains deterministic and local.

## Acceptance result

All issue #549 tasks and quickstart scenarios are complete. Endpoint recovery,
per-mode bounds, crash-race resume, per-item local verification reuse,
cross-mode hashes, late-generation rejection, the shared verifier taxonomy,
telemetry reconciliation, route parity, reload-safe UI status, and companion
dgxlib capacity resolution all have focused passing evidence. The repository's
remaining broad-suite failures are unchanged on `origin/main` or caused by the
documented local worktree environment; none are introduced by #549.
