# Codex CLI transport fixtures

These files are small, process-boundary fixtures for the feature-016 Codex
adapter. They describe the structured result returned by a brokered polish
turn; the adapter validates the envelope before converting it to the existing
Anthropic-shaped response facade.

The contract is
[`brokered-turn.schema.json`](../../../specs/016-codex-cli-parity/contracts/brokered-turn.schema.json).

| Fixture | Intended use | Contract status |
|---|---|---|
| `direct_success.json` | Normal direct text result; useful as the simplest successful fake child output. | Valid |
| `broker_multi_action.json` | One structured turn containing two ordered action requests. | Valid |
| `broker_tool_error.json` | Syntactically valid request for an unknown polish operation; the parent dispatcher should return tool-error feedback. | Valid envelope; semantic tool error |
| `broker_empty.json` | Empty text and no actions. | Invalid envelope; must fail closed |
| `broker_invalid.json` | Truncated JSON transport payload. | Invalid transport; JSON parsing must fail closed |

`arguments_json` is deliberately a JSON string in the outer envelope. The
parent, not the Codex child, owns operation validation and document mutation.
Unknown operation names are therefore allowed through transport validation so
the existing dispatcher can produce its normal error result; malformed JSON,
empty results, and malformed envelopes are fatal for that turn.

The fixtures do not contain credentials, real campaign content, or a model
identifier. An omitted model is intentional: model resolution is tested at the
CLI boundary as explicit model → `CG_CODEX_MODEL` → saved subscription default.
Provider `--batch` is not represented here because it is refused for
`codex-cli`; application-level grouping and the parent-brokered polish loop are
separate interaction shapes.
