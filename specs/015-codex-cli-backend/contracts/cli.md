# Contract: Consistency CLI with `codex-cli`

## Invocation

```text
python3 session_doc/check_consistency.py DOCUMENT
  --config CONFIG
  --backend codex-cli
  [--model MODEL]
  [--context PATH ...]
  [--output REPORT]
```

All existing document, config, context, output, and issue-count behavior remains
unchanged. `codex-cli` joins the shared `--backend` vocabulary; it is not added to
the web UI in this feature.

## Model resolution

| Input | Effective Codex behavior |
|---|---|
| Explicit compatible `--model` | Pass it to `codex exec --model`. |
| No flag, `CG_CODEX_MODEL` set | Pass the environment value. |
| Neither set | Omit `--model`; Codex uses its subscription/config default. |
| Explicit/environment `claude-*` | Refuse before invocation with an actionable error. |

For every existing backend, an omitted `--model` still resolves to the existing
`DEFAULT_MODEL`. Help/status output must describe an omitted Codex model as the
Codex subscription default, not display the inherited Claude default.

`CG_CODEX_TIMEOUT` controls the child deadline and defaults to 600 seconds. Invalid
values fail before invocation.

## Batch behavior

Any Batch API request with `--backend codex-cli` is rejected by the existing
non-Anthropic backend guard. No subprocess is started and no alternative provider
is selected.

## Success behavior

- Run one Codex child for the explicitly selected document.
- Write a non-empty Markdown audit to the normal report path.
- Preserve the existing issue-count/status presentation.
- Leave the source document and all campaign context unchanged.

## Error behavior

The command catches `CodexCliError`, writes one concise actionable diagnostic to
stderr, returns nonzero, and does not create a misleading successful report.
Diagnostics distinguish missing CLI, login/authentication, invalid model/timeout,
timeout, process failure, and empty result. Unexpected programming errors are not
masked by a broad runtime-error catch.

## Security behavior

Even if the parent command has `OPENAI_API_KEY` or `CODEX_API_KEY`, the Codex child
does not receive them. The invocation requires the saved ChatGPT subscription
login and executes under the adapter contract's isolation policy.

## Compatibility behavior

Existing backend defaults, retry behavior, thinking options, and Claude Code
behavior remain unchanged. `codex-cli` is keyless for the shared credential gate
but is not classified as thinking-capable.
