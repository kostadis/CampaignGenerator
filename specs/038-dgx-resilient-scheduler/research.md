# Research: Resilient DGX Work Scheduler

## R1. Authoritative concurrency and precedence

**Decision**: Add optional positive `max_concurrency` to dgxlib's per-model configuration. Resolve per-endpoint parallelism as explicit `--parallel` > selected DGX model's `max_concurrency` > `DEFAULT_EXTRACT_PARALLEL` (6). Record source as `explicit`, `dgxlib:<model>`, or `fallback`.

**Rationale**: `campaignlib/api/backends.py` already resolves per-model timeouts and request behavior through `dgxlib.resolve_model_config`, the constitutional DGX seam. Issue #539 identifies 8 as the served capacity of `qwen3.8-flash-next`. A nullable field preserves older registries and non-DGX behavior.

**Alternatives considered**: Hard-code 8 in CampaignGenerator (duplicates server truth); probe `/models` for capacity (the wire response does not promise it); store it in campaign config (machine behavior becomes campaign state).

## R2. Scheduler location and dependency direction

**Decision**: Place a provider-neutral scheduler in `pipelines/summary_native/scheduler.py`. It receives stable work items, endpoint descriptors, call/health adapters, a result committer, and an injected clock. It does not import provider SDKs, parse campaign sources, or know artifact formats.

**Rationale**: Extraction and audit share `extract._run_pool`, but the helper has no health/retry/durability contract. NPC drafting has a separate serial loop. A summary-native scheduler is reusable without broadening campaignlib into pipeline policy. Provider calls still cross only campaignlib.

**Alternatives considered**: Extend `_run_pool` inside extract (wrong ownership); put scheduling in campaignlib (mixes product durable semantics into API boundary); add a daemon/database queue (recurring state tax and second truth).

## R3. Transport retry versus cross-endpoint retry

**Decision**: campaignlib exposes a small public classifier for the final exception after `stream_api`/`call_api` exhausts retries. The scheduler reassigns only transport/endpoint failures and does not call that endpoint again for the item. Model-response validation rejection remains an operation outcome; a separately named content-repair attempt may remain only where the existing operation contract requires it.

**Rationale**: campaignlib already retries rate limit, overload, connection, timeout, and selected 5xx errors. Current extract/audit catch every exception and retry once, duplicating a complete retry chain and mixing malformed output with infrastructure failure. Classification belongs at the one call seam.

**Alternatives considered**: Import private `_is_retryable` in each operation (fragmentation); re-run every exception (double retry); infer type from strings (unstable).

## R4. Quarantine and recovery policy

**Decision**: Preflight each endpoint independently. Failed endpoints are quarantined while healthy endpoints may start. One exhausted transport chain immediately quarantines its endpoint. Probe quarantined endpoints at a visible interval; rejoin only after successful model-presence health check. Each item attempts each endpoint at most once per run.

**Rationale**: Current preflight refuses all work if any endpoint is down. Immediate quarantine avoids repeated minutes-long retry chains. Per-item attempted endpoints make exhaustion finite and explainable. Active proof is safer than timer-only reopening.

**Alternatives considered**: Failure-count threshold (wastes work); timer then blind dispatch (risks another item); no in-run rejoin (misses acceptance).

## R5. Determinism and late results

**Decision**: Adapters materialize canonical items with immutable ID and ordinal. Completion may arrive in any order, but canonical artifacts commit once per item and aggregates assemble by ordinal. An assignment generation token rejects late results from obsolete assignments.

**Rationale**: Timing must not influence output. Generation guards the race where a quarantined assignment returns after safe reassignment.

**Alternatives considered**: Assume thread cancellation works (network calls may not cancel); filesystem first-writer race (nondeterministic); completion-order assembly (violates stable output).

## R6. Resume without a parallel checkpoint store

**Decision**: Existing checked caches/drafts/verification artifacts prove successful completion. The run record journals selection, compatibility, attempts, endpoint transitions, and telemetry. Resume reconstructs every selected item, validates its operation artifact/key, and schedules only items without compatible success. A run record cannot turn a missing/invalid artifact into completed state.

**Rationale**: Extract already caches checked chunks, audit caches answers/items, and NPC drafting has keys/index/run records. Issue #549 explicitly requires reuse. The journal supplies observability while remaining subordinate to artifacts.

**Alternatives considered**: SQLite/job DB (second truth); checkpoint JSON declaring completed IDs (can disagree); filename existence only (stale/corrupt success).

## R7. Resume identity

**Decision**: Compatibility binds operation, explicit item/key, model/backend, prompts/rules, audience, and result-affecting options. Endpoint list, assignment, parallel limit, health cadence, timestamps, and telemetry do not invalidate results. `--resume [RUN_ID]` supports exact selection; bare resume chooses exactly one newest compatible incomplete run and refuses zero or ambiguity.

**Rationale**: Endpoint replacement is the recovery purpose. Explicit IDs are deterministic; convenient bare resume is safe only for one compatible candidate.

**Alternatives considered**: Endpoints in cache key (blocks failover); latest timestamp alone (wrong run risk); resume as silent new run (spend surprise).

## R8. Operation adaptation, including verification

**Decision**: Extraction chunks, audit claims, and selected NPC drafts are remote work items. NPC verification is currently deterministic and remains model-free; it uses the same stable item/result/journal path with a bounded local executor and no invented DGX calls. If #523 later adds an endpoint-backed verifier, its adapter uses the scheduler and the same operational envelope. Align taxonomy now.

**Rationale**: `npc_verify.py` explicitly says deterministic and never calls a model. Routing it to DGX would violate its trust contract and add spend. Shared scheduling/reporting can apply per NPC without inventing a model boundary.

**Alternatives considered**: Make verification call DGX (scope/authority regression); exclude verification (misses parent scope); block on #523 (adapter can be forward-compatible).

## R9. Failure taxonomy

**Decision**: Use two axes. Operational outcome is success/cached, model-response rejection, verifier finding/rejection, transport failure, or retry exhausted. Verification findings additionally use #523 categories: `unsupported_or_contradicted`, `citation_non_entailment`, `superseded_claim`, `knowledge_leak`, `missing_source`, `presentation_only`, `verifier_transport_or_protocol`. Keep legacy detailed codes as subcodes/evidence.

**Rationale**: Typography and dead endpoints require different actions. Two axes preserve current precise mechanical codes while making #519 and #523 reports agree.

**Alternatives considered**: Replace legacy codes now (breaking/lossy); one flat mixed list (not actionable); call all verifier failures model rejection (incorrect).

## R10. Telemetry and token usage

**Decision**: Record per-attempt monotonic duration, endpoint, scheduler retry ordinal, outcome, and usage when campaignlib can supply it. Use `null` and `usage_available: false` when the facade returns text only. Derive aggregates from attempt records.

**Rationale**: Current `stream_api` returns text and not every backend exposes usage. Honest absence meets the requirement without estimates; event-derived totals cannot drift from counters.

**Alternatives considered**: Estimate tokens (not provider usage); change every call return type in this feature (excess scope); omit usage (misses issue).

## R11. CLI, route, and UI parity

**Decision**: Use shared `--endpoints`, optional `--parallel`, and `--resume [RUN_ID]` grammar for remote operations, plus durable read-only status. Routes build CLI argv and stream execution. Summary Native shows extract/audit; existing NPC dossiers UI shows draft/verify. Both display resolved source and endpoint/local worker health.

**Rationale**: Principles VI, IX, XI require CLI engine and UI reach. Status cannot rely on SSE because reload/disconnect is an acceptance case. Per-run endpoints preserve current machine-wiring policy.

**Alternatives considered**: Browser queue state (lost); in-process route scheduler (split brain); persist endpoints in campaign content config (wrong state owner).

## R12. Migration and compatibility

**Decision**: Add schema-versioned run fields with tolerant old-record readers. Preserve cache keys unless result inputs change. No workspace migration. Document that omitted parallel may rise from 6 to model-declared value.

**Rationale**: Old caches are valuable; run records are generated history rather than authored schema. The behavior change is deliberate and visible.

**Alternatives considered**: Rewrite history (risk); ignore old caches (waste); dual cache locations (fragmentation).
