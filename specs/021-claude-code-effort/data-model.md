# Data Model: Claude Code Subscription Effort Level

**Feature**: `021-claude-code-effort` | **Date**: 2026-09-01

Every field below is **optional and additive**. Absent means omission, omission reproduces today's behaviour exactly, and no existing file changes shape — so Constitution Principle XIII is not triggered and no migrator ships with this feature.

---

## 1. Vocabulary

```
ClaudeCodeEffort = Literal["low", "medium", "high", "xhigh", "max"]
CLAUDE_CODE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
```

Declared in `campaignlib/selection.py` beside `CodexReasoningEffort`, and re-exported through `campaignlib/__init__.py`.

Five values, not six. `minimal` is Codex-only; the Claude Code CLI's `--effort` does not accept it, and inventing it would produce a flag whose `--help` lists a value that fails at runtime (research R1).

**Ordering matters for one rule only**: `xhigh` and `max` are the two levels the provider refuses when thinking is disabled. Everything else is an opaque label.

---

## 2. Claude Code Effort Selection *(what was asked for)*

The operator's request, before the engine has had its say.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `claude_code_effort` | `ClaudeCodeEffort \| None` | `None` | The requested level. `None` = defer to the tier above, then to omission. |

**Where it lives**, one field per tier, all optional:

| Tier | Location | Field |
|---|---|---|
| Request | route payload / CLI argv | `--claude-code-effort`, or the request body field |
| Service | `ModelSelection` on `session_doc.yaml` (`backends.profiles['claude-code']`), `ensemble.yaml`, `planning.yaml`, `party.yaml` | `claude_code_effort` |
| Platform | `platform.yaml` | `runtime.default_claude_code_effort` |
| Environment | process env | `CG_CLAUDE_CODE_EFFORT` |

**Validation**
- Must be one of the five values. A value outside the set, a non-string, an empty string, or a string with surrounding whitespace is rejected naming the accepted set.
- An absent or whitespace-only `CG_CLAUDE_CODE_EFFORT` is **omission**, not an empty override — it must not create a falsy value that outranks the tier above.
- A selection paired with a backend other than `claude-code` is **refused at resolution**, not ignored.

**Storable but not runnable.** Following `ModelSelection`'s existing rule for incompatible model/backend pairs and unsatisfiable `batch`, a `claude_code_effort` stored on a profile whose backend is currently `codex-cli` is a legal *write* and a refused *run*. Rejecting the write would make the refusal message unreachable and would erase the operator's setting when they switch backends to fix something else.

**`is_empty()` must learn this field** on all three shapes that implement it — `ModelSelection`, `BackendProfile`, `EnsembleBackend`. A profile carrying only an effort selection has something to say; if `is_empty()` misses the field, that profile is treated as no override at all and is silently dropped by the save paths that gate on emptiness. This is the exact failure the `batch` field's existing note documents, and it is the single most likely place for this feature to fail quietly.

---

## 3. Resolved Effort State *(what actually ran)*

**This is not the same object as the selection, and the distinction is the feature.** A run can send `high` that nobody chose.

| Field | Type | Meaning |
|---|---|---|
| `effective_model` | `str` | The model id sent to the child. |
| `effort_sent` | `ClaudeCodeEffort \| None` | The level passed as `--effort`, or `None` when the argument was omitted entirely. |
| `source` | `"explicit" \| "environment" \| "clamp" \| "inherited"` | Who decided. |
| `override_sent` | `bool` | Whether CampaignGenerator supplied `--effort` at all. |
| `thinking_on` | `bool` | The resolved thinking state, because it is what makes the top two levels legal or not. |

### The four sources

| Source | `effort_sent` | `override_sent` | When | Reported as |
|---|---|---|---|---|
| `explicit` | the chosen level | `true` | Request/service/platform tier resolved a value | the operator's choice |
| `environment` | the env value | `true` | Only `CG_CLAUDE_CODE_EFFORT` was set | environment-derived |
| `clamp` | `"high"` | `true` | Nothing chosen; thinking suppressed; model is clamp-eligible | **the engine's compatibility clamp, with its reason** |
| `inherited` | `None` | `false` | Nothing chosen; no clamp applies | inherited from the operator's own Claude Code settings — value unknown to us |

Codex has three sources. Claude Code has four, because today's single silent "omission" is really two different behaviours the operator cannot currently tell apart. Splitting them is what FR-020 and SC-008 require.

`inherited` must never claim a value. The child resolves `effortLevel` from `~/.claude/settings.json`, which this process does not read; asserting a level we did not send would be an Optimistic Lie in the one record meant to end them.

---

## 4. Effort/Thinking Conflict

Not a stored entity — a validation rule, stated once and applied in two places (research R2).

**Conflict holds when all three are true:**
1. `effort_sent` ∈ {`xhigh`, `max`} **and** its source is `explicit` or `environment`
2. `thinking_on` is `false`
3. the model is **not** in an always-thinking family (`fable` / `mythos` markers)

**On conflict**: refuse before the child process spawns. Do not enable thinking. Do not lower the level. Do not spawn and let the provider reject it.

The message must name the selected level, state that it requires thinking, and give both remedies — including `CG_CLAUDE_CODE_THINKING=1` by name, since thinking has no flag and no UI control (research R7). A remedy the operator cannot locate is not a remedy.

**Condition 3 is load-bearing.** On always-thinking families the clamp is already correctly skipped and the top levels are legal; firing the refusal there would block a working configuration.

**Condition 1 excludes the clamp by construction** — the clamp only ever emits `high`, so it can never conflict with itself.

---

## 5. Claude Code Backend Profile

The operator's stored Claude Code UI configuration: the existing model, plus the optional remembered effort.

**Isolation is a requirement, not a consequence.** The profile map is keyed by backend name (`claude-code`, `codex-cli`), so:
- Setting a Claude Code effort must not read, write, or clear `codex_reasoning_effort`.
- Both may be stored simultaneously; each stays dormant while the other backend is active.
- Switching backends must not erase either, and must not migrate one into the other.

`session_editor_config_shared.py` already keys `BackendProfile` this way for `claude-code` and `codex-cli`, so isolation comes from the existing structure — the work is not to build it but to avoid breaking it, and to assert it (FR-015, SC-003).

---

## 6. Entry-Point Inventory

Not persisted state; the acceptance artifact FR-025 requires.

| Class | Members | Obligation |
|---|---|---|
| Model-bearing CLIs | the 30 callers of `add_backend_args` | **accept** — inherited automatically, since `add_backend_args` registers the option |
| Dispatchers | `ensemble`, `ensemble_batch`, `ensemble_extract`, `facts_to_state`, `polish`, `sd_agent` | **forward** to every applicable child |
| Config tiers | `platform_config_service`, `session_editor_config_shared`, `ensemble_config_shared` | **resolve** with the documented precedence |
| Routers | `config_routes`, `ensemble`, `scene_editor`, `connections` | **pass the flag**, never a default literal |
| UI surfaces | `AppSidebar`, `SelectionPanel`, `KnobDrawer`, `EnsembleSetup`, `SessionDocEditor`, `ReviewAssemble`, `ConnectionGraph`, `StreamOutput` | **expose or report** |

The guardrail test's real work is the dispatchers and the UI. CLI acceptance is structural — a new CLI calling `add_backend_args` cannot omit the option — but forwarding and rendering are per-file discipline, and that is where drift appears.
