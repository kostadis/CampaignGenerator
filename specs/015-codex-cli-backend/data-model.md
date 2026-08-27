# Phase 1 Data Model: Codex CLI Subscription Backend

This feature adds no persistent database or workspace schema. The model below
describes transient request, execution-policy, process, and report values.

## ConsistencyAuditRequest

| Field | Type | Rules |
|---|---|---|
| `system_instructions` | string | Required, text passed as Codex developer instructions. |
| `user_content` | string | Exactly one non-empty, text-only user turn. |
| `requested_model` | optional string | Explicit CLI/model-facade value; `claude-*` is invalid for Codex. |
| `inherited_model` | optional string | Existing provider default; never forwarded to Codex merely because it is the parser default. |
| `max_tokens` | optional integer | Accepted for facade compatibility; advisory only for this adapter. |
| `timeout_seconds` | positive finite number | From `CG_CODEX_TIMEOUT`; defaults to 600. |

Validation rejects tools, images, assistant history, multiple user turns,
non-text blocks, empty content, and incompatible explicit models before starting a
child process.

## ModelSelection

| Field | Type | Meaning |
|---|---|---|
| `explicit` | optional string | Value supplied by the caller/`--model`. |
| `environment` | optional string | `CG_CODEX_MODEL`. |
| `effective` | optional string | `explicit`, else `environment`, else absent. |
| `source` | enum | `explicit`, `environment`, or `codex-default`. |

The selected value is trimmed, must be non-empty when present, and must not begin
with `claude-` (case-insensitive). Other values are passed through; Codex remains
the authority on whether its installed version/account supports them.

## CodexExecutionPolicy

| Field | Fixed behavior |
|---|---|
| Authentication | Force `chatgpt`; use Codex-owned saved login. |
| Environment denylist | Remove `OPENAI_API_KEY` and `CODEX_API_KEY`. |
| Working directory | Newly created private temporary directory outside the repository. |
| Filesystem | `read-only` Codex sandbox; temporary result file is the sole intended child output. |
| Repository context | Skip git requirement, ignore rules, load zero project-doc bytes. |
| User configuration | Ignore user config; use strict inline runtime policy. |
| Extension surfaces | Disable apps, plugins, remote plugins, hooks, agents, shell, browser/computer/image tools, view-image, tool suggestion, skill search/installation, and workspace dependencies. |
| Network/model tools | Disable web search; expose no executable tool path. |
| Persistence | `--ephemeral`; remove temporary directory after every outcome. |
| Fallback | None. Never retry through or switch to another provider. |

## SubscriptionExecution

| Field | Type | Notes |
|---|---|---|
| `argv` | list of strings | Fully separated arguments; never a shell command. |
| `stdin` | string | User content only. |
| `environment` | string map | Parent copy after credential-key removal. |
| `cwd` | path | Same isolated directory supplied through `--cd`. |
| `timeout` | positive finite number | Subprocess deadline. |
| `result_path` | path | Temporary `--output-last-message` target. |
| `return_code` | optional integer | Available after process completion. |
| `stdout` | string | Captured for diagnostics only. |
| `stderr` | string | Captured and bounded before inclusion in errors. |
| `result_text` | optional string | Trim-validated final Markdown. |
| `state` | enum | See lifecycle below. |

## ConsistencyReport

| Field | Type | Rules |
|---|---|---|
| `markdown` | string | Non-empty final Codex message. |
| `issue_count` | integer | Existing CLI-derived count; semantics remain unchanged. |
| `output_path` | path | Explicit/default report file already owned by the consistency workflow. |

The report remains an unapproved draft. No source document or campaign fact is
modified by producing it.

## Lifecycle

```text
assembled
   |
validated -----> invalid_config
   |
prepared ------> missing_cli
   |
running --------> auth_failed
   |  |  |------> timed_out
   |  |---------> process_failed
   |------------> empty_result
   |
succeeded
   |
persisted
```

All terminal branches clean temporary state. Failure branches do not persist a
report and do not transition to another backend.

## Migration assessment

No persistent state changes. No migration CLI or `migration.md` is required.
