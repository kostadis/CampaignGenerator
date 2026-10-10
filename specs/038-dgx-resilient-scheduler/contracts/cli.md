# CLI Contract

## Shared scheduler flags

```text
summary_native extract ... [--endpoints URL [URL ...]] [--parallel N] [--resume [RUN_ID]]
summary_native audit ... [--endpoints URL [URL ...]] [--parallel N] [--resume [RUN_ID]]
summary_native npc-draft ... [--endpoints URL [URL ...]] [--parallel N] [--resume [RUN_ID]]
summary_native npc-verify ... [--parallel N] [--resume [RUN_ID]]
```

NPC verification is currently deterministic and local. Its parallel value bounds local item workers and its start line says `local`; it does not invent model calls. If local parallelism is deferred, accept only 1 while still implementing stable journaling/resume.

- Omitted remote `--parallel`: resolve through [dgxlib.md](dgxlib.md). Parser default is `None`, never literal 6.
- Explicit `--parallel N`: positive, independently enforced per endpoint and recorded as explicit.
- `--endpoints`: DGX only; normalized IDs unique; endpoint must serve model to become healthy.
- Bare `--resume`: choose exactly one newest compatible incomplete run; refuse zero or ambiguity.
- `--resume RUN_ID`: resume exact run after operation/range/selection/compatibility validation.
- `--resume` with `--force` or dump-only: refuse.
- Resume never broadens selection. Current materialized selection equals saved selection.

## Output

First execution line includes effective provenance and durable work counts:

```text
parallel 8 per endpoint (dgxlib: qwen3.8-flash-next); 2/2 endpoints healthy; 17 pending, 23 cached
```

Progress identifies item, ordinal, endpoint/local executor, assignment, outcome, and duration. Endpoint quarantine/recovery is explicit. URLs never expose credentials. Progress may be completion ordered; final artifacts/reports are canonical ordered.

Each operation provides read-only status JSON through existing CLI conventions. Routes use that read model rather than reproduce scheduler rules.

## Exit semantics

| Condition | Exit |
|---|---:|
| all success/cached; verification complete with no failure | 0 |
| invalid selection/flags/resume or no endpoint healthy initially | 2 |
| some useful results and some unfinished/retry exhausted | existing incomplete exit, currently 3 |
| every remote item fails at model-call boundary and no cache success | existing model-failed exit, currently 4 |
| verification completes with failing draft(s) | existing verify-failed exit, currently 5 |

The record keeps model rejection, verifier rejection, transport failure, and retry exhaustion distinct even where a coarse exit is shared.
