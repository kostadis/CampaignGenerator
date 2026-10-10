# Quickstart: Validate the Resilient DGX Scheduler

Use fake/in-process endpoints and temporary campaign fixtures; no live DGX or paid call is required.

## Prerequisites

```bash
cd /path/to/CampaignGenerator
python -m pytest --version
cd frontend && npm install && cd ..
```

Prepare a minimal summary-native fixture with explicit chapters, two fake OpenAI-compatible endpoints serving `qwen3.8-flash-next`, controlled delays, and fake dgxlib `max_concurrency=8`.

## 1. Default and provenance

```bash
pytest -q tests/test_summary_native_concurrency.py tests/test_dgx_registry.py
```

Expected: omitted DGX value is 8/source dgxlib; absent field is fallback 6; explicit 3 wins; malformed presence refuses; each endpoint stays within bound.

## 2. Failure, quarantine, failover, recovery

```bash
pytest -q tests/test_summary_native_scheduler.py -k 'quarantine or failover or recover or bound'
```

Fixture: both endpoints preflight; A completes two items then emits a final campaignlib-classified timeout; scheduler quarantines A and requeues unfinished item to B; B continues; injected time triggers successful A probe and rejoin.

Expected: all eligible items complete, no duplicate commit, each item visits an endpoint at most once, and event/attempt totals reconcile. Also cover all-preflight-fail, retry exhaustion, model rejection without quarantine, and ignored late generation.

## 3. Cache-based resume

```bash
pytest -q tests/test_summary_native_scheduler.py tests/test_summary_native_extract.py -k resume
```

Expected: compatible checked chunks receive no call; incomplete output is scheduled; artifact-success/record-missing repairs without call; record-success/artifact-missing invalidates; changed result inputs refuse/invalidate; endpoint topology changes preserve results; completed resume makes zero calls; no/ambiguous run refuses.

Repeat for audit and NPC draft. For NPC verification, stale reports rerun locally and failing verdicts remain verifier outcomes rather than transport failures.

## 4. Stable order and hashes

```bash
pytest -q tests/test_summary_native_scheduler.py -k deterministic
```

Run the same deterministic fixture serially, parallel with reversed delays, with failover, and interruption/resume. Aggregate output bytes/hashes must match; telemetry may differ and is excluded from content identity.

## 5. Taxonomy and telemetry

```bash
pytest -q tests/test_summary_native_scheduler.py tests/test_summary_native_npc_verify.py -k 'taxonomy or telemetry or usage'
```

Inject each operational and verifier category. Expect one terminal group per item, retained legacy subcodes, honest unavailable usage, and reconciled aggregate/per-endpoint math.

## 6. CLI/routes

```bash
pytest -q tests/test_summary_native_cli.py tests/test_summary_native_routes.py tests/test_npc_dossiers_routes.py
```

Expected: argv carries explicit values/resume, omission injects no literal 6, invalid combinations fail before spawn, status reconstructs from disk, and routes contain no scheduling policy.

## 7. UI reload

```bash
cd frontend
npm run build
```

With fake service: select explicit scope; confirm resolved 8/source; start two-endpoint work; observe quarantine; reload; confirm durable progress/health and resume; resume and inspect categorized result. Repeat NPC draft and deterministic verify. Empty selection remains disabled and engine-refused.

## 8. Full regression and docs

```bash
pytest -q
cd frontend && npm run build
```

Review `docs/cli/summary_native_howto.md` and `docs/cli/npc_dossiers_howto.md` for changed default, precedence, resume identity, health, categories, recovery, and current model-free verification. Verify the dgx-fun/dgxlib companion declares `qwen3.8-flash-next.max_concurrency: 8`; fake consumer tests alone do not complete #539.
