# Data Model: Codex CLI Parity Across CLIs

This feature changes typed configuration and in-memory request/response models. It
does not introduce a database or move campaign artifacts.

## 1. Backend Selection

The canonical provider choice shared by command lines, server resolution, stored
configuration, and Vue controls.

| Field | Type | Rules |
|---|---|---|
| `backend` | `anthropic \| dgx \| openrouter \| claude-code \| codex-cli` | One canonical spelling; required after selection resolution. |
| `model` | optional string | Trimmed. An explicit Codex value must not be `claude-*`; an omitted Codex value remains omitted. |
| `model_origin` | resolution-only enum | `request`, `service`, `platform`, `literal`, or absent; not persisted. |
| `batch` | boolean | Provider message batching. Valid only with `anthropic`. |
| `backend_origin` | resolution-only enum | `request`, `service`, `platform`, or literal fallback; not persisted. |

### Validation

- `codex-cli` with an explicit `claude-*` model is invalid.
- `codex-cli` with an inherited `claude-*` platform/literal default resolves to
  `model = None` rather than an invented replacement.
- `codex-cli` with `batch = true` is invalid before command construction.
- Other backend compatibility and default rules remain unchanged.

### Resolution transition

```text
unresolved selection
  -> choose backend by existing request/service/platform precedence
  -> choose model and retain its origin
  -> if Codex + inherited Claude model: omit model
  -> otherwise validate backend/model compatibility
  -> validate provider batch
  -> emit CLI arguments
```

## 2. CLI Model Intent

An in-memory value used by each direct command to distinguish omission from an
explicit argument while preserving that command's legacy non-Codex default.

| Field | Type | Rules |
|---|---|---|
| `requested_model` | optional string | Parser value; `None` means `--model` was omitted. |
| `legacy_default` | optional string or resolver callback | Existing provider/default behavior for that command, including intentional `None`. |
| `backend` | canonical backend | Resolved before the API call. |
| `effective_model` | optional string | Explicit value, legacy non-Codex default, or `None` for an omitted Codex model. |
| `explicit` | boolean or equivalent provenance | True only when the operator/config supplied the model. |

The helper runs after command-specific choices such as fast/model modes have been
applied. It never silently rewrites an explicit incompatible model.

## 3. Subscription Request

One immutable parent-side description of one Codex child execution.

| Field | Type | Rules |
|---|---|---|
| `developer_instructions` | string | Fixed adapter protocol plus caller system text; never includes arbitrary repository instructions. |
| `user_input` | string | Direct user text or typed broker transcript. |
| `model` | optional string | Explicit value, `CG_CODEX_MODEL`, or omitted for subscription default. |
| `timeout_seconds` | positive finite number | Feature-15 validation and default are retained per child. |
| `output_schema_path` | optional temporary path | Present only for structured brokered turns. |
| `working_directory` | fresh temporary directory | Outside the campaign repository and removed on every exit. |
| `environment` | sanitized mapping | Saved login environment retained; metered keys and extension configuration removed. |

### States

```text
validated -> prepared -> running -> succeeded -> cleaned
                      \-> refused/failed/timed-out/interrupted -> cleaned
```

No failed, partial, empty, or whitespace-only result transitions to `succeeded`.

## 4. Broker Transcript

Ordered semantic history supplied to a fresh Codex process for a polish turn.

| Field | Type | Rules |
|---|---|---|
| `version` | constant | Protocol version owned by the adapter. |
| `messages` | ordered array | At least one valid message; order is preserved exactly. |
| `message.role` | `user \| assistant` | No inferred or merged roles. |
| `message.blocks` | ordered array | Only the block shapes below are allowed. |

### Block variants

| Block | Required fields | Validation |
|---|---|---|
| User text | `type=text`, `text` | Non-empty text. |
| Assistant text | `type=text`, `text` | Text preserved verbatim. |
| Assistant action request | `type=tool_use`, `id`, `name`, `input` | Unique non-empty ID; input is an object. |
| User action result | `type=tool_result`, `tool_use_id`, `content`, `is_error` | References an outstanding action exactly once. |

The normalizer rejects unsupported roles/blocks, duplicate IDs, results without a
matching request, malformed object inputs, and unresolved action ordering.

## 5. Brokered Turn Result

Structured output from one isolated Codex child before the parent performs any
requested operation.

| Field | Type | Rules |
|---|---|---|
| `text` | string | May accompany action requests; final response must not be wholly empty. |
| `tool_calls` | array | Zero or more requested host actions. |
| `tool_calls[].name` | non-empty string | Not enum-constrained at transport level; workflow validates against `TOOL_DISPATCH`. |
| `tool_calls[].arguments_json` | JSON string | Must decode to an object or the transport fails closed. |

### Adapter response facade

| Field | Value |
|---|---|
| `content` | Ordered text blocks followed by host-assigned `tool_use` blocks. |
| `stop_reason` | `tool_use` when any action exists; otherwise `end_turn`. |
| `usage.input_tokens` | `None`. |
| `usage.output_tokens` | `None`. |

Host-generated tool-use IDs are opaque and unique within the polish conversation.
They are returned unchanged in the next typed transcript.

## 6. Brokered Polish Operation

The existing parent-owned action request after transport parsing.

| Field | Type | Rules |
|---|---|---|
| `id` | opaque string | Correlates exactly one result. |
| `name` | string | Must exist in the existing `TOOL_DISPATCH`. |
| `arguments` | object | Validated by the existing operation implementation. |
| `scope` | `ToolContext` | Limits reads and edits to selected recap, voice/context documents, and output draft. |
| `result` | text plus error flag | Returned as a `tool_result`; an error is feedback, not a successful edit. |

The declared operation set remains:

- `list_sections`
- `read_doc_section`
- `read_recap`
- `read_voice_file`
- `read_context_doc`
- `apply_edit`
- `insert_section`
- `record_critique`
- `finish`

The child never receives those operations as executable tools; only the parent can
dispatch them.

## 7. Capability Inventory Entry

One test-owned record for every production command that registers or forwards the
shared backend selection.

| Field | Type | Rules |
|---|---|---|
| `command` | unique string | Production CLI entry point. |
| `family` | enum | Session document, prep/ingest/search/integration, grounding, or ensemble. |
| `kind` | `direct \| dispatcher` | Direct starts model operations; dispatcher forwards selection only. |
| `registrar` | `shared \| plural-endpoint \| dispatcher` | Identifies the parser seam that must use canonical vocabulary. |
| `interaction_shapes` | set | Direct text, cached-system blocks, fan-out, sequential, brokered polish, or forwarding. |
| `ui_invocation` | reference | Direct UI builder or owning transitive workflow face. Required unless an explicit constitutional exemption is recorded. |
| `batch_meanings` | set | Provider message batch and any distinct application-level grouping. |

Discovery tests compare the inventory to production parser/dispatcher usage so a
new command cannot be omitted silently.

## 8. Persisted Configuration

### Existing generic documents

`platform.yaml`, grounding, party, planning, and ensemble documents retain their
current field layout. Only the accepted backend enum widens.

### Session editor backend profiles

The per-backend profile collection gains:

| Python field | YAML alias | Value |
|---|---|---|
| `codex_cli` | `codex-cli` | Existing `BackendProfile` shape with a defaulted optional model. |

Older documents without this field load successfully. Saving may materialize the
defaulted profile according to the existing serializer, and a saved Codex model
does not overwrite another backend's profile.

## Migration Assessment

No migration is required. Backend enum widening and a defaulted additive profile
do not change the meaning or location of existing values. Compatibility tests must
prove old documents load and new Codex profile data round-trips.
