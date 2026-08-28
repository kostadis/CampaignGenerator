# Phase 0 Research: Codex CLI Parity Across CLIs

**Feature**: `016-codex-cli-parity`  
**Baseline dependency**: merged PR #350 / feature `015-codex-cli-backend`

## Decision 1: Extend the feature-15 seam instead of creating a second backend

**Decision**: Treat PR #350 as a required baseline. Extend
`campaignlib/api/codex_cli.py` and the existing provider-neutral helpers in
`campaignlib/api/client.py`; do not add a parallel Codex client or invoke Codex
directly from individual pipelines.

**Rationale**: Feature 15 already owns authentication, model precedence, timeout
validation, environment sanitization, ephemeral execution, cleanup, error
classification, and no-fallback behavior. Reusing that seam keeps all 30 commands
on one security and error contract.

**Alternatives considered**:

- Per-command `subprocess` calls: rejected because isolation and failure behavior
  would drift across four CLI families.
- A new provider name for advanced workflows: rejected because `polish` is an
  interaction shape, not a different provider.

## Decision 2: Keep direct messages narrow and add a brokered-turn capability

**Decision**: Preserve the direct `client.messages.create()` contract for the
ordinary text path. Add a separate host-brokered message capability to the Codex
client and let `call_api_with_tools()` select it through capability detection. The
direct path continues to reject arbitrary tools, images, and general multi-turn
requests.

**Rationale**: Only `pipelines/ensemble/polish.py` needs declared action requests
and application-maintained tool-result history. Giving that shape an explicit
capability prevents the safe direct path from becoming a generic tool emulator.
`polish.run_agent_loop()` can remain provider-neutral and keep ownership of tool
validation, dispatch, iteration limits, traces, and file mutations.

**Alternatives considered**:

- Enable Codex shell, MCP, plugin, or web tools: rejected because the child must
  have no executable capability.
- Branch on `codex-cli` inside `polish.py`: rejected because provider translation
  belongs at the API seam.
- Make the direct message API accept all history and tools: rejected because it
  would weaken a deliberately small contract for every caller.

## Decision 3: Replay polish history as typed data into fresh structured turns

**Decision**: Each polish iteration starts a new feature-15-style
`codex exec --ephemeral` process. Ordered user, assistant, `tool_use`, and
`tool_result` blocks are normalized and serialized as a typed JSON transcript on
stdin. The fixed developer instructions describe the broker protocol and declared
action schemas. `--output-schema` constrains the child to a host-action envelope.

**Rationale**: Codex CLI does not expose a native multi-message invocation that
simultaneously preserves feature 15's fresh-process ephemerality and tool-free
isolation. Typed replay preserves semantic roles, order, IDs, error status, and
text without granting the child continuity or repository access. The parent is
still the only action executor.

**Alternatives considered**:

- `codex exec resume`: rejected because it introduces persisted session state and
  weakens per-turn isolation.
- Flatten history into prose: rejected because role, block, and tool-result
  boundaries would become ambiguous.
- Reuse one long-lived child: rejected because a later turn could retain state not
  represented in the workflow transcript.

## Decision 4: Fail closed at both syntax and operation boundaries

**Decision**: The output schema accepts response text and an array of requested
operations. Each operation carries a name and JSON-encoded object arguments. The
adapter rejects malformed envelopes, malformed argument JSON, invalid history,
duplicate or unresolved IDs, and empty outputs. It converts valid requests to the
existing Anthropic-shaped blocks, assigns opaque host IDs, derives
`stop_reason=tool_use` when actions are present, and exposes a usage object whose
token values are `None`. Unknown but well-formed action names continue to the
existing `TOOL_DISPATCH` refusal so the model receives normal tool-error feedback.

**Rationale**: Schema validation protects the transport boundary while existing
polish validation remains the authority for named operations, argument meaning,
document scope, and loop completion. The usage facade is required by the existing
trace writer even though Codex CLI does not report compatible token counts.

**Alternatives considered**:

- Constrain operation names in the output schema: rejected because an unknown
  operation should become the workflow's established tool error, not an opaque
  transport failure.
- Execute operations in the child: rejected because all document access and
  mutation must remain in the parent process.

## Decision 5: Accept ordered system text blocks on the direct path

**Decision**: Extend the direct adapter's system normalizer to accept either a
string or an ordered list of text blocks. Preserve text and order while ignoring
Anthropic cache-control metadata. Continue rejecting non-text system blocks.

**Rationale**: Several production callers use the shared `cache_system` path,
which turns system text into cache-marked content blocks. Prompt caching is a
provider concern; it must not make otherwise valid text calls unsupported on a
subscription backend.

**Alternatives considered**:

- Add provider checks to every cached caller: rejected because this would spread
  provider dialect into pipeline code.
- Disable `cache_system` globally: rejected because it would change existing
  Anthropic behavior.

## Decision 6: Centralize backend vocabulary and model provenance

**Decision**: Make `campaignlib.selection.Backend` and `BACKENDS` the canonical
backend vocabulary and consume it from the shared CLI registrar and server config
models. Add a shared CLI model-resolution helper used by every direct model-bearing
command. Parsers preserve whether `--model` was explicit; after command-specific
mode flags are applied, the helper restores each command's legacy default for
non-Codex backends, leaves an omitted Codex model unset, and retains explicit
values for compatibility validation.

**Rationale**: A literal Claude default cannot be distinguished from an explicit
incompatible choice after ordinary argparse defaulting. Provenance is necessary
to satisfy both rules: omit an inherited Claude model for Codex, but refuse an
explicit one. One vocabulary and one resolver also prevent help-text and default
drift across 26 shared registrars and four hand-written parsers/dispatchers.

**Alternatives considered**:

- Silently drop every Claude-looking model in the adapter: rejected because it
  would hide an explicit user error.
- Inspect `sys.argv` in the client: rejected because dispatchers, tests, and UI
  command builders do not share one argv provenance model.
- Copy the feature-15 auditor's conditional into each command: rejected because
  26 direct-command copies would immediately become a new dialect.

The helper receives each command's actual `legacy_default`, including `None` where
DGX or dispatcher wiring intentionally chooses the model. Command-generated
`--fast` Claude models count as explicit intent and are refused with Codex; this
feature does not invent an unspecified Codex fast-model mapping.

## Decision 7: Resolve UI selections at the existing server seam

**Decision**: Extend `campaignlib.selection.compatible()` and
`server/platform_config_service.py::resolve_selection()` for Codex. Explicit
request/service models remain explicit and incompatible Claude IDs are refused.
Inherited platform or literal Claude defaults are omitted for Codex so
`CG_CODEX_MODEL`, then the subscription default, can apply. Keep
`selection_cli_args()` and `backend_cli_args()` generic.

**Rationale**: All server command builders already consume resolved selections.
Fixing the existing seam gives manual and UI-launched commands identical backend
and model intent without provider branches in routers.

**Alternatives considered**:

- Substitute a guessed Codex model: rejected because the saved subscription owns
  the final default.
- Special-case every router: rejected because UI/CLI parity would be untestable as
  one rule.

## Decision 8: Map all 30 commands and enforce bidirectional reachability

**Decision**: Maintain a production capability matrix that discovers every shared
registrar and explicit dispatcher, classifies each command as direct or forwarding,
and maps it to a direct or transitive UI invocation. Existing workflow selectors
inherit Codex from the canonical config API. `ensemble`, `ensemble_extract`,
`extract_facts`, and the dispatcher-only `sd_agent` are covered by their existing
owning workflow faces and must prove end-to-end forwarding. Seven standalone
capabilities currently lack reachability and receive explicit faces in this
feature: `check_consistency`, `transform`, `vtt_voice_compare`, `scabard_sync`,
`synthesise_polish`, `narrate_chapter`, and `polish`. There is no implicit CLI-only
exemption.

The Scabard face accepts its access key in the request body and passes it to the
CLI through a child-only `SCABARD_ACCESS_KEY` environment override. The CLI retains
its explicit argument for manual compatibility but accepts the environment fallback;
the server's command preview and subprocess diagnostics redact the override and
never place the secret in argv.

**Rationale**: The current static batch test lists 22 shared registrars and omits
four current users (`sd_agent`, `narrate_chapter`, `grounding_sections`, and
`thread_registry`). Source discovery finds 26 shared registrars,
`facts_to_state`'s plural-endpoint parser, and three forwarding dispatchers.
Constitution XI requires the backend choice to be reachable from the UI, while
Constitution XII requires one spelling and meaning across that family.

**Alternatives considered**:

- Preserve the stale manual list: rejected because it already misses production
  commands.
- Treat "existing UI surfaces" as a CLI-only exemption: rejected because the
  constitution requires an explicit human exemption and none was requested.

## Decision 9: Keep the meanings of batch separate

**Decision**: Provider message `--batch` continues to reject every non-Anthropic
backend before work starts. Direct clients, `facts_to_state`, server resolution,
and dispatcher-only `ensemble` enforce the refusal before spawning a child. This
also closes the existing `ensemble` forwarding defect where `--batch` can reach a
child parser that does not accept it. `--batch-scenes`, ensemble local fan-out,
concurrency, resume, and HTML review remain application-level behavior. Default
batched-scene handling includes both subscription CLI backends (`claude-code` and
`codex-cli`), but explicit user settings remain authoritative.

**Rationale**: These controls operate at different layers. Reusing the generic
provider-batch refusal and existing application orchestration preserves cost,
scope, and retry expectations.

**Alternatives considered**:

- Map provider batch to local fan-out: rejected because it changes billing and
  completion semantics.
- Disable every option containing "batch" for Codex: rejected because it removes
  backend-independent workflow features.

## Decision 10: Persist only the existing selection shapes

**Decision**: Widen backend enums and add the defaulted `codex-cli` profile alias to
the session editor's per-backend profile collection. Do not add a second platform
model field or persist the timeout. Existing four-profile session documents load
with a default Codex profile; new documents round-trip the additive alias.

**Rationale**: Platform, grounding, party, planning, and ensemble selections
already store backend/model/batch generically. The editor intentionally remembers
models per backend and therefore needs one additive profile. `CG_CODEX_TIMEOUT`
remains the feature-15 execution control.

**Migration ruling**: This is enum widening plus a defaulted additive field. No
old value changes meaning or location and old files remain valid, so Principle
XIII does not require a one-shot migration or `migration.md`. Compatibility and
round-trip tests are required.

## Decision 11: Verify contracts at three levels

**Decision**: Use (1) adapter and resolver unit tests, (2) production-inventory and
command-builder contract tests, and (3) representative workflow/UI integration
tests. Keep one optional authenticated smoke run outside the deterministic suite.

**Rationale**: Spawning a real authenticated child for all 26 direct commands would
be slow and non-hermetic. Mocked subprocess tests can prove exact transport,
isolation, structured output, cleanup, and no fallback; workflow fixtures prove
that normal artifacts and boundaries are preserved; one smoke validates the local
Codex installation and saved login.

**Alternatives considered**:

- Live-test every command in CI: rejected because it depends on operator auth and
  a changing subscription service.
- Test only the shared adapter: rejected because parser, selection, forwarding,
  and artifact regressions can occur above the seam.

## Resolved Technical Unknowns

- **Codex structured output**: current Codex CLI supports `--output-schema` and
  `--output-last-message` for non-interactive runs.
- **Ephemeral history**: `codex exec resume` exists but is intentionally not used;
  typed replay into a fresh process preserves the isolation contract.
- **Token streaming**: no scoped workflow requires true token-by-token delivery;
  the established streaming-shaped facade may yield one complete final chunk.
- **State migration**: no breaking state-shape change is required.
- **New dependencies**: none. The implementation uses existing Python standard
  library facilities and current project dependencies.

## Sources

- [CampaignGenerator PR #350](https://github.com/kostadis/CampaignGenerator/pull/350)
  for the merged feature-15 baseline and certified auditor behavior.
- [Official Codex CLI reference](https://developers.openai.com/codex/cli/reference/)
  for non-interactive execution, ephemeral runs, output schemas, ignored user
  configuration, and final-message output controls.
