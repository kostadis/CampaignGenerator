# Quickstart / Validation: Source-Custody Rebase

## Automated (no private campaign, no model endpoint)

```bash
python -m pytest tests/test_rebase_*.py tests/test_delta_*.py tests/test_claims_*.py -q
cd frontend && npm test -- SourceRebase && npm run build
```

### The fixture

The fixture is `tests/_rebase_fixture.py`. It extends the spec 039 delta fixture (`tests/_delta_us2.py`) and builds a git-initialised synthetic campaign containing:

- an active generation through chapter 5 with four documents, a timeline and a reference tree;
- a pending chapter-6 delta, with three NPC receipts already published and grounding staged;
- four corrected summaries mirroring ToEE (see the table).

| Fixture chapter | Correction | Expected path |
|---|---|---|
| 2 | payment terms changed in a cited entry | adopt-with-repairs (repair) |
| 3 | contradictory annotation removed from a cited entry | adopt-with-repairs (repair) |
| 4 | "unaware" → "not yet told" in a cited entry | adopt-with-repairs (hold allowed) |
| 5 | prisoner count, where the pending ch6 candidate also carries the old count | adopt-with-repairs, plus a pending-candidate finding after rebind |
| 1 (variant test) | whitespace-only change in an uncited region | adopt-unaffected, zero model calls |

Old bytes are committed to the fixture's git history before the corrections.

### Scenarios to prove

1. **Blocked first.** `claims select` on the pending plan exits non-zero with `CLAIMS_SOURCE_STALE`, and the message names a chapter with its expected and actual digests (FR-002).
2. **Inspect.** `delta rebase inspect --json` lists exactly chapters 2–5. Nothing is written, and the model-call counter is 0 (FR-001, SC-008).
3. **Prepare.** `delta rebase prepare --source …(2,3,4,5) --for-plan <pending>`:
   - creates snapshots under `custody/objects/`;
   - leaves corrected summaries byte-identical;
   - produces an impact set that lists the cited lines and marks the timeline as unknown.
4. **Semantic refusal.** `rebase decide --source-decision 5=adopt-unaffected` → `REBASE_SEMANTIC_CHANGE` (SC-002).
5. **Repair, decide.** Repairs are added and approved, chapter 4's line is held, and the timeline is attested-unaffected with a reason. All sources are then decided.
6. **Gates.** Run `grounding check`, `grounding preview`, the real `claims select`/`check` (not mocked), the exact signoffs and `grounding apply`. Then:
   - a new generation is active, and its parent is the old generation;
   - every old generation file is byte-identical (SC-004);
   - the staged range manifest lists only chapters 2–5, with gaps.
7. **Rebind and resume.** `delta plan rebind --plan <pending> --baseline <new>`:
   - NPC receipts are unchanged, and the NPC publish count is 0;
   - the grounding check flags the chapter-6 candidate's old prisoner count;
   - after repair, ch6 grounding publishes (SC-001).
8. **Stale boundaries.** Mutate each of source, baseline, impact, edit, decisions and preview after binding. Each produces exit 3 naming the input (SC-005).
9. **Recovery.** Inject a failure at each journaled promotion phase, then recover: there is one whole-bundle state, and an identical re-apply writes nothing (SC-006).
10. **Old bytes missing or wrong.** Delete the git history, or supply a wrong file → `REBASE_OLD_BYTES_UNAVAILABLE` / `MISMATCH`, naming the providers tried.

## Manual (ToEE, operator)

Follow `docs/cli/source_custody_rebase_howto.md`. Start from `/home/kostadis/toee/toee` with plan `plan-0a0f7aa90623202d`:

1. Run inspect, which should list chapters 16, 17, 38 and 42.
2. Prepare with `--for-plan`.
3. Review in the UI at `/grounding/rebase`.
4. Apply.
5. Rebind.
6. Finish the chapter 43 publication.
