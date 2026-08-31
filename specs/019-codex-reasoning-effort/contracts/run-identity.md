# Contract: Codex Run Identity and Observability

## Canonical identity

The final adapter resolves model and effort before starting `codex exec` and
constructs one `CodexRunIdentity`. This object is the source for human output,
errors, and machine-readable metadata.

```json
{
  "backend": "codex-cli",
  "model": "gpt-5.6-sol",
  "model_source": "explicit",
  "codex_reasoning_effort": "max",
  "codex_reasoning_effort_source": "explicit",
  "codex_reasoning_override": true
}
```

For total effort omission:

```json
{
  "backend": "codex-cli",
  "model": "Codex default",
  "model_source": "omitted",
  "codex_reasoning_effort": "Codex default",
  "codex_reasoning_effort_source": "omitted",
  "codex_reasoning_override": false
}
```

`model` may be explicit, environment-derived through `CG_CODEX_MODEL`, or
`Codex default`. The effort source is exactly `explicit`, `environment`, or
`omitted` at the final child boundary.

## Human-readable status line

Before `subprocess.run`, every direct, streaming, and brokered Codex request
emits one stable line:

```text
Codex run: model=gpt-5.6-sol (explicit); reasoning_effort=max (explicit)
```

Examples:

```text
Codex run: model=gpt-5.6-sol (environment); reasoning_effort=high (environment)
Codex run: model=Codex default (omitted); reasoning_effort=Codex default (omitted)
```

The line is emitted after local validation and before model work. It contains no
credential, prompt content, campaign path, or user configuration.

## Terminal and UI behavior

- Manual CLI users see the line in ordinary command output before generated
  content or progress.
- Subprocess-backed server routes stream it through the existing SSE `data`
  events; no new event type is required.
- Existing UI output/progress/result panes preserve and display the line.
- Parent dispatchers may report configured forwarding intent, but the final
  direct child's line is authoritative for environment and omission sources.
- Fan-out produces one line per newly started Codex unit, matching each actual
  child execution.

## Durable logs and sidecars

`server/subprocess_runner.py::_save_run_log()` already stores the command and
captured output. The canonical line must therefore appear under `## Output` for
every UI subprocess-backed run, including environment/default cases absent from
the command argv.

Any existing command-specific record that reports a Codex model also adds the
effort value and source. This includes JSON/JSONL execution traces such as the
ensemble polish run event. Records that never report a model need not acquire a
new metadata schema solely for this feature.

## In-process Connection Graph exception

`server/routers/connections.py::extract_connections()` invokes the shared
client inside the server process, so it has no `stream_subprocess` SSE capture
or Markdown subprocess log. Its successful response adds:

```json
{
  "run_identity": {
    "backend": "codex-cli",
    "model": "gpt-5.6-sol",
    "model_source": "explicit",
    "codex_reasoning_effort": "max",
    "codex_reasoning_effort_source": "explicit",
    "codex_reasoning_override": true
  }
}
```

`ConnectionGraph.vue` renders this identity near the result/cache summary. The
response field is absent or provider-appropriate for non-Codex runs; it never
pretends another backend has Codex reasoning effort.

## Error contract

Local validation errors occur before a child and contain:

- the invalid value or environment variable name;
- the six accepted values;
- the effective backend when wrong-backend use caused the error.

If Codex rejects a canonical but unsupported model/effort pair, the surfaced
error includes both selections, for example:

```text
codex-cli failed for model 'example-model' with reasoning effort 'max': ...
```

The diagnostic does not claim which values the model supports unless Codex
itself supplies that detail. The run starts no replacement child and creates no
successful artifact.

## Security and compatibility

- Identity output never reveals API keys, saved-login tokens, prompts, or
  user-config contents.
- Existing run-log redaction remains active.
- Omitted effort is labeled `Codex default`, not an inferred value.
- Existing Anthropic, DGX, OpenRouter, and Claude Code output is unchanged.
- Existing Codex output without an explicit or environment value gains only the
  truthful default identity line; its child argv and behavior remain unchanged.

## Verification assertions

Tests prove that:

1. the line precedes the fake child invocation;
2. explicit, environment, and omitted cases use the exact labels above;
3. the Markdown run log captures the line even when the command has no effort
   flag;
4. model-specific child failure includes model and effort and starts one child;
5. the Connection Graph response exposes the same identity;
6. every model-reporting metadata site includes effort and source;
7. redaction and existing command-event behavior remain unchanged.
