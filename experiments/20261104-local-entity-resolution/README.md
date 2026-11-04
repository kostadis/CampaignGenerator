# Local model comparison for contextual entity references

This replays the final, explicitly marked orc/ogre experiment against the local
DGX model. The baseline is gpt-6.1-sol at medium effort. The verified live local
model is `qwen3.8-flash-next` at `http://192.168.1.147:8001/v1`; the other
documented Spark endpoint refused connections. No service was reconfigured.

The system strings and user prompts are copied byte-for-byte from the frozen
baseline and verified against its records. The payload, source spans, hidden
draft expectations, case order and evidence evaluator remain unchanged.
Gold is copied for local scoring but never enters model requests.

Normal local mode uses `thinking=False`, temperature 0 and a 16,000-token
completion cap. Reasoning mode uses `thinking=True` with the same task inputs
and cap. A final non-thinking configuration uses the server's verified native
JSON-schema control to enforce the output structure already specified in the
prompt; it supplies no expected relationship answers. The OpenAI-compatible
request extras, actual served model, token usage,
finish reason and elapsed time are captured through CampaignGenerator's adapter.
Reasoning content is not copied into the report; only its length is recorded.

## Run

From the worktree, with the existing CampaignGenerator environment:

```bash
python experiments/20261104-local-entity-resolution/run_local.py \
  --baseline /tmp/orc-identity-real-20261103-marked \
  --out /tmp/orc-local-new-run \
  --endpoint http://192.168.1.147:8001/v1 \
  --model qwen3.8-flash-next --thinking off
```

Use a fresh output directory; `--resume` retains completed raw responses,
including protocol failures, and completes missing arms without repairing or
rerunning the retained response. A protocol failure returns exit 3 after both
arms have been attempted. `--thinking on` selects reasoning mode explicitly.
All model calls use `campaignlib.api`; there is no provider/model fallback.

After both modes finish:

```bash
python experiments/20261104-local-entity-resolution/compare.py \
  --baseline /tmp/orc-identity-real-20261103-marked \
  --local /tmp/orc-identity-qwen-off-20261104 \
  --local /tmp/orc-identity-qwen-on-20261104 \
  --local /tmp/orc-identity-qwen-schema-20261104 \
  --out /tmp/orc-local-comparison.json

python -m pytest experiments/20261104-local-entity-resolution/test_run_local.py -q
```

The main comparison checks complete parseable output, 13/13 stricter source
expectations, exact-target quotation coverage, strict false coidentity, graph
conflicts and 16/16 appropriate words-only abstentions. The unresolved
exploratory membership case is also retained rather than hidden by the strict
score. Parsing failure is reported as unscoreable, not converted to guessed
semantic answers or silently repaired JSON.

The two local modes are distinct operating configurations, not equivalent
reasoning budgets to Codex medium. The local endpoint is shared and calls may
overlap, so elapsed times are observational. Codex timing was not recorded.
This small source-based fixture does not establish general model equivalence.
To reproduce the native-schema mode, use a fresh directory with
`--thinking off --structured json-schema`. See [FINDINGS.md](FINDINGS.md) for
the completed comparison and its failures.

The initial reasoning-mode response was empty and the original driver failed
before persisting its transport observations. Its recovered record explicitly
marks finish reason, token usage, served-model echo and exact elapsed time as
unavailable; no token-exhaustion claim is made. Its control was not run. The
driver now preserves backend response metadata when final text is empty, covered
by a regression test. Normal mode's malformed response is retained as a failure
and was not repaired or rerun during resume.

Private source passages and raw outputs remain outside the repository in the
named runtime directories. Production registry and campaign files are unchanged.
