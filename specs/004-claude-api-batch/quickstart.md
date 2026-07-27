# Quickstart: Validating Claude API Batch Mode

**Feature**: 004-claude-api-batch. Runnable scenarios proving the spec's success criteria. Details: [contracts/cli-batch-flag.md](contracts/cli-batch-flag.md), [data-model.md](data-model.md).

## Prerequisites

- `ANTHROPIC_API_KEY` set; repo editable-installed into the server venv is **not** required (CLI-only feature), but console scripts must resolve (`uv pip install -e .` if testing via installed names).
- A campaign workspace with real inputs (e.g. the OOTA checkout) for the end-to-end runs; unit-level checks run from `tests/` with fakes.
- Run CLIs from the campaign dir (config auto-detection).

## 1. Identical artifacts, discounted billing (SC-001, SC-002 / FR-004)

```bash
# Sequential baseline (writes docs/planning_draft.md)
planning --synthesize --output docs/planning_draft.seq.md

# Batch run of the same synthesis
planning --synthesize --batch --output docs/planning_draft.batch.md
```

**Expect**: stderr shows `Batch submitted: msgbatch_… (1 requests)`, progress ticks, exit 0; both outputs are complete documents of the same kind/location pattern. Billing console shows the batch run at the batch rate. (Content differs run-to-run — the check is completeness and placement, not byte equality across separate generations.)

Multi-unit case (the real win):

```bash
distill --batch          # extraction fan-out through run_extract_pipeline
```

**Expect**: one submission line with N requests (N = missing chunks only — pre-populate some chunk files to verify skip-if-exists runs before submission), all chunk files written, then the normal synthesize stage.

## 2. Uniform parameter across CLIs (SC-002 / FR-002)

```bash
for cli in prep sd_plan sd_consistency sd_narrate scene_extract enhance_summary \
           distill party campaign_state planning npc_table make_tracking query \
           transform dnd_sheet synthesise_world_state synthesise_polish \
           extract_facts polish scrub_mechanics check_consistency vtt_voice_compare \
           scabard_sync facts_to_state; do
  $cli --help 2>&1 | grep -q -- "--batch" || echo "MISSING: $cli"
done
```

**Expect**: no `MISSING:` lines.

## 3. Fail-fast on non-anthropic backends (FR-003)

```bash
sd_plan --batch --backend claude-code ... ; echo "exit=$?"
CG_BACKEND=openrouter sd_plan --batch ...  ; echo "exit=$?"
```

**Expect**: immediate error naming the backend and `--batch`, non-zero exit, no API traffic, no partial outputs.

## 4. Partial failure is loud and non-zero (SC-003 / FR-008)

Unit-tested with the `_fake_client_with_batches` fake (one succeeded + one errored item):

```bash
env -u PYTHONPATH ~/.venvs/main/bin/python -m pytest tests/test_batch_api.py -q
```

**Expect**: tests assert successful item's file written (atomically), `FAILED <custom_id>: …` line emitted, exit code propagated non-zero, truncation banner fired for a fake `stop_reason="max_tokens"` item (FR-010).

## 5. Abort cancels the remote batch (SC-005 / FR-009)

```bash
distill --batch &     # start a real multi-unit batch
kill -TERM %1         # graceful abort (same signal the web UI abort sends first)
```

**Expect**: stderr shows `Abort received — requesting batch cancellation… status: canceling`, process exits non-zero. Verify in the provider console (or via the printed batch id) that the batch is canceling/canceled — no silently running remote work.

## 6. No-batch runs unchanged (SC-004 / FR-011)

```bash
env -u PYTHONPATH ~/.venvs/main/bin/python -m pytest -q   # full suite, from the branch checkout
```

**Expect**: pre-existing tests pass unchanged (known pre-existing failures excepted); a sequential run of any CLI produces the same behavior/outputs as before the change.

## 7. Order-dependent CLIs degrade correctly (FR-006 boundary)

```bash
sd_narrate --batch <session-args>
```

**Expect**: N sequential `Batch submitted: … (1 requests)` lines (one per scene — the handoff chain forbids grouping), final narration files present per scene; help text documents the degraded mode.
