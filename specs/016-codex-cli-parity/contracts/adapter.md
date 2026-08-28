# Contract: Codex CLI Adapter

## Direct text capability

`client.messages.create()` and `client.messages.stream()` remain the ordinary
provider facade.

### Accepted input

- Exactly one user message containing a string or ordered text blocks.
- System content as a string or ordered text blocks. Cache-control metadata may be
  present and has no effect on Codex transport.
- Optional compatible explicit Codex model.
- Existing output-token arguments, accepted as workflow sizing intent even though
  no equivalent Codex flag is promised.

### Rejected input

- More than one message.
- Assistant or tool-result history.
- Images or non-text content blocks.
- Arbitrary tool declarations or tool choice.
- Explicit `claude-*` model IDs.

### Output

- A non-empty Anthropic-shaped text response with `stop_reason=end_turn`.
- Streaming-shaped callers receive one complete final text chunk.
- No token count is fabricated.

## Brokered polish capability

The Codex client exposes a separate brokered message resource. The shared
`call_api_with_tools()` helper selects that resource when present and otherwise
retains the established provider path.

### Accepted input

- The ordered text/tool history used by `polish.run_agent_loop()`.
- The existing polish tool schemas.
- The same model and timeout semantics as the direct capability.

### Transport

1. Validate and normalize the full history.
2. Serialize it as the versioned typed transcript defined in `data-model.md`.
3. Write the broker result schema into the fresh temporary directory.
4. Start one fresh `codex exec --ephemeral` child with `--output-schema` and the
   same strict isolation flags and sanitized environment as the direct path.
5. Parse and validate the final structured message.
6. Convert it to existing text/tool-use response blocks. Do not perform actions in
   the adapter.
7. Remove the temporary directory on every exit.

### Result and error behavior

- Host-generated tool IDs are opaque and unique.
- `stop_reason=tool_use` iff one or more action requests are returned.
- `response.usage.input_tokens` and `response.usage.output_tokens` exist and are
  `None` for trace compatibility.
- Malformed history, output-schema failure, invalid JSON, non-object arguments,
  failed process, timeout, or empty result is fatal for that turn.
- Unknown but syntactically valid action names reach the existing polish dispatcher
  and return its normal tool-error feedback.
- There is no provider fallback and no transparent retry.

## Isolation invariant

Every direct request and every brokered polish turn must independently prove:

- fresh temporary working directory outside the campaign repository;
- read-only sandbox;
- ephemeral Codex execution;
- repository instructions and user config ignored;
- web, shell, plugins, apps, MCP servers, and delegation disabled;
- metered provider key variables absent from the child;
- saved Codex authentication still available;
- cleanup after success, refusal, error, interruption, and timeout.

Any Codex installation that cannot honor the complete command surface fails closed.

## Stable ownership

- `campaignlib/api/codex_cli.py`: Codex transport, isolation, normalization, and
  response facade.
- `campaignlib/api/client.py`: provider-neutral capability lookup and call helpers.
- `pipelines/ensemble/polish.py`: operation declarations, validation, dispatch,
  loop control, trace, and file mutations.

No pipeline, router, or Vue component may invoke Codex directly.
