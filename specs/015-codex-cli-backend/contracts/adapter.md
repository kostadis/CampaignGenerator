# Contract: Shared Codex CLI Adapter

## Public facade shape

`make_client(backend="codex-cli", model=<optional>)` returns an
Anthropic-shaped `_CodexCliClient` that supports:

```python
client.messages.create(
    model: str | None,
    system: str,
    messages: list[dict],
    max_tokens: int,
    **kwargs,
) -> response

with client.messages.stream(
    model: str | None,
    system: str,
    messages: list[dict],
    max_tokens: int,
    **kwargs,
) as stream:
    for text in stream.text_stream:
        ...
```

`create` returns an object compatible with the existing response text extractor.
`stream.text_stream` yields exactly one chunk: the complete final response.
`max_tokens` is accepted but is not forwarded because `codex exec` has no matching
flag. Anthropic thinking parameters are not forwarded.

## Accepted input

- One system/developer string.
- Exactly one user message.
- User content as a string or text blocks only.
- An optional explicit model, otherwise `CG_CODEX_MODEL`, otherwise no model flag.

The adapter rejects assistant history, multiple user turns, tools/tool results,
images, unknown content blocks, empty prompt text, and model values beginning with
`claude-`.

## Process invocation

The command is constructed as an argv list equivalent to:

```text
codex exec
  --ephemeral
  --ignore-user-config
  --ignore-rules
  --strict-config
  --skip-git-repo-check
  --sandbox read-only
  --cd <private-temp-dir>
  --color never
  -c approval_policy="never"
  -c forced_login_method="chatgpt"
  -c web_search="disabled"
  -c tools.web_search=false
  -c apps._default.enabled=false
  -c agents.enabled=false
  -c project_doc_max_bytes=0
  --disable <each verified executable feature family>
  -c developer_instructions=<TOML-quoted-system-text>
  --output-last-message <private-temp-result-path>
  [--model <effective-model>]
  -
```

The executable feature family is: `apps`, `hooks`, `multi_agent`, `plugins`,
`remote_plugin`, `shell_tool`, `skill_search`,
`skill_mcp_dependency_install`, `workspace_dependencies`, `tool_suggest`,
`browser_use`, `browser_use_external`, `computer_use`, `image_generation`,
`view_image`, and `code_mode_host`.

The subprocess receives user content through stdin, uses the isolated directory
as both process cwd and Codex `--cd`, captures stdout/stderr, and has no shell.
Its environment is the current environment minus `OPENAI_API_KEY` and
`CODEX_API_KEY`. `CG_CODEX_TIMEOUT` defaults to 600 seconds and must parse as a
positive finite number.

This contract targets the verified Codex CLI 0.150.1 command surface. Strict
configuration is intentional: an older or incompatible CLI must fail rather than
run with a weaker policy.

## Output contract

On exit zero, read `--output-last-message`, require non-whitespace text, and
return it through the facade. The temporary directory is deleted whether the run
succeeds or fails. A non-empty result is never read as success after a nonzero
process exit.

## Failure contract

Raise `CodexCliError` with a concise category and bounded diagnostics for:

- missing `codex` executable;
- invalid timeout or incompatible model;
- authentication/login failure;
- timeout expiration;
- any other nonzero exit;
- exit zero with a missing or empty result.

The exception is excluded from shared transient retry classification. The adapter
never falls back to Anthropic, OpenRouter, OpenAI-compatible, Claude Code, or DGX.

## Credential and isolation assertions

Tests must observe the actual environment and argv passed to `subprocess`, not
only helper return values. Required assertions are: both API-key names are absent;
the cwd is outside the repository; developer content and stdin remain distinct;
all fixed isolation options are present once; and temporary artifacts disappear
after success, timeout, and process failure.
