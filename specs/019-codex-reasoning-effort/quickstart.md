# Quickstart: Validate Codex Reasoning Effort Everywhere

This guide validates the feature after implementation. Automated scenarios use
the fake Codex CLI and spend no model tokens. The final authenticated smoke test
is optional.

## Prerequisites

- Python satisfying `pyproject.toml` (`>=3.9`) with project test dependencies.
- Node `^20.19.0` or `>=22.12.0` for the locked Vite 8 toolchain.
- Frontend dependencies installed from `frontend/package-lock.json`.
- For the optional live smoke only: a compatible Codex CLI with saved ChatGPT
  login and access to `gpt-5.6-sol`.

From the repository root:

```bash
rtk proxy python -m pip install -e '.[test]'
rtk npm --prefix frontend ci
```

## 1. Validate adapter resolution and transport

```bash
rtk pytest tests/test_codex_cli_backend.py tests/test_check_consistency_codex.py tests/test_codex_reasoning_effort.py
```

Expected coverage:

- all six explicit values are accepted;
- explicit value beats `CG_CODEX_REASONING_EFFORT`;
- environment-only value is labeled `environment`;
- whitespace environment produces `Codex default`;
- omission adds no `model_reasoning_effort` argv entry;
- `gpt-5.6-sol` plus `max` reaches the fake child unchanged;
- invalid/empty values and explicit wrong-backend use start no child;
- direct, streaming, and brokered requests use the same option;
- isolation flags and credential stripping remain unchanged;
- a child compatibility error names model and effort and never falls back.

See [Production CLI contract](contracts/cli-family.md) and
[Run identity contract](contracts/run-identity.md).

## 2. Validate all 30 production CLI surfaces

```bash
rtk pytest tests/test_codex_cli_family.py tests/test_backend_seam_guardrails.py
rtk pytest tests/test_sd_agent.py tests/test_ensemble_dispatch.py tests/test_ensemble_batch_flag.py tests/test_facts_to_state.py
```

Expected coverage:

- 26 direct commands obtain exactly one canonical option;
- `facts_to_state` consumes the shared hand-written-parser helper;
- `sd_agent`, `ensemble`, `ensemble_batch`, and `ensemble_extract` forward an
  explicit effort to every applicable child;
- omission remains omitted across dispatchers so the final adapter owns the
  environment fallback;
- `enhance_summary` and `check_consistency` use the shared path;
- a future Codex-capable command without effort parity fails discovery.

## 3. Validate server resolution, persistence, and run logs

```bash
rtk pytest tests/test_platform_config_service.py tests/test_config_routes.py
rtk pytest tests/test_selection_isolation.py tests/test_service_selection_override.py
rtk pytest tests/test_session_editor_config_service.py tests/test_editor_service_integration.py tests/test_editor_pipeline.py
rtk pytest tests/test_ensemble_config_defaults.py tests/test_ensemble_gates.py tests/test_subprocess_abort.py
rtk pytest tests/test_codex_reasoning_config.py tests/test_connections.py tests/test_polish_codex.py
```

Expected coverage:

- `/api/config/models` publishes the six canonical values;
- request → service → platform → environment → omission precedence is visible
  in resolved selection JSON;
- only request/service/platform values become a CLI flag;
- old YAML without effort fields loads without rewrite;
- global, session-editor, generic-service, and ensemble values round-trip;
- effort-only overrides are not discarded by `is_empty()`;
- switching backend retains Codex memory without sending it elsewhere;
- every server command builder forwards the central flag;
- environment/default identity appears in durable Markdown run logs;
- the in-process Connection Graph response returns run identity.

See [UI/server contract](contracts/ui-selection.md) and
[Data model](data-model.md).

## 4. Validate the frontend

```bash
rtk pytest tests/test_codex_reasoning_ui.py
rtk npm --prefix frontend run build
```

Expected result: `vue-tsc -b` and the Vite production build succeed. Review the
UI against these checks:

1. Set the global backend to Codex and confirm exactly seven effort choices.
2. Select `max`, reload, switch to another backend and back, and confirm `max`
   is retained without appearing for the other backend.
3. Repeat in a generic service selection, Session Doc Editor, and both relevant
   ensemble stage selections.
4. Clear the selection. With no environment fallback, the resolved preview and
   run output say `Codex default`; with an environment fallback, they identify
   the environment value.
5. Launch a run and confirm the progress/result output shows both model and
   effort before generated content.
6. Run Connection Graph extraction and confirm its result summary shows the
   returned identity despite the absence of a subprocess SSE stream.

## 5. Run the full deterministic suite

```bash
rtk pytest tests/
rtk npm --prefix frontend run build
```

No authenticated Codex child should be started by this suite.

## 6. Optional authenticated smoke: explicit `max`

Choose an expendable document and output path. This call may spend subscription
tokens:

```bash
rtk proxy check_consistency /path/to/document.md \
  --config /path/to/config.yaml \
  --backend codex-cli \
  --model gpt-5.6-sol \
  --codex-reasoning-effort max \
  --output /tmp/cg357-consistency.md
```

Expected before model output:

```text
Codex run: model=gpt-5.6-sol (explicit); reasoning_effort=max (explicit)
```

Confirm the command succeeds, the report lands only at the requested path, and
the invocation still contains `--ignore-user-config` plus one
`model_reasoning_effort="max"` override.

## 7. Optional authenticated smoke: environment and omission

Environment fallback:

```bash
rtk proxy env CG_CODEX_REASONING_EFFORT=high check_consistency \
  /path/to/document.md \
  --config /path/to/config.yaml \
  --backend codex-cli \
  --model gpt-5.6-sol \
  --output /tmp/cg357-consistency-env.md
```

Expected identity includes `reasoning_effort=high (environment)`.

Total omission:

```bash
rtk proxy env -u CG_CODEX_REASONING_EFFORT check_consistency \
  /path/to/document.md \
  --config /path/to/config.yaml \
  --backend codex-cli \
  --model gpt-5.6-sol \
  --output /tmp/cg357-consistency-default.md
```

Expected identity includes `reasoning_effort=Codex default (omitted)`, and the
child argv contains no `model_reasoning_effort` key.
