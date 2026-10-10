# Scheduler Run Record Contract

The atomic record journals invocation, attempts, endpoint transitions, telemetry, and saved selection. It cannot alone prove item completion: resume validates the operation cache/result artifact and compatibility key.

## Minimum version 2 shape

```json
{
  "schema": 2,
  "run_id": "20261010T120000Z",
  "operation": "extract",
  "range": {"since": 2, "until": 70},
  "selection": {"digest": "sha256", "items": ["chunk:001", "chunk:002"]},
  "compatibility_digest": "sha256",
  "backend": "dgx",
  "model": "qwen3.8-flash-next",
  "concurrency": {"value": 8, "source": "dgxlib", "model": "qwen3.8-flash-next", "declared_max": 8},
  "endpoints": [],
  "items": [],
  "attempts": [],
  "endpoint_events": [],
  "status": "running",
  "started": "RFC3339",
  "updated": "RFC3339",
  "finished": null,
  "exit_code": null
}
```

Detailed types are in [data-model.md](../data-model.md).

## Deterministic serialization and atomicity

- Selection/items use item ordinal; endpoints use configured normalized order.
- Attempts use dispatch sequence/stable ID, not completion timing; endpoint events use locked monotonic sequence.
- JSON uses sorted keys and final newline.
- Timing, assignment, and telemetry never enter content hashes/cache keys.
- Rewrite after initial selection/preflight, each endpoint transition, terminal attempt, canonical commit, and finalization.
- If artifact commit wins a crash race, resume validates it and repairs the record without a call. If record says success but artifact is invalid, resume invalidates and schedules it.

## Taxonomy

Operational categories: `model_response_rejection`, `verifier_finding`, `transport_failure`, `retry_exhausted`.

Verifier categories: `unsupported_or_contradicted`, `citation_non_entailment`, `superseded_claim`, `knowledge_leak`, `missing_source`, `presentation_only`, `verifier_transport_or_protocol`.

Existing codes such as `citation-mismatch`, `not-found`, `typography-normalised`, and `manual-dropped` remain detailed codes. Mapping is explicit/versioned, never inferred from messages.

## Privacy

Records remain owner-local and may contain private campaign labels/evidence. Endpoint serialization strips user-info, query secrets, and credentials. Private capability review endpoints receive no scheduler mutation power.
