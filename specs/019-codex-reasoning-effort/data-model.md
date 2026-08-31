# Data Model: Codex Reasoning Effort Everywhere

This feature adds optional fields to existing YAML-backed selection models and
transient values used during CLI/server resolution. It adds no database and no
new campaign-content artifact.

## 1. CodexReasoningEffort

Canonical vocabulary shared by Python parser validation, Pydantic models,
server responses, and UI options.

| Value | Meaning |
|---|---|
| `minimal` | Request the model's minimal supported reasoning effort. |
| `low` | Request low reasoning effort. |
| `medium` | Request medium reasoning effort. |
| `high` | Request high reasoning effort. |
| `xhigh` | Request extra-high effort when the selected model supports it. |
| `max` | Request maximum effort when the selected model supports it; required for `gpt-5.6-sol`. |

### Validation

- Values are case-sensitive canonical strings.
- No aliases, whitespace-padded values, empty explicit values, or free text are
  accepted.
- Vocabulary validity is local. Model compatibility is validated by Codex.
- Omission is represented by `None`, never by a sentinel string such as
  `default` and never by a guessed effort.

## 2. CLIReasoningIntent

Transient immutable result of resolving one CLI invocation.

| Field | Type | Rules |
|---|---|---|
| `backend` | canonical backend | Effective backend after existing CLI/environment backend resolution. |
| `requested_effort` | optional `CodexReasoningEffort` | Explicit `--codex-reasoning-effort`; `None` when absent. |
| `environment_effort` | optional `CodexReasoningEffort` | Trimmed `CG_CODEX_REASONING_EFFORT`; whitespace-only means absent. |
| `effective_effort` | optional `CodexReasoningEffort` | Explicit, else environment, else `None`. |
| `source` | `explicit \| environment \| omitted` | Provenance used in output and errors. |
| `emit_override` | boolean | True exactly when the adapter will add `model_reasoning_effort`. |

### Resolution

```text
parsed
  -> resolve effective backend
  -> explicit value present?
       yes + backend != codex-cli -> invalid
       yes + valid vocabulary     -> explicit
       no  + backend != codex-cli -> omitted (ignore Codex environment)
       no  + valid environment    -> environment
       no  + blank/unset env      -> omitted
       no  + invalid environment  -> invalid
```

An invalid state stops before `_CodexCliClient` construction or a dispatcher
starts a child. Defensive validation also runs at the final adapter boundary.

## 3. ModelSelection (existing, extended)

Shared persisted service selection in `campaignlib/selection.py`.

| Field | Type | Persistence meaning |
|---|---|---|
| `backend` | optional canonical backend | Existing service/backend override. |
| `model` | optional string | Existing model override. |
| `batch` | optional boolean | Existing provider message-batch override. |
| `codex_reasoning_effort` | optional `CodexReasoningEffort` | Codex-only remembered override; `None` means defer. |

### Rules

- `is_empty()` is false when effort is the only selected field.
- The effort field participates in resolution only when the effective backend
  is `codex-cli`.
- A remembered value remains stored while another backend is active, but is
  dormant and never emitted to that backend.
- Existing strict subclasses inherit the field:
  `BackendProfile` in `session_doc.yaml`, `EnsembleBackend` in `ensemble.yaml`,
  and grounding/party/planning/projection selections in their existing owner
  documents.
- Subclasses that override `is_empty()` include the new field in that method.

## 4. PlatformRuntime (existing, extended)

App-wide selection persisted under `runtime` in `platform.yaml`.

| Field | Type | Notes |
|---|---|---|
| `default_model` | string | Existing active/global compatibility field. |
| `default_backend` | canonical backend | Existing app-wide backend. |
| `default_models` | backend → optional string map | Existing per-backend model memory. |
| `default_batch` | boolean | Existing app-wide batch selection. |
| `default_codex_reasoning_effort` | optional `CodexReasoningEffort` | App-wide Codex-specific effort memory. |

`None` produces no persisted CampaignGenerator override. Switching the active
backend does not clear the field and does not send it to another provider.

## 5. ResolvedSelection (existing, extended)

Transient server-side selection used by previews and command builders.

| Field | Type | Rules |
|---|---|---|
| `model`, `backend`, origins | existing fields | Existing request/service/platform pairing behavior is unchanged. |
| `batch`, `batch_origin` | existing fields | Existing independent batch behavior is unchanged. |
| `codex_reasoning_effort` | optional `CodexReasoningEffort` | Effective configured or environment value for Codex; absent for other backends or total omission. |
| `codex_reasoning_effort_origin` | `request \| service \| platform \| environment \| omitted` | Configuration tier or fallback source. |
| `codex_reasoning_override` | boolean | True for request/service/platform origins; false for environment/omitted. |
| `refusal` | optional string | Existing incompatibility field, extended for wrong-backend explicit effort. |

### Server resolution

```text
resolve existing model/backend pair
  -> if backend is codex-cli:
       request effort ?? service effort ?? platform effort ?? environment ?? omitted
  -> else:
       explicit request effort -> refusal
       persisted/env Codex memory -> dormant, resolved effort omitted
  -> validate vocabulary
  -> build preview
  -> emit CLI flag only for request/service/platform effort
```

The environment-derived value may be shown in a resolved preview, but is not
converted into a CLI flag; the child inherits the environment so the final
adapter still reports the truthful `environment` source.

## 6. CodexRunIdentity

Immutable actual identity assembled at the sole Codex execution boundary.

| Field | Type | Rules |
|---|---|---|
| `backend` | constant `codex-cli` | Always explicit. |
| `model` | string or `Codex default` | Explicit model, `CG_CODEX_MODEL`, or omission state as resolved by the adapter. |
| `model_source` | `explicit \| environment \| omitted` | Existing model provenance when available. |
| `reasoning_effort` | `CodexReasoningEffort` or `Codex default` | Final resolved effort. |
| `reasoning_effort_source` | `explicit \| environment \| omitted` | Final source. |
| `override_sent` | boolean | False only for total omission. |

### Visibility

- Printed before `subprocess.run` starts model work.
- Included in adapter failure context.
- Captured by CLI stdout/stderr, server SSE output, and Markdown run logs.
- Added to any command-specific sidecar/JSONL event that already records a
  Codex model.
- Returned explicitly by the in-process Connection Graph API path.

## 7. CodexExecution

Existing feature-15 execution object with one added optional input.

| Field | Type | Notes |
|---|---|---|
| `argv` | list of strings | Existing isolated command plus one conditional `-c` pair. |
| `reasoning_effort` | optional `CodexReasoningEffort` | From `CodexRunIdentity`; absent means omit override. |
| `environment` | string map | Existing sanitized child environment. |
| `working_directory` | temporary path | Existing isolated directory. |
| `timeout`, result/error fields | existing | Unchanged. |

### State transitions

```text
assembled
  -> locally_validated
       \-> invalid_vocabulary / wrong_backend       (no child)
  -> identity_reported
  -> child_started
       \-> codex_rejected_model_effort / failed     (no fallback)
       \-> timed_out / interrupted                   (no fallback)
  -> nonempty_result_validated
  -> existing_artifact_persisted
  -> cleaned
```

Every terminal branch retains the existing temporary-directory cleanup and
artifact-integrity behavior. A failed model/effort combination never transitions
to successful artifact persistence.

## 8. CapabilityInventoryEntry (existing, extended)

Test-owned record used to enforce all-use parity.

| Field | Type | New rule |
|---|---|---|
| `command` | unique production command | Existing 30-command discovery baseline. |
| `kind` | `direct \| dispatcher` | Existing classification. |
| `registrar` | `shared \| plural-endpoint \| dispatcher` | Identifies the shared effort helper each surface must consume. |
| `effort_option` | boolean/evidence | Must prove exactly one canonical option is accepted or forwarded. |
| `ui_invocation` | existing reachability reference | Must prove the owning UI can select or inherit effort and display run identity. |
| `metadata_sites` | zero or more locations | Every model-reporting site must also report effort. |

Discovery fails when a new Codex-capable surface has no inventory entry or
bypasses the shared parser, resolver, formatter, or UI reachability contract.

## Migration Assessment

No migration is required. All persisted additions are optional and default to
`None`; old `platform.yaml`, `session_doc.yaml`, `ensemble.yaml`, grounding,
party, planning, and projection documents load with their existing meaning.
No field moves or changes interpretation, and loading does not rewrite the
document. Compatibility tests must prove old-document load plus new-value
round-trip before release.
