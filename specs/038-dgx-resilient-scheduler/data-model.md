# Data Model: Resilient DGX Work Scheduler

Durable files remain under existing summary-native output roots. These are logical records, not a database.

## ConcurrencyResolution

| Field | Type | Rules |
|---|---|---|
| `value` | positive integer | Effective calls in flight per endpoint |
| `source` | `explicit \| dgxlib \| fallback` | Stable provenance |
| `model` | string or null | Required for dgxlib source |
| `declared_max` | positive integer or null | Registry value when present |

Explicit values must be positive. A present dgxlib value must be positive; malformed presence refuses, while absence permits fallback 6.

## WorkItem

| Field | Type | Rules |
|---|---|---|
| `item_id` | string | Unique stable operation identity |
| `ordinal` | nonnegative integer | Unique contiguous canonical order |
| `operation` | enum | `extract`, `audit`, `npc-draft`, `npc-verify` |
| `compatibility_key` | SHA-256 | Binds result-affecting input |
| `display` | object | Non-authoritative progress label |
| `artifact_refs` | path list | Adapter-validated completion evidence |
| `attempted_endpoints` | string set | No same-endpoint scheduler retry |
| `assignment_generation` | integer | Rejects stale late completions |
| `state` | ItemState | Derived state |

```text
pending -> in_flight -> succeeded
                    -> model_rejected
                    -> verifier_rejected
                    -> transport_waiting -> in_flight (different endpoint)
                                          -> retry_exhausted
pending -> cached
pending -> invalidated -> in_flight
```

`succeeded` and `cached` require compatible artifacts. `transport_waiting` is nonterminal. Older-generation completion is recorded as ignored and cannot commit.

## EndpointState

| Field | Type | Rules |
|---|---|---|
| `endpoint_id` | string | Unique normalized identity; collision refuses |
| `url` | string | Per-run wiring; secrets redacted on disk/output |
| `model` | string | Must appear in successful health response |
| `limit` | positive integer | Independent bound |
| `state` | `unknown \| healthy \| quarantined \| probing \| retired` | Dispatch only healthy |
| `active_count` | integer | 0..limit runtime projection |
| `last_check_at` | timestamp/null | UTC display time |
| `last_failure` | failure/null | Quarantine reason |
| `quarantine_started_at` | timestamp/null | Present while quarantined |
| `recoveries` | integer | Derived transitions |

```text
unknown -> healthy/quarantined
healthy -> quarantined
quarantined -> probing -> healthy/quarantined
healthy/quarantined -> retired
```

## AttemptRecord

| Field | Type | Rules |
|---|---|---|
| `attempt_id` | string | Unique in run |
| `item_id` | string | References WorkItem |
| `endpoint_id` | string or `local` | Local for deterministic verification |
| `assignment_generation` | integer | Must match to commit |
| `started_at`, `finished_at` | timestamp | Wall-time audit |
| `duration_ms` | nonnegative integer | Monotonic measurement |
| `outcome` | enum | `success`, `model_rejected`, `verifier_rejected`, `transport_failure`, `ignored_late_result` |
| `failure` | FailureEnvelope/null | Structured non-success |
| `usage` | object/null | Provider usage when exposed |
| `usage_available` | boolean | False exactly when usage null |

Attempts are the source for endpoint telemetry. A transport-failed attempt is not necessarily a terminal item.

## FailureEnvelope

| Field | Type | Rules |
|---|---|---|
| `operational_category` | enum | `model_response_rejection`, `verifier_finding`, `transport_failure`, `retry_exhausted` |
| `code` | string | Stable existing/new detailed code |
| `message` | string | Sanitized explanation |
| `retryable_elsewhere` | boolean | True only after campaignlib transport exhaustion |
| `verifier_category` | enum/null | Shared #523 category |
| `evidence_refs` | list | Existing paths/lines/excerpts |

Verifier categories: `unsupported_or_contradicted`, `citation_non_entailment`, `superseded_claim`, `knowledge_leak`, `missing_source`, `presentation_only`, `verifier_transport_or_protocol`.

## SchedulerRunRecord

| Field | Type | Rules |
|---|---|---|
| `schema` | integer | New version 2; compatible v1 readable |
| `run_id` | string | Unique invocation identity |
| `operation`, `range` | enum/object | Existing operation/range identity |
| `selection` | ordered IDs + digest | Explicit, nonempty |
| `compatibility_digest` | SHA-256 | Result context |
| `backend`, `model` | strings | Resolved invocation |
| `concurrency` | ConcurrencyResolution | Value/source |
| `endpoints` | ordered summaries | Invocation topology |
| `health_interval_seconds` | positive number | Execution context only |
| `items` | ordered summaries | Canonical ordinal |
| `attempts` | ordered AttemptRecords | Dispatch sequence, not completion race |
| `endpoint_events` | ordered transitions | Monotonic sequence |
| `status` | enum | `running`, `incomplete`, `completed`, `refused`, `interrupted` |
| timestamps, `exit_code` | values | Atomic progress/finalization |

Rewrite atomically after initial selection/preflight, endpoint transitions, terminal attempts, canonical commits, and finalization. Resume always revalidates artifacts.

## Operation completion evidence

| Operation | Item | Compatible success | Incomplete/stale |
|---|---|---|---|
| extract | chunk/content key | raw output plus current valid checked JSON/key | missing section/raw pair/key mismatch |
| audit | tracking item/key | accepted cached answer under current inputs | not-judged/key mismatch/missing answer |
| npc-draft | selected NPC/draft key | complete draft plus matching current key | incomplete file/missing outline/key mismatch |
| npc-verify | selected NPC/draft+evidence digest | current verification result for exact inputs | missing/stale/unexecuted; failing verdict is terminal verifier rejection |

## Telemetry projection

Per endpoint derive attempted, successful, transport-failed, reassigned, retried-from-elsewhere, active, latency distribution, usage totals/unknown count, health checks, quarantine duration, and recoveries. Run totals derive from canonical item states plus attempts; cached items have no endpoint attempt.
