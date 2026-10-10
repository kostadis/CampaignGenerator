# Local UI and Route Contract

CLI remains engine. Route builders validate simple inputs, construct fixed argv, and use existing subprocess/SSE execution. They do not schedule or own endpoint health.

## Run parameters

Extract/audit/NPC draft accept omitted or positive `parallel`, repeated `endpoints`, and boolean/run-ID `resume`. NPC verify accepts resume and local parallel. Invalid resume+force, empty selection, non-DGX endpoints, or nonpositive values return 400 before spawn. Engine compatibility refusals retain exact code/message.

## Status projection

```json
{
  "present": true,
  "run_id": "...",
  "operation": "extract",
  "status": "incomplete",
  "concurrency": {"value": 8, "source": "dgxlib", "model": "qwen3.8-flash-next"},
  "counts": {"total": 40, "cached": 23, "completed": 12, "unfinished": 5, "failed": 0},
  "endpoints": [
    {"id": "spark-a", "state": "quarantined", "active": 0, "limit": 8, "reason": "...", "last_check": "..."}
  ],
  "outcomes": {},
  "resume_available": true
}
```

Rebuild projection from disk each request. Malformed records produce safe incomplete/error state, never success.

## UI behavior

- Show resolved concurrency/source before start when available and recorded resolution afterward; remove hard-coded “Blank = 6”.
- Materialize selection/range; Select all writes explicit scope; empty disables and engine refuses.
- Show endpoint state/limit/active/completed/latency/failures/quarantine/recovery.
- Preserve resume after reload; distinguish start and resume.
- Separate operational groups and show shared verifier category plus detailed code/evidence.
- SSE disconnect never fabricates completion; status refresh reads disk.
- Browser/Pinia/local storage is never checkpoint truth.

Extraction/audit live in existing Summary Native view. NPC draft/verify live in existing NPC dossiers workflow. Cross-link if useful; do not duplicate the NPC workflow merely to satisfy wording.
