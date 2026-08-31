# Phase 0 Research: Codex Reasoning Effort Everywhere

**Feature**: `019-codex-reasoning-effort`
**Baseline**: features `015-codex-cli-backend` and `016-codex-cli-parity`

## Decision 1: Use the specified six-value CampaignGenerator vocabulary

**Decision**: Define one canonical value set: `minimal`, `low`, `medium`,
`high`, `xhigh`, and `max`. Do not accept aliases, capitalization variants,
free text, or API-only `none`.

**Rationale**: The [Codex configuration reference](https://developers.openai.com/codex/config-reference/)
documents `model_reasoning_effort` and the general values `minimal`, `low`,
`medium`, `high`, and model-dependent `xhigh`. The
[GPT-5.6-sol model page](https://developers.openai.com/api/docs/models/gpt-5.6-sol)
documents reasoning support through `max`. The feature specification therefore
uses the union required by CG#357 and leaves the selected model to enforce its
supported subset. A fixed local vocabulary catches typos before token-spending
work without freezing a model-to-effort compatibility matrix that will age.

**Alternatives considered**:

- Accept only the five values in the generic config table: rejected because it
  would exclude the issue's required `max` case for `gpt-5.6-sol`.
- Add `none`: rejected because it is not in the accepted feature vocabulary and
  is not equivalent to omission; omission means CampaignGenerator sends no
  override.
- Maintain a per-model compatibility table: rejected because model capability
  changes independently of this repository and silent repair is forbidden.

## Decision 2: Extend the existing Codex seam, not each caller

**Decision**: Keep `campaignlib/api/codex_cli.py::_codex_cli_generate` as the
single child-process boundary. Thread the optional effort through
`_CodexCliClient` and its direct, streaming, and brokered message facades, then
let `_command` add the Codex configuration override.

**Rationale**: All current request shapes converge at this function before
`subprocess.run`. One change covers ordinary calls, the streaming-shaped facade,
and the host-brokered polish loop while retaining the feature-15 isolation,
credential stripping, timeout, cleanup, and error contract.

**Alternatives considered**:

- Add `codex exec` options in individual pipeline commands: rejected because it
  creates provider dialects and bypasses the one external-dependency seam.
- Teach routers to invoke Codex directly: rejected because the CLI must remain
  the engine and UI the face.
- Store reasoning effort in user Codex configuration: rejected because
  `--ignore-user-config` is an intentional security and reproducibility boundary.

## Decision 3: Resolve CLI intent once with explicit provenance

**Decision**: Add one shared parser helper and one resolver alongside the
existing backend/model helpers. Resolution is:

```text
explicit --codex-reasoning-effort
  -> trimmed CG_CODEX_REASONING_EFFORT
  -> omission (Codex default)
```

The result carries `explicit`, `environment`, or `omitted` provenance. Empty or
whitespace environment input is omission. An explicitly supplied empty or
unknown value is invalid. An explicit Codex-only option with a non-Codex
effective backend is invalid; an ambient environment variable is simply
ignored by non-Codex runs.

**Rationale**: `argparse` choices validate ordinary explicit values, but the
shared resolver is still required for environment values, effective backend
resolution through `CG_BACKEND`, dispatchers, provenance, and defensive callers
that construct namespaces directly. This mirrors the established
`resolve_cli_model` and `client_from_args` fail-fast pattern.

**Alternatives considered**:

- Put the environment value in the parser default: rejected because it loses
  explicit-versus-environment provenance and makes non-Codex parsers consume a
  Codex-only setting.
- Resolve the environment separately in every command: rejected because it
  would create 30 precedence implementations.
- Treat explicit empty text as omission: rejected because it hides operator and
  UI serialization errors.

## Decision 4: Send one TOML-safe override only when selected

**Decision**: When an effort resolves, `_command` appends one separated argv
pair equivalent to:

```text
-c model_reasoning_effort="<value>"
```

The value is serialized as a TOML-compatible quoted string using the same safe
construction style as existing inline Codex configuration. When omitted, no
`model_reasoning_effort` argument appears. Existing `--ignore-user-config`,
`--strict-config`, `--ephemeral`, sandbox, feature disables, and forced saved
login options remain byte-for-byte intact except for the new conditional pair.

**Rationale**: `codex exec -c/--config key=value` is the documented launch-time
configuration override. Conditional emission preserves current Codex behavior
exactly for every existing caller that does not choose an effort.

**Alternatives considered**:

- Always send a guessed default such as `medium`: rejected because it changes
  existing subscription/model defaults.
- Remove `--ignore-user-config` so a saved value can flow through: rejected
  because it weakens the existing fail-closed boundary and does not provide a
  per-run UI/CLI control.
- Use shell-string concatenation: rejected because the adapter intentionally
  builds a separated argv list without a shell.

## Decision 5: Reuse the discovered 30-command inventory

**Decision**: Extend the production discovery in
`tests/test_backend_seam_guardrails.py` and `tests/test_codex_cli_family.py`.
The shared registrar gives 26 direct commands the option. The hand-written
`facts_to_state` parser and the four runtime dispatchers (`sd_agent`,
`ensemble`, `ensemble_batch`, and `ensemble_extract`) consume the same parser
or formatting helper. Dispatchers forward explicit values to every applicable
child; environment fallback is inherited and resolved only at the final Codex
adapter.

**Rationale**: The existing baseline already distinguishes 30 production
surfaces, 26 direct model-bearing commands, and four forwarding dispatchers.
Extending discovery is stronger than a new manual list and automatically fails
when a future backend surface omits effort parity. It directly covers the
issue's named `enhance_summary` and `check_consistency` commands.

**Alternatives considered**:

- Patch only commands named in CG#357: rejected because the user requires all
  Codex CLI uses and the constitution forbids sibling CLI dialects.
- Rely only on adapter environment fallback: rejected because explicit flags
  would be lost in dispatchers and help would remain inconsistent.
- Copy the choice tuple into four dispatcher parsers: rejected because a shared
  helper can preserve one vocabulary and one help string.

## Decision 6: Extend the shared server selection model and formatter

**Decision**: Add optional Codex effort fields to `ModelSelection`,
`PlatformRuntime`, and `ResolvedSelection`. Server tier resolution is request →
service → platform → environment → omission for preview purposes. An
environment-derived value is never converted into a child flag; the final CLI
reads the inherited environment and preserves truthful source reporting.
`selection_cli_args()` is the only server-side producer of
`--codex-reasoning-effort` for request/service/platform values.

Update all `is_empty()` overrides so effort-only service selections are not
dropped. Preserve the value while another backend is active, but keep it
dormant. Update `_editor_service_selection()` and replacement PUT paths so they
do not erase it. The ensemble/editor/projection builders that temporarily
replace the resolved backend for existing formatter behavior must still carry
the already-validated effort field to the final CLI argv.

**Rationale**: All UI launch paths already converge through
`resolve_selection()` and `selection_cli_args()`. Extending that seam preserves
one precedence and command construction rule without provider branches in
routers. The server may validate and describe its own environment in a preview,
but leaving transport resolution to the CLI avoids turning an environment
fallback into an apparently explicit override.

**Alternatives considered**:

- Resolve `CG_CODEX_REASONING_EFFORT` in the browser or every router: rejected
  because browsers do not own server environment and the CLI is the contract.
- Add reasoning parameters to every run endpoint: rejected because the shared
  selection API already owns model/backend options.
- Clear effort when switching backend: rejected because Codex-specific memory
  must survive a switch without leaking into another provider.

## Decision 7: Publish one vocabulary to every UI selector

**Decision**: Extend `GET /api/config/models` with the canonical effort list and
hydrate it in `frontend/src/stores/config.ts`. Every relevant UI uses that list
for a fixed select containing “Codex default” plus the six explicit values:

- global `AppSidebar.vue`;
- generic `SelectionPanel.vue` service overrides;
- session editor `KnobDrawer.vue` / `SessionDocEditor.vue`;
- ensemble stage setup in `EnsembleSetup.vue` / `useEnsembleRun.ts`.

Selector help states compatibility is model-dependent and highlights
`gpt-5.6-sol` support for `max`. Clearing to “Codex default” stores no explicit
value; a server environment fallback may still apply and will be identified at
run time.

**Rationale**: A server-published list prevents six TypeScript copies and makes
the select/no-free-text guarantee testable. Existing owners already persist
model/backend selections at the correct scopes.

**Alternatives considered**:

- Hard-code the values in each Vue component: rejected because UI vocabulary
  would drift from parser validation.
- Add a free-text box like optional model: rejected because the specification
  requires a closed value set and early validation.
- Create browser-local persistence: rejected because pipeline state belongs on
  disk and must survive CLI/UI interchange.

## Decision 8: Make the actual run identity authoritative

**Decision**: Immediately before starting a Codex child, emit one canonical
identity line containing effective model, resolved effort or “Codex default,”
and effort source. Include the same identity in adapter errors. Existing SSE
streaming captures the line, and `server/subprocess_runner.py::_save_run_log`
persists it with the command and output.

For `server/routers/connections.py::extract_connections`, the only UI path that
invokes `client_from_args()` in-process rather than through `stream_subprocess`,
return the same run identity in the API response and render it in
`ConnectionGraph.vue`. Any existing command-specific sidecar or summary that
already records a Codex model also records the effort state.

**Rationale**: Reporting at the adapter boundary reflects the final
`CG_CODEX_MODEL` and effort environment fallback, not merely the server's
configured preview. Reusing stdout/SSE/log capture avoids a parallel event or
log schema; the one in-process exception needs an explicit response field.

**Alternatives considered**:

- Report only the command line: rejected because environment-derived and
  omitted values do not appear there.
- Report only the configured UI selection: rejected because environment
  fallback can change the actual run.
- Add a new SSE event type for all routes: rejected because existing output is
  already visible, persisted, and compatible with current clients.

## Decision 9: Let Codex enforce model-specific compatibility without fallback

**Decision**: CampaignGenerator rejects unknown effort vocabulary and wrong
backend use before child work. For a canonical effort unsupported by the
selected model or installed Codex version, surface the existing nonzero
`CodexCliError` with model and effort context. Start only that one child and do
not retry another model, effort, backend, or unconfigured default.

**Rationale**: The compatibility relation is external and model-dependent.
Codex is the authoritative validator; CampaignGenerator's job is to retain
intent and make the failure actionable.

**Alternatives considered**:

- Downgrade `max` to `xhigh`: rejected because it silently changes operator
  intent.
- Retry without an override: rejected because it can produce a successful but
  unrequested artifact and spend additional tokens.
- Reject every unlisted model locally: rejected because valid future models
  would require a CampaignGenerator release.

## Decision 10: Treat persistence changes as additive

**Decision**: Add optional, default-`None` fields to existing strict Pydantic
models and compatible optional TypeScript interfaces. Do not add a migration
CLI or `migration.md`. Add tests that old configuration loads unchanged and
new Codex effort values round-trip without altering another provider profile.

**Rationale**: No field moves, changes meaning, becomes required, or is read
from a retired location. Missing values retain the exact pre-feature omission
behavior, so Constitution Principle XIII's breaking-state migration rule does
not trigger.

**Alternatives considered**:

- Write `medium` into old files during load: rejected because that is a lazy
  behavior-changing migration.
- Add a new reasoning settings document: rejected because the existing
  selection owners already define the correct persistence scopes.

## Decision 11: Verify transport, family parity, UI parity, and compatibility

**Decision**: Use four complementary test layers:

1. adapter/resolver unit tests for the six values, precedence, exact argv,
   omission, invalid input, error context, all request facades, and isolation;
2. the 30-surface AST inventory plus dispatcher forwarding tests;
3. config/service/route tests for persistence, resolution, command building,
   run identity, and the Connection Graph exception;
4. TypeScript checking and the Vite production build for all selectors.

Keep authenticated Codex execution as an optional manual smoke test only.

**Rationale**: CI must prove exact transport and artifacts without requiring a
saved account, spending tokens, or depending on live model availability. The
fake Codex fixture already captures argv, environment, input, and output.

**Alternatives considered**:

- Live Codex calls in pytest: rejected as credential-dependent, costly, and
  nondeterministic.
- Only test the adapter: rejected because dispatchers and UI command builders
  can silently drop a correct adapter option.
- Only grep Vue literals: rejected because the generic `SelectionPanel` has
  dynamic Codex reachability without a local `codex-cli` literal.

## Resolved Unknowns

All Technical Context fields and integration decisions are resolved. No open
questions remain.
