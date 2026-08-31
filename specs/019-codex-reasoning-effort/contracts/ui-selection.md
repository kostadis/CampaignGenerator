# Contract: UI and Server Reasoning-Effort Parity

## Canonical flow

```text
server-published effort vocabulary
  -> Vue fixed select
  -> existing owner YAML / optional per-run request
  -> resolve_selection (request -> service -> platform -> environment -> omission)
  -> selection_cli_args
  -> existing CLI command builder
  -> --codex-reasoning-effort when UI value is explicit
  -> shared CLI resolver and Codex adapter
  -> run identity in UI output/result
```

No Vue component or FastAPI route invokes Codex directly, constructs
`model_reasoning_effort`, or reimplements inference behavior.

## Config vocabulary response

`GET /api/config/models` adds one field while preserving existing fields:

```json
{
  "backends": ["anthropic", "dgx", "openrouter", "claude-code", "codex-cli"],
  "codex_reasoning_efforts": [
    "minimal", "low", "medium", "high", "xhigh", "max"
  ]
}
```

The frontend hydrates this array through `frontend/src/stores/config.ts` and
uses it for every effort select. Missing vocabulary from an incompatible old
server disables the new selector with an actionable compatibility message; it
does not fall back to a duplicated hard-coded list.

## Selector contract

When effective or editable backend is `codex-cli`, the control contains exactly
seven choices:

1. `Codex default` — persisted as no explicit value;
2. `minimal`;
3. `low`;
4. `medium`;
5. `high`;
6. `xhigh`;
7. `max`.

The control is a select, not free text. Help says model support varies and
`gpt-5.6-sol` supports `max`. “Codex default” means no explicit UI value; if
`CG_CODEX_REASONING_EFFORT` exists on the server, the resolved preview and
actual run identify that environment fallback instead.

## UI ownership and persistence

| UI surface | Owner and field | Required behavior |
|---|---|---|
| `AppSidebar.vue` | `platform.yaml` → `runtime.default_codex_reasoning_effort` | Show for global Codex backend; save through `PUT /api/config/runtime`; retain across reload/backend switches. |
| `SelectionPanel.vue` (used transitively by grounding, party, planning, projection, prep/setup panels) | existing service `ModelSelection.codex_reasoning_effort` | Allow service override or defer; include value/origin in resolved preview; replacement PUTs preserve the field. |
| `KnobDrawer.vue` and `SessionDocEditor.vue` | `session_doc.yaml` → `backends.codex-cli.codex_reasoning_effort` | Hydrate, emit, save, and restore the Codex profile without changing other profiles. |
| `EnsembleSetup.vue` and `useEnsembleRun.ts` | `ensemble.yaml` → each applicable stage `EnsembleBackend.codex_reasoning_effort` | One Codex select per model-bearing stage; switching/resetting backend does not erase remembered effort. |
| `ReviewAssemble.vue` and other streamed run/result views | existing selected profile plus SSE output | Show effective run identity wherever model/run output is shown; no second selector when configuration is owned by the profile above. |
| `ConnectionGraph.vue` | existing selection plus extraction response identity | Display returned model/effort identity because this route runs in-process and has no subprocess SSE/log stream. |

All persistence is server-owned YAML. No selection exists only in component
state or browser storage.

## Stored selection JSON

Existing selection payloads accept an additive optional field:

```json
{
  "backend": "codex-cli",
  "model": "gpt-5.6-sol",
  "batch": false,
  "codex_reasoning_effort": "max"
}
```

Clearing to Codex default sends `null` or omits the field according to the
existing endpoint's partial/full-update contract. It never sends an empty
string. Loading a document with no field produces `null` without writing the
document.

## Resolved preview JSON

Responses based on `ResolvedSelection.as_dict()` add:

```json
{
  "codex_reasoning_effort": "max",
  "codex_reasoning_effort_origin": "service",
  "codex_reasoning_override": true
}
```

Allowed origins are `request`, `service`, `platform`, `environment`, and
`omitted`. For total omission:

```json
{
  "codex_reasoning_effort": null,
  "codex_reasoning_effort_origin": "omitted",
  "codex_reasoning_override": false
}
```

For an environment value, the preview shows the value and origin but
`codex_reasoning_override` remains false; `selection_cli_args()` emits no flag
so the final CLI remains the authority that reports the environment source.

For a non-Codex effective backend, remembered Codex profile values are dormant
and the preview omits them. An explicit per-run Codex effort paired with another
backend returns the existing incompatibility response before command creation.

## Command-builder contract

`server/platform_config_service.py::selection_cli_args()` is the only server
producer of `--codex-reasoning-effort`. It emits the pair only for a validated
request/service/platform Codex effort. Existing specialized command builders in
ensemble, scene editor, and projections must retain the effort when they adapt
the resolved selection for backend-argument formatting; no router reconstructs
the field independently.

`server/routers/scene_editor.py::_editor_service_selection()` copies the Codex
profile effort together with model/backend/batch. All run routes keep their
existing files, selected work, force/resume, concurrency, and review behavior.

## Backend-switch isolation

- Switching from Codex to another backend hides or disables the effort control.
- The remembered Codex value is not cleared.
- The other provider receives no Codex flag or setting.
- Switching back restores the remembered Codex value.
- A global Codex value does not overwrite a service's explicit Codex value.
- Clearing a service value resumes platform, environment, then omission
  precedence without copying the inherited value into the service document.

## Validation and error presentation

- Invalid JSON/YAML values are rejected by canonical Pydantic validation and
  surfaced through existing config error handling.
- Wrong-backend explicit use appears as an incompatible selection before an SSE
  child command event.
- A model-specific Codex rejection appears in streamed output/result with both
  model and effort and no fallback status.
- Progress/output panes and durable logs retain the canonical run identity line.
- The Connection Graph response carries the same identity in a machine-readable
  field and the view renders it near the result/cache summary.

## Acceptance assertions

1. Every selector-owning Codex UI surface renders the same server-published
   seven choices.
2. Reload and backend switch round-trip a Codex effort without modifying another
   provider profile.
3. Equivalent manual CLI and UI-launched explicit selections produce the same
   child override and run identity.
4. Codex default with environment set displays `environment`; with environment
   unset it displays `Codex default` and sends no override.
5. Static reachability tests cover dynamic `SelectionPanel` consumers as well
   as files containing a literal `codex-cli` selector.
