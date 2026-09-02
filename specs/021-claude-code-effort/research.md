# Phase 0 Research: Claude Code Subscription Effort Level

**Feature**: `021-claude-code-effort` | **Date**: 2026-09-01

The spec carried no unresolved NEEDS CLARIFICATION into planning — its only marker (FR-009) was ruled by the operator at the specification checkpoint. These nine decisions are the design questions planning itself raised.

---

## R1 — One provider-prefixed option, not a shared `--effort`

**Decision**: Introduce `--claude-code-effort` / `CG_CLAUDE_CODE_EFFORT` / `ModelSelection.claude_code_effort`, parallel to but separate from #359's `--codex-reasoning-effort` / `CG_CODEX_REASONING_EFFORT` / `codex_reasoning_effort`.

**Rationale**: Constitution Principle XII is the governing text, and it cuts *against* merging here. The two vocabularies are not the same set:

| | Codex | Claude Code |
|---|---|---|
| Accepted | `minimal`, `low`, `medium`, `high`, `xhigh`, `max` | `low`, `medium`, `high`, `xhigh`, `max` |
| Extra rule | model support varies; provider rejects at call | top two require thinking enabled |
| Omission | send nothing | send nothing **or** the compatibility clamp |

A single `--effort` would accept `minimal` on one backend and reject it on the other, and would mean "send nothing" on one and "send `high`" on the other. That is one spelling with two meanings and two defaults — precisely the dialect XII exists to prevent. Two names, each with one meaning, is the compliant shape; the family-wide obligation is satisfied by registering the new option across all 30 CLIs *at once*, which R8 covers.

**Alternatives considered**:
- *Rename #359's flag to a shared `--reasoning-effort` and branch validation on the resolved backend.* Rejected: churns a shipped, documented surface; `argparse` `choices=` cannot express a backend-dependent set, so validation would move out of the parser and the `--help` text would list values that fail at runtime.
- *Reuse `make_client(reasoning_effort=…)`.* Rejected: that parameter is typed `CodexReasoningEffort` and consumed by `_CodexCliClient`. Overloading it makes the client's contract depend on which backend string was passed — a Split-Brain waiting to diverge (R5).

---

## R2 — Where the effort/thinking conflict refusal fires

**Decision**: Two guards, with "before model work starts" defined as **before the `claude` child process is spawned**.

1. **Fast fail at the edge** (argparse in `client_from_args`, and the route edge in `platform_config_service.resolve_selection`) when the conflict is already determined — an explicit `xhigh`/`max`, a clamp-eligible model, and no thinking opt-in in the environment.
2. **Hard guard in `_claude_code_generate`**, immediately before `subprocess.run`, covering the case the edge cannot see.

**Rationale**: `thinking` reaches this backend as a **per-call argument** (`stream_api` forwards it via `_THINKING_EXTRA_CLIENTS`, `campaignlib/api/client.py:464`), not as parsed argv. At parse time the resolver knows the model and `CG_CLAUDE_CODE_THINKING`, but not a per-call `thinking=True`. A single argparse-time check would therefore refuse a call that would in fact have been legal. A single deep check would satisfy correctness but give the operator the error late, after a dispatcher had already started other children.

Both guards raise the same message from one shared helper, so there is one refusal text, not two that drift. No tokens are spent in either case: the guard precedes process spawn, and the child is what costs.

**Alternatives considered**:
- *Guard only in `_claude_code_generate`.* Rejected: correct but late; a fan-out would refuse child 7 after children 1–6 ran.
- *Guard only at argparse.* Rejected: refuses legal calls, and misses the UI path entirely.

---

## R3 — Omission keeps the clamp, and the clamp names itself

**Decision**: When nothing resolves, behaviour is byte-identical to today — `--effort high` on a clamp-eligible model with thinking suppressed, nothing at all otherwise. The clamp is reported as its own source rather than presented as the operator's choice.

**Rationale**: The clamp is not incidental. With thinking off the provider refuses the top two levels, and the operator's own `~/.claude/settings.json` currently pins `effortLevel: xhigh` — so "omission means send nothing" would hard-fail every default `claude-code` run on the machine this feature is being built on. FR-005 and SC-005 make preservation a gate.

But the clamp is also the defect User Story 3 names: it silently overrides a level the operator deliberately set, and nothing says so. Keeping the behaviour while reporting it is what turns an Optimistic Lie into discoverable state (Principle VIII).

**Alternatives considered**:
- *Drop the clamp now that effort is selectable.* Rejected: breaks every default run for a pinned-high operator, and the spec forbids changing omission behaviour.
- *Report the clamp as `explicit`.* Rejected: it would attribute the engine's compatibility decision to the human, which is the misreport the feature exists to end.

---

## R4 — A run identity for `claude-code`, mirroring Codex's

**Decision**: Add a run-identity value object to the `claude-code` path carrying effective model, resolved effort (or "inherited"), source, and whether an override was sent. Emit exactly one banner before the child spawns, and include the same fields wherever the path already records the effective model.

**Rationale**: `campaignlib/api/codex_cli.py:121` already does this for Codex; the `claude-code` path has no equivalent, which is why FR-018/019/020 exist. Copying the shape keeps the two subscription backends legible as one family and lets `StreamOutput.vue` parse one identity format rather than two.

**Alternatives considered**: *Log the effort ad hoc at each call site.* Rejected — a fact assembled in six places is a Split-Brain; and #359's banner-per-run discipline (one banner, bounded output) exists because a per-call print flooded streamed polish output.

---

## R5 — Threading the value through the one seam

**Decision**: `make_client(claude_code_effort=…, claude_code_effort_source=…)` → `_ClaudeCodeClient` → `_ClaudeCodeMessages.create/stream` → `_claude_code_generate`, which owns the final `--effort` argv decision alongside the existing thinking/clamp logic.

**Rationale**: Principle V — the `claude` CLI is reached through exactly one file, and `_claude_code_generate` is already the sole place that builds that argv. The clamp lives there, so the override must be decided there too; splitting them would let two functions disagree about what `--effort` the child gets. Routers and pipelines pass a *value*, never a command line.

**Alternatives considered**: *Resolve in the router and pass a fully-built argv.* Rejected outright — Principle VI, and it would put the clamp rule in the server.

---

## R6 — Config tiers reuse the existing precedence machinery

**Decision**: `request > service > platform > environment > omission`, resolved by the existing `platform_config_service.resolve_selection`, with a new `runtime.default_claude_code_effort` at the platform tier and `claude_code_effort` on the shared `ModelSelection` at the service tier.

**Rationale**: This machinery already exists and already carries `codex_reasoning_effort` through the same four tiers with origin tracking. Adding a parallel field costs one literal per tier and inherits origin reporting, storable-not-runnable semantics, and the wrong-backend refusal for free. Defaults are declared once in the config model that owns them (Principle XII); routes take a sentinel and resolve at the edge, so no `claude-code`-shaped literal appears in a router — the rule `tests/test_ensemble_config_defaults.py` enforces.

`is_empty()` on `ModelSelection`, `BackendProfile`, and `EnsembleBackend` must all learn the new field, or a profile carrying only an effort selection is treated as no override at all and is dropped on save — the exact bug the `batch` field's `is_empty()` note documents.

---

## R7 — Thinking is unreachable, and the FR-009 ruling inherits that

**Decision**: Record the consequence; do not widen scope to fix it. Make the refusal message name the only remedy that actually exists.

**Finding**: `thinking` has **no CLI flag and no UI control** anywhere in the repo. The only operator-reachable lever is `CG_CLAUDE_CODE_THINKING`; the per-call Python argument exists but no caller passes it.

**Consequence**: With FR-009 ruling "refuse, never auto-enable", `xhigh` and `max` are selectable in the UI and on the CLI but reachable only by an operator who also exports an environment variable — except on always-thinking model families, where they work directly. The refusal message must therefore say `CG_CLAUDE_CODE_THINKING=1` explicitly rather than gesture at "enable thinking", or it names a remedy the operator cannot find.

**Why not fix it here**: adding a thinking flag and its UI face is a second capability with its own parity obligation under Principle XI, and it was not asked for. Absorbing it would be exactly the scope widening the operator did not authorise. **Follow-up**: opened as [#365](https://github.com/kostadis/CampaignGenerator/issues/365) — a first-class thinking control, cross-referencing this feature and the measurement in `backends.py`'s module comment.

**Alternatives considered**: *Quietly treat an explicit `xhigh`/`max` as a thinking opt-in.* Rejected — the operator ruled against exactly this, on the grounds that it makes a 4× run-time decision on their behalf.

---

## R8 — The parity inventory and the guardrail that defends it

**Decision**: Register the option inside `add_backend_args`, and add a guardrail test that fails when a Claude Code-capable surface lacks it.

**Finding**: `add_backend_args` (`campaignlib/api/client.py:350`) already calls `add_codex_reasoning_arg(parser)`. All 30 model-bearing CLIs therefore inherit the Codex flag without naming it; only the 4 ensemble dispatchers call it explicitly, because they must *forward* the value to children rather than merely accept it.

**Consequence**: CLI parity is one edit, not thirty — and it is structurally durable, since a new CLI that calls `add_backend_args` gets the option automatically. The guardrail's real job is the two places structure cannot cover: the **dispatchers** (which must forward) and the **UI** (which has no such shared registration point).

**UI coverage caveat**: there is no frontend component-test harness (#345), so UI parity is asserted by static source checks over `frontend/src/**`, exactly as `tests/test_codex_reasoning_ui.py` does. This proves a control is *present in source*, not that it renders or persists — the quickstart's manual steps are what cover that, and the gap is stated rather than papered over.

---

## R9 — Validating from a worktree

**Decision**: Run the acceptance suite from the primary checkout, or account explicitly for every skipped file.

**Rationale**: Issue [#286](https://github.com/kostadis/CampaignGenerator/issues/286) — six test files skip silently in a worktree, so a green suite inside `worktrees/021-claude-code-effort` is not evidence. The quickstart names `-rs` to surface skip reasons rather than trusting a green summary.

**Also required**: the package must be editable-installed into the server's venv before any UI validation, or `/run/*` fails with `Stream error — check terminal` because the console script is missing. This bites on every fresh worktree; the quickstart puts it first.
