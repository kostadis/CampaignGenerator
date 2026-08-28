# Quickstart: Validate Codex CLI Parity

This guide is for implementation and review of feature 016. It assumes PR #350 /
feature 015 has been integrated into the working branch.

## 1. Confirm the baseline and toolchain

```bash
rtk git status --short
rtk codex --version
rtk python --version
rtk npm --prefix frontend --version
```

The Codex installation must support the feature-15 non-interactive isolation flags,
including ephemeral execution, ignored user config, and structured output schemas.
Do not weaken the command when an older installation lacks one of them.

## 2. Validate the adapter boundary

Run the focused direct and brokered-turn tests:

```bash
rtk pytest tests/test_codex_cli_backend.py tests/test_polish_codex.py tests/test_polish.py
```

Review failures against [the adapter contract](./contracts/adapter.md). The suite
must cover direct text, ordered system blocks, typed history, multiple action
requests, opaque IDs, tool-error feedback, usage-null trace compatibility,
malformed output/history, timeout, cleanup, exact child isolation, and zero
fallback.

The transport fixture meanings and their intentional invalid cases are recorded
in [`tests/fixtures/codex_cli/README.md`](../../tests/fixtures/codex_cli/README.md).
`broker_empty.json` and `broker_invalid.json` are expected fail-closed inputs;
they should not be “fixed” to make every fixture schema-valid.

## 3. Validate all 30 CLI surfaces

```bash
rtk pytest tests/test_backend_seam_guardrails.py tests/test_batch_flag_uniformity.py tests/test_no_credential_gate.py tests/test_openrouter_seam.py tests/test_claude_code_backend.py
```

The guardrail must discover exactly the current 30-command production inventory,
not rely on the old 22-entry registrar list. It must prove:

- 26 shared registrars plus `facts_to_state` and three hand-written dispatchers,
  with `sd_agent` classified separately as a shared-registrar runtime dispatcher;
- one canonical `codex-cli` spelling and help meaning;
- shared model-provenance resolution for every direct command;
- inherited Codex model omission and explicit incompatible-model refusal;
- provider `--batch` refusal before every direct or dispatcher launch;
- no Codex subprocess use outside the adapter.

## 4. Validate dispatch and workflow shapes

```bash
rtk pytest tests/test_sd_agent.py tests/test_ensemble_dispatch.py tests/test_ensemble_pipeline.py tests/test_ensemble_batch_flag.py tests/test_facts_to_state.py tests/test_narrate_chapter.py tests/test_grounding_backend.py tests/test_campaignlib_pipeline.py tests/test_scene_extract.py
```

These tests should use a fake executable or mocked subprocess and assert request
boundaries plus normal artifact paths. They do not require a saved login. Include
the full `ensemble_batch -> ensemble -> ensemble_extract -> extract_facts` chain and
the dispatcher-only `sd_agent` chain.

## 5. Validate server/config/UI parity

```bash
rtk pytest tests/test_platform_config_service.py tests/test_service_selection_override.py tests/test_selection_isolation.py tests/test_session_editor_config_service.py tests/test_editor_service_integration.py tests/test_editor_pipeline.py tests/test_ensemble_config_defaults.py tests/test_ensemble_gates.py
rtk npm --prefix frontend run build
```

Verify the 30-row capability map in
[the UI selection contract](./contracts/ui-selection.md): every command has a
direct or tested transitive invocation, all selectors expose Codex once, and CLI/UI
fixtures resolve identical backend and model intent. Old session editor config must
load without a Codex profile and a newly saved profile must round-trip separately.

For the Scabard route, tests must prove the access key is absent from argv, command
previews, logs, process diagnostics, and error messages.

## 6. Run the full regression suite

```bash
rtk pytest
rtk npm --prefix frontend run build
```

Existing Anthropic, DGX, OpenRouter, and Claude Code defaults and results must remain
unchanged. Treat any new live-provider fallback or retry as a release blocker.

## 7. Optional authenticated smoke

Run this only on an operator workstation with a saved Codex login. Remove metered
provider keys from the shell used for the smoke, choose one small fixture from each
of the four CLI families, and invoke the command with:

```text
--backend codex-cli
```

For at least one run, omit `--model`; for another, provide an explicit compatible
Codex model. Confirm the normal artifact location, visible progress, complete
cleanup, and no fallback-provider attempt. Also run one UI-launched equivalent and
compare its resolved argv/model intent. Do not make authenticated subscription
runs part of the deterministic test suite.

## 8. Documentation review

Confirm `docs/cli/cli_tools.md` covers:

- all 30 commands and their direct/dispatcher status;
- saved-login prerequisite and no-key behavior;
- explicit model -> `CG_CODEX_MODEL` -> subscription default precedence;
- timeout and actionable failure categories;
- the child isolation boundary and brokered polish ownership;
- provider `--batch` refusal versus application-level batching;
- direct and transitive UI reachability;
- no images, arbitrary tools, or fallback providers.

## 9. Implementation verification record

The feature-016 implementation was reviewed on 2026-08-27 with deterministic,
non-authenticated tests. The adapter/polish suite passed 103 tests; the workflow
and dispatcher suites passed 309 tests plus the three direct grounding Codex
cases; the server/config/UI checkpoint passed 184 Python tests; the complete
30-row reachability checkpoint passed 31 tests; and the provider-batch/timeout
checkpoint passed 186 tests. The frontend production build completed
successfully. No executed regression test showed a fallback-provider attempt or
an Anthropic, OpenRouter, or Claude Code behavior regression.

Two environment limitations prevented a single clean all-tests number in this
worktree:

- the inventory command completed 321 tests but its three DGX construction
  cases could not import the optional external `dgxlib` package;
- a raw full-suite collection stopped at `tests/test_mcp_server.py` because the
  current Python environment does not have the declared `mcp` dependency
  installed. Several pre-existing FastAPI `TestClient` suites also hang during
  local application startup, so equivalent direct route/service assertions were
  used for the feature checkpoints above.

These are dependency/test-environment blockers rather than feature-016 failures.
Re-run sections 3, 5, and 6 in the fully provisioned project environment before
release to obtain the final repository-wide pass count.
