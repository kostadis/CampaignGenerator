# Quickstart: Codex CLI Consistency Audits

## Prerequisites

Use a Codex CLI compatible with the 0.150.1 command surface and authenticate it
through ChatGPT:

```bash
codex --version
codex login
```

The CampaignGenerator command does not accept or forward an OpenAI API key for
this backend. Authentication remains in Codex-owned login storage.

## Run deterministic tests first

The implementation must pass the focused no-token suite:

```bash
pytest \
  tests/test_codex_cli_backend.py \
  tests/test_check_consistency_codex.py \
  tests/test_openrouter_seam.py \
  tests/test_backend_seam_guardrails.py \
  tests/test_no_credential_gate.py \
  tests/test_claude_code_backend.py \
  tests/test_check_consistency_batch.py \
  tests/test_consistency_canonical.py
```

The pre-implementation focused baseline is 37 passing tests. A broader selected
baseline had 245 passes, 147 skips, and three failures solely because the optional
`dgxlib` package was unavailable; compare against that known environment issue
rather than attributing it to this feature.

## Run one live audit

Choose a disposable or already-reviewed document and explicit campaign context.
The live command consumes subscription capacity:

```bash
env -u OPENAI_API_KEY -u CODEX_API_KEY \
  python3 session_doc/check_consistency.py path/to/document.md \
  --config path/to/config.yaml \
  --backend codex-cli \
  --context path/to/campaign-context.md \
  --output /tmp/codex-consistency-report.md
```

Expected behavior:

- the command runs one isolated `codex exec` process;
- Codex uses the saved ChatGPT login and its default model;
- the source document/context remain byte-for-byte unchanged;
- the output file contains a non-empty Markdown audit; and
- the report is a draft requiring human review.

To override the subscription default model for one run:

```bash
python3 session_doc/check_consistency.py path/to/document.md \
  --config path/to/config.yaml \
  --backend codex-cli \
  --model MODEL_ID \
  --output /tmp/codex-consistency-report.md
```

Use only a model available to the installed Codex CLI/account; the adapter passes
non-Claude names through and Codex validates them.

## Environment defaults

```bash
export CG_CODEX_MODEL=MODEL_ID
export CG_CODEX_TIMEOUT=600
```

Precedence is explicit `--model`, then `CG_CODEX_MODEL`, then the Codex default.
The timeout must be a positive finite number of seconds. Environment defaults do
not add a batch mode or fallback provider.

## Verify expected failures

Each command must fail before producing a successful report:

```bash
# Incompatible inherited/provider model
python3 session_doc/check_consistency.py path/to/document.md \
  --config path/to/config.yaml --backend codex-cli --model claude-sonnet-4

# Invalid timeout
CG_CODEX_TIMEOUT=0 python3 session_doc/check_consistency.py path/to/document.md \
  --config path/to/config.yaml --backend codex-cli

# Unsupported Batch API path (use the repository's existing batch flag syntax)
python3 session_doc/check_consistency.py path/to/document.md \
  --config path/to/config.yaml --backend codex-cli --batch
```

Also verify the missing-login diagnostic by using a disposable Codex home with no
credentials; do not delete or overwrite the operator's real login state.

## Verify skill delivery

After the separate dotfiles changes are tracked, resolve the installed skill
links and invoke `$consistency-check` and `$staged-consistency` against a safe
session. Confirm both reach `--backend codex-cli`, preserve issue-by-issue human
approval, and do not alter the staged HTML review flow.

## Final regression checks

```bash
git diff --check
pytest tests/test_retrieve_render_isolation.py
pytest tests/test_consistency_canonical.py
```

No live Codex invocation belongs in CI; the subprocess behavior is covered by
mocks, while this authenticated smoke test remains an intentional operator check.

## Implementation validation (2026-08-27)

- Codex CLI `0.150.1` accepted the complete strict isolation command and
  produced a non-empty report from synthetic document/context input with
  `OPENAI_API_KEY` and `CODEX_API_KEY` removed.
- SHA-256 hashes for both synthetic input files were identical before and after
  the live run, and no `cg_codex_cli_*` temporary directory remained.
- The focused feature/compatibility suite passed 276 tests.
- `tests/test_backend_seam_guardrails.py` passed 209 tests and retained its
  three pre-existing environment failures because optional `dgxlib` is absent.
- The full `tests/` collection remains unavailable in this environment because
  optional package `mcp` is absent (`tests/test_mcp_server.py`); this occurs
  during collection before feature tests run.
- Direct worktree script execution required the worktree root on `PYTHONPATH`
  because the local editable install points at the main checkout. Installed or
  main-checkout usage is unchanged.
