# Phase 0 Research: Codex CLI Subscription Backend

## Decision 1: Add a dedicated Codex integration seam

**Decision**: Implement `_CodexCliClient` and `CodexCliError` in
`campaignlib/api/codex_cli.py`, then select it from `campaignlib/api/client.py`.

**Rationale**: Codex is an external subprocess boundary with distinct input,
authentication, isolation, output, and failure semantics. A dedicated file keeps
Principle V's one-seam rule visible and avoids adding more provider-specific
branches to `backends.py`.

**Alternatives considered**: Put the adapter in `backends.py` (rejected because
that file already contains several unrelated HTTP/Claude-compatible adapters);
invoke Codex directly from `check_consistency.py` (rejected because it bypasses
the shared client facade and cannot serve other consistency callers).

## Decision 2: Invoke a verified, fail-closed `codex exec` command

**Decision**: Build an argv list without a shell and use the Codex 0.150.1 command
surface: `exec`, `--ephemeral`, `--ignore-user-config`, `--ignore-rules`,
`--strict-config`, `--skip-git-repo-check`, `--sandbox read-only`, an isolated
`--cd`, `--color never`, stdin `-`, and `--output-last-message`. Apply inline
configuration for `approval_policy="never"`, `forced_login_method="chatgpt"`,
disabled web search/apps/agents/project docs, and disable every verified
executable feature family (plugins, MCP-adjacent skill installation, shell,
browsers, computer use, image generation, view-image, and multi-agent features).

**Rationale**: The official non-interactive contract supports stdin, an ephemeral
session, read-only sandboxing, config overrides, and final-message output. Strict
config makes incompatible Codex versions fail visibly instead of silently
weakening isolation. Forced ChatGPT login makes the subscription-only contract
explicit.

**Alternatives considered**: Trust user configuration (rejected because it can
start plugins/MCP); use `--json` and parse event streams (rejected because only
the final Markdown report is needed); rely only on environment key stripping
(rejected because authentication mode should also be constrained).

## Decision 3: Keep developer and user prompt roles separate

**Decision**: Serialize the system text as the TOML-compatible
`developer_instructions` config value and send only the user document/context
payload through process stdin. Never concatenate both into one prompt argument.

**Rationale**: The current facade supplies a system prompt separately from the
single user message, and Codex exposes a developer-instruction configuration key.
An argv array plus JSON string serialization avoids shell interpretation while
preserving Unicode and line breaks.

**Alternatives considered**: Concatenate prompts (rejected because it destroys
role distinction); write prompts into the repository (rejected because it leaks
audit content and breaks cleanup guarantees).

## Decision 4: Define an enforceable isolation boundary

**Decision**: Guarantee that execution ignores repository/project instructions,
does not load user config, cannot start user-configured plugins/MCP, and exposes
no executable tools or web search. Do not claim that administrator or bundled
instruction metadata is absent.

**Rationale**: `--ignore-user-config`, `--ignore-rules`, zero project-document
bytes, an external temporary working directory, feature disables, and read-only
sandboxing enforce the issue's operational boundary. The documented CLI does
not provide a universal “ignore every instruction source/skill/MCP” switch, so
the specification was narrowed rather than promising an untestable absolute.

**Alternatives considered**: Preserve the absolute “no instructions of any kind”
wording (rejected as unverifiable); create an empty `CODEX_HOME` (rejected because
it also hides the operator's saved ChatGPT authentication).

## Decision 5: Read the final answer from a temporary result file

**Decision**: Pass `--output-last-message <temp-path>`, require a successful exit,
then read and validate the non-whitespace result. Treat stderr as bounded
diagnostic material and clean the entire temporary directory on every path.

**Rationale**: Codex writes progress to stderr and the final response to stdout;
the dedicated result path is less vulnerable to progress/protocol changes while
still following the documented interface.

**Alternatives considered**: Treat all stdout as the result (workable but less
explicit); parse JSONL events (unnecessary coupling); accept an empty result after
exit zero (rejected because it would create a misleading blank report).

## Decision 6: Resolve models without inheriting a Claude default

**Decision**: Change the consistency parser's `--model` default to `None`. Existing
backends resolve `None` to `DEFAULT_MODEL`; `codex-cli` resolves explicit
`--model`, then `CG_CODEX_MODEL`, then omits `--model` so Codex uses its own
configured subscription default. Reject explicit or environment values beginning
with `claude-`; pass other names through and let Codex validate them.

**Rationale**: The current parser cannot tell an omitted model from its inherited
Claude default. A sentinel preserves all existing defaults while avoiding a
frozen allowlist for rapidly changing Codex models.

**Alternatives considered**: Hardcode a Codex model (creates drift); maintain an
OpenAI model allowlist (becomes stale); silently discard `claude-*` (hides operator
error).

## Decision 7: Make timeout and failures typed and actionable

**Decision**: Resolve `CG_CODEX_TIMEOUT` once, defaulting to 600 seconds, and reject
non-numeric, non-finite, zero, or negative values. Raise `CodexCliError` for a
missing executable, invalid model/timeout, timeout expiry, authentication failure,
nonzero exit (with bounded stderr), or empty successful output. Do not retry or
fall back to another provider.

**Rationale**: These are operator/configuration or child-process failures, not
transient API errors. Typed errors let `check_consistency.py` produce concise
messages without catching unrelated programming failures.

**Alternatives considered**: Reuse the shared retry detector (could spend more
time or switch semantics); broad `RuntimeError` handling (masks bugs); unlimited
stderr (can flood terminal/test logs).

## Decision 8: Preserve the Anthropic-shaped facade narrowly

**Decision**: Support `.messages.create(...)` and a `.messages.stream(...)`
context manager whose `text_stream` yields exactly one final chunk. Accept the
existing `max_tokens` argument for interface compatibility but do not map it,
because `codex exec` exposes no equivalent output-token flag. Reject tools,
images, assistant history, multiple user turns, and non-text blocks.

**Rationale**: Existing callers can continue through `call_api` and `stream_api`,
while explicit validation prevents the adapter from pretending to support
conversation or tool semantics it cannot preserve.

**Alternatives considered**: Simulate streaming from subprocess stdout (progress
and final output have different roles); silently flatten multi-turn input
(destroys message semantics); invent a token-limit config mapping (unsupported).

## Decision 9: Separate keyless and thinking-capable client sets

**Decision**: Keep `_THINKING_EXTRA_CLIENTS` unchanged and introduce a distinct
`_KEYLESS_CLIENTS` set containing Claude Code and Codex CLI clients. Credential
gating uses `_KEYLESS_CLIENTS`; thinking forwarding continues to use only the
providers that support it.

**Rationale**: The current tuple serves two unrelated policies. Adding Codex to
it directly would accidentally forward Anthropic thinking options.

**Alternatives considered**: Add Codex to the existing tuple (incorrect feature
coupling); special-case it in each call path (duplication).

## Decision 10: Reuse the existing non-Anthropic batch guard

**Decision**: Add `codex-cli` to backend choices and client construction, while
retaining the existing rule that Batch API mode is Anthropic-only.

**Rationale**: Codex execution is one local child per audit and has no compatible
batch surface. The shared guard already owns this policy.

**Alternatives considered**: Queue multiple `codex exec` calls behind `--batch`
(changes meaning and could create an implicit token-spending blast radius).

## Decision 11: Test the subprocess seam without spending subscription tokens

**Decision**: Add focused mocked tests for exact argv, environment, stdin,
temporary-directory cleanup, output, model precedence, timeout/errors, facade
compatibility, unsupported inputs, no retry, and no fallback. Add CLI integration
tests with a mocked Codex client and update shared backend guardrail tests. Keep one
manual authenticated smoke test in `quickstart.md`.

**Rationale**: Deterministic CI should not require a user's Codex login or spend
tokens. The pre-change focused baseline is 37 passing tests. A broader selected
baseline had 245 passes, 147 skips, and three unrelated failures caused by the
optional `dgxlib` package being absent.

**Alternatives considered**: Live Codex calls in pytest (nondeterministic,
credential-dependent, costly); only unit-test the command builder (misses CLI
prompt/report integration).

## Decision 12: Treat skill edits as a separate repository delivery

**Decision**: Update the canonical sources at
`/home/kroussos/src/mytools/dotfiles/codex/skills/{consistency-check,staged-consistency}/SKILL.md`.
Do not edit their `~/.codex/skills` symlinks as independent artifacts. Track and
commit those edits separately from CampaignGenerator.

**Rationale**: The installed skills resolve to the dotfiles repository, which is
outside this worktree and currently untracked there. CampaignGenerator CI must
not depend on a particular home-directory installation.

**Alternatives considered**: Edit generated/install paths (not portable); copy
skills into this repository (creates two sources of truth); omit skill delivery
(does not satisfy issue #348).

## Decision 13: Apply the explicit no-UI exemption

**Decision**: Do not add `codex-cli` to the web selector or server command
builders in this feature.

**Rationale**: Issue #348 explicitly defers the frontend selector, and the user
requested that issue. This is the human-authored no-UI ruling required by
Constitution Principle XI, not an implicit follow-up.

**Alternatives considered**: Add UI wiring now (expands scope beyond the adopted
issue); omit the ruling from the plan (would violate the constitution).

## Decision 14: Document the new operator contract in normative surfaces

**Decision**: Update `README.md`, `docs/cli/cli_tools.md`,
`docs/core/configuration.md`, `docs/system/component-campaigngenerator.md`, and
`docs/system/index.md` with the subscription prerequisite, backend spelling,
environment variables, security boundary, batch restriction, and CLI-only scope.

**Rationale**: Backend setup and failure behavior are operator-visible and should
not live only in code or a skill. No migration document is needed because no
persistent state shape changes.

**Alternatives considered**: Document only in the feature spec (not an operator
surface); add a config-schema entry (unnecessary because both settings are
environment/runtime policy).

## Primary references

- [OpenAI non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- [OpenAI Codex CLI command reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
- [OpenAI Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
- Installed `codex-cli 0.150.1` help and feature inventory, verified 2026-08-27
