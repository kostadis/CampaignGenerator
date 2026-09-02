# Contract: CLI Option Family

**Feature**: `021-claude-code-effort`

Constitution Principle XII in concrete form: one spelling, one meaning, one default, introduced across the whole family in one act.

---

## The option

```
--claude-code-effort {low,medium,high,xhigh,max}
```

**Help text** (single source, shown identically on all 30 CLIs):

> Claude Code CLI effort level. Applies only to `--backend claude-code`;
> `CG_CLAUDE_CODE_EFFORT` is the fallback. Omit to keep the current behaviour
> (a compatibility clamp when thinking is suppressed, otherwise your own
> `~/.claude/settings.json` `effortLevel`). `xhigh` and `max` require thinking
> — set `CG_CLAUDE_CODE_THINKING=1`, or the call is refused. Higher levels
> increase run time.

**Default**: `None` — absent, not a value. `None` and `"low"` must remain distinguishable at every tier.

---

## Registration

Registered **inside `add_backend_args`** (`campaignlib/api/client.py`), beside the existing `add_codex_reasoning_arg(parser)` call.

```
add_backend_args(parser)
  ├── --backend / --endpoint / --batch
  ├── add_codex_reasoning_arg(parser)        # existing
  └── add_claude_code_effort_arg(parser)     # new
```

This is the whole of CLI parity. All 30 callers inherit the option; a CLI added tomorrow inherits it too. A helper that must be called separately by each script would be a parity obligation renewed 30 times — the drift Principle XII names.

`add_claude_code_effort_arg` is still exported for the dispatchers, which need to name it when building child argv.

---

## Resolution

`resolve_cli_claude_effort(args) -> ClaudeCodeEffortIntent`, mirroring `resolve_cli_reasoning`.

**Precedence**: explicit argv/UI → `CG_CLAUDE_CODE_EFFORT` → omission.

```
effective_backend = args.backend if set and != anthropic, else CG_BACKEND, else anthropic

if args.claude_code_effort is not None:
    validate ∈ CLAUDE_CODE_EFFORTS            → else ValueError naming the set
    require effective_backend == "claude-code" → else ValueError naming the backend
    return source="explicit"

if effective_backend != "claude-code":
    return source="omitted"                    # dormant on other backends, never leaks

raw = os.environ.get("CG_CLAUDE_CODE_EFFORT")
if raw is None or not raw.strip():
    return source="omitted"

validate raw.strip() ∈ CLAUDE_CODE_EFFORTS     → else ValueError naming CG_CLAUDE_CODE_EFFORT
return source="environment"
```

**Note the ordering**: the backend check for an *explicit* value happens before the environment is consulted, so `--claude-code-effort max --backend dgx` refuses rather than silently ignoring. But a *non-`claude-code`* run with `CG_CLAUDE_CODE_EFFORT` merely set in the shell is omission, not a refusal — an environment variable is ambient, and refusing on it would make an exported convenience break every unrelated command.

---

## Refusals

All raise before any client is constructed or any child spawns. Each names what was wrong and what to do.

| Case | Message shape |
|---|---|
| Value outside the set | `--claude-code-effort value 'ultra' must be one of: low, medium, high, xhigh, max` |
| Empty or padded value | `--claude-code-effort must be one of: low, medium, high, xhigh, max` |
| Wrong backend | `--claude-code-effort applies only to --backend claude-code; effective backend is 'dgx'` |
| Bad environment value | `CG_CLAUDE_CODE_EFFORT value 'ultra' must be one of: low, medium, high, xhigh, max` |
| Effort/thinking conflict | `--claude-code-effort 'max' requires extended thinking, which is disabled for this call. Either lower the effort to 'high' or below, or set CG_CLAUDE_CODE_THINKING=1. Refusing rather than changing your thinking setting or silently lowering the effort.` |

The conflict message is produced by **one shared helper**, called from both guard sites (research R2), so the edge and the seam cannot drift into two wordings of the same refusal.

---

## Dispatcher forwarding

Six commands run Claude Code children and must forward the resolved value to **every** one: `ensemble`, `ensemble_batch`, `ensemble_extract`, `facts_to_state`, `polish`, `sd_agent`.

**Contract**:
- Forward the **resolved** value, not the raw argv — a child that re-reads `CG_CLAUDE_CODE_EFFORT` for itself would reach the same answer today and a different one the moment a service tier is involved.
- Forward to every applicable child, including those started by retry and resume.
- Apply to `claude-code` stages only. A mixed-backend plan leaves other stages untouched.
- Change nothing else: work sets, caching, retries, concurrency, timeouts, overwrite rules, output locations, and human-review checkpoints are all unaffected.

---

## Client construction

`client_from_args` threads the resolved value into `make_client`:

```python
if effort_intent.backend == "claude-code" and effort_intent.effective_effort is not None:
    client_kwargs.update(
        claude_code_effort=effort_intent.effective_effort,
        claude_code_effort_source=effort_intent.source,
    )
```

Separate kwargs from Codex's `reasoning_effort` / `reasoning_effort_source` (research R1/R5). `make_client` passes them to `_ClaudeCodeClient` only; every other backend's construction is untouched.

---

## What must not change

- Omission produces a **byte-identical** invocation to the pre-feature baseline (SC-005).
- No other backend's argv, defaults, or behaviour moves (FR-023).
- The existing thinking opt-in keeps its default, its env var, and its always-thinking family list.
- Credential stripping, tool isolation (`--disallowed-tools '*'`), MCP isolation (`--strict-mcp-config`), the `CLAUDE_CODE_MAX_OUTPUT_TOKENS` ceiling, and auto-continue detection are untouched (FR-022).
